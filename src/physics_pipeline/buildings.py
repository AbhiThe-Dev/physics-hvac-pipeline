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
)


def get_building(building_id: str) -> BaseBuilding:
    for b in BASE_BUILDINGS:
        if b.building_id == building_id:
            return b
    raise KeyError(building_id)
