"""
Run the Daratha IPWR OpenMC model (model.py) and plot 2D neutron-flux maps
from a mesh tally.

Workflow
  1. Import model.py  -> builds materials/geometry/settings and writes the XML.
  2. Define mesh tallies (this file) and write tallies.xml (overrides the
     simple spectrum tally model.py exported).
  3. openmc.run()
  4. Open the statepoint, pull the tally data, reshape onto the mesh.
  5. Plot flux maps (total + 3 energy groups), a pin-power map, and an axial
     flux profile.

Usage
    export OPENMC_CROSS_SECTIONS=/path/to/cross_sections.xml
    python run_flux_map.py                         # run + plot
    python run_flux_map.py --particles 50000 --batches 200 --inactive 50
    python run_flux_map.py --mesh-n 120            # finer than pin pitch
    python run_flux_map.py --no-run                # just re-plot last statepoint
    python run_flux_map.py --show                  # also open plot windows

Outputs (PNG): flux_map_xy.png, pin_power_xy.png, flux_axial.png

Notes
  * Mesh default is 60 x 60 over the core, i.e. exactly one cell per fuel pin
    (15 pins x 4 assemblies = 60, pitch 1.32 cm). Guide tubes / RCCA tubes show
    up as low-flux or zero-fission cells.
  * Flux is normalized to the 32 MWt core power (kappa-fission based), so the
    absolute scale is n/cm^2/s. Change POWER_W below to rescale.
  * Pin-level maps are statistically noisy with few particles. Use >= 50,000
    particles/batch for smooth maps.
"""

import argparse
import glob
import os

import numpy as np
import openmc

import model  # builds geometry/materials/settings; does NOT run (guarded)

# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------
POWER_W = 32.0e6                       # thermal power for normalization (32 MWt)
EV_TO_J = 1.602176634e-19
ENERGY_EDGES_EV = [0.0, 0.625, 1.0e5, 20.0e6]   # thermal | epithermal | fast
ENERGY_LABELS = ["Thermal (<0.625 eV)",
                 "Epithermal (0.625 eV - 100 keV)",
                 "Fast (>100 keV)"]

# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument("--particles", type=int, default=None)
parser.add_argument("--batches", type=int, default=None)
parser.add_argument("--inactive", type=int, default=None)
parser.add_argument("--mesh-n", type=int, default=60,
                    help="mesh cells per side over the core (60 = 1 per pin)")
parser.add_argument("--axial-bins", type=int, default=56)
parser.add_argument("--no-run", action="store_true",
                    help="skip the transport run; plot the existing statepoint")
parser.add_argument("--show", action="store_true", help="show plot windows")
args = parser.parse_args()

import matplotlib
if not args.show:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

# ---------------------------------------------------------------------------
# 1. Settings overrides
# ---------------------------------------------------------------------------
if args.particles:
    model.settings.particles = args.particles
if args.batches:
    model.settings.batches = args.batches
if args.inactive is not None:
    model.settings.inactive = args.inactive
if model.settings.inactive >= model.settings.batches:
    raise SystemExit("inactive batches must be < total batches")

# ---------------------------------------------------------------------------
# 2. Mesh tallies
# ---------------------------------------------------------------------------
hw = model.core_half_width                       # 39.6 cm
z_half = model.ACTIVE_LENGTH_CM / 2.0            # 55 cm
z_ext = z_half + model.AXIAL_REFLECTOR_CM        # 85 cm (incl. axial reflector)
n = args.mesh_n

# 2D radial mesh: whole core, one axial bin spanning the active length
mesh_xy = openmc.RegularMesh(name="core_xy")
mesh_xy.dimension = (n, n, 1)
mesh_xy.lower_left = (-hw, -hw, -z_half)
mesh_xy.upper_right = (hw, hw, z_half)

# Axial profile mesh: single radial cell over the core, bins in z (incl. reflectors)
nz = args.axial_bins
mesh_z = openmc.RegularMesh(name="core_axial")
mesh_z.dimension = (1, 1, nz)
mesh_z.lower_left = (-hw, -hw, -z_ext)
mesh_z.upper_right = (hw, hw, z_ext)

mf_xy = openmc.MeshFilter(mesh_xy)
mf_z = openmc.MeshFilter(mesh_z)
ef = openmc.EnergyFilter(ENERGY_EDGES_EV)

t_flux = openmc.Tally(name="flux_xy")
t_flux.filters = [mf_xy]
t_flux.scores = ["flux"]

t_flux_g = openmc.Tally(name="flux_xy_groups")
t_flux_g.filters = [mf_xy, ef]            # mesh = slow index, energy = fast index
t_flux_g.scores = ["flux"]

t_fis = openmc.Tally(name="kappa_fission_xy")
t_fis.filters = [mf_xy]
t_fis.scores = ["kappa-fission"]

t_ax = openmc.Tally(name="axial")
t_ax.filters = [mf_z]
t_ax.scores = ["flux", "kappa-fission"]

tallies = openmc.Tallies([t_flux, t_flux_g, t_fis, t_ax])

# ---------------------------------------------------------------------------
# 3. Write XML + run
# ---------------------------------------------------------------------------
sp_path = f"statepoint.{model.settings.batches}.h5"

if not args.no_run:
    model.materials.export_to_xml()
    model.geometry.export_to_xml()
    model.settings.export_to_xml()
    tallies.export_to_xml()
    if os.path.exists(sp_path):
        os.remove(sp_path)
    openmc.run()
else:
    # use the newest statepoint present
    found = sorted(glob.glob("statepoint.*.h5"),
                   key=lambda p: int(p.split(".")[1]))
    if not found:
        raise SystemExit("No statepoint.*.h5 found; run without --no-run first.")
    sp_path = found[-1]

# ---------------------------------------------------------------------------
# 4. Read statepoint
# ---------------------------------------------------------------------------
print(f"\nReading {sp_path}")
sp = openmc.StatePoint(sp_path)
try:
    keff = sp.keff
    print(f"k-eff = {keff.nominal_value:.5f} +/- {keff.std_dev:.5f}")
except AttributeError:
    print("k-eff =", sp.k_combined)

tf = sp.get_tally(name="flux_xy")
tg = sp.get_tally(name="flux_xy_groups")
tk = sp.get_tally(name="kappa_fission_xy")
ta = sp.get_tally(name="axial")

# Mesh bin ordering: x varies fastest, then y, then z -> reshape (nz, ny, nx).
def xy(vec):
    return np.asarray(vec).reshape(1, n, n)[0]

dx = 2 * hw / n
cell_vol_xy = dx * dx * model.ACTIVE_LENGTH_CM          # cm^3

# --- Power normalization: source rate [n/s] from total kappa-fission --------
kappa_mean = tk.mean.ravel()                             # eV per source particle
kappa_total_J = kappa_mean.sum() * EV_TO_J               # J per source particle
src_rate = POWER_W / kappa_total_J                       # source particles / s
print(f"Source rate for {POWER_W/1e6:.1f} MWt: {src_rate:.3e} n/s")

# --- Total flux map [n/cm^2/s] ----------------------------------------------
flux_tot = xy(tf.mean.ravel()) / cell_vol_xy * src_rate
flux_tot_sd = xy(tf.std_dev.ravel()) / cell_vol_xy * src_rate

# --- Group flux maps ---------------------------------------------------------
ng = len(ENERGY_LABELS)
g_mean = tg.mean.reshape(n * n, ng)
flux_g = [xy(g_mean[:, g]) / cell_vol_xy * src_rate for g in range(ng)]

# --- Pin power (relative) ----------------------------------------------------
fis = xy(kappa_mean)
nonzero = fis > 0.02 * fis.max()
pin_rel = np.where(nonzero, fis / fis[nonzero].mean(), np.nan)
print(f"Radial peak / average (fueled cells, mesh {n}x{n}): "
      f"{np.nanmax(pin_rel):.3f}")

mask = flux_tot > 0
rel_err = np.where(mask, flux_tot_sd / np.where(mask, flux_tot, 1), np.nan)
print(f"Mean relative std. dev. of flux per mesh cell: {np.nanmean(rel_err)*100:.2f}%")

# ---------------------------------------------------------------------------
# 5. Plots
# ---------------------------------------------------------------------------
extent = [-hw, hw, -hw, hw]
pitch = model.ASSEM_PITCH_CM
grid = np.arange(-hw, hw + 1e-6, pitch)


def draw_assembly_grid(ax):
    for g in grid:
        ax.axvline(g, color="white", lw=0.6, alpha=0.7)
        ax.axhline(g, color="white", lw=0.6, alpha=0.7)


def panel(ax, data, title, cmap="inferno", label="n/cm$^2$/s"):
    im = ax.imshow(data, origin="lower", extent=extent, cmap=cmap,
                   interpolation="nearest")
    draw_assembly_grid(ax)
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("x [cm]")
    ax.set_ylabel("y [cm]")
    cb = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label(label)


# Figure 1: total + 3 energy groups
fig1, axes = plt.subplots(2, 2, figsize=(12, 10))
panel(axes[0, 0], flux_tot, "Total flux (mid-core, active length avg)")
for g, ax in zip(range(ng), [axes[0, 1], axes[1, 0], axes[1, 1]]):
    panel(ax, flux_g[g], ENERGY_LABELS[g])
fig1.suptitle(f"Daratha IPWR - neutron flux, {POWER_W/1e6:.0f} MWt "
              f"(Gd2O3={model.MODEL_GD2O3_ABSORBER}, RCCA={model.MODEL_RCCA_RODS})",
              fontsize=12)
fig1.tight_layout()
fig1.savefig("flux_map_xy.png", dpi=200)

# Figure 2: relative pin power
fig2, ax2 = plt.subplots(figsize=(7, 6))
panel(ax2, pin_rel, "Relative fission power (pin-resolved)", cmap="viridis",
      label="power / avg fueled-cell power")
fig2.tight_layout()
fig2.savefig("pin_power_xy.png", dpi=200)

# Figure 3: axial profile
z_edges = np.linspace(-z_ext, z_ext, nz + 1)
z_mid = 0.5 * (z_edges[1:] + z_edges[:-1])
dz = z_edges[1] - z_edges[0]
vol_ax = (2 * hw) ** 2 * dz
ax_flux = ta.get_slice(scores=["flux"]).mean.ravel() / vol_ax * src_rate
ax_fis = ta.get_slice(scores=["kappa-fission"]).mean.ravel()

fig3, ax3 = plt.subplots(figsize=(7, 5))
ax3.plot(z_mid, ax_flux, "o-", ms=3, label="Flux (core-avg)")
ax3.set_xlabel("z [cm]")
ax3.set_ylabel("Flux [n/cm$^2$/s]")
ax3.axvspan(-z_half, z_half, color="orange", alpha=0.12, label="Active fuel")
ax3b = ax3.twinx()
ax3b.plot(z_mid, ax_fis / ax_fis.max(), "s--", ms=3, color="crimson",
          label="Relative fission power")
ax3b.set_ylabel("Relative fission power")
h1, l1 = ax3.get_legend_handles_labels()
h2, l2 = ax3b.get_legend_handles_labels()
ax3.legend(h1 + h2, l1 + l2, loc="lower center")
ax3.set_title("Axial profile")
fig3.tight_layout()
fig3.savefig("flux_axial.png", dpi=200)

print("\nWrote flux_map_xy.png, pin_power_xy.png, flux_axial.png")
if args.show:
    plt.show()
