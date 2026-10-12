#!/usr/bin/env python3
"""
OpenMC Plot GUI
================

A Tkinter GUI for generating OpenMC geometry plots.

Workflow:
  1. Point the GUI at a directory that already contains OpenMC input files
     (geometry.xml / materials.xml / settings.xml, or a model.xml). The
     directory must NOT need a plots.xml to already exist -- this tool
     creates one for you.
  2. Set plot parameters (origin, width/height, pixel resolution, basis
     plane, color-by mode, background color) in the form.
  3. Click "Generate & Plot". The tool writes plots.xml into the input
     directory, runs `openmc --plot` (or `openmc-plot` fallback) in that
     directory, loads the resulting PPM/PNG image, converts it if needed,
     and displays it in the panel on the right.
  4. Change parameters and click "Generate & Plot" again as many times as
     you like -- each run overwrites plots.xml and re-renders the image.

Requirements:
  - Python 3.8+
  - Pillow (PIL) for image display/conversion:  pip install pillow
  - OpenMC installed and importable, OR the `openmc` CLI available on PATH
    (this script will try `python -m openmc` and the `openmc` executable).

Run:
  python openmc_plot_gui.py
"""

import os
import sys
import glob
import shutil
import subprocess
import threading
import traceback
import xml.etree.ElementTree as ET
from xml.dom import minidom

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None


APP_TITLE = "OpenMC Plot GUI"

REQUIRED_ANY = ["model.xml"]
REQUIRED_SET = ["geometry.xml", "materials.xml", "settings.xml"]


def pretty_xml(elem):
    """Return a nicely indented XML string for an ElementTree Element."""
    rough = ET.tostring(elem, encoding="utf-8")
    reparsed = minidom.parseString(rough)
    pretty = reparsed.toprettyxml(indent="  ")
    # Strip blank lines minidom tends to introduce
    lines = [line for line in pretty.split("\n") if line.strip()]
    return "\n".join(lines) + "\n"


class Tooltip:
    """Simple tooltip for a widget."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event=None):
        if self.tipwindow or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw, text=self.text, justify="left", background="#ffffe0",
            relief="solid", borderwidth=1, font=("TkDefaultFont", 9),
            wraplength=320,
        )
        label.pack(ipadx=4, ipady=2)

    def hide(self, _event=None):
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


class OpenMCPlotGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1200x780")
        self.minsize(1000, 650)

        self.input_dir = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Choose an input directory to begin.")

        # Plot parameter variables
        self.var_basis = tk.StringVar(value="xy")
        self.var_origin_x = tk.StringVar(value="0.0")
        self.var_origin_y = tk.StringVar(value="0.0")
        self.var_origin_z = tk.StringVar(value="0.0")
        self.var_width = tk.StringVar(value="100.0")
        self.var_height = tk.StringVar(value="100.0")
        self.var_pix_x = tk.StringVar(value="600")
        self.var_pix_y = tk.StringVar(value="600")
        self.var_color_by = tk.StringVar(value="material")  # material | cell
        self.var_background = tk.StringVar(value="255,255,255")
        self.var_plot_type = tk.StringVar(value="slice")  # slice | voxel (slice supported for image)
        self.var_level = tk.StringVar(value="")  # universe level, optional
        self.var_show_overlaps = tk.BooleanVar(value=False)
        self.var_overlap_color = tk.StringVar(value="255,0,0")

        self.current_image = None  # PIL Image
        self.tk_image = None       # ImageTk.PhotoImage (kept alive)
        self.last_zoom = 1.0

        self._build_ui()
        self._check_pillow()

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        self._build_menu()

        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)

        # Top bar: directory selection
        top = ttk.Frame(outer, padding=(10, 8))
        top.pack(fill="x", side="top")

        ttk.Label(top, text="Input directory:").pack(side="left")
        entry = ttk.Entry(top, textvariable=self.input_dir, width=70)
        entry.pack(side="left", padx=6)
        ttk.Button(top, text="Browse...", command=self.browse_dir).pack(side="left")
        ttk.Button(top, text="Scan", command=self.scan_directory).pack(side="left", padx=(6, 0))

        # Main split: left = params, right = image
        main = ttk.PanedWindow(outer, orient="horizontal")
        main.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = ttk.Frame(main, padding=(0, 0, 10, 0))
        right = ttk.Frame(main)
        main.add(left, weight=0)
        main.add(right, weight=1)

        self._build_param_panel(left)
        self._build_image_panel(right)

        # Status bar
        status = ttk.Frame(outer, relief="sunken")
        status.pack(fill="x", side="bottom")
        ttk.Label(status, textvariable=self.status_var, anchor="w").pack(
            fill="x", padx=6, pady=3
        )

    def _build_menu(self):
        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Open input directory...", command=self.browse_dir)
        filemenu.add_command(label="Save plots.xml as...", command=self.save_plots_xml_as)
        filemenu.add_separator()
        filemenu.add_command(label="Save displayed image as...", command=self.save_image_as)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filemenu)
        self.config(menu=menubar)

    def _build_param_panel(self, parent):
        canvas = tk.Canvas(parent, width=340, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw", width=320)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        pad = dict(padx=8, pady=4)

        # --- Detected files ---
        box = ttk.LabelFrame(scroll_frame, text="Detected input files")
        box.pack(fill="x", **pad)
        self.files_label = ttk.Label(box, text="(none yet)", justify="left", wraplength=300)
        self.files_label.pack(fill="x", padx=6, pady=6)

        # --- Basis / geometry ---
        box = ttk.LabelFrame(scroll_frame, text="Plot geometry")
        box.pack(fill="x", **pad)

        row = ttk.Frame(box); row.pack(fill="x", padx=6, pady=3)
        ttk.Label(row, text="Basis plane:", width=16).pack(side="left")
        basis_combo = ttk.Combobox(
            row, textvariable=self.var_basis, values=["xy", "xz", "yz"],
            state="readonly", width=10,
        )
        basis_combo.pack(side="left")
        Tooltip(basis_combo, "2D slice plane through the geometry.")

        row = ttk.Frame(box); row.pack(fill="x", padx=6, pady=3)
        ttk.Label(row, text="Origin (x,y,z):", width=16).pack(side="left")
        ttk.Entry(row, textvariable=self.var_origin_x, width=7).pack(side="left", padx=2)
        ttk.Entry(row, textvariable=self.var_origin_y, width=7).pack(side="left", padx=2)
        ttk.Entry(row, textvariable=self.var_origin_z, width=7).pack(side="left", padx=2)

        row = ttk.Frame(box); row.pack(fill="x", padx=6, pady=3)
        ttk.Label(row, text="Width x Height:", width=16).pack(side="left")
        ttk.Entry(row, textvariable=self.var_width, width=8).pack(side="left", padx=2)
        ttk.Label(row, text="x").pack(side="left")
        ttk.Entry(row, textvariable=self.var_height, width=8).pack(side="left", padx=2)
        Tooltip(row, "Physical width/height of the plot window (cm).")

        row = ttk.Frame(box); row.pack(fill="x", padx=6, pady=3)
        ttk.Label(row, text="Pixels (x,y):", width=16).pack(side="left")
        ttk.Entry(row, textvariable=self.var_pix_x, width=8).pack(side="left", padx=2)
        ttk.Entry(row, textvariable=self.var_pix_y, width=8).pack(side="left", padx=2)

        row = ttk.Frame(box); row.pack(fill="x", padx=6, pady=3)
        ttk.Label(row, text="Universe level:", width=16).pack(side="left")
        ttk.Entry(row, textvariable=self.var_level, width=8).pack(side="left", padx=2)
        Tooltip(row, "Optional integer. Leave blank to plot the deepest level everywhere.")

        # --- Appearance ---
        box = ttk.LabelFrame(scroll_frame, text="Appearance")
        box.pack(fill="x", **pad)

        row = ttk.Frame(box); row.pack(fill="x", padx=6, pady=3)
        ttk.Label(row, text="Color by:", width=16).pack(side="left")
        ttk.Combobox(
            row, textvariable=self.var_color_by, values=["material", "cell"],
            state="readonly", width=10,
        ).pack(side="left")

        row = ttk.Frame(box); row.pack(fill="x", padx=6, pady=3)
        ttk.Label(row, text="Background RGB:", width=16).pack(side="left")
        ttk.Entry(row, textvariable=self.var_background, width=14).pack(side="left", padx=2)
        ttk.Button(row, text="Pick...", command=self._pick_background_color).pack(side="left", padx=4)

        row = ttk.Frame(box); row.pack(fill="x", padx=6, pady=3)
        chk = ttk.Checkbutton(row, text="Highlight overlaps", variable=self.var_show_overlaps)
        chk.pack(side="left")

        row = ttk.Frame(box); row.pack(fill="x", padx=6, pady=3)
        ttk.Label(row, text="Overlap RGB:", width=16).pack(side="left")
        ttk.Entry(row, textvariable=self.var_overlap_color, width=14).pack(side="left", padx=2)

        # --- Random colors button (color spec editing left simple: material/cell coloring
        #     is automatic in OpenMC when no <color> elements are given) ---
        note = ttk.Label(
            box,
            text="Note: material/cell colors are auto-assigned by OpenMC unless\n"
                 "you edit plots.xml manually afterward to add <color> entries.",
            justify="left", foreground="#555555", wraplength=300,
        )
        note.pack(fill="x", padx=6, pady=(4, 6))

        # --- Actions ---
        box = ttk.LabelFrame(scroll_frame, text="Actions")
        box.pack(fill="x", **pad)

        self.run_button = ttk.Button(
            box, text="Generate plots.xml && Plot", command=self.on_generate_and_plot
        )
        self.run_button.pack(fill="x", padx=6, pady=(6, 3))

        row = ttk.Frame(box); row.pack(fill="x", padx=6, pady=3)
        ttk.Button(row, text="Preview XML", command=self.on_preview_xml).pack(
            side="left", expand=True, fill="x", padx=(0, 3)
        )
        ttk.Button(row, text="Reset params", command=self.on_reset_params).pack(
            side="left", expand=True, fill="x", padx=(3, 0)
        )

        self.progress = ttk.Progressbar(box, mode="indeterminate")
        self.progress.pack(fill="x", padx=6, pady=(6, 6))

    def _build_image_panel(self, parent):
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Zoom In", command=lambda: self.zoom_image(1.25)).pack(side="left")
        ttk.Button(toolbar, text="Zoom Out", command=lambda: self.zoom_image(0.8)).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Fit", command=self.fit_image).pack(side="left")
        ttk.Button(toolbar, text="Save Image As...", command=self.save_image_as).pack(side="right")

        container = ttk.Frame(parent, relief="sunken", borderwidth=1)
        container.pack(fill="both", expand=True, pady=(6, 0))

        self.img_canvas = tk.Canvas(container, background="#222222")
        hbar = ttk.Scrollbar(container, orient="horizontal", command=self.img_canvas.xview)
        vbar = ttk.Scrollbar(container, orient="vertical", command=self.img_canvas.yview)
        self.img_canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)

        self.img_canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        self.canvas_image_id = None
        self.placeholder_text_id = self.img_canvas.create_text(
            300, 200, text="No plot generated yet", fill="white", font=("TkDefaultFont", 14)
        )

    def _check_pillow(self):
        if Image is None:
            messagebox.showwarning(
                APP_TITLE,
                "Pillow is not installed. Image display/conversion will not work.\n"
                "Install it with:  pip install pillow",
            )

    # ------------------------------------------------------------------ #
    # Directory handling
    # ------------------------------------------------------------------ #
    def browse_dir(self):
        d = filedialog.askdirectory(title="Select OpenMC input directory")
        if d:
            self.input_dir.set(d)
            self.scan_directory()

    def scan_directory(self):
        d = self.input_dir.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showerror(APP_TITLE, "Please choose a valid directory.")
            return

        found = sorted(os.listdir(d))
        xml_files = [f for f in found if f.lower().endswith(".xml")]

        has_model = "model.xml" in xml_files
        has_set = all(f in xml_files for f in REQUIRED_SET)

        if not has_model and not has_set:
            msg = (
                "This directory does not look like a complete OpenMC input set.\n"
                f"Expected either model.xml, or all of: {', '.join(REQUIRED_SET)}.\n\n"
                f"Found XML files: {', '.join(xml_files) if xml_files else '(none)'}"
            )
            self.files_label.config(text=msg, foreground="#b00000")
            self.status_var.set("Directory scan: missing required input files.")
            return

        listing = "\n".join(f"- {f}" for f in xml_files) if xml_files else "(no XML files)"
        if "plots.xml" in xml_files:
            listing += "\n\n(plots.xml already exists and will be overwritten)"
        self.files_label.config(text=listing, foreground="#000000")
        self.status_var.set(f"Found valid OpenMC input set in: {d}")

        # Try to auto-populate a sensible default origin/width from geometry bounding box
        self._try_autofill_from_geometry(d)

    def _try_autofill_from_geometry(self, directory):
        """Best-effort: use OpenMC's Python API to get a bounding box and
        suggest origin/width/height. Silently does nothing if unavailable."""
        def worker():
            try:
                import openmc  # noqa
                cwd = os.getcwd()
                os.chdir(directory)
                try:
                    if os.path.exists("model.xml"):
                        model = openmc.Model.from_model_xml("model.xml")
                        geom = model.geometry
                    else:
                        geom = openmc.Geometry.from_xml("geometry.xml")
                    bbox = geom.bounding_box
                    lower, upper = bbox
                    import math
                    if all(math.isfinite(v) for v in list(lower) + list(upper)):
                        cx = (lower[0] + upper[0]) / 2
                        cy = (lower[1] + upper[1]) / 2
                        cz = (lower[2] + upper[2]) / 2
                        w = abs(upper[0] - lower[0]) * 1.05 or 100.0
                        h = abs(upper[1] - lower[1]) * 1.05 or 100.0

                        def apply():
                            self.var_origin_x.set(f"{cx:.4g}")
                            self.var_origin_y.set(f"{cy:.4g}")
                            self.var_origin_z.set(f"{cz:.4g}")
                            self.var_width.set(f"{w:.4g}")
                            self.var_height.set(f"{h:.4g}")
                            self.status_var.set(
                                "Auto-filled origin/width/height from geometry bounding box."
                            )
                        self.after(0, apply)
                finally:
                    os.chdir(cwd)
            except Exception:
                # Non-fatal: user can set params manually.
                pass

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ #
    # Parameter validation & XML generation
    # ------------------------------------------------------------------ #
    def _parse_rgb(self, s, field_name):
        parts = [p.strip() for p in s.split(",")]
        if len(parts) != 3:
            raise ValueError(f"{field_name} must be 'R,G,B' (0-255 each). Got: {s!r}")
        vals = []
        for p in parts:
            try:
                v = int(p)
            except ValueError:
                raise ValueError(f"{field_name} contains a non-integer: {p!r}")
            if not (0 <= v <= 255):
                raise ValueError(f"{field_name} values must be 0-255. Got: {v}")
            vals.append(v)
        return vals

    def _validate_and_collect(self):
        errors = []

        def as_float(var, name):
            try:
                return float(var.get())
            except ValueError:
                errors.append(f"{name} must be a number.")
                return None

        def as_int(var, name, min_val=1):
            try:
                v = int(float(var.get()))
                if v < min_val:
                    errors.append(f"{name} must be >= {min_val}.")
                return v
            except ValueError:
                errors.append(f"{name} must be an integer.")
                return None

        origin = [
            as_float(self.var_origin_x, "Origin X"),
            as_float(self.var_origin_y, "Origin Y"),
            as_float(self.var_origin_z, "Origin Z"),
        ]
        width = as_float(self.var_width, "Width")
        height = as_float(self.var_height, "Height")
        pix_x = as_int(self.var_pix_x, "Pixels X")
        pix_y = as_int(self.var_pix_y, "Pixels Y")

        level = None
        level_str = self.var_level.get().strip()
        if level_str:
            try:
                level = int(level_str)
            except ValueError:
                errors.append("Universe level must be an integer if provided.")

        try:
            background = self._parse_rgb(self.var_background.get(), "Background color")
        except ValueError as e:
            errors.append(str(e))
            background = None

        overlap_color = None
        if self.var_show_overlaps.get():
            try:
                overlap_color = self._parse_rgb(self.var_overlap_color.get(), "Overlap color")
            except ValueError as e:
                errors.append(str(e))

        if width is not None and width <= 0:
            errors.append("Width must be > 0.")
        if height is not None and height <= 0:
            errors.append("Height must be > 0.")

        if errors:
            raise ValueError("\n".join(errors))

        return {
            "basis": self.var_basis.get(),
            "origin": origin,
            "width": width,
            "height": height,
            "pix_x": pix_x,
            "pix_y": pix_y,
            "color_by": self.var_color_by.get(),
            "background": background,
            "level": level,
            "show_overlaps": self.var_show_overlaps.get(),
            "overlap_color": overlap_color,
        }

    def _build_plots_xml_tree(self, params):
        root = ET.Element("plots")
        plot = ET.SubElement(root, "plot", id="1", name="gui_plot")
        plot.set("color_by", params["color_by"])
        plot.set("basis", params["basis"])
        plot.set("type", "slice")

        ET.SubElement(plot, "origin").text = " ".join(f"{v}" for v in params["origin"])
        ET.SubElement(plot, "width").text = f"{params['width']} {params['height']}"
        ET.SubElement(plot, "pixels").text = f"{params['pix_x']} {params['pix_y']}"

        if params["background"] is not None:
            ET.SubElement(plot, "background").text = " ".join(
                str(v) for v in params["background"]
            )

        if params["level"] is not None:
            ET.SubElement(plot, "level").text = str(params["level"])

        if params["show_overlaps"]:
            ET.SubElement(plot, "show_overlaps").text = "true"
            if params["overlap_color"] is not None:
                ET.SubElement(plot, "overlap_color").text = " ".join(
                    str(v) for v in params["overlap_color"]
                )

        return root

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def on_reset_params(self):
        self.var_basis.set("xy")
        self.var_origin_x.set("0.0")
        self.var_origin_y.set("0.0")
        self.var_origin_z.set("0.0")
        self.var_width.set("100.0")
        self.var_height.set("100.0")
        self.var_pix_x.set("600")
        self.var_pix_y.set("600")
        self.var_color_by.set("material")
        self.var_background.set("255,255,255")
        self.var_show_overlaps.set(False)
        self.var_overlap_color.set("255,0,0")
        self.var_level.set("")
        self.status_var.set("Parameters reset to defaults.")

    def _pick_background_color(self):
        rgb, _hexval = colorchooser.askcolor(title="Choose background color")
        if rgb:
            r, g, b = (int(round(c)) for c in rgb)
            self.var_background.set(f"{r},{g},{b}")

    def on_preview_xml(self):
        try:
            params = self._validate_and_collect()
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        root = self._build_plots_xml_tree(params)
        xml_str = pretty_xml(root)

        win = tk.Toplevel(self)
        win.title("plots.xml preview")
        win.geometry("500x500")
        text = tk.Text(win, wrap="none", font=("Courier", 10))
        text.insert("1.0", xml_str)
        text.config(state="normal")
        text.pack(fill="both", expand=True)

    def save_plots_xml_as(self):
        try:
            params = self._validate_and_collect()
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        root = self._build_plots_xml_tree(params)
        xml_str = pretty_xml(root)
        path = filedialog.asksaveasfilename(
            defaultextension=".xml", initialfile="plots.xml",
            filetypes=[("XML files", "*.xml")],
        )
        if path:
            with open(path, "w") as f:
                f.write(xml_str)
            self.status_var.set(f"Saved: {path}")

    def on_generate_and_plot(self):
        d = self.input_dir.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showerror(APP_TITLE, "Please choose a valid input directory first.")
            return

        xml_files = [f for f in os.listdir(d) if f.lower().endswith(".xml")]
        has_model = "model.xml" in xml_files
        has_set = all(f in xml_files for f in REQUIRED_SET)
        if not has_model and not has_set:
            messagebox.showerror(
                APP_TITLE,
                "Directory is missing required OpenMC input files "
                f"(need model.xml, or all of {', '.join(REQUIRED_SET)}).",
            )
            return

        try:
            params = self._validate_and_collect()
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return

        root = self._build_plots_xml_tree(params)
        xml_str = pretty_xml(root)
        plots_path = os.path.join(d, "plots.xml")
        try:
            with open(plots_path, "w") as f:
                f.write(xml_str)
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Could not write plots.xml:\n{e}")
            return

        self.status_var.set("plots.xml written. Running OpenMC plotter...")
        self.run_button.config(state="disabled")
        self.progress.start(12)

        threading.Thread(target=self._run_openmc_plot, args=(d,), daemon=True).start()

    def _run_openmc_plot(self, directory):
        error = None
        image_path = None
        log_output = ""
        try:
            # Clean up old plot outputs so we know which one is fresh
            for pattern in ("plot_*.ppm", "plot_*.png", "*.ppm"):
                for old in glob.glob(os.path.join(directory, pattern)):
                    try:
                        os.remove(old)
                    except OSError:
                        pass

            # Strategy 1: use the OpenMC Python API directly (most reliable --
            # works regardless of whether a CLI entry point is on PATH).
            api_error = None
            api_succeeded = False
            try:
                import openmc  # noqa
                cwd = os.getcwd()
                os.chdir(directory)
                try:
                    openmc.plot_geometry(output=False)
                    api_succeeded = True
                    log_output = "(ran via openmc.plot_geometry() Python API)"
                finally:
                    os.chdir(cwd)
            except Exception as e:
                api_error = e

            if not api_succeeded:
                # Strategy 2: the `openmc` console-script executable.
                # (NOTE: `python -m openmc` does NOT work -- openmc is a
                # package with no __main__.py, so it must be invoked as an
                # executable, not via `-m`.)
                exe = shutil.which("openmc")
                cmd_variants = []
                if exe:
                    cmd_variants.append([exe, "--plot"])
                cmd_variants.append(["openmc", "--plot"])

                last_exc = None
                proc = None
                for cmd in cmd_variants:
                    try:
                        proc = subprocess.run(
                            cmd, cwd=directory, capture_output=True, text=True, timeout=600
                        )
                        break
                    except (FileNotFoundError, OSError) as e:
                        last_exc = e
                        proc = None
                        continue

                if proc is None:
                    raise RuntimeError(
                        "Could not run OpenMC.\n\n"
                        f"Python API attempt failed with: {api_error}\n\n"
                        "The `openmc` command-line executable was also not found "
                        "on PATH. Make sure OpenMC is installed in this Python "
                        "environment (pip/conda install openmc) and, if you rely "
                        "on the CLI, that its Scripts/bin directory is on PATH.\n"
                        f"Last CLI error: {last_exc}"
                    )

                log_output = (proc.stdout or "") + "\n" + (proc.stderr or "")

                if proc.returncode != 0:
                    raise RuntimeError(
                        f"OpenMC exited with code {proc.returncode}.\n\n"
                        f"Output:\n{log_output.strip()[-4000:]}"
                    )

            candidates = sorted(
                glob.glob(os.path.join(directory, "plot_*.ppm"))
                + glob.glob(os.path.join(directory, "plot_*.png"))
                + glob.glob(os.path.join(directory, "*.ppm"))
            )
            if not candidates:
                raise RuntimeError(
                    "OpenMC ran successfully but no plot image (plot_*.ppm/.png) "
                    "was found in the directory.\n\n"
                    f"Output:\n{log_output.strip()[-4000:]}"
                )
            image_path = candidates[-1]

        except Exception as e:
            error = str(e)

        self.after(0, self._on_plot_finished, image_path, error)

    def _on_plot_finished(self, image_path, error):
        self.progress.stop()
        self.run_button.config(state="normal")

        if error:
            self.status_var.set("Error running OpenMC. See dialog for details.")
            messagebox.showerror(APP_TITLE, error)
            return

        if Image is None:
            self.status_var.set(f"Plot created at {image_path}, but Pillow is unavailable to display it.")
            return

        try:
            img = Image.open(image_path)
            img.load()
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"Failed to load generated image:\n{e}")
            self.status_var.set("Failed to load generated image.")
            return

        # Also save a PNG copy alongside for convenience if source was PPM
        try:
            if image_path.lower().endswith(".ppm"):
                png_path = os.path.splitext(image_path)[0] + ".png"
                img.save(png_path)
        except Exception:
            pass

        self.current_image = img
        self.last_zoom = 1.0
        self._render_current_image()
        self.status_var.set(f"Plot displayed from: {image_path}")

    # ------------------------------------------------------------------ #
    # Image display helpers
    # ------------------------------------------------------------------ #
    def _render_current_image(self):
        if self.current_image is None or ImageTk is None:
            return
        w, h = self.current_image.size
        zw, zh = max(1, int(w * self.last_zoom)), max(1, int(h * self.last_zoom))
        display_img = self.current_image.resize((zw, zh), Image.LANCZOS) if (zw, zh) != (w, h) else self.current_image
        self.tk_image = ImageTk.PhotoImage(display_img)

        self.img_canvas.delete("all")
        self.canvas_image_id = self.img_canvas.create_image(0, 0, anchor="nw", image=self.tk_image)
        self.img_canvas.configure(scrollregion=(0, 0, zw, zh))

    def zoom_image(self, factor):
        if self.current_image is None:
            return
        self.last_zoom = max(0.1, min(10.0, self.last_zoom * factor))
        self._render_current_image()

    def fit_image(self):
        if self.current_image is None:
            return
        cw = self.img_canvas.winfo_width() or 600
        ch = self.img_canvas.winfo_height() or 600
        w, h = self.current_image.size
        self.last_zoom = max(0.05, min(cw / w, ch / h))
        self._render_current_image()

    def save_image_as(self):
        if self.current_image is None:
            messagebox.showinfo(APP_TITLE, "No image to save yet.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG image", "*.png"), ("JPEG image", "*.jpg"), ("All files", "*.*")],
        )
        if path:
            try:
                img = self.current_image
                if path.lower().endswith((".jpg", ".jpeg")) and img.mode == "RGBA":
                    img = img.convert("RGB")
                img.save(path)
                self.status_var.set(f"Image saved to: {path}")
            except Exception as e:
                messagebox.showerror(APP_TITLE, f"Failed to save image:\n{e}")


def main():
    app = OpenMCPlotGUI()
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
