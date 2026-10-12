"""
OpenMC criticality (k-eff) model for the Daratha Atomics 10 MWe / 32 MWt
Integral PWR, built from the parameters in:

  "Engineering a Factory-Manufactured 10 MWe Integral PWR for India"
  Daratha Atomics, Technical Thesis and Engineering Basis, September 2026.

Two optional features named in the whitepaper (but not specified in enough
detail to be unambiguous) can be toggled in Section 1. Set both to False to
reproduce the base case (unrodded, unpoisoned, k-eff ~1.18):

  1. Gd2O3 burnable absorber: 12 of 204 fuel-pin positions per assembly use
     UO2 + 4.0 wt% Gd2O3 (paper Sec 2.1: "12 pins/assembly with 4.0 wt%
     Gd2O3; requirement still under review").
  2. RCCAs (Rod Cluster Control Assemblies): Ag-In-Cd rods inserted into the
     guide tubes of 12 of the 16 assemblies (paper Sec 2.1: "12 RCCAs;
     current design target SDM >5.5% delta-k/k with highest-worth rod stuck
     out").

The Gd2O3 loading pattern, RCCA material/geometry, rod-capable tube count
and rodded-assembly map are NOT in the whitepaper. The values used here are
generic PWR-family placeholders, not Daratha's actual design choices.

Requires OpenMC 0.14+ (openmc.model.RectangularPrism) and cross-section data
(e.g. ENDF/B-VIII.0) with OPENMC_CROSS_SECTIONS set to cross_sections.xml.

Usage:
    export OPENMC_CROSS_SECTIONS=/path/to/endfb-viii.0-hdf5/cross_sections.xml
    python model.py
"""

import numpy as np
import openmc

# ---------------------------------------------------------------------------
# 1. PARAMETERS
# ---------------------------------------------------------------------------

# --- Feature toggles --------------------------------------------------------
MODEL_GD2O3_ABSORBER = True   # False -> no burnable absorber
MODEL_RCCA_RODS      = False   # False -> guide tubes left as water (all rods out)

# --- From the whitepaper (Sec 2.1, 2.2, Fig 1) ------------------------------
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

GD_PINS_PER_ASSEM = 12                # "12 pins/assembly with 4.0 wt% Gd2O3"
GD2O3_WT_FRACTION = 0.04              # 4.0 wt% Gd2O3 in the pin
N_RCCA_TOTAL      = 12                # "12 RCCAs": interpreted as 12 of the 16
                                      # assemblies each receiving a rod cluster
                                      # (ambiguous in the paper)

# --- Derived arithmetic -----------------------------------------------------
ASSEM_PITCH_CM = CORE_WIDTH_M * 100.0 / N_ASSEM_SIDE      # 19.8 cm
PIN_PITCH_CM   = ASSEM_PITCH_CM / ASSEM_LATTICE           # 1.32 cm
assert ASSEM_LATTICE**2 == PINS_PER_ASSEM + GUIDE_PER_ASSEM

# --- Engineering assumptions (NOT in the whitepaper) ------------------------
FUEL_OD_CM         = 0.92     # fuel pellet outer diameter
GAP_OD_CM          = 0.936    # fuel-clad gap outer diameter (He)
CLAD_OD_CM         = 1.075    # cladding outer diameter (Zircaloy-4)
GT_INNER_OD_CM     = 1.10     # guide tube inner diameter
GT_OUTER_OD_CM     = 1.20     # guide tube outer diameter
AXIAL_REFLECTOR_CM = 30.0     # water reflector above/below active fuel
BARREL_THK_CM      = 3.0      # core barrel thickness
RPV_WALL_THK_CM    = 7.0      # RPV wall thickness

RCCA_ABSORBER_OD_CM = 0.86    # Ag-In-Cd slug OD
RCCA_CLAD_OD_CM     = 0.98    # stainless clad OD
assert RCCA_CLAD_OD_CM < GT_INNER_OD_CM, "RCCA rod must fit inside the guide tube"

T_CORE_AVG_K = ((T_INLET_C + T_OUTLET_C) / 2.0) + 273.15  # ~575.65 K

# ---------------------------------------------------------------------------
# 2. MATERIALS
# ---------------------------------------------------------------------------

fuel = openmc.Material(name="UO2 fuel, 4.0 wt% U-235")
fuel.add_element("U", 1.0, enrichment=FUEL_ENRICH_WT)
fuel.add_element("O", 2.0)
fuel.set_density("g/cm3", 10.4)
fuel.temperature = T_CORE_AVG_K

# UO2 + Gd2O3 homogeneous pin: 96 wt% UO2 (4 wt% enriched) + 4 wt% Gd2O3.
# All components are given as weight fractions (do not mix 'ao' and 'wo').
_M_U, _M_O, _M_GD = 238.0, 16.0, 157.0
_w_uo2  = 1.0 - GD2O3_WT_FRACTION
_w_gd2o3 = GD2O3_WT_FRACTION
_m_uo2   = _M_U + 2 * _M_O
_m_gd2o3 = 2 * _M_GD + 3 * _M_O

gd_fuel = openmc.Material(name="UO2 + 4.0 wt% Gd2O3 burnable absorber")
gd_fuel.add_element("U", _w_uo2 * _M_U / _m_uo2, percent_type="wo",
                    enrichment=FUEL_ENRICH_WT)
gd_fuel.add_element("Gd", _w_gd2o3 * 2 * _M_GD / _m_gd2o3, percent_type="wo")
gd_fuel.add_element(
    "O",
    _w_uo2 * 2 * _M_O / _m_uo2 + _w_gd2o3 * 3 * _M_O / _m_gd2o3,
    percent_type="wo",
)
gd_fuel.set_density("g/cm3", 10.0)
gd_fuel.temperature = T_CORE_AVG_K

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

# 0 ppm soluble boron (paper's zero-soluble-boron baseline)
water = openmc.Material(name="Light water, 0 ppm B")
water.add_element("H", 2.0)
water.add_element("O", 1.0)
water.set_density("g/cm3", 0.72)   # ~303 C, 15.5 MPa
water.temperature = T_CORE_AVG_K
water.add_s_alpha_beta("c_H_in_H2O")

guide_tube_water = water.clone()
guide_tube_water.name = "Guide tube water (unrodded)"

rcca_gap_water = water.clone()
rcca_gap_water.name = "RCCA rod-to-tube clearance water"

steel = openmc.Material(name="SS304 (core barrel / RPV)")
steel.add_element("Fe", 0.695)
steel.add_element("Cr", 0.190)
steel.add_element("Ni", 0.095)
steel.add_element("Mn", 0.020)
steel.set_density("g/cm3", 8.0)

rcca_absorber = openmc.Material(name="Ag-In-Cd RCCA absorber")
rcca_absorber.add_element("Ag", 0.80)
rcca_absorber.add_element("In", 0.15)
rcca_absorber.add_element("Cd", 0.05)
rcca_absorber.set_density("g/cm3", 10.16)

rcca_clad = openmc.Material(name="RCCA rod clad (SS304)")
rcca_clad.add_element("Fe", 0.70)
rcca_clad.add_element("Cr", 0.19)
rcca_clad.add_element("Ni", 0.10)
rcca_clad.add_element("Mn", 0.01)
rcca_clad.set_density("g/cm3", 8.0)

materials_list = [fuel, helium, clad, water, guide_tube_water, steel]
if MODEL_GD2O3_ABSORBER:
    materials_list.append(gd_fuel)
if MODEL_RCCA_RODS:
    materials_list += [rcca_absorber, rcca_clad, rcca_gap_water]

materials = openmc.Materials(materials_list)

# ---------------------------------------------------------------------------
# 3. GEOMETRY
# ---------------------------------------------------------------------------

# --- 3a. Plain UO2 fuel pin -------------------------------------------------
fuel_or = openmc.ZCylinder(r=FUEL_OD_CM / 2.0)
gap_or  = openmc.ZCylinder(r=GAP_OD_CM / 2.0)
clad_or = openmc.ZCylinder(r=CLAD_OD_CM / 2.0)

fuel_pin_universe = openmc.Universe(name="fuel_pin", cells=[
    openmc.Cell(name="fuel", fill=fuel, region=-fuel_or),
    openmc.Cell(name="gap", fill=helium, region=+fuel_or & -gap_or),
    openmc.Cell(name="clad", fill=clad, region=+gap_or & -clad_or),
    openmc.Cell(name="pin_moderator", fill=water, region=+clad_or),
])

# --- 3a-bis. Gd2O3 burnable-absorber pin (same geometry, different fuel) ----
gd_pin_universe = openmc.Universe(name="gd_pin", cells=[
    openmc.Cell(name="gd_fuel", fill=gd_fuel, region=-fuel_or),
    openmc.Cell(name="gd_gap", fill=helium, region=+fuel_or & -gap_or),
    openmc.Cell(name="gd_clad", fill=clad, region=+gap_or & -clad_or),
    openmc.Cell(name="gd_pin_moderator", fill=water, region=+clad_or),
])

# --- 3b. Guide tube, unrodded (water-filled) --------------------------------
gt_ir = openmc.ZCylinder(r=GT_INNER_OD_CM / 2.0)
gt_or = openmc.ZCylinder(r=GT_OUTER_OD_CM / 2.0)

guide_tube_universe = openmc.Universe(name="guide_tube", cells=[
    openmc.Cell(name="gt_water_inner", fill=guide_tube_water, region=-gt_ir),
    openmc.Cell(name="gt_tube_wall", fill=clad, region=+gt_ir & -gt_or),
    openmc.Cell(name="gt_moderator", fill=water, region=+gt_or),
])

# --- 3b-bis. Guide tube with RCCA rod inserted ------------------------------
# absorber -> rod clad -> water clearance -> tube wall -> moderator
rcca_rod_or  = openmc.ZCylinder(r=RCCA_ABSORBER_OD_CM / 2.0)
rcca_clad_or = openmc.ZCylinder(r=RCCA_CLAD_OD_CM / 2.0)

rcca_universe = openmc.Universe(name="rcca_rod", cells=[
    openmc.Cell(name="rcca_absorber", fill=rcca_absorber, region=-rcca_rod_or),
    openmc.Cell(name="rcca_clad", fill=rcca_clad, region=+rcca_rod_or & -rcca_clad_or),
    openmc.Cell(name="rcca_clearance", fill=rcca_gap_water, region=+rcca_clad_or & -gt_ir),
    openmc.Cell(name="rcca_tube_wall", fill=clad, region=+gt_ir & -gt_or),
    openmc.Cell(name="rcca_moderator", fill=water, region=+gt_or),
])

# --- 3c. Lattice position maps (row, col) in the 15x15 assembly -------------
# Generic symmetric placeholders; the whitepaper publishes no lattice map.
guide_tube_positions = [
    (2, 2), (2, 7), (2, 12),
    (4, 4), (4, 7), (4, 10),
    (7, 2), (7, 4), (7, 10), (7, 12),
    (7, 7),                      # center tube: instrument tube, never rodded
    (10, 4), (10, 7), (10, 10),
    (12, 2), (12, 7), (12, 12),
    (4, 2), (4, 12), (10, 2), (10, 12),
]
assert len(guide_tube_positions) == GUIDE_PER_ASSEM
assert len(set(guide_tube_positions)) == GUIDE_PER_ASSEM

# 20 rod-capable tubes (all except the center instrument tube), inserted
# together as one cluster when an assembly is "rodded".
rcca_rod_positions = [p for p in guide_tube_positions if p != (7, 7)]

# 12 Gd2O3 pins, chosen from fuel-pin (non-guide-tube) positions.
gd_pin_positions = [
    (1, 1), (1, 7), (1, 13),
    (13, 1), (13, 7), (13, 13),
    (4, 1), (10, 1), (4, 13), (10, 13),
    (1, 4), (1, 10),
]
assert len(gd_pin_positions) == GD_PINS_PER_ASSEM
assert len(set(gd_pin_positions)) == GD_PINS_PER_ASSEM
assert set(gd_pin_positions).isdisjoint(guide_tube_positions), \
    "Gd2O3 pins must not overlap guide tubes"


def build_assembly_universe(name, rodded, gd_loaded):
    """One 15x15 assembly. rodded -> RCCA rods in 20 guide tubes;
    gd_loaded -> 12 pins replaced by UO2+Gd2O3."""
    amap = np.full((ASSEM_LATTICE, ASSEM_LATTICE), fuel_pin_universe, dtype=object)
    for (i, j) in guide_tube_positions:
        amap[i, j] = guide_tube_universe
    if rodded:
        for (i, j) in rcca_rod_positions:
            amap[i, j] = rcca_universe
    if gd_loaded:
        for (i, j) in gd_pin_positions:
            amap[i, j] = gd_pin_universe

    lattice = openmc.RectLattice(name=f"{name}_lattice")
    lattice.lower_left = (-ASSEM_PITCH_CM / 2.0, -ASSEM_PITCH_CM / 2.0)
    lattice.pitch = (PIN_PITCH_CM, PIN_PITCH_CM)
    lattice.universes = amap

    prism = openmc.model.RectangularPrism(
        width=ASSEM_PITCH_CM, height=ASSEM_PITCH_CM, boundary_type="transmission"
    )
    cell = openmc.Cell(name=f"{name}_interior", fill=lattice, region=-prism)
    return openmc.Universe(name=name, cells=[cell])


gd_flag_options  = [True, False] if MODEL_GD2O3_ABSORBER else [False]
rod_flag_options = [True, False] if MODEL_RCCA_RODS else [False]

assembly_universes = {}
for gd_flag in gd_flag_options:
    for rod_flag in rod_flag_options:
        assembly_universes[(rod_flag, gd_flag)] = build_assembly_universe(
            f"assembly_rod{int(rod_flag)}_gd{int(gd_flag)}",
            rodded=rod_flag, gd_loaded=gd_flag,
        )

# --- 3d. 4x4 core map -------------------------------------------------------
# Gd2O3 in every assembly; RCCAs in 12 of 16 assemblies (4 corners unrodded).
core_positions = [(r, c) for r in range(N_ASSEM_SIDE) for c in range(N_ASSEM_SIDE)]
last = N_ASSEM_SIDE - 1
corner_positions = {(0, 0), (0, last), (last, 0), (last, last)}
rodded_core_positions = set(core_positions) - corner_positions
assert len(rodded_core_positions) == N_RCCA_TOTAL

core_map = np.empty((N_ASSEM_SIDE, N_ASSEM_SIDE), dtype=object)
for (r, c) in core_positions:
    is_rodded = MODEL_RCCA_RODS and (r, c) in rodded_core_positions
    core_map[r, c] = assembly_universes[(is_rodded, MODEL_GD2O3_ABSORBER)]

core_lattice = openmc.RectLattice(name="4x4 core")
core_lattice.lower_left = (-CORE_WIDTH_M * 100.0 / 2.0, -CORE_WIDTH_M * 100.0 / 2.0)
core_lattice.pitch = (ASSEM_PITCH_CM, ASSEM_PITCH_CM)
core_lattice.universes = core_map

# --- 3e. Radial/axial regions: core -> barrel -> downcomer -> RPV wall ------
core_half_width = CORE_WIDTH_M * 100.0 / 2.0
core_prism = openmc.model.RectangularPrism(
    width=CORE_WIDTH_M * 100.0, height=CORE_WIDTH_M * 100.0,
    boundary_type="transmission",
)
core_box = -core_prism

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

core_cell = openmc.Cell(
    name="core_lattice_region", fill=core_lattice,
    region=core_box & +z_active_bottom & -z_active_top,
)
inner_reflector_cell = openmc.Cell(
    name="inner_radial_reflector", fill=water,
    region=~core_box & -barrel_inner_cyl & +z_active_bottom & -z_active_top,
)
bottom_reflector_cell = openmc.Cell(
    name="bottom_axial_reflector", fill=water,
    region=-barrel_inner_cyl & +z_bottom & -z_active_bottom,
)
top_reflector_cell = openmc.Cell(
    name="top_axial_reflector", fill=water,
    region=-barrel_inner_cyl & +z_active_top & -z_top,
)
barrel_cell = openmc.Cell(
    name="core_barrel", fill=steel,
    region=+barrel_inner_cyl & -barrel_outer_cyl & +z_bottom & -z_top,
)
downcomer_cell = openmc.Cell(
    name="downcomer", fill=water,
    region=+barrel_outer_cyl & -rpv_inner_cyl & +z_bottom & -z_top,
)
rpv_wall_cell = openmc.Cell(
    name="rpv_wall", fill=steel,
    region=+rpv_inner_cyl & -rpv_outer_cyl & +z_bottom & -z_top,
)

root_universe = openmc.Universe(name="root", cells=[
    core_cell, inner_reflector_cell, bottom_reflector_cell, top_reflector_cell,
    barrel_cell, downcomer_cell, rpv_wall_cell,
])
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

lower_left  = (-core_half_width, -core_half_width, -ACTIVE_LENGTH_CM / 2.0)
upper_right = (core_half_width, core_half_width, ACTIVE_LENGTH_CM / 2.0)
settings.source = openmc.IndependentSource(
    space=openmc.stats.Box(lower_left, upper_right, only_fissionable=True)
)

# ---------------------------------------------------------------------------
# 5. TALLIES
# ---------------------------------------------------------------------------

tallies = openmc.Tallies()
spectrum_tally = openmc.Tally(name="flux_spectrum")
spectrum_tally.filters = [openmc.EnergyFilter(np.logspace(-5, 7, 50))]
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
    print(f"MODEL_GD2O3_ABSORBER = {MODEL_GD2O3_ABSORBER}")
    print(f"MODEL_RCCA_RODS      = {MODEL_RCCA_RODS}")
    if MODEL_RCCA_RODS:
        print(f"Rodded assemblies ({len(rodded_core_positions)}): "
              f"{sorted(rodded_core_positions)}")
    # plot_geometry.py imports this module, so no transport solve happens there.
    openmc.run()
