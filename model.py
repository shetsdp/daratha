"""
OpenMC criticality (k-eff) model for the Daratha Atomics 10 MWe / 32 MWt
Integral PWR, built from the parameters in:

  "Engineering a Factory-Manufactured 10 MWe Integral PWR for India"
  Daratha Atomics, Technical Thesis and Engineering Basis, September 2026.

This is a BASIC unrodded, unpoisoned (no burnable absorber), fixed-temperature
k-eff model. See PARAMETERS.md in this folder for exactly which numbers come
from the whitepaper vs. which are engineering assumptions filled in to make
the model runnable (pin/clad/gap dimensions, guide tube size, absorber
loading, reflector thicknesses -- none of these are given in the paper).

Usage:
    export OPENMC_CROSS_SECTIONS=/path/to/endfb-viii.0-hdf5/cross_sections.xml
    python model.py
"""

import numpy as np
import openmc

# ---------------------------------------------------------------------------
# 1. PARAMETERS
# ---------------------------------------------------------------------------

# --- From the whitepaper (Sec 2.1, 2.2, Fig 1) ---------------------------
N_ASSEM_SIDE      = 4                 # 4x4 assembly array
ASSEM_LATTICE     = 15                # 15x15 pin lattice per assembly
PINS_PER_ASSEM    = 204               # fuel pins per assembly
GUIDE_PER_ASSEM   = 21                # guide/control tubes per assembly
ACTIVE_LENGTH_CM  = 110.0             # 1.10 m active fuel length
CORE_WIDTH_M      = 0.792             # 4x4 array footprint width
CORE_BARREL_ID_M  = 1.15
RPV_ID_M          = 1.50
FUEL_ENRICH_WT    = 4.0               # wt% U-235
PRIMARY_PRES_MPA  = 15.5
T_INLET_C         = 285.0
T_OUTLET_C        = 320.0

# --- Derived directly from the above (arithmetic) -----------
ASSEM_PITCH_CM = CORE_WIDTH_M * 100.0 / N_ASSEM_SIDE      # 19.8 cm
PIN_PITCH_CM   = ASSEM_PITCH_CM / ASSEM_LATTICE           # 1.32 cm
assert ASSEM_LATTICE**2 == PINS_PER_ASSEM + GUIDE_PER_ASSEM

# --- Engineering assumptions (NOT given in the whitepaper) ----------------
# See PARAMETERS.md for rationale. Change these freely as real design data
# becomes available.
FUEL_OD_CM        = 0.92     # fuel pellet outer diameter
GAP_OD_CM         = 0.936    # fuel-clad gap outer diameter (He gap)
CLAD_OD_CM        = 1.075    # cladding outer diameter (Zircaloy-4)
GT_INNER_OD_CM    = 1.10     # guide tube inner (water) diameter
GT_OUTER_OD_CM    = 1.20     # guide tube outer diameter
AXIAL_REFLECTOR_CM = 30.0    # water reflector above/below active fuel
BARREL_THK_CM      = 3.0     # core barrel steel thickness (assumed)
RPV_WALL_THK_CM    = 7.0     # RPV wall thickness (assumed, not from paper)

T_CORE_AVG_K = (((T_INLET_C + T_OUTLET_C) / 2.0) + 273.15)  # ~575.65 K

# ---------------------------------------------------------------------------
# 2. MATERIALS
# ---------------------------------------------------------------------------

fuel = openmc.Material(name="UO2 fuel, 4.0 wt% U-235")
fuel.add_element("U", 1.0, enrichment=FUEL_ENRICH_WT)
fuel.add_element("O", 2.0)
fuel.set_density("g/cm3", 10.4)  # typical PWR UO2 sintered density (~96% TD)
fuel.temperature = T_CORE_AVG_K

helium = openmc.Material(name="He gap gas")
helium.add_element("He", 1.0)
helium.set_density("g/cm3", 0.0015)
helium.temperature = T_CORE_AVG_K

clad = openmc.Material(name="Zircaloy-4 cladding")
clad.add_element("Zr", 0.982)
clad.add_element("Sn", 0.014)
clad.add_element("Fe", 0.002)
clad.add_element("Cr", 0.001)
clad.add_element("O", 0.001)
clad.set_density("g/cm3", 6.56)
clad.temperature = T_CORE_AVG_K

# Borated-water baseline is 0 ppm per the paper (zero-soluble-boron strategy)
water = openmc.Material(name="Light water moderator/coolant, 0 ppm B")
water.add_element("H", 2.0)
water.add_element("O", 1.0)
water.set_density("g/cm3", 0.72)  # approx density of water at ~303 C, 15.5 MPa
water.temperature = T_CORE_AVG_K
water.add_s_alpha_beta("c_H_in_H2O")

guide_tube_water = water.clone()
guide_tube_water.name = "Guide tube water (unrodded)"

steel = openmc.Material(name="SS304 (core barrel / RPV, structural)")
steel.add_element("Fe", 0.695)
steel.add_element("Cr", 0.190)
steel.add_element("Ni", 0.095)
steel.add_element("Mn", 0.020)
steel.set_density("g/cm3", 8.0)

materials = openmc.Materials(
    [fuel, helium, clad, water, guide_tube_water, steel]
)
materials.cross_sections = None  # set via OPENMC_CROSS_SECTIONS env var

# ---------------------------------------------------------------------------
# 3. GEOMETRY
# ---------------------------------------------------------------------------

# --- 3a. Fuel pin cell -----------------------------------------------------
fuel_or   = openmc.ZCylinder(r=FUEL_OD_CM / 2.0)
gap_or    = openmc.ZCylinder(r=GAP_OD_CM / 2.0)
clad_or   = openmc.ZCylinder(r=CLAD_OD_CM / 2.0)

fuel_cell = openmc.Cell(name="fuel", fill=fuel, region=-fuel_or)
gap_cell  = openmc.Cell(name="gap", fill=helium, region=+fuel_or & -gap_or)
clad_cell = openmc.Cell(name="clad", fill=clad, region=+gap_or & -clad_or)
mod_cell  = openmc.Cell(name="pin_moderator", fill=water, region=+clad_or)

fuel_pin_universe = openmc.Universe(
    name="fuel_pin", cells=[fuel_cell, gap_cell, clad_cell, mod_cell]
)

# --- 3b. Guide tube cell (unrodded: filled with water) ---------------------
gt_ir = openmc.ZCylinder(r=GT_INNER_OD_CM / 2.0)
gt_or = openmc.ZCylinder(r=GT_OUTER_OD_CM / 2.0)

gt_water_cell = openmc.Cell(name="gt_water_inner", fill=guide_tube_water, region=-gt_ir)
gt_clad_cell  = openmc.Cell(name="gt_tube_wall", fill=clad, region=+gt_ir & -gt_or)
gt_mod_cell   = openmc.Cell(name="gt_moderator", fill=water, region=+gt_or)

guide_tube_universe = openmc.Universe(
    name="guide_tube", cells=[gt_water_cell, gt_clad_cell, gt_mod_cell]
)

# --- 3c. 15x15 assembly lattice --------------------------------------------
# Guide/control tube pattern: a simple, roughly-centered/symmetric placement
# of 21 guide tubes in a 15x15 array is used since the paper gives no
# published lattice map. This is a reasonable generic PWR-like pattern, not
# a design-specific one -- replace with the real map when available.
assembly_map = np.full((ASSEM_LATTICE, ASSEM_LATTICE), fuel_pin_universe, dtype=object)

guide_tube_positions = [
    (2, 2), (2, 7), (2, 12),
    (4, 4), (4, 7), (4, 10),
    (7, 2), (7, 4), (7, 10), (7, 12),
    (7, 7),   # instrument/center tube counted among the 21
    (10, 4), (10, 7), (10, 10),
    (12, 2), (12, 7), (12, 12),
    (4, 2), (4, 12), (10, 2), (10, 12),
]
assert len(guide_tube_positions) == GUIDE_PER_ASSEM

for (i, j) in guide_tube_positions:
    assembly_map[i, j] = guide_tube_universe

assembly_lattice = openmc.RectLattice(name="15x15 fuel assembly")
assembly_lattice.lower_left = (-ASSEM_PITCH_CM / 2.0, -ASSEM_PITCH_CM / 2.0)
assembly_lattice.pitch = (PIN_PITCH_CM, PIN_PITCH_CM)
assembly_lattice.universes = assembly_map

assembly_prism = openmc.model.RectangularPrism(
    width=ASSEM_PITCH_CM, height=ASSEM_PITCH_CM, boundary_type="transmission"
)
assembly_cell = openmc.Cell(name="assembly_interior", fill=assembly_lattice, region=-assembly_prism)
assembly_universe = openmc.Universe(name="assembly", cells=[assembly_cell])

# --- 3d. 4x4 core lattice of assemblies ------------------------------------
core_lattice = openmc.RectLattice(name="4x4 core")
core_lattice.lower_left = (-CORE_WIDTH_M * 100.0 / 2.0, -CORE_WIDTH_M * 100.0 / 2.0)
core_lattice.pitch = (ASSEM_PITCH_CM, ASSEM_PITCH_CM)
core_lattice.universes = np.full(
    (N_ASSEM_SIDE, N_ASSEM_SIDE), assembly_universe, dtype=object
)

# --- 3e. Radial regions: core -> barrel -> downcomer -> RPV wall -----------
core_half_width = CORE_WIDTH_M * 100.0 / 2.0
core_prism = openmc.model.RectangularPrism(
    width=CORE_WIDTH_M * 100.0, height=CORE_WIDTH_M * 100.0, boundary_type="transmission"
)
core_box = -core_prism  # region inside the prism (used for the core-lattice cell)

barrel_id_cm = CORE_BARREL_ID_M * 100.0
barrel_od_cm = barrel_id_cm + 2 * BARREL_THK_CM
rpv_id_cm    = RPV_ID_M * 100.0
rpv_od_cm    = rpv_id_cm + 2 * RPV_WALL_THK_CM

barrel_inner_cyl = openmc.ZCylinder(r=barrel_id_cm / 2.0)
barrel_outer_cyl = openmc.ZCylinder(r=barrel_od_cm / 2.0)
rpv_inner_cyl    = openmc.ZCylinder(r=rpv_id_cm / 2.0)
rpv_outer_cyl    = openmc.ZCylinder(r=rpv_od_cm / 2.0, boundary_type="vacuum")

z_bottom = openmc.ZPlane(z0=-(ACTIVE_LENGTH_CM / 2.0 + AXIAL_REFLECTOR_CM), boundary_type="vacuum")
z_top    = openmc.ZPlane(z0=+(ACTIVE_LENGTH_CM / 2.0 + AXIAL_REFLECTOR_CM), boundary_type="vacuum")
z_active_bottom = openmc.ZPlane(z0=-ACTIVE_LENGTH_CM / 2.0)
z_active_top    = openmc.ZPlane(z0=+ACTIVE_LENGTH_CM / 2.0)

axial_region = +z_bottom & -z_top

core_cell = openmc.Cell(
    name="core_lattice_region",
    fill=core_lattice,
    region=core_box & +z_active_bottom & -z_active_top,
)

# Water reflector between core edge and core barrel ID, active-length height
inner_reflector_cell = openmc.Cell(
    name="inner_radial_reflector",
    fill=water,
    region=~core_box & -barrel_inner_cyl & +z_active_bottom & -z_active_top,
)

# Axial water reflectors above/below the active core, out to barrel ID
bottom_reflector_cell = openmc.Cell(
    name="bottom_axial_reflector",
    fill=water,
    region=-barrel_inner_cyl & +z_bottom & -z_active_bottom,
)
top_reflector_cell = openmc.Cell(
    name="top_axial_reflector",
    fill=water,
    region=-barrel_inner_cyl & +z_active_top & -z_top,
)

barrel_cell = openmc.Cell(
    name="core_barrel",
    fill=steel,
    region=+barrel_inner_cyl & -barrel_outer_cyl & +z_bottom & -z_top,
)
downcomer_cell = openmc.Cell(
    name="downcomer",
    fill=water,
    region=+barrel_outer_cyl & -rpv_inner_cyl & +z_bottom & -z_top,
)
rpv_wall_cell = openmc.Cell(
    name="rpv_wall",
    fill=steel,
    region=+rpv_inner_cyl & -rpv_outer_cyl & +z_bottom & -z_top,
)

root_universe = openmc.Universe(
    name="root",
    cells=[
        core_cell,
        inner_reflector_cell,
        bottom_reflector_cell,
        top_reflector_cell,
        barrel_cell,
        downcomer_cell,
        rpv_wall_cell,
    ],
)

geometry = openmc.Geometry(root_universe)

# ---------------------------------------------------------------------------
# 4. SETTINGS
# ---------------------------------------------------------------------------

settings = openmc.Settings()
settings.run_mode = "eigenvalue"
settings.particles = 10000
settings.batches = 150
settings.inactive = 30
settings.temperature = {"method": "interpolation"}

# Initial fission source: uniform box over the active core region
lower_left  = (-core_half_width, -core_half_width, -ACTIVE_LENGTH_CM / 2.0)
upper_right = (core_half_width, core_half_width, ACTIVE_LENGTH_CM / 2.0)
settings.source = openmc.IndependentSource(
    space=openmc.stats.Box(lower_left, upper_right, only_fissionable=True)
)

# ---------------------------------------------------------------------------
# 5. TALLIES (optional but useful: flux/fission-rate spectrum sanity checks)
# ---------------------------------------------------------------------------

tallies = openmc.Tallies()
energy_filter = openmc.EnergyFilter(np.logspace(-5, 7, 50))
spectrum_tally = openmc.Tally(name="flux_spectrum")
spectrum_tally.filters = [energy_filter]
spectrum_tally.scores = ["flux"]
tallies.append(spectrum_tally)

# ---------------------------------------------------------------------------
# 6. EXPORT AND RUN
# ---------------------------------------------------------------------------

materials.export_to_xml()
geometry.export_to_xml()
settings.export_to_xml()
tallies.export_to_xml()

if __name__ == "__main__":
    # Runs the k-eff transport calculation. plot_geometry.py imports this
    # file as a module instead (materials/geometry/settings/tallies are
    # already built and XML-exported above by the time this line is
    # reached), so it never hits this branch and no transport solve happens
    # just to make a plot.
    openmc.run()
