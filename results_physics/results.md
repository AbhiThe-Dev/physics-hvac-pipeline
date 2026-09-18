# Physics-based test case pipeline: foundation run

**These are synthetic, physics-simulated test buildings, not real occupied buildings, and not the DOE Commercial Prototype Building Models.** They are small ASHRAE 90.1 Appendix G baseline-system test fixtures from `NREL/OpenStudio-resources` (BSD-3-Clause, same license as the OpenStudio SDK). The `OpenStudio-Prototype-Buildings` repo has no license file and its real generator code has moved to `openstudio-standards` (a Ruby toolchain); sourcing real DOE prototypes was deferred by explicit decision, documented in this run's provenance, in favor of proving the pipeline end to end first.

**Scope of this run:** 2 topologies x 1 climate zone (Chicago-OHare_TMY3_ASHRAE-CZ5A-cold, weather file `USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw`), 693 total troubleshooting trials, run with the EXISTING Bayesian benchmark's current placeholder noise rates (['0%', '5%', '15%']) -- purely to confirm this new physics pipeline produces sensible, non-degenerate results end to end through the existing troubleshooting-mode machinery, unmodified. **No noise-rate calibration from physics was attempted; that is explicitly out of scope for this run.**

**Trial-count reconciliation, before presenting the number above:** the previous (AHU-direct-only) run reported 630 trials; this run reports 693. The multiplier per blueprint is unchanged (63 = 7 policies x 3 noise levels x 3 tie-break seeds, all replayed against the same corrupted blueprint) -- the difference is entirely in how many blueprints survive scoping, not in that multiplier. Adding pump<->coil support let exactly one previously-empty blueprint (`sys07_vav_reheat`, severity 1, one seeded variant) keep its single event -- previously a pump/coil removal with no in-scope edge type to fall back on, filtered down to zero events and skipped entirely. 693 = 630 + 63, i.e. one additional surviving blueprint's full trial contingent, nothing else changed. (For completeness, the earlier 756-to-630 drop, from before AHU-direct existed, was the *same* filter-and-skip mechanism on its first appearance -- `scope.py` didn't exist yet, so all 12 blueprints were used with their full unfiltered event set back then; introducing it alongside AHU-direct dropped 2 of the 12 severity-1 blueprints to zero events, giving 10 x 63 = 630.)

## Topologies extracted

| building_id | description | HVAC | nodes | feeds edges | node types |
|---|---|---|---|---|---|
| `sys08_vav_parallel_piu` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 1 AHU (VAV fan, chilled-water cooling coil, electric heating coil) -> 10 Parallel-PIU-Reheat VAV terminals -> 10 zones; chilled-water plant with 1 pump/chiller | 25 | 21 | AHU=1, Cooling_Coil=1, Fan=1, HVAC_Zone=10, Heating_Coil=1, Pump=1, VAV=10 |
| `sys07_vav_reheat` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 1 AHU (VAV fan, chilled-water cooling coil) -> 10 VAV-Reheat terminals (hot-water reheat coils) -> 10 zones; separate chilled-water and hot-water plants (chiller + condenser loop, boiler) | 36 | 32 | AHU=1, Cooling_Coil=1, Fan=1, HVAC_Zone=10, Heating_Coil=11, Pump=2, VAV=10 |

## Structural corruption: physical rewiring plausibility

All three real edge types identified in the original exclusion breakdown are now in scope: **terminal-unit<->zone** reassignment (original mechanism), **AHU<->zone-direct** (prior addition), and **pump<->coil**, new in this run -- a heating/cooling coil misconnected to the wrong plant loop/pump, or falsely claimed connected/disconnected. `generate_blueprint` is still called completely unmodified on the full graph; `physics_pipeline/scope.py` filters its output events down to these three edge types and reconstructs `claimed_edges` to match -- the same approach proven for AHU-direct, not the restricted-input-graph approach that failed earlier (see `scope.py`'s docstring for why).

**Coverage progression, same denominator throughout:** of the same 24 corruption events `generate_blueprint` would draw on these seeds/severities: 10/24 (42%) terminal<->zone alone -> 13/24 (54%) adding AHU<->zone-direct -> **18/24 (75%) now, with pump<->coil added.** The remaining 6 (25%) are structurally inapplicable, the same way AHU<->Terminal_Unit already was, not a gap in what's built:

- 6x target is VAV (not a zone or coil edge type this pipeline rewires)

All 6 remaining exclusions are `target is VAV`, i.e. an AHU<->Terminal_Unit edge -- there's only ever one AHU per building in this batch, so reassigning "which AHU feeds this terminal" isn't a meaningful rewire. **No pump/coil events remain excluded**: every pump<->coil candidate this batch's seeds actually drew landed in scope.

**Two coil-specific findings from Step 0, confirmed rather than assumed to generalize from the AHU-direct case:**
1. A coil survives disconnection from its plant loop (unlike a terminal, which `removeBranchForZone` destroys) -- verified by resolving its handle and calling methods on it afterward -- so reassigning a coil to a different pump needs no cloning at all.
2. A coil left connected to the air side with no water connection is **not** valid EnergyPlus input (fails with a missing-node-name error), unlike a zone, which can validly go unconditioned. A genuine "no pump feeds this coil" removal has to fully delete the coil, not just disconnect its water side -- and there are two structurally different delete paths depending on whether the coil is a standalone AHU-level component (`removeFromAirLoopHVAC()` works directly) or embedded inside a VAV:Reheat terminal (`removeFromAirLoopHVAC()` silently returns `False` -- it only reaches direct branch components -- so the terminal itself has to be replaced with its no-reheat equivalent instead; most `Heating_Coil` targets on `sys07_vav_reheat` are this second case).

**Cross-event collision: real, quantified, and now fixed rather than just tolerated.** Multiple corruption events in one blueprint are applied sequentially to the same scratch model; a zone-targeting event's terminal replacement can cascade-delete a reheat coil that a *different*, independently-drawn coil-targeting event in the same blueprint also targets by node id -- `generate_blueprint`'s own duplicate-target guard can't catch this, since the two events have different targets (a zone and a coil) that happen to share an underlying object the graph never represents as connected at all. An empirical study (pure graph-level simulation across severities 1-10, 200 seeds each, no EnergyPlus calls needed) found this is systematic, not a coincidence: 0% at severity 1, 15% at severity 3, 37% at severity 5, 92% at severity 10 on `sys07_vav_reheat` (every zone has a hydronic reheat coil); a flat 0% on `sys08_vav_parallel_piu` (electric reheat coils, no plant connection to cascade-delete). Fixed structurally -- `rewire.build_zone_to_coil_map()` + `scope.filter_collision_events()` drop a colliding event *before* it's ever attempted, reusing the same event-filter-and-reconstruct-claimed_edges pattern already proven for edge-type scoping -- rather than just continuing to fail gracefully and report it. This batch's one known collision case (severity 3, one seeded variant) now shows 0 attempted-and-failed events instead of 1.

**Cross-medium pump/coil risk: real, and it WAS observed in this batch -- correcting an earlier report.** A prior version of this report said this risk was "confirmed in Step 0 but not observed in this batch." That was wrong: two misattribution events in this batch did move a heating coil onto sys07's *only other pump* (the chilled-water one) -- a genuine cross-medium swap. It just doesn't fail the way the original Step 0 test (a *cooling* coil forced onto hot water) did. That direction produces `FindRootSimpleController` convergence errors -- loud, already caught by the severe-error count. This direction (a *heating* coil forced onto chilled water) produces **0 severe errors** while the coil silently delivers **exactly 0.0 W of heat, every hour** -- confirmed via a dedicated January-window baseline-vs-corrupted comparison (see the new functional-effect check below). "0 severe errors" alone was never sufficient evidence of physical plausibility for pump/coil events; it just hadn't been checked against the coil's actual output before now. Both events in this batch that hit this are flagged `functionally dead` in the table below.

**Findings from the prior AHU-direct addition (kept for context):** the first version of the removal rewire left an orphaned `Coil:Heating:Water` object after `AirLoopHVAC.removeBranchForZone()` destroyed its terminal, fixed by disconnecting the coil's plant-loop membership first; and `AirLoopHVAC.addBranchForZone(zone)` (no terminal argument) silently auto-clones a matching terminal on an already-populated airloop rather than leaving the zone bare, requiring the explicit 3-argument overload instead.

| building | severity | corruption seed | event | type | target class | outcome | severe errors | functional check |
|---|---|---|---|---|---|---|---|---|
| `sys08_vav_parallel_piu` | 1 | 91301001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys08_vav_parallel_piu` | 2 | 91302001 | 0 | removal | HVAC_Zone | clean | 0 | - |
| `sys08_vav_parallel_piu` | 2 | 91302002 | 0 | removal | HVAC_Zone | clean | 0 | - |
| `sys08_vav_parallel_piu` | 3 | 91303001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys08_vav_parallel_piu` | 3 | 91303001 | 1 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys08_vav_parallel_piu` | 3 | 91303002 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys08_vav_parallel_piu` | 3 | 91303002 | 1 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys07_vav_reheat` | 1 | 91301001 | 0 | removal | Heating_Coil | clean | 0 | - |
| `sys07_vav_reheat` | 1 | 91301002 | 0 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys07_vav_reheat` | 2 | 91302001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys07_vav_reheat` | 2 | 91302002 | 0 | misattribution | Heating_Coil | clean (0 severe errors) | 0 | **FUNCTIONALLY DEAD** (11227W -> 0W, 1/1-1/3) |
| `sys07_vav_reheat` | 2 | 91302002 | 1 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys07_vav_reheat` | 3 | 91303001 | 0 | misattribution | Heating_Coil | clean (0 severe errors) | 0 | **FUNCTIONALLY DEAD** (14606W -> 0W, 1/1-1/3) |
| `sys07_vav_reheat` | 3 | 91303001 | 1 | removal | HVAC_Zone | clean | 0 | - |
| `sys07_vav_reheat` | 3 | 91303001 | 2 | removal | Heating_Coil | clean | 0 | - |
| `sys07_vav_reheat` | 3 | 91303002 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys07_vav_reheat` | 3 | 91303002 | 1 | fabrication | HVAC_Zone | clean | 0 | - |

**Summary: 17 in-scope events attempted (collision-filtered events never reach this table at all -- see the collision note above); 15 clean and functionally confirmed, 2 passed 0-severe-errors but are functionally dead (caught only by the new functional-effect check, not by severe_errors), 0 failed to rewire.** Reported as-is, not rounded up to a clean line or hidden. The 25% still excluded from the full candidate pool (AHU<->Terminal_Unit, structurally inapplicable) never reach this table at all.

## Fault injection: independent performance-fault mechanism

For each blueprint, an `FaultModel:ThermostatOffset` (+5 degC sensor offset) is injected on the TRUE (uncorrupted) model near the corruption site, using the exact locality logic `symptom_flagged_nodes` already defines for the symptom-triggered troubleshooting experiment. **This is a fully independent, separately-toggleable mechanism from the structural corruption above** -- a different model copy, no shared state -- confirming the two were not accidentally fused into one step.

**A real API gap found:** OpenStudio's `openstudio.model` Python API has no wrapper class for any of EnergyPlus's dozen-plus `FaultModel:*` objects (confirmed: nothing case-insensitively matching "fault" in `dir(openstudio.model)`, out of ~4800 names). Faults are injected as raw IDF objects on the post-`ForwardTranslator` `Workspace` instead -- a standard, well-documented EnergyPlus-only pattern, just one level below OpenStudio's typed Model API.

**Coverage gap: pump/coil-only blueprints are blind-mode-only, by decision, not by oversight.** `symptom_flagged_nodes` flags the corruption target plus its immediate neighbors under any relation; for a pump<->coil-only blueprint those neighbors are the AHU/pump side, never a zone, so there's no zone to inject a thermostat-offset fault into. One blueprint in this batch (`sys07_vav_reheat`, severity 1, the pump/coil removal) has no fault record for exactly this reason. `FaultModel:Fouling:Coil` was investigated as a coil-level substitute and does NOT generalize the way its original single-building validation suggested: the same default fouling factor that gave a moderate +3.4C effect on `sys08`'s central cooling coil instead drops `sys07`'s central cooling coil's output to exactly 0.0 W (complete shutdown, not degradation), and has **zero measurable effect** on `sys07`'s reheat coils at all -- confirmed by comparing `Heating Coil U Factor Times Area Value` against `...Before Fouling` (bit-identical at both the default factor and 100x it). Rather than ship a fault mechanism that produces misleading all-or-nothing results, pump/coil-only blueprints stay blind-mode-only until this is properly investigated -- the code for a coil-level fault call exists in `pipeline.py` (`_run_coil_fault`), unused, as a documented starting point, not a validated mechanism.

**An incidental data-quality fix found while building the functional-effect check:** the SQL query behind these deviation numbers previously had no `EnvironmentPeriodIndex` filter, silently averaging the real July run period together with the 7 sizing/design-day environments EnergyPlus always runs first. The new `_query_series` helper (built for the coil functional check, then reused here when `run_fault_injection` was refactored to share it) filters to only the actual run period. The deviations below are slightly different from earlier versions of this report as a result (e.g. `sys08` seed 91301001: -4.50C before, -3.82C now) -- both were non-degenerate and directionally correct, but the new numbers are the accurate ones.

| building | corruption seed | target zone | baseline sim ok | faulted sim ok | max abs deviation (C) | mean deviation (C) |
|---|---|---|---|---|---|---|
| `sys08_vav_parallel_piu` | 91301001 | Thermal Zone 3 | True | True | 5.02 | -3.82 |
| `sys08_vav_parallel_piu` | 91302001 | Thermal Zone 5 | True | True | 5.00 | -4.03 |
| `sys08_vav_parallel_piu` | 91302002 | Thermal Zone 10 | True | True | 5.00 | -4.02 |
| `sys08_vav_parallel_piu` | 91303001 | Thermal Zone 10 | True | True | 5.00 | -4.02 |
| `sys08_vav_parallel_piu` | 91303002 | Thermal Zone 1 | True | True | 5.02 | -3.72 |
| `sys07_vav_reheat` | 91301002 | Thermal Zone 6 | True | True | 5.00 | -3.50 |
| `sys07_vav_reheat` | 91302001 | Thermal Zone 7 | True | True | 5.00 | -3.74 |
| `sys07_vav_reheat` | 91302002 | Thermal Zone 9 | True | True | 5.00 | -3.43 |
| `sys07_vav_reheat` | 91303001 | Thermal Zone 5 | True | True | 5.00 | -2.98 |
| `sys07_vav_reheat` | 91303002 | Thermal Zone 10 | True | True | 5.00 | -3.44 |

All fault runs produced a measurable, localized, non-degenerate temperature deviation (not zero, not NaN, not building-wide) -- a realistic symptom signal a technician could plausibly notice.

## Troubleshooting-against-a-blueprint results (existing Bayesian benchmark, placeholder noise rates)

Everything below is produced by calling `hvac_benchmark.evaluate.troubleshooting_report.build_troubleshooting_section` completely unmodified, on the physics-extracted topologies/blueprints above instead of the real-Brick-model topologies it normally receives -- confirming the existing Bayesian machinery accepts physics-derived graphs without any changes to its own code.

**Read the "Symptom-triggered" rows below with the fault-injection coverage gap above in mind.** `symptom_flagged_nodes` -- the graph-locality function `build_troubleshooting_section` uses to decide which nodes count as "symptom-flagged" -- runs at the abstract graph level for every blueprint uniformly, whether or not this pipeline actually injected a physics-based EnergyPlus fault to back that symptom up. One blueprint feeding the `sys07_vav_reheat` rows below (severity 1, seed 91301001, a pump<->coil-only removal) has no fault record at all (see above) -- pump/coil-only blueprints are blind-mode-only by decision -- yet its trials still appear in the "Symptom-triggered" table, using the abstract locality flag on its own. Do not read "Symptom-triggered" coverage here as "every blueprint has a physics-validated fault behind it" -- one does not.

## Troubleshooting-against-a-blueprint (separate evaluation mode)

**This section is a separate evaluation mode from the full-topology-discovery results above and is never blended with them.** Discovery mode assumes near-zero prior knowledge and measures tests to reconstruct an entire graph from scratch. This mode assumes the opposite starting condition: a trusted blueprint (the true graph, deliberately corrupted at a few points) is already given, and the task is to find the corrupted edge(s) in as few tests as possible -- the day-to-day troubleshooting scenario, not a periodic full audit.

- **2 real topologies** evaluated in this mode: sys07_vav_reheat, sys08_vav_parallel_piu (the same `feeds`-eligible topologies used by the primary discovery benchmark above).
- Corruption severities tested: [1, 2, 3] corrupted edge(s) (an edge = one corruption event; misattribution counts as one event even though it touches two candidate pairs), with 3 independently-seeded corrupted-blueprint variants per (topology, severity), each replayed across 3 tie-break/noise seeds -- a deliberately bounded sample (mirroring the ablation-subset bounding elsewhere in this report), not a statistically powered sweep.

> **Evidence level: small case study, same caveat as the rest of this document.** Numbers below are within-topology variability across corrupted-blueprint variants and seeds, not additional independent buildings or corruption instances beyond what is listed above. No pooled cross-topology number is computed or implied anywhere in this section.

**Belief model reuse:** this mode reuses the exact same Bernoulli update and expected-information-gain machinery as discovery mode (`bayes.update` / `expected_information_gain`), completely unmodified -- only the prior changes (near-certain on blueprint-claimed edges, sparse-floor elsewhere), confirming the two modes did not need a parallel inference system.

**Candidate universe:** identical physically-plausible candidate set as discovery mode's `feeds` benchmark, not just blueprint-claimed edges -- required so an undocumented real connection (a *removal* corruption) can be tested at all. One consequence: **the `full_sweep` baseline only re-tests blueprint-claimed edges, so by construction it can never find a removal-type corruption** -- a structural limitation of that reference baseline, not a bug, visible below wherever removal corruptions appear in a topology's mix.

**Metric:** tests needed until every corrupted candidate is simultaneously flagged (current belief disagrees with the blueprint's own claim), first-reached and sustained-to-end-of-trial, median [range] across variants x seeds, with attainment rate. Also reported: false-positive rate (fraction of genuinely-correct blueprint edges ever incorrectly flagged along the way) and needless-retest count (tests spent on edges that were both blueprint-claimed-true and genuinely correct) -- a technician chasing a phantom problem, or an algorithm ignoring the strong prior it was given, are both counted as real costs here, never as neutral.

### sys07_vav_reheat

Corruption types actually generated for this topology across all variants: fabrication, misattribution, removal.

**Blind verification**

severity = 1 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 68 [33-86] (n=6) | 100% | 68 [33-86] (n=6) | 100% | 0.0% [0.0%-0.0%] | 31 [31-31] (n=6) |
| active | 5% | 72 [38-103] (n=6) | 100% | 72 [38-103] (n=6) | 100% | 0.0% [0.0%-0.0%] | 33 [31-35] (n=6) |
| active | 15% | 96 [45-118] (n=5) | 83% | 96 [45-118] (n=5) | 83% | 0.0% [0.0%-0.0%] | 40 [37-41] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 31 [31-31] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 33 [31-35] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 40 [37-41] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 38 [9-78] (n=6) | 100% | 38 [9-78] (n=6) | 100% | 0.0% [0.0%-0.0%] | 32 [31-32] (n=6) |
| active | 5% | 40 [10-100] (n=6) | 100% | 40 [10-100] (n=6) | 100% | 0.0% [0.0%-0.0%] | 34 [31-36] (n=6) |
| active | 15% | 56 [11-131] (n=6) | 100% | 56 [11-131] (n=6) | 100% | 0.0% [0.0%-0.0%] | 41 [37-42] (n=6) |
| full_sweep | 0% | 21 [9-25] (n=3) | 50% | 21 [9-25] (n=3) | 50% | 0.0% [0.0%-0.0%] | 32 [31-32] (n=6) |
| full_sweep | 5% | 34 [34-36] (n=3) | 50% | 34 [34-36] (n=3) | 50% | 0.0% [0.0%-0.0%] | 34 [31-36] (n=6) |
| full_sweep | 15% | 43 [37-43] (n=3) | 50% | 43 [37-43] (n=3) | 50% | 0.0% [0.0%-0.0%] | 41 [37-42] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 42 [23-80] (n=6) | 100% | 42 [23-80] (n=6) | 100% | 0.0% [0.0%-0.0%] | 30 [29-32] (n=6) |
| active | 5% | 48 [29-103] (n=6) | 100% | 48 [29-103] (n=6) | 100% | 0.0% [0.0%-0.0%] | 32 [29-36] (n=6) |
| active | 15% | 44 [39-142] (n=4) | 67% | 44 [39-142] (n=4) | 67% | 0.0% [0.0%-0.0%] | 39 [35-42] (n=6) |
| full_sweep | 0% | 26 [23-31] (n=3) | 50% | 26 [23-31] (n=3) | 50% | 0.0% [0.0%-0.0%] | 30 [29-32] (n=6) |
| full_sweep | 5% | 37 [36-43] (n=3) | 50% | 37 [36-43] (n=3) | 50% | 0.0% [0.0%-0.0%] | 32 [29-36] (n=6) |
| full_sweep | 15% | 46 [42-52] (n=3) | 50% | 48 [46-52] (n=3) | 50% | 0.0% [0.0%-0.0%] | 39 [35-42] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

**Symptom-triggered**

severity = 1 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 10 [7-13] (n=6) | 100% | 10 [7-13] (n=6) | 100% | 0.0% [0.0%-0.0%] | 31 [31-31] (n=6) |
| active | 5% | 10 [7-13] (n=6) | 100% | 10 [7-13] (n=6) | 100% | 0.0% [0.0%-0.0%] | 38 [32-47] (n=6) |
| active | 15% | 13 [11-27] (n=6) | 100% | 13 [11-27] (n=6) | 100% | 0.5% [0.0%-2.2%] | 53 [39-73] (n=6) |
| symptom_naive | 0% | 8 [1-11] (n=6) | 100% | 8 [1-11] (n=6) | 100% | 0.0% [0.0%-0.0%] | 6 [1-10] (n=6) |
| symptom_naive | 5% | 8 [1-11] (n=6) | 100% | 8 [1-11] (n=6) | 100% | 0.0% [0.0%-0.0%] | 11 [2-22] (n=6) |
| symptom_naive | 15% | 10 [1-31] (n=6) | 100% | 11 [1-31] (n=6) | 100% | 0.5% [0.0%-2.2%] | 20 [3-44] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 31 [31-31] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 38 [32-47] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.5% [0.0%-2.2%] | 53 [39-73] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 10 [2-21] (n=6) | 100% | 10 [2-21] (n=6) | 100% | 0.0% [0.0%-0.0%] | 32 [31-32] (n=6) |
| active | 5% | 10 [2-21] (n=6) | 100% | 10 [2-21] (n=6) | 100% | 0.0% [0.0%-1.1%] | 40 [34-49] (n=6) |
| active | 15% | 12 [2-31] (n=6) | 100% | 12 [2-33] (n=6) | 100% | 0.5% [0.0%-3.3%] | 60 [42-75] (n=6) |
| symptom_naive | 0% | 10 [6-19] (n=6) | 100% | 10 [6-19] (n=6) | 100% | 0.0% [0.0%-0.0%] | 7 [2-12] (n=6) |
| symptom_naive | 5% | 10 [6-19] (n=6) | 100% | 10 [6-19] (n=6) | 100% | 0.0% [0.0%-1.1%] | 14 [4-28] (n=6) |
| symptom_naive | 15% | 10 [6-19] (n=6) | 100% | 10 [6-67] (n=6) | 100% | 0.5% [0.0%-3.3%] | 30 [6-50] (n=6) |
| full_sweep | 0% | 21 [9-25] (n=3) | 50% | 21 [9-25] (n=3) | 50% | 0.0% [0.0%-0.0%] | 32 [31-32] (n=6) |
| full_sweep | 5% | 21 [9-25] (n=3) | 50% | 21 [9-25] (n=3) | 50% | 0.0% [0.0%-1.1%] | 40 [34-49] (n=6) |
| full_sweep | 15% | 21 [9-25] (n=3) | 50% | 21 [9-25] (n=3) | 50% | 0.5% [0.0%-3.3%] | 60 [42-75] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 13 [3-24] (n=6) | 100% | 13 [3-24] (n=6) | 100% | 0.0% [0.0%-0.0%] | 30 [29-32] (n=6) |
| active | 5% | 13 [3-24] (n=6) | 100% | 20 [4-28] (n=6) | 100% | 0.0% [0.0%-1.1%] | 40 [36-45] (n=6) |
| active | 15% | 9 [5-44] (n=5) | 83% | 10 [5-44] (n=5) | 83% | 1.1% [1.1%-3.3%] | 58 [48-67] (n=6) |
| symptom_naive | 0% | 18 [14-23] (n=6) | 100% | 18 [14-23] (n=6) | 100% | 0.0% [0.0%-0.0%] | 7 [4-10] (n=6) |
| symptom_naive | 5% | 18 [14-23] (n=6) | 100% | 18 [16-47] (n=6) | 100% | 0.0% [0.0%-1.1%] | 15 [8-22] (n=6) |
| symptom_naive | 15% | 19 [14-67] (n=5) | 83% | 58 [17-73] (n=5) | 83% | 1.1% [1.1%-3.3%] | 29 [16-40] (n=6) |
| full_sweep | 0% | 26 [23-31] (n=3) | 50% | 26 [23-31] (n=3) | 50% | 0.0% [0.0%-0.0%] | 30 [29-32] (n=6) |
| full_sweep | 5% | 26 [23-31] (n=3) | 50% | 31 [26-44] (n=3) | 50% | 0.0% [0.0%-1.1%] | 40 [36-45] (n=6) |
| full_sweep | 15% | 26 [23-31] (n=3) | 50% | 31 [26-48] (n=3) | 50% | 1.1% [1.1%-3.3%] | 58 [48-67] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

### sys08_vav_parallel_piu

Corruption types actually generated for this topology across all variants: fabrication, misattribution, removal.

**Blind verification**

severity = 1 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 9 [5-20] (n=3) | 100% | 9 [5-20] (n=3) | 100% | 0.0% [0.0%-0.0%] | 21 [21-21] (n=3) |
| active | 5% | 10 [6-23] (n=3) | 100% | 10 [6-25] (n=3) | 100% | 0.0% [0.0%-0.0%] | 21 [21-23] (n=3) |
| active | 15% | 12 [9-15] (n=2) | 67% | 13 [11-15] (n=2) | 67% | 0.0% [0.0%-0.0%] | 33 [25-39] (n=3) |
| full_sweep | 0% | 9 [5-20] (n=3) | 100% | 9 [5-20] (n=3) | 100% | 0.0% [0.0%-0.0%] | 21 [21-21] (n=3) |
| full_sweep | 5% | 23 [23-24] (n=3) | 100% | 23 [23-27] (n=3) | 100% | 0.0% [0.0%-0.0%] | 21 [21-23] (n=3) |
| full_sweep | 15% | 32 [30-33] (n=2) | 67% | 32 [32-33] (n=2) | 67% | 0.0% [0.0%-0.0%] | 33 [25-39] (n=3) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 47 [43-62] (n=6) | 100% | 47 [43-62] (n=6) | 100% | 0.0% [0.0%-0.0%] | 20 [20-20] (n=6) |
| active | 5% | 61 [47-75] (n=5) | 83% | 61 [47-75] (n=5) | 83% | 0.0% [0.0%-0.0%] | 20 [20-22] (n=6) |
| active | 15% | 78 [68-104] (n=3) | 50% | 78 [68-104] (n=3) | 50% | 0.0% [0.0%-0.0%] | 30 [24-38] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 20 [20-20] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 20 [20-22] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 30 [24-38] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 33 [9-62] (n=6) | 100% | 33 [9-62] (n=6) | 100% | 0.0% [0.0%-0.0%] | 20 [20-21] (n=6) |
| active | 5% | 24 [12-79] (n=5) | 83% | 24 [12-79] (n=5) | 83% | 0.0% [0.0%-0.0%] | 20 [20-23] (n=6) |
| active | 15% | 37 [15-41] (n=3) | 50% | 39 [15-41] (n=3) | 50% | 0.0% [0.0%-0.0%] | 32 [24-39] (n=6) |
| full_sweep | 0% | 16 [9-21] (n=3) | 50% | 16 [9-21] (n=3) | 50% | 0.0% [0.0%-0.0%] | 20 [20-21] (n=6) |
| full_sweep | 5% | 25 [25-26] (n=3) | 50% | 25 [25-26] (n=3) | 50% | 0.0% [0.0%-0.0%] | 20 [20-23] (n=6) |
| full_sweep | 15% | 40 [29-47] (n=3) | 50% | 40 [29-50] (n=3) | 50% | 0.0% [0.0%-0.0%] | 32 [24-39] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

**Symptom-triggered**

severity = 1 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 1 [1-3] (n=3) | 100% | 1 [1-3] (n=3) | 100% | 0.0% [0.0%-0.0%] | 21 [21-21] (n=3) |
| active | 5% | 1 [1-3] (n=3) | 100% | 1 [1-3] (n=3) | 100% | 0.0% [0.0%-0.0%] | 23 [23-25] (n=3) |
| active | 15% | 1 [1-23] (n=3) | 100% | 1 [1-23] (n=3) | 100% | 0.0% [0.0%-0.0%] | 41 [33-47] (n=3) |
| symptom_naive | 0% | 7 [3-11] (n=3) | 100% | 7 [3-11] (n=3) | 100% | 0.0% [0.0%-0.0%] | 2 [2-2] (n=3) |
| symptom_naive | 5% | 7 [3-11] (n=3) | 100% | 7 [3-11] (n=3) | 100% | 0.0% [0.0%-0.0%] | 4 [4-4] (n=3) |
| symptom_naive | 15% | 7 [3-43] (n=3) | 100% | 7 [3-43] (n=3) | 100% | 0.0% [0.0%-0.0%] | 10 [10-10] (n=3) |
| full_sweep | 0% | 9 [5-20] (n=3) | 100% | 9 [5-20] (n=3) | 100% | 0.0% [0.0%-0.0%] | 21 [21-21] (n=3) |
| full_sweep | 5% | 9 [5-20] (n=3) | 100% | 9 [5-20] (n=3) | 100% | 0.0% [0.0%-0.0%] | 23 [23-25] (n=3) |
| full_sweep | 15% | 9 [5-44] (n=3) | 100% | 9 [5-44] (n=3) | 100% | 0.0% [0.0%-0.0%] | 41 [33-47] (n=3) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 7 [4-9] (n=6) | 100% | 7 [4-9] (n=6) | 100% | 0.0% [0.0%-0.0%] | 20 [20-20] (n=6) |
| active | 5% | 8 [4-86] (n=6) | 100% | 8 [4-86] (n=6) | 100% | 0.0% [0.0%-0.0%] | 21 [21-23] (n=6) |
| active | 15% | 17 [6-32] (n=6) | 100% | 17 [6-34] (n=6) | 100% | 0.7% [0.0%-1.4%] | 32 [26-41] (n=6) |
| symptom_naive | 0% | 6 [4-9] (n=6) | 100% | 6 [4-9] (n=6) | 100% | 0.0% [0.0%-0.0%] | 1 [1-1] (n=6) |
| symptom_naive | 5% | 8 [4-23] (n=6) | 100% | 8 [4-23] (n=6) | 100% | 0.0% [0.0%-0.0%] | 2 [2-2] (n=6) |
| symptom_naive | 15% | 18 [4-30] (n=6) | 100% | 27 [4-43] (n=6) | 100% | 0.7% [0.0%-1.4%] | 4 [3-10] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 20 [20-20] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 21 [21-23] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.7% [0.0%-1.4%] | 32 [26-41] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 9 [3-16] (n=6) | 100% | 9 [3-16] (n=6) | 100% | 0.0% [0.0%-0.0%] | 20 [20-21] (n=6) |
| active | 5% | 10 [3-91] (n=6) | 100% | 10 [3-91] (n=6) | 100% | 0.0% [0.0%-1.4%] | 25 [23-27] (n=6) |
| active | 15% | 20 [4-65] (n=6) | 100% | 36 [4-67] (n=6) | 100% | 2.9% [0.0%-2.9%] | 40 [32-52] (n=6) |
| symptom_naive | 0% | 15 [11-19] (n=6) | 100% | 15 [11-19] (n=6) | 100% | 0.0% [0.0%-0.0%] | 4 [3-4] (n=6) |
| symptom_naive | 5% | 16 [12-41] (n=6) | 100% | 16 [12-41] (n=6) | 100% | 0.0% [0.0%-1.4%] | 8 [6-10] (n=6) |
| symptom_naive | 15% | 32 [12-59] (n=6) | 100% | 70 [12-83] (n=6) | 100% | 2.9% [0.0%-2.9%] | 16 [11-23] (n=6) |
| full_sweep | 0% | 16 [9-21] (n=3) | 50% | 16 [9-21] (n=3) | 50% | 0.0% [0.0%-0.0%] | 20 [20-21] (n=6) |
| full_sweep | 5% | 16 [9-21] (n=3) | 50% | 16 [9-21] (n=3) | 50% | 0.0% [0.0%-1.4%] | 25 [23-27] (n=6) |
| full_sweep | 15% | 16 [9-21] (n=3) | 50% | 21 [9-50] (n=3) | 50% | 2.9% [0.0%-2.9%] | 40 [32-52] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
