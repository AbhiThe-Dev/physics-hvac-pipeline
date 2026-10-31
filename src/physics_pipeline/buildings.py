"""Registry of the base building models used by this foundation pipeline.

Per the license finding in Step 0 (the DOE prototype buildings repo the
project eventually wants has no license and its real generator code lives
in openstudio-standards, which needs a Ruby toolchain to run), and the
confirmed decision to defer real DOE prototypes, these are small test
fixtures from NREL/OpenStudio-resources (same org, same clear BSD-3 license
as the OpenStudio SDK itself) -- picked for genuinely different HVAC
topologies (different terminal-unit classes, different central plant
equipment), not different building shapes. Confirmed minimal scope: 2
topologies x 1 climate zone.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PHYSICS_PIPELINE_ROOT = Path(__file__).resolve().parents[2]
VENDOR = PHYSICS_PIPELINE_ROOT / "vendor"

ENERGYPLUS_DIR = VENDOR / "EnergyPlus-25.2.0-cf7368216c-Darwin-macOS13-arm64"
ENERGYPLUS_BIN = ENERGYPLUS_DIR / "energyplus"
ENERGYPLUS_IDD = ENERGYPLUS_DIR / "Energy+.idd"

WEATHER_FILE = ENERGYPLUS_DIR / "WeatherData" / "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw"
CLIMATE_LABEL = "Chicago-OHare_TMY3_ASHRAE-CZ5A-cold"

RESOURCES_DIR = VENDOR / "OpenStudio-resources" / "model" / "simulationtests"


@dataclass(frozen=True)
class BaseBuilding:
    building_id: str
    osm_path: Path
    description: str
    hvac_summary: str


BASE_BUILDINGS: tuple[BaseBuilding, ...] = (
    BaseBuilding(
        building_id="sys08_vav_parallel_piu",
        osm_path=RESOURCES_DIR / "baseline_sys08.osm",
        description="10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building "
        "(NREL/OpenStudio-resources, BSD-3-Clause)",
        hvac_summary="1 AHU (VAV fan, chilled-water cooling coil, electric heating coil) -> "
        "10 Parallel-PIU-Reheat VAV terminals -> 10 zones; chilled-water plant with 1 pump/chiller",
    ),
    BaseBuilding(
        building_id="sys07_vav_reheat",
        osm_path=RESOURCES_DIR / "baseline_sys07.osm",
        description="10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building "
        "(NREL/OpenStudio-resources, BSD-3-Clause)",
        hvac_summary="1 AHU (VAV fan, chilled-water cooling coil) -> 10 VAV-Reheat terminals "
        "(hot-water reheat coils) -> 10 zones; separate chilled-water and hot-water plants "
        "(chiller + condenser loop, boiler)",
    ),
    BaseBuilding(
        building_id="sys05_vav_reheat_dx",
        osm_path=RESOURCES_DIR / "baseline_sys05.osm",
        description="10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building "
        "(NREL/OpenStudio-resources, BSD-3-Clause)",
        hvac_summary="1 AHU (VAV fan, DX cooling coil) -> 10 VAV-Reheat terminals (hot-water reheat "
        "coils) -> 10 zones; a single hot-water plant (1 pump/boiler) -- the cooling coil is DX, "
        "not on any plant loop, so this building has only ONE medium/pump, unlike sys07's two",
    ),
    BaseBuilding(
        building_id="sys06_vav_piu_dx",
        osm_path=RESOURCES_DIR / "baseline_sys06.osm",
        description="10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building "
        "(NREL/OpenStudio-resources, BSD-3-Clause)",
        hvac_summary="1 AHU (VAV fan, DX cooling coil, electric heating coil) -> 10 Parallel-PIU-Reheat "
        "VAV terminals (electric reheat) -> 10 zones; NO plant loop and NO pump anywhere in the "
        "building -- fully DX/electric",
    ),
    BaseBuilding(
        building_id="sys01_ptac",
        osm_path=RESOURCES_DIR / "baseline_sys01.osm",
        description="10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building "
        "(NREL/OpenStudio-resources, BSD-3-Clause)",
        hvac_summary="10 zone-level Packaged Terminal Air Conditioners (PTAC), NO AirLoopHVAC at all "
        "-- each unit: DX cooling coil (no plant loop) + hydronic heating coil, all 10 sharing ONE "
        "hot-water plant (1 pump/boiler). Required new extract.py/rewire.py code paths, not a "
        "drop-in reuse of the AirLoopHVAC-based mechanisms sys05-sys08 share.",
    ),
    BaseBuilding(
        building_id="sys02_pthp",
        osm_path=RESOURCES_DIR / "baseline_sys02.osm",
        description="10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building "
        "(NREL/OpenStudio-resources, BSD-3-Clause)",
        hvac_summary="10 zone-level Packaged Terminal Heat Pumps (PTHP), NO AirLoopHVAC at all -- "
        "each unit: DX cooling coil AND DX heating coil, zero PlantLoops/pumps anywhere in the "
        "building. Reuses sys01's new packaged-unit extract.py/rewire.py code paths directly; its "
        "own zero-collision-risk/zero-coil-target-events status was independently confirmed, not "
        "inherited from sys01 or sys06.",
    ),
    BaseBuilding(
        building_id="sys03_psz_ac",
        osm_path=RESOURCES_DIR / "baseline_sys03.osm",
        description="10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building "
        "(NREL/OpenStudio-resources, BSD-3-Clause)",
        hvac_summary="10 dedicated single-zone AirLoopHVACs (PSZ-AC), one per zone, not one shared "
        "central AHU -- each with its own DX cooling coil, gas heating coil, fan, and "
        "AirTerminal:SingleDuct:ConstantVolume:NoReheat pass-through terminal. NO PlantLoop "
        "anywhere. Required new rewire.py handling for single-zone-per-airloop topology: a "
        "dedicated AHU left with zero zones after a branch removal is invalid EnergyPlus input "
        "(the whole airloop must be deleted, not just the branch); its SetpointManager:SingleZone:* "
        "must be retargeted (not deleted) when the airloop survives with a different zone, and a "
        "from/to-airloop aliasing case (two zones temporarily sharing one airloop) that segfaulted "
        "before being fixed.",
    ),
    BaseBuilding(
        building_id="sys04_psz_hp",
        osm_path=RESOURCES_DIR / "baseline_sys04.osm",
        description="10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building "
        "(NREL/OpenStudio-resources, BSD-3-Clause)",
        hvac_summary="10 dedicated single-zone AirLoopHVACs (PSZ-HP), same architecture as sys03 -- "
        "each with DX cooling, DX heating, electric backup heating, a fan, and an "
        "AirTerminal:SingleDuct:ConstantVolume:NoReheat pass-through terminal. NO PlantLoop anywhere. "
        "All sys03 rewire.py fixes (airloop deletion, setpoint-manager retarget, aliasing guard) "
        "confirmed to carry over directly -- verified with its own full sweep, not assumed.",
    ),
    BaseBuilding(
        building_id="sys09_furnace_gas",
        osm_path=RESOURCES_DIR / "baseline_sys09.osm",
        description="10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building "
        "(NREL/OpenStudio-resources, BSD-3-Clause)",
        hvac_summary="10 dedicated single-zone AirLoopHVACs, same architecture as sys03/04 but "
        "heating-only (gas furnace, no cooling coil at all) -- each with a Coil:Heating:Gas, a fan, "
        "and an AirTerminal:SingleDuct:ConstantVolume:NoReheat pass-through terminal. NO PlantLoop "
        "anywhere. Same rewire.py fixes as sys03/04 apply directly.",
    ),
    BaseBuilding(
        building_id="sys10_furnace_electric",
        osm_path=RESOURCES_DIR / "baseline_sys10.osm",
        description="10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building "
        "(NREL/OpenStudio-resources, BSD-3-Clause)",
        hvac_summary="10 dedicated single-zone AirLoopHVACs, same architecture as sys09 but electric "
        "resistance heat instead of gas -- each with a Coil:Heating:Electric, a fan, and an "
        "AirTerminal:SingleDuct:ConstantVolume:NoReheat pass-through terminal. NO PlantLoop anywhere. "
        "Surfaced a fourth variant of the setpoint-manager issue found on sys03 -- "
        "`set_ahu_direct_service`'s own AHU-direct move (not just `_remove_branch_safely`'s callers) "
        "needed the same capture-before-move-and-retarget fix, found on an actual production-scope "
        "seed (severity 3), not just an exploratory one.",
    ),
)


def get_building(building_id: str) -> BaseBuilding:
    for b in BASE_BUILDINGS:
        if b.building_id == building_id:
            return b
    raise KeyError(building_id)
