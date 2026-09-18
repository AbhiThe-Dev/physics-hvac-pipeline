"""End-to-end orchestration for one base building: extract the true
topology, generate a corrupted blueprint (reusing hvac_benchmark's own
corruption logic unmodified), physically rewire a scratch copy of the model
to confirm the blueprint's claim is a constructible configuration, inject an
independent performance fault on the TRUE model near the corruption site to
generate a symptom signal, then run the existing troubleshooting-mode
Bayesian trial using the CURRENT placeholder noise rates (0/5/15%) --
exactly as scoped: prove the pipeline end to end, not calibrate anything.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import openstudio

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))  # ../../../src -> hvac_benchmark

from hvac_benchmark.config import BenchmarkConfig
from hvac_benchmark.data.ontology import BrickOntology
from hvac_benchmark.experiment.blueprint import Blueprint, symptom_flagged_nodes
from hvac_benchmark.experiment.troubleshooting_runner import (
    TROUBLESHOOTING_BLIND_POLICIES,
    TROUBLESHOOTING_SYMPTOM_POLICIES,
    TroubleshootingTrialResult,
    run_troubleshooting_trial,
)

from . import faults as faults_mod
from . import rewire as rewire_mod
from . import simulate as sim_mod
from .buildings import BaseBuilding, ENERGYPLUS_BIN, ENERGYPLUS_IDD, WEATHER_FILE
from .extract import extract_topology, to_hvac_benchmark_graph
from .scope import generate_scoped_blueprint


def _resolve(model: "openstudio.model.Model", node_id: str):
    obj = model.getModelObject(openstudio.toUUID(node_id))
    if not obj.is_initialized():
        return None
    return obj.get()


def _zone_of(obj) -> "openstudio.model.ThermalZone | None":
    z = obj.to_ThermalZone()
    return z.get() if z.is_initialized() else None


@dataclass
class PhysicalPlausibilityRecord:
    event_index: int
    corruption_type: str
    target_brick_type: str | None
    rewired: bool
    reason: str
    forward_translation_ok: bool | None = None
    severe_errors: int | None = None
    warning_count: int | None = None
    # Coil-targeted events only: does the corrupted coil actually deliver a
    # functional effect, checked in a season-appropriate window against a
    # true baseline, rather than trusting severe_errors==0 alone -- a coil
    # misattributed across water media can run with 0 severe errors while
    # delivering exactly 0 W (found on this pipeline's own "clean" results:
    # a heating coil moved onto a chilled-water pump showed 0.0 W heating
    # rate at every hour of a January re-check, no error, no crash).
    functional_check_done: bool = False
    functional_variable: str | None = None
    functional_window: str | None = None
    baseline_output_w: float | None = None
    corrupted_output_w: float | None = None
    functionally_dead: bool | None = None


@dataclass
class FaultInjectionRecord:
    fault_type: str
    target_zone_or_coil: str
    injected: bool
    baseline_sim_ok: bool
    faulted_sim_ok: bool
    max_abs_deviation: float | None
    mean_deviation: float | None
    variable: str


@dataclass
class BuildingRunBundle:
    building: BaseBuilding
    building_id: str
    tg: object  # hvac_benchmark.graph.networkx_build.TopologyGraph
    n_nodes: int
    n_feeds_edges: int
    node_type_counts: dict[str, int]
    blueprints: list[Blueprint] = field(default_factory=list)
    plausibility: dict[int, list[PhysicalPlausibilityRecord]] = field(default_factory=dict)  # corruption_seed -> records
    fault_records: dict[int, FaultInjectionRecord] = field(default_factory=dict)  # corruption_seed -> record
    trial_results: list[TroubleshootingTrialResult] = field(default_factory=list)


def load_and_extract(building: BaseBuilding):
    translator = openstudio.osversion.VersionTranslator()
    model = translator.loadModel(openstudio.path(str(building.osm_path))).get()
    bid, config_type, nx_graph, edges_by_relation, extraction = extract_topology(
        model, building.building_id, "synthetic_physics"
    )
    tg = to_hvac_benchmark_graph(bid, config_type, nx_graph, edges_by_relation)
    return model, tg, extraction


def _find_zone_fed_by(tg, terminal_id: str) -> str | None:
    for s, t in tg.edges_by_relation["feeds"]:
        if s == terminal_id and tg.node_type(t) == "HVAC_Zone":
            return t
    return None


_COIL_TARGET_TYPES = ("Cooling_Coil", "Heating_Coil")


def _resolve_pump(model, node_id: str):
    obj = _resolve(model, node_id)
    if obj is None:
        return None
    for accessor in ("to_PumpVariableSpeed", "to_PumpConstantSpeed"):
        opt = getattr(obj, accessor)()
        if opt.is_initialized():
            return opt.get()
    return None


def _resolve_coil(model, node_id: str):
    obj = _resolve(model, node_id)
    if obj is None:
        return None
    for accessor in ("to_CoilCoolingWater", "to_CoilHeatingWater"):
        opt = getattr(obj, accessor)()
        if opt.is_initialized():
            return opt.get()
    return None


def _handle_coil_event(model, tg, event) -> tuple[bool, str]:
    """Pump<->coil dispatch, mirroring the zone dispatch below: removal
    fully deletes the coil (the only way to represent "no pump feeds this
    coil" that EnergyPlus will actually simulate -- confirmed in Step 0 that
    a half-connected coil is not valid input); fabrication and
    misattribution are the same physical operation (move the coil's plant
    connection), since a coil's water side can only be on one plant loop at
    a time."""
    stale_note = (
        " -- this node was resolvable when generate_blueprint drew this event, so it was most "
        "likely destroyed as a side effect of physically applying an EARLIER event in this same "
        "blueprint to this same scratch model (e.g. a reheat coil deleted along with the terminal "
        "it belonged to, when a fabrication/misattribution event on a different, unrelated zone "
        "happened to pick that terminal's zone as its target); not a bug in this event's own rewire"
    )

    if event.corruption_type == "removal":
        s, t = event.discordant_pairs[0]
        coil = _resolve_coil(model, t)
        if coil is None:
            return False, f"could not resolve coil {t!r} for removal{stale_note}"
        ok = rewire_mod.remove_coil_service(model, coil)
        return ok, "fully removed the coil (no pump feeds it, blueprint claims no connection)"

    if event.corruption_type == "fabrication":
        s, t = event.discordant_pairs[0]
    else:  # misattribution
        (_s_true, t), (s, _t_wrong) = event.discordant_pairs

    pump = _resolve_pump(model, s)
    coil = _resolve_coil(model, t)
    if pump is None or coil is None:
        missing = ("pump" if pump is None else "") + ("+coil" if pump is None and coil is None else "coil" if coil is None else "")
        return False, f"could not resolve {missing} ({s!r}, {t!r}){stale_note}"
    ok = rewire_mod.reassign_coil(model, coil, pump)
    verb = "fabricated" if event.corruption_type == "fabrication" else "misattributed"
    if ok:
        return True, f"moved the coil's plant connection to the {verb} pump's loop"
    return False, f"attempted to move the coil's plant connection to the {verb} pump's loop, " \
                  "but the rewire call itself failed"


def _coil_variable_and_window(target_type: str) -> tuple[str, tuple[int, int, int, int]]:
    """A heating coil needs a heating-season window to be exercised at all
    -- checked in July, essentially every reheat coil (true or corrupted)
    reads near-zero, which would make a genuinely dead coil indistinguishable
    from a normally-quiet one. Cooling coils keep the July window already
    used elsewhere in this pipeline."""
    if target_type == "Heating_Coil":
        return "Heating Coil Heating Rate", (1, 1, 1, 3)
    return "Cooling Coil Total Cooling Rate", (7, 1, 7, 3)


def _query_series(sql_path: Path, variable: str, key_upper: str) -> list[float]:
    import sqlite3

    con = sqlite3.connect(sql_path)
    cur = con.cursor()
    cur.execute(
        "SELECT rd.Value FROM ReportData rd "
        "JOIN ReportDataDictionary rdd ON rd.ReportDataDictionaryIndex = rdd.ReportDataDictionaryIndex "
        "JOIN Time t ON rd.TimeIndex = t.TimeIndex "
        "WHERE rdd.Name=? AND rdd.KeyValue=? AND t.EnvironmentPeriodIndex=("
        "  SELECT MAX(EnvironmentPeriodIndex) FROM EnvironmentPeriods)"
        "ORDER BY rd.TimeIndex",
        (variable, key_upper),
    )
    rows = [r[0] for r in cur.fetchall()]
    con.close()
    return rows


_DEAD_COIL_THRESHOLD_W = 50.0  # baseline must clear this to count as "was actually active"


@dataclass
class CoilFunctionalResult:
    variable: str
    window: str
    baseline_output_w: float
    corrupted_output_w: float
    functionally_dead: bool


def check_coil_functional_effect(
    building: BaseBuilding,
    tg,
    event,
    out_dir: Path,
) -> CoilFunctionalResult | None:
    """Independent of the translate-and-run-clean check above: does the
    corrupted coil configuration actually deliver a functional effect, in a
    season-appropriate window, compared to a true baseline in the same
    window? Only meaningful for fabrication/misattribution (the coil
    object survives, just reconnected) -- removal's functional effect is
    already covered by the directional zone-temperature check from Step 0
    (a fully-removed coil's absence is unambiguous, not something that can
    hide the way a live-but-misattributed coil can)."""
    if event.corruption_type == "removal":
        return None

    if event.corruption_type == "fabrication":
        s, t = event.discordant_pairs[0]
    else:  # misattribution
        (_s_true, t), (s, _t_wrong) = event.discordant_pairs

    target_type = tg.node_type(t)
    if target_type not in _COIL_TARGET_TYPES:
        return None

    variable, (bm, bd, em, ed) = _coil_variable_and_window(target_type)
    translator = openstudio.osversion.VersionTranslator()

    base_model = translator.loadModel(openstudio.path(str(building.osm_path))).get()
    base_coil = _resolve_coil(base_model, t)
    if base_coil is None:
        return None
    coil_name_upper = base_coil.name().get().upper()
    sim_mod.set_scoped_output(base_model, bm, bd, em, ed)
    base_ws = sim_mod.forward_translate(base_model)
    base_idf = out_dir / f"functional_baseline_{t.strip('{}')}.idf"
    sim_mod.save_workspace_as_idf(base_ws, base_idf)
    base_result = sim_mod.run_energyplus(
        base_idf, WEATHER_FILE, out_dir / f"functional_baseline_run_{t.strip('{}')}",
        ENERGYPLUS_BIN, ENERGYPLUS_IDD,
    )

    corrupt_model = translator.loadModel(openstudio.path(str(building.osm_path))).get()
    ok, _reason = _handle_coil_event(corrupt_model, tg, event)
    if not ok:
        return None
    sim_mod.set_scoped_output(corrupt_model, bm, bd, em, ed)
    corrupt_ws = sim_mod.forward_translate(corrupt_model)
    corrupt_idf = out_dir / f"functional_corrupt_{event.target.strip('{}')}.idf"
    sim_mod.save_workspace_as_idf(corrupt_ws, corrupt_idf)
    corrupt_result = sim_mod.run_energyplus(
        corrupt_idf, WEATHER_FILE, out_dir / f"functional_corrupt_run_{event.target.strip('{}')}",
        ENERGYPLUS_BIN, ENERGYPLUS_IDD,
    )

    if not (base_result.success and corrupt_result.success):
        return None

    base_series = _query_series(base_result.output_dir / "eplusout.sql", variable, coil_name_upper)
    corrupt_series = _query_series(corrupt_result.output_dir / "eplusout.sql", variable, coil_name_upper)
    if not base_series or not corrupt_series:
        return None

    base_mean = sum(base_series) / len(base_series)
    corrupt_mean = sum(corrupt_series) / len(corrupt_series)
    functionally_dead = base_mean >= _DEAD_COIL_THRESHOLD_W and corrupt_mean < 1.0

    return CoilFunctionalResult(
        variable=variable, window=f"{bm}/{bd}-{em}/{ed}",
        baseline_output_w=base_mean, corrupted_output_w=corrupt_mean,
        functionally_dead=functionally_dead,
    )


def check_blueprint_physical_plausibility(
    building: BaseBuilding,
    tg,
    blueprint: Blueprint,
    out_dir: Path,
) -> list[PhysicalPlausibilityRecord]:
    """For each corruption event whose target is a zone, physically rewire
    a scratch copy of the model to match the blueprint's (wrong) claim and
    confirm it forward-translates and simulates without severe errors --
    i.e. the corrupted documentation describes a buildable configuration,
    not nonsense. Events whose target isn't a zone (out of scope for the
    rewiring mechanism this pipeline implements) are recorded as such, not
    silently skipped."""
    translator = openstudio.osversion.VersionTranslator()
    model = translator.loadModel(openstudio.path(str(building.osm_path))).get()

    records: list[PhysicalPlausibilityRecord] = []
    any_rewired = False

    for idx, event in enumerate(blueprint.events):
        target_type = tg.node_type(event.target)

        if target_type in _COIL_TARGET_TYPES:
            ok, reason = _handle_coil_event(model, tg, event)
            any_rewired = any_rewired or ok
            record = PhysicalPlausibilityRecord(
                event_index=idx, corruption_type=event.corruption_type,
                target_brick_type=target_type, rewired=ok, reason=reason,
            )
            if ok:
                functional = check_coil_functional_effect(building, tg, event, out_dir)
                if functional is not None:
                    record.functional_check_done = True
                    record.functional_variable = functional.variable
                    record.functional_window = functional.window
                    record.baseline_output_w = functional.baseline_output_w
                    record.corrupted_output_w = functional.corrupted_output_w
                    record.functionally_dead = functional.functionally_dead
            records.append(record)
            continue

        if target_type != "HVAC_Zone":
            records.append(PhysicalPlausibilityRecord(
                event_index=idx, corruption_type=event.corruption_type,
                target_brick_type=target_type, rewired=False,
                reason=f"target is {target_type!r} -- out of scope for the rewiring mechanisms "
                       f"implemented here (terminal-unit<->zone, AHU<->zone-direct, pump<->coil)",
            ))
            continue

        target_zone = _zone_of(_resolve(model, event.target))
        ok = False
        reason = ""
        if event.corruption_type == "removal":
            s, t = event.discordant_pairs[0]
            ok = rewire_mod.remove_zone_service(model, target_zone)
            reason = "removed the true terminal->zone branch (blueprint claims no connection)"
        elif event.corruption_type == "fabrication":
            s, t = event.discordant_pairs[0]
            source_type = tg.node_type(s)
            if source_type == "AHU":
                ahu_airloop = _resolve(model, s).to_AirLoopHVAC().get()
                ok = rewire_mod.set_ahu_direct_service(model, ahu_airloop, target_zone)
                reason = "constructed an AHU-direct pass-through terminal so the AHU serves the claimed " \
                         "zone directly" if ok else "attempted to construct an AHU-direct connection to " \
                         "the claimed zone, but the rewire call itself failed"
            elif source_type not in ("VAV", "Terminal_Unit"):
                reason = (f"fabricated source is {source_type!r} -- out of scope for the terminal<->zone "
                          f"and AHU<->zone rewiring this pipeline implements (e.g. a pump/coil edge)")
            else:
                donor_zone_id = _find_zone_fed_by(tg, s)
                if donor_zone_id is None:
                    reason = f"could not find a zone truly fed by fabricated source {s!r} to clone a terminal from"
                else:
                    donor_zone = _zone_of(_resolve(model, donor_zone_id))
                    ok = rewire_mod.add_extra_service(model, donor_zone, target_zone)
                    reason = "added an extra branch so the fabricated source also serves the claimed zone" if ok \
                        else "attempted to replace the target zone's terminal with a clone of the fabricated " \
                             "source's terminal type, but the rewire call itself failed"
        elif event.corruption_type == "misattribution":
            (_s_true, t_true), (s_wrong, _t_wrong) = event.discordant_pairs
            source_type = tg.node_type(s_wrong)
            if source_type == "AHU":
                ahu_airloop = _resolve(model, s_wrong).to_AirLoopHVAC().get()
                ok = rewire_mod.set_ahu_direct_service(model, ahu_airloop, target_zone)
                reason = "reassigned the claimed zone to an AHU-direct pass-through terminal in place of " \
                         "its true terminal" if ok else "attempted to reassign the claimed zone to an " \
                         "AHU-direct connection, but the rewire call itself failed"
            elif source_type not in ("VAV", "Terminal_Unit"):
                reason = (f"misattributed source is {source_type!r} -- out of scope for the terminal<->zone "
                          f"and AHU<->zone rewiring this pipeline implements (e.g. a pump/coil edge)")
            else:
                donor_zone_id = _find_zone_fed_by(tg, s_wrong)
                if donor_zone_id is None:
                    reason = f"could not find a zone truly fed by misattributed source {s_wrong!r} to move"
                else:
                    donor_zone = _zone_of(_resolve(model, donor_zone_id))
                    ok = rewire_mod.reassign_terminal(model, donor_zone, target_zone)
                    reason = "reassigned the misattributed terminal from its true zone to the claimed zone" if ok \
                        else "attempted to reassign the misattributed terminal to the claimed zone, but the " \
                             "rewire call itself failed"
        else:
            reason = f"unknown corruption type {event.corruption_type!r}"

        any_rewired = any_rewired or ok
        records.append(PhysicalPlausibilityRecord(
            event_index=idx, corruption_type=event.corruption_type,
            target_brick_type=target_type, rewired=ok, reason=reason,
        ))

    if not any_rewired:
        return records

    try:
        ws = sim_mod.forward_translate(model)
    except RuntimeError as exc:
        for r in records:
            if r.rewired:
                r.forward_translation_ok = False
                r.reason += f" | forward translation failed: {exc}"
        return records

    sim_mod.set_scoped_output(model, 7, 1, 7, 3)
    ws = sim_mod.forward_translate(model)
    idf_path = out_dir / f"blueprint_{blueprint.building_id}_{blueprint.corruption_seed}.idf"
    sim_mod.save_workspace_as_idf(ws, idf_path)
    result = sim_mod.run_energyplus(idf_path, WEATHER_FILE, out_dir / f"run_{blueprint.corruption_seed}",
                                     ENERGYPLUS_BIN, ENERGYPLUS_IDD)
    for r in records:
        if r.rewired:
            r.forward_translation_ok = True
            r.severe_errors = result.severe_error_count
            r.warning_count = result.warning_count
    return records


def run_fault_injection(
    building: BaseBuilding,
    tg,
    blueprint: Blueprint,
    out_dir: Path,
    baseline_cache: dict[tuple, sim_mod.SimulationResult],
) -> FaultInjectionRecord | None:
    """Applies an EnergyPlus Operational Fault to the TRUE (uncorrupted)
    model, localized near the corruption site via the exact same
    `symptom_flagged_nodes` locality logic the existing troubleshooting
    experiment already uses, and confirms a measurable deviation from an
    unfaulted baseline run of the same true model -- entirely independent
    of the structural-corruption check above (a different Model copy, no
    shared state).

    Pump/coil-only blueprints are deliberately left without a fault record
    (blind-mode-only) rather than wired to `_run_coil_fault` below.
    `FaultModel:Fouling:Coil` was checked against sys07 (querying `Heating
    Coil U Factor Times Area Value` vs `...Before Fouling`) and does not
    generalize the way the original sys08-only validation suggested: on
    sys07's central cooling coil the same default factor that gave a
    moderate +3.4C effect on sys08 instead drops cooling output to exactly
    0.0 W (complete shutdown, not degradation); on sys07's reheat coils --
    the actual target for most pump/coil candidates on this building -- the
    UA-with-fouling and UA-before-fouling outputs are bit-identical at both
    the default factor and 100x it, i.e. the fault has no effect at all.
    `_run_coil_fault` is kept below, unused, as a documented starting point
    for whoever investigates this properly, not as a validated mechanism."""
    flagged = symptom_flagged_nodes(tg, blueprint)
    zone_targets = [n for n in flagged if tg.node_type(n) == "HVAC_Zone"]
    if zone_targets:
        return _run_zone_fault(building, tg, blueprint, out_dir, baseline_cache, sorted(zone_targets)[0])

    return None


def _run_zone_fault(building, tg, blueprint, out_dir, baseline_cache, target_zone_id) -> FaultInjectionRecord:
    translator = openstudio.osversion.VersionTranslator()

    baseline_key = (building.building_id, "zone", 7, 1, 7, 3)
    if baseline_key not in baseline_cache:
        base_model = translator.loadModel(openstudio.path(str(building.osm_path))).get()
        sim_mod.set_scoped_output(base_model, 7, 1, 7, 3)
        base_ws = sim_mod.forward_translate(base_model)
        base_idf = out_dir / f"true_baseline_{building.building_id}.idf"
        sim_mod.save_workspace_as_idf(base_ws, base_idf)
        baseline_cache[baseline_key] = sim_mod.run_energyplus(
            base_idf, WEATHER_FILE, out_dir / f"true_baseline_run_{building.building_id}",
            ENERGYPLUS_BIN, ENERGYPLUS_IDD,
        )
    baseline_result = baseline_cache[baseline_key]

    fault_model = translator.loadModel(openstudio.path(str(building.osm_path))).get()
    sim_mod.set_scoped_output(fault_model, 7, 1, 7, 3)
    ws = sim_mod.forward_translate(fault_model)

    target_zone_obj = _resolve(fault_model, target_zone_id)
    zone_name = target_zone_obj.name().get()
    injected = faults_mod.add_thermostat_offset_fault(ws, zone_name, offset_degC=5.0)
    fault_idf = out_dir / f"fault_{blueprint.building_id}_{blueprint.corruption_seed}.idf"
    sim_mod.save_workspace_as_idf(ws, fault_idf)
    fault_result = sim_mod.run_energyplus(
        fault_idf, WEATHER_FILE, out_dir / f"fault_run_{blueprint.corruption_seed}",
        ENERGYPLUS_BIN, ENERGYPLUS_IDD,
    )

    max_dev, mean_dev = _compare_series(
        baseline_result, fault_result, "Zone Mean Air Temperature", zone_name.upper()
    )
    return FaultInjectionRecord(
        fault_type="thermostat_offset_5C",
        target_zone_or_coil=zone_name,
        injected=injected,
        baseline_sim_ok=baseline_result.success,
        faulted_sim_ok=fault_result.success,
        max_abs_deviation=max_dev,
        mean_deviation=mean_dev,
        variable="Zone Mean Air Temperature",
    )


def _run_coil_fault(building, tg, blueprint, out_dir, baseline_cache, target_coil_id) -> FaultInjectionRecord | None:
    """Coil-level counterpart to `_run_zone_fault`, for pump/coil-only
    blueprints that have no zone in their flagged neighborhood at all
    (confirmed while validating pump/coil support: `symptom_flagged_nodes`
    only ever flags AHU/pump-side neighbors for a coil target). Uses
    `FaultModel:Fouling:Coil` -- already implemented in `faults.py` and
    verified working in Step 0, just not wired in here until now -- with
    the same season-matched-window discipline as the coil functional-
    effect check: a heating coil barely runs in July regardless of fault
    state, so its fault would be indistinguishable from noise there."""
    target_type = tg.node_type(target_coil_id)
    coil_idd_type = "Coil:Heating:Water" if target_type == "Heating_Coil" else "Coil:Cooling:Water"
    variable, (bm, bd, em, ed) = _coil_variable_and_window(target_type)

    translator = openstudio.osversion.VersionTranslator()

    baseline_key = (building.building_id, "coil", bm, bd, em, ed)
    if baseline_key not in baseline_cache:
        base_model = translator.loadModel(openstudio.path(str(building.osm_path))).get()
        sim_mod.set_scoped_output(base_model, bm, bd, em, ed)
        base_ws = sim_mod.forward_translate(base_model)
        base_idf = out_dir / f"true_baseline_coil_{building.building_id}_{bm}{bd}.idf"
        sim_mod.save_workspace_as_idf(base_ws, base_idf)
        baseline_cache[baseline_key] = sim_mod.run_energyplus(
            base_idf, WEATHER_FILE, out_dir / f"true_baseline_coil_run_{building.building_id}_{bm}{bd}",
            ENERGYPLUS_BIN, ENERGYPLUS_IDD,
        )
    baseline_result = baseline_cache[baseline_key]

    fault_model = translator.loadModel(openstudio.path(str(building.osm_path))).get()
    coil = _resolve_coil(fault_model, target_coil_id)
    if coil is None:
        return None
    coil_name = coil.name().get()
    sim_mod.set_scoped_output(fault_model, bm, bd, em, ed)
    ws = sim_mod.forward_translate(fault_model)
    injected = faults_mod.add_coil_fouling_fault(ws, coil_name, coil_idd_type=coil_idd_type)
    fault_idf = out_dir / f"fault_coil_{blueprint.building_id}_{blueprint.corruption_seed}.idf"
    sim_mod.save_workspace_as_idf(ws, fault_idf)
    fault_result = sim_mod.run_energyplus(
        fault_idf, WEATHER_FILE, out_dir / f"fault_coil_run_{blueprint.corruption_seed}",
        ENERGYPLUS_BIN, ENERGYPLUS_IDD,
    )

    max_dev, mean_dev = _compare_series(baseline_result, fault_result, variable, coil_name.upper())
    return FaultInjectionRecord(
        fault_type="coil_fouling",
        target_zone_or_coil=coil_name,
        injected=injected,
        baseline_sim_ok=baseline_result.success,
        faulted_sim_ok=fault_result.success,
        max_abs_deviation=max_dev,
        mean_deviation=mean_dev,
        variable=variable,
    )


def _compare_series(baseline_result, fault_result, variable, key_upper) -> tuple[float | None, float | None]:
    if not (baseline_result.success and fault_result.success):
        return None, None
    base_series = _query_series(baseline_result.output_dir / "eplusout.sql", variable, key_upper)
    fault_series = _query_series(fault_result.output_dir / "eplusout.sql", variable, key_upper)
    if not base_series or not fault_series or len(base_series) != len(fault_series):
        return None, None
    diffs = [f - b for f, b in zip(fault_series, base_series)]
    return max(abs(d) for d in diffs), sum(diffs) / len(diffs)


def run_building(
    building: BaseBuilding,
    config: BenchmarkConfig,
    ontology: BrickOntology,
    out_dir: Path,
    severities: tuple[int, ...],
    n_seeds_per_severity: int,
    base_corruption_seed: int,
) -> BuildingRunBundle:
    model, tg, _extraction = load_and_extract(building)
    zone_to_coil = rewire_mod.build_zone_to_coil_map(model)
    del model  # only needed transiently for extraction; rewiring reloads fresh copies

    type_counts: dict[str, int] = {}
    for n in tg.nodes():
        t = tg.node_type(n) or "UNTYPED"
        type_counts[t] = type_counts.get(t, 0) + 1

    bundle = BuildingRunBundle(
        building=building, building_id=building.building_id, tg=tg,
        n_nodes=tg.nx_graph.number_of_nodes(),
        n_feeds_edges=len(tg.edges_by_relation["feeds"]),
        node_type_counts=type_counts,
    )

    baseline_cache: dict[tuple, sim_mod.SimulationResult] = {}
    out_dir.mkdir(parents=True, exist_ok=True)

    for severity in severities:
        for variant in range(n_seeds_per_severity):
            corruption_seed = base_corruption_seed + severity * 1000 + variant
            blueprint = generate_scoped_blueprint(tg, ontology, severity, corruption_seed, zone_to_coil=zone_to_coil)
            if len(blueprint.events) == 0:
                continue
            bundle.blueprints.append(blueprint)

            bundle.plausibility[corruption_seed] = check_blueprint_physical_plausibility(
                building, tg, blueprint, out_dir
            )
            fault_record = run_fault_injection(building, tg, blueprint, out_dir, baseline_cache)
            if fault_record is not None:
                bundle.fault_records[corruption_seed] = fault_record

            for symptom_mode, policy_set in (
                (False, TROUBLESHOOTING_BLIND_POLICIES),
                (True, TROUBLESHOOTING_SYMPTOM_POLICIES),
            ):
                for policy in policy_set:
                    for noise in config.noise_levels:
                        for seed in range(config.base_seed, config.base_seed + config.troubleshooting_n_seeds_per_variant):
                            bundle.trial_results.append(
                                run_troubleshooting_trial(tg, ontology, blueprint, policy, symptom_mode, noise, seed, config)
                            )

    return bundle
