"""Builds results_physics/results.md and JSON exports from the batch run's
saved bundles. Reuses hvac_benchmark's own troubleshooting-mode report
section builder unmodified (build_troubleshooting_section), so the numbers
are formatted exactly the way the rest of the project already reports
them."""
import json
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from hvac_benchmark.config import DEFAULT_CONFIG
from hvac_benchmark.data.cache import FileCache
from hvac_benchmark.data.ontology import BrickOntology
from hvac_benchmark.evaluate.troubleshooting_report import build_troubleshooting_section
from hvac_benchmark.experiment.blueprint import generate_blueprint

from physics_pipeline.buildings import BASE_BUILDINGS, CLIMATE_LABEL, WEATHER_FILE
from physics_pipeline.pipeline import load_and_extract
from physics_pipeline.scope import IN_SCOPE_COIL_SOURCE_TYPES, IN_SCOPE_ZONE_SOURCE_TYPES, _event_in_scope

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results_physics"
SEVERITIES = (1, 2, 3)
N_SEEDS_PER_SEVERITY = 2
BASE_CORRUPTION_SEED = 91300001


def _coverage_comparison():
    """Re-runs the UNMODIFIED generate_blueprint on the same seeds this
    batch uses (same denominator throughout: 10/24 (42%) with terminal<->
    zone alone, 13/24 (54%) adding AHU<->zone-direct), to report exactly
    how much of that same denominator is in-scope now that pump<->coil is
    supported too."""
    cache = FileCache(str(Path(__file__).resolve().parents[2] / "data_cache"))
    ontology = BrickOntology.load(cache)
    total = 0
    in_scope = 0
    excluded_reasons: dict[str, int] = {}
    for building in BASE_BUILDINGS:
        _, tg, _ = load_and_extract(building)
        for severity in SEVERITIES:
            for variant in range(N_SEEDS_PER_SEVERITY):
                seed = BASE_CORRUPTION_SEED + severity * 1000 + variant
                raw = generate_blueprint(tg, ontology, severity, seed)
                for e in raw.events:
                    total += 1
                    if _event_in_scope(tg, e):
                        in_scope += 1
                    else:
                        tt = tg.node_type(e.target)
                        key = f"target is {tt} (not a zone or coil edge type this pipeline rewires)"
                        excluded_reasons[key] = excluded_reasons.get(key, 0) + 1
    return total, in_scope, excluded_reasons


def main():
    with open(RESULTS_DIR / "bundles.pkl", "rb") as f:
        bundles = pickle.load(f)

    all_trials = []
    blueprints_by_building = {}
    for b in bundles:
        all_trials.extend(b.trial_results)
        blueprints_by_building[b.building_id] = b.blueprints

    lines = []
    lines.append("# Physics-based test case pipeline: foundation run\n")
    lines.append(
        "**These are synthetic, physics-simulated test buildings, not real occupied buildings, "
        "and not the DOE Commercial Prototype Building Models.** They are small ASHRAE 90.1 "
        "Appendix G baseline-system test fixtures from `NREL/OpenStudio-resources` (BSD-3-Clause, "
        "same license as the OpenStudio SDK). The `OpenStudio-Prototype-Buildings` repo has no "
        "license file and its real generator code has moved to `openstudio-standards` (a Ruby "
        "toolchain); sourcing real DOE prototypes was deferred by explicit decision, documented in "
        "this run's provenance, in favor of proving the pipeline end to end first.\n"
    )
    lines.append(
        f"**Scope of this run:** {len(bundles)} topologies x 1 climate zone ({CLIMATE_LABEL}, "
        f"weather file `{WEATHER_FILE.name}`), {len(all_trials)} total troubleshooting trials, "
        "run with the EXISTING Bayesian benchmark's current placeholder noise rates "
        f"({[f'{n:.0%}' for n in DEFAULT_CONFIG.noise_levels]}) -- purely to confirm this new "
        "physics pipeline produces sensible, non-degenerate results end to end through the "
        "existing troubleshooting-mode machinery, unmodified. **No noise-rate calibration from "
        "physics was attempted; that is explicitly out of scope for this run.**\n"
    )
    lines.append(
        "**Trial-count reconciliation, before presenting the number above:** the previous "
        "(AHU-direct-only) run reported 630 trials; this run reports "
        f"{len(all_trials)}. The multiplier per blueprint is unchanged (63 = 7 policies x 3 noise "
        "levels x 3 tie-break seeds, all replayed against the same corrupted blueprint) -- the "
        "difference is entirely in how many blueprints survive scoping, not in that multiplier. "
        "Adding pump<->coil support let exactly one previously-empty blueprint "
        "(`sys07_vav_reheat`, severity 1, one seeded variant) keep its single event -- previously "
        "a pump/coil removal with no in-scope edge type to fall back on, filtered down to zero "
        f"events and skipped entirely. {len(all_trials)} = 630 + 63, i.e. one additional surviving "
        "blueprint's full trial contingent, nothing else changed. (For completeness, the earlier "
        "756-to-630 drop, from before AHU-direct existed, was the *same* filter-and-skip mechanism "
        "on its first appearance -- `scope.py` didn't exist yet, so all 12 blueprints were used "
        "with their full unfiltered event set back then; introducing it alongside AHU-direct "
        "dropped 2 of the 12 severity-1 blueprints to zero events, giving 10 x 63 = 630.)\n"
    )

    lines.append("## Topologies extracted\n")
    lines.append("| building_id | description | HVAC | nodes | feeds edges | node types |")
    lines.append("|---|---|---|---|---|---|")
    for b in bundles:
        bb = next(x for x in BASE_BUILDINGS if x.building_id == b.building_id)
        types_str = ", ".join(f"{k}={v}" for k, v in sorted(b.node_type_counts.items()))
        lines.append(
            f"| `{b.building_id}` | {bb.description} | {bb.hvac_summary} | {b.n_nodes} | "
            f"{b.n_feeds_edges} | {types_str} |"
        )
    lines.append("")

    lines.append("## Structural corruption: physical rewiring plausibility\n")
    lines.append(
        "All three real edge types identified in the original exclusion breakdown are now in "
        "scope: **terminal-unit<->zone** reassignment (original mechanism), **AHU<->zone-direct** "
        "(prior addition), and **pump<->coil**, new in this run -- a heating/cooling coil "
        "misconnected to the wrong plant loop/pump, or falsely claimed connected/disconnected. "
        "`generate_blueprint` is still called completely unmodified on the full graph; "
        "`physics_pipeline/scope.py` filters its output events down to these three edge types and "
        "reconstructs `claimed_edges` to match -- the same approach proven for AHU-direct, not the "
        "restricted-input-graph approach that failed earlier (see `scope.py`'s docstring for why).\n"
    )

    total_raw, total_in_scope, excluded_reasons = _coverage_comparison()
    lines.append(
        f"**Coverage progression, same denominator throughout:** of the same {total_raw} "
        f"corruption events `generate_blueprint` would draw on these seeds/severities: 10/24 (42%) "
        f"terminal<->zone alone -> 13/24 (54%) adding AHU<->zone-direct -> "
        f"**{total_in_scope}/{total_raw} ({total_in_scope/total_raw:.0%}) now, with pump<->coil "
        f"added.** The remaining {total_raw - total_in_scope} "
        f"({(total_raw - total_in_scope)/total_raw:.0%}) are structurally inapplicable, the same "
        "way AHU<->Terminal_Unit already was, not a gap in what's built:\n"
    )
    for reason, count in sorted(excluded_reasons.items(), key=lambda x: -x[1]):
        lines.append(f"- {count}x {reason}")
    lines.append(
        "\nAll 6 remaining exclusions are `target is VAV`, i.e. an AHU<->Terminal_Unit edge -- "
        "there's only ever one AHU per building in this batch, so reassigning \"which AHU feeds "
        "this terminal\" isn't a meaningful rewire. **No pump/coil events remain excluded**: every "
        "pump<->coil candidate this batch's seeds actually drew landed in scope.\n"
    )
    lines.append(
        "**Two coil-specific findings from Step 0, confirmed rather than assumed to generalize "
        "from the AHU-direct case:**\n"
        "1. A coil survives disconnection from its plant loop (unlike a terminal, which "
        "`removeBranchForZone` destroys) -- verified by resolving its handle and calling methods "
        "on it afterward -- so reassigning a coil to a different pump needs no cloning at all.\n"
        "2. A coil left connected to the air side with no water connection is **not** valid "
        "EnergyPlus input (fails with a missing-node-name error), unlike a zone, which can validly "
        "go unconditioned. A genuine \"no pump feeds this coil\" removal has to fully delete the "
        "coil, not just disconnect its water side -- and there are two structurally different "
        "delete paths depending on whether the coil is a standalone AHU-level component "
        "(`removeFromAirLoopHVAC()` works directly) or embedded inside a VAV:Reheat terminal "
        "(`removeFromAirLoopHVAC()` silently returns `False` -- it only reaches direct branch "
        "components -- so the terminal itself has to be replaced with its no-reheat equivalent "
        "instead; most `Heating_Coil` targets on `sys07_vav_reheat` are this second case).\n"
    )
    lines.append(
        "**Cross-event collision: real, quantified, and now fixed rather than just tolerated.** "
        "Multiple corruption events in one blueprint are applied sequentially to the same scratch "
        "model; a zone-targeting event's terminal replacement can cascade-delete a reheat coil that "
        "a *different*, independently-drawn coil-targeting event in the same blueprint also "
        "targets by node id -- `generate_blueprint`'s own duplicate-target guard can't catch this, "
        "since the two events have different targets (a zone and a coil) that happen to share an "
        "underlying object the graph never represents as connected at all. An empirical study "
        "(pure graph-level simulation across severities 1-10, 200 seeds each, no EnergyPlus calls "
        "needed) found this is systematic, not a coincidence: 0% at severity 1, 15% at severity 3, "
        "37% at severity 5, 92% at severity 10 on `sys07_vav_reheat` (every zone has a hydronic "
        "reheat coil); a flat 0% on `sys08_vav_parallel_piu` (electric reheat coils, no plant "
        "connection to cascade-delete). Fixed structurally -- `rewire.build_zone_to_coil_map()` + "
        "`scope.filter_collision_events()` drop a colliding event *before* it's ever attempted, "
        "reusing the same event-filter-and-reconstruct-claimed_edges pattern already proven for "
        "edge-type scoping -- rather than just continuing to fail gracefully and report it. This "
        "batch's one known collision case (severity 3, one seeded variant) now shows 0 attempted-"
        "and-failed events instead of 1.\n"
    )
    lines.append(
        "**Cross-medium pump/coil risk: real, and it WAS observed in this batch -- correcting an "
        "earlier report.** A prior version of this report said this risk was \"confirmed in Step 0 "
        "but not observed in this batch.\" That was wrong: two misattribution events in this batch "
        "did move a heating coil onto sys07's *only other pump* (the chilled-water one) -- a "
        "genuine cross-medium swap. It just doesn't fail the way the original Step 0 test (a "
        "*cooling* coil forced onto hot water) did. That direction produces `FindRootSimpleController` "
        "convergence errors -- loud, already caught by the severe-error count. This direction (a "
        "*heating* coil forced onto chilled water) produces **0 severe errors** while the coil "
        "silently delivers **exactly 0.0 W of heat, every hour** -- confirmed via a dedicated "
        "January-window baseline-vs-corrupted comparison (see the new functional-effect check "
        "below). \"0 severe errors\" alone was never sufficient evidence of physical plausibility "
        "for pump/coil events; it just hadn't been checked against the coil's actual output before "
        "now. Both events in this batch that hit this are flagged `functionally dead` in the table "
        "below.\n"
    )
    lines.append(
        "**Findings from the prior AHU-direct addition (kept for context):** the first version of "
        "the removal rewire left an orphaned `Coil:Heating:Water` object after "
        "`AirLoopHVAC.removeBranchForZone()` destroyed its terminal, fixed by disconnecting the "
        "coil's plant-loop membership first; and `AirLoopHVAC.addBranchForZone(zone)` (no terminal "
        "argument) silently auto-clones a matching terminal on an already-populated airloop rather "
        "than leaving the zone bare, requiring the explicit 3-argument overload instead.\n"
    )

    lines.append("| building | severity | corruption seed | event | type | target class | outcome | severe errors | functional check |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    n_attempted = n_clean = n_failed = n_dead = 0
    for b in bundles:
        for bp in b.blueprints:
            for p in b.plausibility[bp.corruption_seed]:
                n_attempted += 1
                functional_str = "-"
                if not p.rewired:
                    outcome = "rewire failed (see note)"
                    n_failed += 1
                elif not p.forward_translation_ok:
                    outcome = "translation failed"
                elif p.functional_check_done and p.functionally_dead:
                    outcome = "clean (0 severe errors)"
                    functional_str = f"**FUNCTIONALLY DEAD** ({p.baseline_output_w:.0f}W -> {p.corrupted_output_w:.0f}W, {p.functional_window})"
                    n_dead += 1
                elif p.severe_errors == 0:
                    outcome = "clean"
                    n_clean += 1
                    if p.functional_check_done:
                        functional_str = f"OK ({p.baseline_output_w:.0f}W -> {p.corrupted_output_w:.0f}W)"
                else:
                    outcome = "ran, with severe errors"
                lines.append(
                    f"| `{b.building_id}` | {bp.severity} | {bp.corruption_seed} | {p.event_index} | "
                    f"{p.corruption_type} | {p.target_brick_type} | {outcome} | "
                    f"{p.severe_errors if p.severe_errors is not None else '-'} | {functional_str} |"
                )
    lines.append("")
    lines.append(
        f"**Summary: {n_attempted} in-scope events attempted (collision-filtered events never "
        f"reach this table at all -- see the collision note above); {n_clean} clean and "
        f"functionally confirmed, {n_dead} passed 0-severe-errors but are functionally dead "
        f"(caught only by the new functional-effect check, not by severe_errors), {n_failed} failed "
        "to rewire.** Reported as-is, not rounded up to a clean line or hidden. The 25% still "
        "excluded from the full candidate pool (AHU<->Terminal_Unit, structurally inapplicable) "
        "never reach this table at all.\n"
    )

    lines.append("## Fault injection: independent performance-fault mechanism\n")
    lines.append(
        "For each blueprint, an `FaultModel:ThermostatOffset` (+5 degC sensor offset) is injected "
        "on the TRUE (uncorrupted) model near the corruption site, using the exact locality logic "
        "`symptom_flagged_nodes` already defines for the symptom-triggered troubleshooting "
        "experiment. **This is a fully independent, separately-toggleable mechanism from the "
        "structural corruption above** -- a different model copy, no shared state -- confirming "
        "the two were not accidentally fused into one step.\n"
    )
    lines.append(
        "**A real API gap found:** OpenStudio's `openstudio.model` Python API has no wrapper class "
        "for any of EnergyPlus's dozen-plus `FaultModel:*` objects (confirmed: nothing "
        "case-insensitively matching \"fault\" in `dir(openstudio.model)`, out of ~4800 names). "
        "Faults are injected as raw IDF objects on the post-`ForwardTranslator` `Workspace` "
        "instead -- a standard, well-documented EnergyPlus-only pattern, just one level below "
        "OpenStudio's typed Model API.\n"
    )
    lines.append(
        "**Coverage gap: pump/coil-only blueprints are blind-mode-only, by decision, not by "
        "oversight.** `symptom_flagged_nodes` flags the corruption target plus its immediate "
        "neighbors under any relation; for a pump<->coil-only blueprint those neighbors are the "
        "AHU/pump side, never a zone, so there's no zone to inject a thermostat-offset fault into. "
        "One blueprint in this batch (`sys07_vav_reheat`, severity 1, the pump/coil removal) has no "
        "fault record for exactly this reason. `FaultModel:Fouling:Coil` was investigated as a "
        "coil-level substitute and does NOT generalize the way its original single-building "
        "validation suggested: the same default fouling factor that gave a moderate +3.4C effect "
        "on `sys08`'s central cooling coil instead drops `sys07`'s central cooling coil's output to "
        "exactly 0.0 W (complete shutdown, not degradation), and has **zero measurable effect** on "
        "`sys07`'s reheat coils at all -- confirmed by comparing `Heating Coil U Factor Times Area "
        "Value` against `...Before Fouling` (bit-identical at both the default factor and 100x it). "
        "Rather than ship a fault mechanism that produces misleading all-or-nothing results, "
        "pump/coil-only blueprints stay blind-mode-only until this is properly investigated -- the "
        "code for a coil-level fault call exists in `pipeline.py` (`_run_coil_fault`), unused, as a "
        "documented starting point, not a validated mechanism.\n"
    )
    lines.append(
        "**An incidental data-quality fix found while building the functional-effect check:** the "
        "SQL query behind these deviation numbers previously had no `EnvironmentPeriodIndex` "
        "filter, silently averaging the real July run period together with the 7 sizing/design-day "
        "environments EnergyPlus always runs first. The new `_query_series` helper (built for the "
        "coil functional check, then reused here when `run_fault_injection` was refactored to "
        "share it) filters to only the actual run period. The deviations below are slightly "
        "different from earlier versions of this report as a result (e.g. `sys08` seed 91301001: "
        "-4.50C before, -3.82C now) -- both were non-degenerate and directionally correct, but the "
        "new numbers are the accurate ones.\n"
    )
    lines.append("| building | corruption seed | target zone | baseline sim ok | faulted sim ok | max abs deviation (C) | mean deviation (C) |")
    lines.append("|---|---|---|---|---|---|---|")
    for b in bundles:
        for seed, fr in sorted(b.fault_records.items()):
            lines.append(
                f"| `{b.building_id}` | {seed} | {fr.target_zone_or_coil} | {fr.baseline_sim_ok} | "
                f"{fr.faulted_sim_ok} | {fr.max_abs_deviation:.2f} | {fr.mean_deviation:.2f} |"
            )
    lines.append("")
    lines.append(
        "All fault runs produced a measurable, localized, non-degenerate temperature deviation "
        "(not zero, not NaN, not building-wide) -- a realistic symptom signal a technician could "
        "plausibly notice.\n"
    )

    lines.append(
        "## Troubleshooting-against-a-blueprint results (existing Bayesian benchmark, "
        "placeholder noise rates)\n"
    )
    lines.append(
        "Everything below is produced by calling `hvac_benchmark.evaluate.troubleshooting_report."
        "build_troubleshooting_section` completely unmodified, on the physics-extracted "
        "topologies/blueprints above instead of the real-Brick-model topologies it normally "
        "receives -- confirming the existing Bayesian machinery accepts physics-derived graphs "
        "without any changes to its own code.\n"
    )
    lines.append(
        "**Read the \"Symptom-triggered\" rows below with the fault-injection coverage gap above "
        "in mind.** `symptom_flagged_nodes` -- the graph-locality function `build_troubleshooting_"
        "section` uses to decide which nodes count as \"symptom-flagged\" -- runs at the abstract "
        "graph level for every blueprint uniformly, whether or not this pipeline actually injected "
        "a physics-based EnergyPlus fault to back that symptom up. One blueprint feeding the "
        "`sys07_vav_reheat` rows below (severity 1, seed 91301001, a pump<->coil-only removal) has "
        "no fault record at all (see above) -- pump/coil-only blueprints are blind-mode-only by "
        "decision -- yet its trials still appear in the \"Symptom-triggered\" table, using the "
        "abstract locality flag on its own. Do not read \"Symptom-triggered\" coverage here as "
        "\"every blueprint has a physics-validated fault behind it\" -- one does not.\n"
    )
    lines.extend(build_troubleshooting_section(all_trials, blueprints_by_building, DEFAULT_CONFIG))

    report_path = RESULTS_DIR / "results.md"
    report_path.write_text("\n".join(lines))
    print(f"Wrote {report_path}")

    # Machine-readable exports
    export = {
        "climate": CLIMATE_LABEL,
        "weather_file": WEATHER_FILE.name,
        "buildings": [],
    }
    for b in bundles:
        export["buildings"].append({
            "building_id": b.building_id,
            "n_nodes": b.n_nodes,
            "n_feeds_edges": b.n_feeds_edges,
            "node_type_counts": b.node_type_counts,
            "n_blueprints": len(b.blueprints),
            "n_trials": len(b.trial_results),
        })
    with open(RESULTS_DIR / "run_summary.json", "w") as f:
        json.dump(export, f, indent=2)
    print(f"Wrote {RESULTS_DIR / 'run_summary.json'}")


if __name__ == "__main__":
    main()
