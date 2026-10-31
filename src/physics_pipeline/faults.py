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

from pathlib import Path

import openstudio

# Same fixed "typical hydronic coil" heat-transfer assumptions EnergyPlus's
# own WaterCoils::EstimateHEXSurfaceArea (Nigusse, FSEC, July 2010) uses to
# split a *cooling* coil's lumped UA into an area+U pair for its sizing
# report: 2 m/s tube water velocity, ~0.5in (0.0122m) tube ID, Ai/Ao=0.07,
# 92% fin efficiency, 140 W/m2C combined air-side film coefficient. These
# constants are coil-size-independent by construction -- the whole point of
# the correlation is to give a plausible physical area from nothing but a
# coil's own UA, without needing real geometry inputs the "simple" water
# coil objects don't carry. Confirmed bit-exact against EnergyPlus's own
# reported "Nominal Coil Surface Area" for a Coil:Cooling:Water (907.08 m2
# for a coil with UA=89433.17 W/K: 89433.17 * _U_OVERALL_INV == 907.08).
_AREA_RATIO = 0.07  # Ai/Ao; also the IDD's own default for this field
_H_WATER_TUBE_INSIDE = 1429.0 * (2.0**0.8) * (0.0122**-0.2)  # W/m2C
_H_AIR_TUBE_OUTSIDE = 58.0 + 82.0  # W/m2C (sensible + latent-equivalent)
_OVERALL_FIN_EFFICIENCY = 0.92
_U_OVERALL_INV = 1.0 / (_H_WATER_TUBE_INSIDE * _AREA_RATIO) + 1.0 / (_H_AIR_TUBE_OUTSIDE * _OVERALL_FIN_EFFICIENCY)  # m2-K/W


def estimate_coil_surface_area(eio_path: Path, coil_name: str, coil_idd_type: str) -> tuple[float, float]:
    """Estimates a simple water coil's Outside Coil Surface Area (and
    returns the standard Inside-to-Outside Ratio alongside it) from that
    SAME coil's own EnergyPlus sizing output -- never a fixed/hardcoded
    number, since a `Coil:Cooling:Water`/`Coil:Heating:Water` object has no
    physical geometry field to read off directly (that's the whole reason
    `add_coil_fouling_fault` previously shipped with these two IDD fields
    unset, which was the actual root cause of the fouling fault appearing
    to have "no effect" on a reheat coil and "total collapse" on a central
    cooling coil -- both were the SAME missing-input bug, just surfaced two
    different ways by two different EnergyPlus-internal code paths).

    For Coil:Cooling:Water, EnergyPlus already computes and reports this
    exact area itself (`WaterCoils::EstimateHEXSurfaceArea`) in
    eplusout.eio's "Water Cooling Coil Capacity Information" line -- parsed
    directly here, not re-derived, since there's no reason to duplicate a
    computation EnergyPlus has already done and published for this specific
    coil. For Coil:Heating:Water (which EnergyPlus's own source doesn't
    extend that reporting to), the same fixed conversion constant is
    applied by hand to the coil's own sized "U-Factor Times Area Value"
    from eplusout.eio's "Component Sizing Information" section -- the
    physical assumptions behind the correlation (hydronic tube-and-fin
    coil construction) are just as applicable to a heating coil's hardware
    as a cooling coil's, EnergyPlus just never wrote the reporting code for
    it. Requires `eio_path` to be from a sizing pass that has ALREADY run
    for this exact model (e.g. the baseline/uncorrupted simulation this
    pipeline already runs for comparison) -- the coil must be autosized (or
    at least have gone through EnergyPlus's sizing pass) for these numbers
    to exist at all."""
    text = eio_path.read_text(errors="replace")
    name_upper = coil_name.strip().upper()

    if coil_idd_type == "Coil:Cooling:Water":
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line.startswith("Water Cooling Coil Capacity Information"):
                continue
            parts = [p.strip() for p in line.split(",")]
            # Component Type, Name, Total Cap, Sens Cap, Latent Cap, SHR, UA, Surface Area
            if len(parts) >= 9 and parts[2].upper() == name_upper:
                return float(parts[8]), _AREA_RATIO
        raise ValueError(
            f"no 'Water Cooling Coil Capacity Information' line for coil {coil_name!r} in {eio_path} "
            "-- was this coil actually simulated (and autosized) in that run?"
        )

    if coil_idd_type == "Coil:Heating:Water":
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line.startswith("Component Sizing Information, Coil:Heating:Water"):
                continue
            if "U-Factor Times Area Value" not in line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5 and parts[2].upper() == name_upper:
                ua = float(parts[-1])
                return ua * _U_OVERALL_INV, _AREA_RATIO
        raise ValueError(
            f"no sized 'U-Factor Times Area Value' for coil {coil_name!r} in {eio_path} "
            "-- was this coil's UA actually autosized (Performance Input Method = "
            "UFactorTimesAreaAndDesignWaterFlowRate) in that run?"
        )

    raise ValueError(f"surface-area estimation is only implemented for hydronic coils, not {coil_idd_type!r}")


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
    outside_coil_surface_area: float,
    inside_to_outside_area_ratio: float = 0.07,
    coil_idd_type: str = "Coil:Cooling:Water",
    water_side_fouling_factor: float = 0.005,
    air_side_fouling_factor: float = 0.0,
    availability_schedule: str = "Always_On",
    severity_schedule: str = "Always_On",
) -> bool:
    """Injects `FaultModel:Fouling:Coil` referencing a `Coil:Cooling:Water`
    (or other supported coil type) object by name, using the
    "FoulingFactor" input method (physical thermal-resistance units,
    m2-K/W) rather than "FouledUARated" -- the latter needs the coil's
    rated UA, which isn't known before a sizing run.

    0.005 m2-K/W is a single fixed "moderate" default, deliberately NOT
    scaled by the blueprint's corruption `severity` -- this pipeline has no
    severity-to-fault-magnitude convention anywhere (`severity` everywhere
    else means "number of corruption events," a purely structural count;
    `add_thermostat_offset_fault`'s one existing physical fault also uses a
    single fixed 5 degC regardless of severity). This value replaces an
    earlier default (0.0005) that was tuned against the broken math below
    (see the surface-area docstring) and, once that bug was fixed, turned
    out to produce a sub-1% effect -- nowhere near "moderate." Re-validated
    across three structurally different coils after the fix: sys07's
    reheat coil (small, UA~1117 W/K) shows a 45% output reduction, sys08's
    central cooling coil (large, UA~89433 W/K) shows 8%, sys05's reheat
    coil (different building, UA~707 W/K) shows 50% -- all clearly
    detectable, none collapse toward 0, matching a single fixed physical
    fouling deposit producing different relative impact on differently
    sized coils, the same way a fixed 5 degC thermostat offset has
    different relative impact on different zones.

    `outside_coil_surface_area` has NO default and must be supplied by the
    caller (see `estimate_coil_surface_area`) -- leaving it unset was the
    root cause of a real bug found while widening the batch to sys05/sys06:
    the `Rfoul = rwater/(Aout*Aratio) + rair/Aout` formula this fault uses
    (EnergyPlus Engineering Reference 11.2.3.2) divides by this field, and
    an unset/blank value reads as 0.0, which made the fault either produce
    zero measurable effect or collapse the coil's output to exactly 0.0 W,
    depending on which EnergyPlus-internal coil-type code path applied it --
    never a moderate, physically-plausible degradation either way. Making
    this a required parameter here (rather than silently defaulting it)
    closes off that exact failure mode from recurring: a caller now has to
    have gone through the derivation, not just forgotten a field."""
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
    fault.setDouble(8, outside_coil_surface_area)
    fault.setDouble(9, inside_to_outside_area_ratio)
    return workspace.addObject(fault).is_initialized()
