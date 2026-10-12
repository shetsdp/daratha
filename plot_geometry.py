"""
Geometry plots for the Daratha Atomics 10 MWe IPWR OpenMC model.

Produces:
  1. A radial (XY) slice at the core midplane, zoomed to one fuel
     assembly -- shows individual fuel pins / guide tubes.
  2. A radial (XY) slice at the core midplane, zoomed to the full core --
     shows the 4x4 assembly array, core barrel, downcomer and RPV wall.
  3. An axial (XZ) slice through the core centerline -- shows active fuel
     height, axial water reflectors, barrel and RPV wall.

This script imports model.py, which builds and XML-exports the materials
and geometry as a side effect of being imported (see the guard at the
bottom of model.py) -- it does NOT run a k-eff transport calculation, only
geometry plotting, which is fast and does not require cross-section data
to be loaded for a transport solve (OpenMC's plotter still needs
materials.xml and geometry.xml to exist, i.e. cross_sections.xml must be
resolvable, but no particles are actually transported).

Usage:
    export OPENMC_CROSS_SECTIONS=/path/to/endfb-viii.0-hdf5/cross_sections.xml
    python plot_geometry.py

Produces PNG files: assembly_xy.png, core_xy.png, core_xz.png
"""

import openmc

# Importing model.py builds materials/geometry/settings/tallies and writes
# their XML files as a side effect (openmc.run() itself is guarded behind
# `if __name__ == "__main__"` in model.py, so it does NOT execute here).
import modelold

# ---------------------------------------------------------------------------
# Color scheme: one consistent color per material across all three plots
# ---------------------------------------------------------------------------
colors = {
    modelold.fuel: "firebrick",
    modelold.helium: "gold",
    modelold.clad: "lightsteelblue",
    modelold.water: "deepskyblue",
    modelold.guide_tube_water: "royalblue",
    modelold.steel: "dimgray",
}

# ---------------------------------------------------------------------------
# Plot 1: single assembly, radial (XY) slice at core midplane
# ---------------------------------------------------------------------------
assembly_plot = openmc.Plot(name="assembly_xy")
assembly_plot.filename = "assembly_xy"
assembly_plot.basis = "xy"
assembly_plot.origin = (0.0, 0.0, 0.0)  # core midplane, z=0
assembly_plot.width = (modelold.ASSEM_PITCH_CM * 1.05, modelold.ASSEM_PITCH_CM * 1.05)
assembly_plot.pixels = (1200, 1200)
assembly_plot.color_by = "material"
assembly_plot.colors = colors
assembly_plot.background = "white"

# ---------------------------------------------------------------------------
# Plot 2: full core, radial (XY) slice at core midplane
# ---------------------------------------------------------------------------
core_xy_plot = openmc.Plot(name="core_xy")
core_xy_plot.filename = "core_xy"
core_xy_plot.basis = "xy"
core_xy_plot.origin = (0.0, 0.0, 0.0)
full_width_cm = modelold.rpv_od_cm * 1.05
core_xy_plot.width = (full_width_cm, full_width_cm)
core_xy_plot.pixels = (1600, 1600)
core_xy_plot.color_by = "material"
core_xy_plot.colors = colors
core_xy_plot.background = "white"

# ---------------------------------------------------------------------------
# Plot 3: full vessel, axial (XZ) slice through the centerline
# ---------------------------------------------------------------------------
core_xz_plot = openmc.Plot(name="core_xz")
core_xz_plot.filename = "core_xz"
core_xz_plot.basis = "xz"
core_xz_plot.origin = (0.0, 0.0, 0.0)
total_height_cm = 2 * (modelold.ACTIVE_LENGTH_CM / 2.0 + modelold.AXIAL_REFLECTOR_CM) * 1.05
core_xz_plot.width = (full_width_cm, total_height_cm)
core_xz_plot.pixels = (1200, 1600)
core_xz_plot.color_by = "material"
core_xz_plot.colors = colors
core_xz_plot.background = "white"

plots = openmc.Plots([assembly_plot, core_xy_plot, core_xz_plot])
plots.export_to_xml()

if __name__ == "__main__":
    # openmc.plot_geometry() calls the `openmc-plot` C++ binary (ray-traces
    # the geometry -- fast, no transport physics, no cross-section
    # temperature interpolation needed) and writes PNGs named after each
    # Plot's `filename`.
    openmc.plot_geometry()
    print("Wrote assembly_xy.png, core_xy.png, core_xz.png")
