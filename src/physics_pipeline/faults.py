"""EnergyPlus Operational Fault injection.

OpenStudio's `openstudio.model` Python API has no wrapper class for any of
EnergyPlus's `FaultModel:*` objects (checked: nothing case-insensitively
matching "fault" in `dir(openstudio.model)`, out of ~4800 names), even
though the E+ IDD defines over a dozen of them (thermostat/humidistat
offset, sensor offsets, coil/boiler/chiller/tower/filter fouling, ...).
Faults are therefore added as raw IDF objects on the `Workspace` returned by
`ForwardTranslator.translateModel()`, *after* Model-level editing is done --
a well-documented E+-only pattern, just not exposed through OpenStudio's
typed Model API.

Structural corruption (rewire.py) and fault injection (this module) are
kept fully independent: a fault is applied to a `Workspace` that has already
been forward-translated from whatever Model you hand it (rewired or not),
and neither knows about the other's existence.
"""

from __future__ import annotations

import openstudio


def add_thermostat_offset_fault(
    workspace: "openstudio.Workspace",
    zone_name: str,
    offset_degC: float = 5.0,
    availability_schedule: str = "Always_On",
    severity_schedule: str = "Always_On",
) -> bool:
    """Injects `FaultModel:ThermostatOffset` referencing `<zone_name>
    Thermostat` (the `ZoneControl:Thermostat` name OpenStudio's forward
    translator always generates for a zone with a thermostat). Returns False
    if no matching thermostat object exists in the workspace."""
    thermostat_name = f"{zone_name} Thermostat"
    matches = [
        o
        for o in workspace.getObjectsByType(openstudio.IddObjectType("ZoneControl:Thermostat"))
        if o.getString(0).get() == thermostat_name
    ]
    if not matches:
        return False

    fault = openstudio.IdfObject(openstudio.IddObjectType("FaultModel:ThermostatOffset"))
    fault.setString(0, f"Fault Thermostat Offset {zone_name}")
    fault.setString(1, thermostat_name)
    fault.setString(2, availability_schedule)
    fault.setString(3, severity_schedule)
    fault.setDouble(4, offset_degC)
    return workspace.addObject(fault).is_initialized()


def add_coil_fouling_fault(
    workspace: "openstudio.Workspace",
    coil_name: str,
    coil_idd_type: str = "Coil:Cooling:Water",
    water_side_fouling_factor: float = 0.0005,
    air_side_fouling_factor: float = 0.0,
    availability_schedule: str = "Always_On",
    severity_schedule: str = "Always_On",
) -> bool:
    """Injects `FaultModel:Fouling:Coil` referencing a `Coil:Cooling:Water`
    (or other supported coil type) object by name, using the
    "FoulingFactor" input method (physical thermal-resistance units,
    m2-K/W) rather than "FouledUARated" -- the latter needs the coil's
    rated UA, which isn't known before a sizing run. 0.0005 m2-K/W is a
    moderate, clearly-detectable water-side fouling deposit."""
    matches = [o for o in workspace.getObjectsByType(openstudio.IddObjectType(coil_idd_type))
               if o.getString(0).get() == coil_name]
    if not matches:
        return False

    fault = openstudio.IdfObject(openstudio.IddObjectType("FaultModel:Fouling:Coil"))
    fault.setString(0, f"Fault Coil Fouling {coil_name}")
    fault.setString(1, coil_name)
    fault.setString(2, availability_schedule)
    fault.setString(3, severity_schedule)
    fault.setString(4, "FoulingFactor")
    # index 5 (UAFouled) intentionally left unset: only used by FouledUARated
    fault.setDouble(6, water_side_fouling_factor)
    fault.setDouble(7, air_side_fouling_factor)
    return workspace.addObject(fault).is_initialized()
