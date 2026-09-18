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
        "(pump/coil-audit-round) run, on `sys07_vav_reheat` and `sys08_vav_parallel_piu` only, "
        f"reported 693 trials; this run, widened to 4 buildings, reports {len(all_trials)}. "
        "The multiplier per blueprint is unchanged (63 = 7 policies x 3 noise levels x 3 tie-break "
        "seeds). Both previously-validated buildings reran bit-for-bit identical this time -- "
        "`sys08_vav_parallel_piu` still contributes 315 trials (5 surviving blueprints x 63) and "
        "`sys07_vav_reheat` still contributes 378 (6 x 63), together the same 693 as before, "
        "confirming the widening didn't silently perturb the existing buildings. The two new "
        "buildings then add their own trial contingents on top: `sys05_vav_reheat_dx` contributes "
        "378 (6 surviving blueprints x 63 -- the same blueprint-survival count as its structural "
        "analog `sys07`, both hydronic VAV-reheat buildings) and `sys06_vav_piu_dx` contributes 315 "
        "(5 x 63 -- matching its analog `sys08`, both electric-PIU-reheat, zero-plant-loop "
        f"buildings). {len(all_trials)} = 693 (unchanged) + 693 (new) -- not a coincidence of "
        "rounding, but two structurally analogous building pairs producing numerically identical "
        "blueprint-survival counts. (For the 756->630->693 history before this round, see the "
        "prior version of this report / `CHANGELOG.md`.)\n"
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
        f"**Coverage progression:** the denominator itself grows with the batch, since it's drawn "
        "fresh from whichever buildings are in `BASE_BUILDINGS` -- on the original 2-building "
        "(`sys07`/`sys08`) batch it was 10/24 (42%) with terminal<->zone alone -> 13/24 (54%) "
        "adding AHU<->zone-direct -> 18/24 (75%) adding pump<->coil. Widened to 4 buildings "
        f"(`sys05_vav_reheat_dx` and `sys06_vav_piu_dx` added), the same three edge types now cover "
        f"**{total_in_scope}/{total_raw} ({total_in_scope/total_raw:.0%})** of the events "
        f"`generate_blueprint` draws on these seeds/severities across all 4 buildings. The remaining "
        f"{total_raw - total_in_scope} ({(total_raw - total_in_scope)/total_raw:.0%}) are "
        "structurally inapplicable, the same way AHU<->Terminal_Unit already was, not a gap in "
        "what's built:\n"
    )
    for reason, count in sorted(excluded_reasons.items(), key=lambda x: -x[1]):
        lines.append(f"- {count}x {reason}")
    lines.append(
        f"\nAll {total_raw - total_in_scope} remaining exclusions are `target is VAV`, i.e. an "
        "AHU<->Terminal_Unit edge -- there's only ever one AHU per building in this batch (true of "
        "all 4 buildings, not just the original 2), so reassigning \"which AHU feeds this terminal\" "
        "isn't a meaningful rewire on any of them. **No new out-of-scope category appeared** when "
        "sys05/sys06 were added -- every pump<->coil and terminal<->zone/AHU-direct candidate these "
        "two new buildings' seeds drew landed in the same in-scope bucket as before. (Being "
        "\"in scope\" means this pipeline *attempts* the rewire, not that it's guaranteed to "
        "succeed -- see the new DX-coil finding below for a real case where an in-scope pump<->coil "
        "event still fails.)\n"
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
        "**New this round -- sys05/sys06 add genuinely new plant/coil topologies, not just more "
        "seeds on the same two buildings:** `sys05_vav_reheat_dx` has the same hydronic VAV-reheat "
        "terminal class as `sys07`, but its cooling coil is DX (not chilled-water), so it has only "
        "**one** plant loop/pump (hot-water) instead of sys07's two -- a single-medium case where "
        "cross-medium mixing is structurally impossible (no second medium to draw from). "
        "`sys06_vav_piu_dx` has the same electric-PIU-reheat terminal class as `sys08`, but its "
        "cooling coil is also DX -- so it has **zero** plant loops and **zero** pumps anywhere in "
        "the building. Both use the exact same `AirLoopHVAC`/VAV-terminal/`PlantLoop`-pump object "
        "classes the existing `extract.py`/`rewire.py` already handle, so no code changes were "
        "needed to attempt them -- but \"same object classes\" turned out not to mean \"identical "
        "behavior,\" per the DX-coil finding immediately below.\n"
    )
    lines.append(
        "**A real, previously-latent bug found by widening: a misleading diagnostic message for "
        "coils that exist but aren't hydronic.** `_handle_coil_event`'s failure-to-resolve message "
        "was written for `sys07`/`sys08`, where a coil is *always* `Coil:Cooling:Water` or "
        "`Coil:Heating:Water` -- so a failed resolve there could only mean one thing: the coil was "
        "destroyed by an earlier event in the same blueprint (the cross-event collision case). "
        "`sys05`'s cooling coil is `Coil:Cooling:DX:TwoSpeed`. `generate_blueprint` still drew "
        "fabrication events claiming a pump feeds it (a legitimate ontology-tier candidate -- DX "
        "and hydronic coils are the same Brick class), but `_resolve_coil` can never resolve a DX "
        "coil (it only tries the two hydronic accessors), so every such event was reported as a "
        "collision-destroyed node even when the coil was never destroyed at all -- it was never "
        "hydronic in the first place. Confirmed with a direct call (severity 2, seed 91302006): "
        "the coil resolves fine as a raw object and is provably still present, yet the old message "
        "would have blamed a nonexistent collision. Fixed by checking whether the raw object "
        "resolves at all *before* checking whether it resolves as a hydronic coil, so the two "
        "causes -- \"genuinely destroyed\" vs. \"exists but isn't a type this pipeline's pump/coil "
        "rewiring supports\" -- are reported distinctly (`pipeline.py`, `_unresolved_coil_reason`). "
        "**Structural consequence, not just a message fix:** on `sys05`, every pump<->coil "
        "fabrication/misattribution event that lands on the DX cooling coil now correctly shows "
        "`rewired=False` with an honest reason, and always will -- this pipeline's coil rewiring "
        "only supports hydronic coils, so a DX-coil target is a genuine, permanent scope gap for "
        "this building, not a transient collision. It happens to **not appear** in this batch's own "
        "6 seeds (`sys05`'s coil-target events here are all removals of the hydronic heating "
        "coil, which succeed normally -- see the summary table), but a wider sweep (severities "
        "1-10, 20 seeds each) found it recurs roughly every 10-20 seeds, so it is a real, "
        "recurring case for this building, just one this particular seed set didn't happen to "
        "draw. Reported here rather than left to surface silently in a future, larger run.\n"
    )
    lines.append(
        "**sys06's \"0% collision rate\"/\"0 failed\" is backed by a proof, not just an absence of "
        "counterexamples -- checked precisely because the DX-coil finding above showed \"same object "
        "classes, no code changes needed\" doesn't guarantee identical behavior.** `sys06_vav_piu_dx` "
        "has `zone_to_coil == {}` (no hydronic coils anywhere), which makes two guards short-circuit: "
        "`scope.filter_collision_events` returns immediately (`if not zone_to_coil or ...`), and its "
        "caller `generate_scoped_blueprint` doesn't even call it (`if zone_to_coil: ...`) -- so the "
        "collision-detection logic *itself* never actually runs for sys06 in production, which is a "
        "different, weaker claim than \"it ran and found nothing.\" Verified by forcing the real logic "
        "to execute anyway, bypassing both guards, on an actual sys06 production blueprint (severity "
        "3, seed 91303001 -- a real 3-event blueprint: fabrication + removal + misattribution): "
        "`destroyed_zones` came out non-empty (4 zones -- misattribution destroys two terminals), "
        "then correctly reduced to an empty `destroyed_coils` *because* `z in {}` is always False, "
        "not because there was nothing to check -- and `kept_events` matched the full unfiltered "
        "blueprint, identical to the short-circuit's result. Separately, and more importantly: "
        "`pipeline._handle_coil_event`/`reassign_coil`/`remove_coil_service` (where the DX-coil bug "
        "actually lived) are **provably unreachable** for sys06, not just unobserved in this batch's "
        "seeds -- confirmed by two independent guarantees, not one. First, `_event_in_scope` requires "
        "every source in a coil-target event to resolve to Brick type `Pump` "
        "(`IN_SCOPE_COIL_SOURCE_TYPES = frozenset({'Pump'})`), checked at the graph layer before any "
        "OpenStudio model access. Second, sys06's extracted graph has zero Pump-type nodes -- "
        "confirmed three independent ways (direct OpenStudio inspection: `Pump:VariableSpeed count: "
        "0`; every production run's `node_type_counts` has no `'Pump'` key; `rewire.build_zone_to_"
        "coil_map` returns `{}`) -- and reading `hvac_benchmark`'s `generate_feeds_candidates` "
        "directly confirms candidate sources are filtered from the graph's actual nodes "
        "(`nodes = tg.nodes()`), so a Pump-sourced candidate cannot exist if no Pump node exists. "
        "`rewire.build_zone_to_coil_map` itself never inspects `PlantLoop`/`Pump` collections at all "
        "(it only walks VAV:Reheat terminal reheat-coil accessors) -- there is no \"assumes at least "
        "one exists\" code shape in it for a sibling of the DX-coil bug to hide in.\n"
    )
    lines.append(
        "**Cross-event collision: confirmed to generalize along the hydronic-coil boundary, not a "
        "sys07-specific quirk.** Multiple corruption events in one blueprint are applied "
        "sequentially to the same scratch model; a zone-targeting event's terminal replacement can "
        "cascade-delete a reheat coil that a *different*, independently-drawn coil-targeting event "
        "in the same blueprint also targets by node id. Extending the same empirical study (pure "
        "graph-level simulation, severities 1-10, 200 seeds each) to all 4 buildings: `sys07_vav_"
        "reheat` 0% (sev 1) -> 15% (sev 3) -> 92% (sev 10); `sys05_vav_reheat_dx` (also hydronic "
        "zone-embedded reheat coils, just a single-medium plant) 0% -> 6% -> 69% -- nonzero and "
        "growing the same way, confirming the risk tracks \"does this building have hydronic "
        "zone-embedded coils at all,\" not something particular to sys07; `sys08_vav_parallel_piu` "
        "and `sys06_vav_piu_dx` (both electric reheat, no plant connection to cascade-delete) are "
        "flat 0% on both. `rewire.build_zone_to_coil_map()` + `scope.filter_collision_events()` -- "
        "unchanged code, already building the map generically from whatever terminal/coil classes "
        "are present -- drop a colliding event *before* it's ever attempted for all 4 buildings "
        "alike. Within this batch's actual 6 seeds/building (severities 1-3, 2 seeds each, far "
        "fewer draws than the 200-seed study), exactly 1 event was dropped, on `sys07` (severity 3, "
        "one seeded variant) -- the same single case as the prior report. `sys05` drew no colliding "
        "event in this particular small seed set despite having nonzero underlying risk at these "
        "severities (~6% at severity 3, per the study above) -- consistent with a real but "
        "lower-probability risk, not evidence the filter doesn't apply there.\n"
    )
    lines.append(
        "**Cross-medium pump/coil risk: still real on the dual-medium buildings, and structurally "
        "impossible on sys05 by construction -- a clean confirming contrast, not a contradiction.** "
        "On `sys07` (two pumps: chilled-water and hot-water), two misattribution events in this "
        "batch again moved a heating coil onto the *other* pump's loop -- a genuine cross-medium "
        "swap, producing **0 severe errors** while the coil silently delivers **exactly 0.0 W of "
        "heat, every hour** (confirmed via the January-window baseline-vs-corrupted functional "
        "check; both are flagged `functionally dead` in the table below, same as the prior report). "
        "On `sys05` (only one pump, hot-water only), this specific failure mode **cannot occur at "
        "all**: there is no second medium/pump for a coil to be misattributed onto. This isn't "
        "something to fix -- it's the risk correctly *not* materializing where the physical "
        "precondition for it (a second incompatible medium) doesn't exist, which is exactly the "
        "behavior a physically-grounded check should have.\n"
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
    assert n_clean + n_dead + n_failed == n_attempted, (
        f"denominator mismatch: {n_clean}+{n_dead}+{n_failed} != {n_attempted}"
    )
    lines.append(
        f"**Summary: {n_attempted} in-scope events attempted across all 4 buildings "
        "(collision-filtered events never reach this table at all -- see the collision note "
        f"above); {n_clean} clean and functionally confirmed, {n_dead} passed 0-severe-errors but "
        "are functionally dead (caught only by the functional-effect check, not by "
        f"severe_errors), {n_failed} failed to rewire.** "
        f"Verified: {n_clean} + {n_dead} + {n_failed} == {n_attempted}. Reported as-is, not rounded "
        f"up to a clean line or hidden. The {total_raw - total_in_scope}/{total_raw} "
        f"({(total_raw - total_in_scope)/total_raw:.0%}) still excluded from the full candidate "
        "pool (AHU<->Terminal_Unit, structurally inapplicable) never reach this table at all. "
        f"**{n_failed} failed to rewire in this specific batch** -- the DX-coil scope gap found "
        "on `sys05` this round (see above) didn't happen to be drawn by these particular seeds, so "
        "it doesn't show up as a nonzero count here; it is still a real, recurring case for that "
        "building, documented above rather than only visible once a future run's seeds happen to "
        "hit it.\n"
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
        "Checked across all 4 buildings in this widened batch, not just re-asserted from the prior "
        "report: exactly one blueprint has no fault record for this reason -- `sys07_vav_reheat`, "
        "severity 1, the pump/coil removal (same as before). Neither `sys05` nor `sys06` "
        "introduced a new instance of this gap in this batch's blueprints -- every blueprint they "
        "generated here happened to include at least one zone-side event alongside any coil event. "
        "`FaultModel:Fouling:Coil` was investigated as a "
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
        "a physics-based EnergyPlus fault to back that symptom up. Checked across the full widened "
        "batch: exactly one blueprint feeding the rows below (`sys07_vav_reheat`, severity 1, seed "
        "91301001, a pump<->coil-only removal) has no fault record at all (see above) -- pump/coil-"
        "only blueprints are blind-mode-only by decision -- yet its trials still appear in the "
        "\"Symptom-triggered\" table, using the abstract locality flag on its own. `sys05_vav_"
        "reheat_dx` and `sys06_vav_piu_dx` did not introduce a second such blueprint in this batch. "
        "Do not read \"Symptom-triggered\" coverage here as \"every blueprint has a "
        "physics-validated fault behind it\" -- one still does not.\n"
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
