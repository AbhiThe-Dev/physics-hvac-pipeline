# Physics-based test case pipeline: foundation run

**These are synthetic, physics-simulated test buildings, not real occupied buildings, and not the DOE Commercial Prototype Building Models.** They are small ASHRAE 90.1 Appendix G baseline-system test fixtures from `NREL/OpenStudio-resources` (BSD-3-Clause, same license as the OpenStudio SDK). The `OpenStudio-Prototype-Buildings` repo has no license file and its real generator code has moved to `openstudio-standards` (a Ruby toolchain); sourcing real DOE prototypes was deferred by explicit decision, documented in this run's provenance, in favor of proving the pipeline end to end first.

**Scope of this run:** 4 topologies x 1 climate zone (Chicago-OHare_TMY3_ASHRAE-CZ5A-cold, weather file `USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw`), 1386 total troubleshooting trials, run with the EXISTING Bayesian benchmark's current placeholder noise rates (['0%', '5%', '15%']) -- purely to confirm this new physics pipeline produces sensible, non-degenerate results end to end through the existing troubleshooting-mode machinery, unmodified. **No noise-rate calibration from physics was attempted; that is explicitly out of scope for this run.**

**Trial-count reconciliation, before presenting the number above:** the previous (pump/coil-audit-round) run, on `sys07_vav_reheat` and `sys08_vav_parallel_piu` only, reported 693 trials; this run, widened to 4 buildings, reports 1386. The multiplier per blueprint is unchanged (63 = 7 policies x 3 noise levels x 3 tie-break seeds). Both previously-validated buildings reran bit-for-bit identical this time -- `sys08_vav_parallel_piu` still contributes 315 trials (5 surviving blueprints x 63) and `sys07_vav_reheat` still contributes 378 (6 x 63), together the same 693 as before, confirming the widening didn't silently perturb the existing buildings. The two new buildings then add their own trial contingents on top: `sys05_vav_reheat_dx` contributes 378 (6 surviving blueprints x 63 -- the same blueprint-survival count as its structural analog `sys07`, both hydronic VAV-reheat buildings) and `sys06_vav_piu_dx` contributes 315 (5 x 63 -- matching its analog `sys08`, both electric-PIU-reheat, zero-plant-loop buildings). 1386 = 693 (unchanged) + 693 (new) -- not a coincidence of rounding, but two structurally analogous building pairs producing numerically identical blueprint-survival counts. (For the 756->630->693 history before this round, see the prior version of this report / `CHANGELOG.md`.)

## Topologies extracted

| building_id | description | HVAC | nodes | feeds edges | node types |
|---|---|---|---|---|---|
| `sys08_vav_parallel_piu` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 1 AHU (VAV fan, chilled-water cooling coil, electric heating coil) -> 10 Parallel-PIU-Reheat VAV terminals -> 10 zones; chilled-water plant with 1 pump/chiller | 25 | 21 | AHU=1, Cooling_Coil=1, Fan=1, HVAC_Zone=10, Heating_Coil=1, Pump=1, VAV=10 |
| `sys07_vav_reheat` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 1 AHU (VAV fan, chilled-water cooling coil) -> 10 VAV-Reheat terminals (hot-water reheat coils) -> 10 zones; separate chilled-water and hot-water plants (chiller + condenser loop, boiler) | 36 | 32 | AHU=1, Cooling_Coil=1, Fan=1, HVAC_Zone=10, Heating_Coil=11, Pump=2, VAV=10 |
| `sys05_vav_reheat_dx` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 1 AHU (VAV fan, DX cooling coil) -> 10 VAV-Reheat terminals (hot-water reheat coils) -> 10 zones; a single hot-water plant (1 pump/boiler) -- the cooling coil is DX, not on any plant loop, so this building has only ONE medium/pump, unlike sys07's two | 35 | 31 | AHU=1, Cooling_Coil=1, Fan=1, HVAC_Zone=10, Heating_Coil=11, Pump=1, VAV=10 |
| `sys06_vav_piu_dx` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 1 AHU (VAV fan, DX cooling coil, electric heating coil) -> 10 Parallel-PIU-Reheat VAV terminals (electric reheat) -> 10 zones; NO plant loop and NO pump anywhere in the building -- fully DX/electric | 24 | 20 | AHU=1, Cooling_Coil=1, Fan=1, HVAC_Zone=10, Heating_Coil=1, VAV=10 |

## Structural corruption: physical rewiring plausibility

All three real edge types identified in the original exclusion breakdown are now in scope: **terminal-unit<->zone** reassignment (original mechanism), **AHU<->zone-direct** (prior addition), and **pump<->coil**, new in this run -- a heating/cooling coil misconnected to the wrong plant loop/pump, or falsely claimed connected/disconnected. `generate_blueprint` is still called completely unmodified on the full graph; `physics_pipeline/scope.py` filters its output events down to these three edge types and reconstructs `claimed_edges` to match -- the same approach proven for AHU-direct, not the restricted-input-graph approach that failed earlier (see `scope.py`'s docstring for why).

**Coverage progression:** the denominator itself grows with the batch, since it's drawn fresh from whichever buildings are in `BASE_BUILDINGS` -- on the original 2-building (`sys07`/`sys08`) batch it was 10/24 (42%) with terminal<->zone alone -> 13/24 (54%) adding AHU<->zone-direct -> 18/24 (75%) adding pump<->coil. Widened to 4 buildings (`sys05_vav_reheat_dx` and `sys06_vav_piu_dx` added), the same three edge types now cover **40/48 (83%)** of the events `generate_blueprint` draws on these seeds/severities across all 4 buildings. The remaining 8 (17%) are structurally inapplicable, the same way AHU<->Terminal_Unit already was, not a gap in what's built:

- 8x target is VAV (not a zone or coil edge type this pipeline rewires)

All 8 remaining exclusions are `target is VAV`, i.e. an AHU<->Terminal_Unit edge -- there's only ever one AHU per building in this batch (true of all 4 buildings, not just the original 2), so reassigning "which AHU feeds this terminal" isn't a meaningful rewire on any of them. **No new out-of-scope category appeared** when sys05/sys06 were added -- every pump<->coil and terminal<->zone/AHU-direct candidate these two new buildings' seeds drew landed in the same in-scope bucket as before. (Being "in scope" means this pipeline *attempts* the rewire, not that it's guaranteed to succeed -- see the new DX-coil finding below for a real case where an in-scope pump<->coil event still fails.)

**Two coil-specific findings from Step 0, confirmed rather than assumed to generalize from the AHU-direct case:**
1. A coil survives disconnection from its plant loop (unlike a terminal, which `removeBranchForZone` destroys) -- verified by resolving its handle and calling methods on it afterward -- so reassigning a coil to a different pump needs no cloning at all.
2. A coil left connected to the air side with no water connection is **not** valid EnergyPlus input (fails with a missing-node-name error), unlike a zone, which can validly go unconditioned. A genuine "no pump feeds this coil" removal has to fully delete the coil, not just disconnect its water side -- and there are two structurally different delete paths depending on whether the coil is a standalone AHU-level component (`removeFromAirLoopHVAC()` works directly) or embedded inside a VAV:Reheat terminal (`removeFromAirLoopHVAC()` silently returns `False` -- it only reaches direct branch components -- so the terminal itself has to be replaced with its no-reheat equivalent instead; most `Heating_Coil` targets on `sys07_vav_reheat` are this second case).

**New this round -- sys05/sys06 add genuinely new plant/coil topologies, not just more seeds on the same two buildings:** `sys05_vav_reheat_dx` has the same hydronic VAV-reheat terminal class as `sys07`, but its cooling coil is DX (not chilled-water), so it has only **one** plant loop/pump (hot-water) instead of sys07's two -- a single-medium case where cross-medium mixing is structurally impossible (no second medium to draw from). `sys06_vav_piu_dx` has the same electric-PIU-reheat terminal class as `sys08`, but its cooling coil is also DX -- so it has **zero** plant loops and **zero** pumps anywhere in the building. Both use the exact same `AirLoopHVAC`/VAV-terminal/`PlantLoop`-pump object classes the existing `extract.py`/`rewire.py` already handle, so no code changes were needed to attempt them -- but "same object classes" turned out not to mean "identical behavior," per the DX-coil finding immediately below.

**A real, previously-latent bug found by widening: a misleading diagnostic message for coils that exist but aren't hydronic.** `_handle_coil_event`'s failure-to-resolve message was written for `sys07`/`sys08`, where a coil is *always* `Coil:Cooling:Water` or `Coil:Heating:Water` -- so a failed resolve there could only mean one thing: the coil was destroyed by an earlier event in the same blueprint (the cross-event collision case). `sys05`'s cooling coil is `Coil:Cooling:DX:TwoSpeed`. `generate_blueprint` still drew fabrication events claiming a pump feeds it (a legitimate ontology-tier candidate -- DX and hydronic coils are the same Brick class), but `_resolve_coil` can never resolve a DX coil (it only tries the two hydronic accessors), so every such event was reported as a collision-destroyed node even when the coil was never destroyed at all -- it was never hydronic in the first place. Confirmed with a direct call (severity 2, seed 91302006): the coil resolves fine as a raw object and is provably still present, yet the old message would have blamed a nonexistent collision. Fixed by checking whether the raw object resolves at all *before* checking whether it resolves as a hydronic coil, so the two causes -- "genuinely destroyed" vs. "exists but isn't a type this pipeline's pump/coil rewiring supports" -- are reported distinctly (`pipeline.py`, `_unresolved_coil_reason`). **Structural consequence, not just a message fix:** on `sys05`, every pump<->coil fabrication/misattribution event that lands on the DX cooling coil now correctly shows `rewired=False` with an honest reason, and always will -- this pipeline's coil rewiring only supports hydronic coils, so a DX-coil target is a genuine, permanent scope gap for this building, not a transient collision. It happens to **not appear** in this batch's own 6 seeds (`sys05`'s coil-target events here are all removals of the hydronic heating coil, which succeed normally -- see the summary table), but a wider sweep (severities 1-10, 20 seeds each) found it recurs roughly every 10-20 seeds, so it is a real, recurring case for this building, just one this particular seed set didn't happen to draw. Reported here rather than left to surface silently in a future, larger run.

**sys06's "0% collision rate"/"0 failed" is backed by a proof, not just an absence of counterexamples -- checked precisely because the DX-coil finding above showed "same object classes, no code changes needed" doesn't guarantee identical behavior.** `sys06_vav_piu_dx` has `zone_to_coil == {}` (no hydronic coils anywhere), which makes two guards short-circuit: `scope.filter_collision_events` returns immediately (`if not zone_to_coil or ...`), and its caller `generate_scoped_blueprint` doesn't even call it (`if zone_to_coil: ...`) -- so the collision-detection logic *itself* never actually runs for sys06 in production, which is a different, weaker claim than "it ran and found nothing." Verified by forcing the real logic to execute anyway, bypassing both guards, on an actual sys06 production blueprint (severity 3, seed 91303001 -- a real 3-event blueprint: fabrication + removal + misattribution): `destroyed_zones` came out non-empty (4 zones -- misattribution destroys two terminals), then correctly reduced to an empty `destroyed_coils` *because* `z in {}` is always False, not because there was nothing to check -- and `kept_events` matched the full unfiltered blueprint, identical to the short-circuit's result. Separately, and more importantly: `pipeline._handle_coil_event`/`reassign_coil`/`remove_coil_service` (where the DX-coil bug actually lived) are **provably unreachable** for sys06, not just unobserved in this batch's seeds -- confirmed by two independent guarantees, not one. First, `_event_in_scope` requires every source in a coil-target event to resolve to Brick type `Pump` (`IN_SCOPE_COIL_SOURCE_TYPES = frozenset({'Pump'})`), checked at the graph layer before any OpenStudio model access. Second, sys06's extracted graph has zero Pump-type nodes -- confirmed three independent ways (direct OpenStudio inspection: `Pump:VariableSpeed count: 0`; every production run's `node_type_counts` has no `'Pump'` key; `rewire.build_zone_to_coil_map` returns `{}`) -- and reading `hvac_benchmark`'s `generate_feeds_candidates` directly confirms candidate sources are filtered from the graph's actual nodes (`nodes = tg.nodes()`), so a Pump-sourced candidate cannot exist if no Pump node exists. `rewire.build_zone_to_coil_map` itself never inspects `PlantLoop`/`Pump` collections at all (it only walks VAV:Reheat terminal reheat-coil accessors) -- there is no "assumes at least one exists" code shape in it for a sibling of the DX-coil bug to hide in.

**Cross-event collision: confirmed to generalize along the hydronic-coil boundary, not a sys07-specific quirk.** Multiple corruption events in one blueprint are applied sequentially to the same scratch model; a zone-targeting event's terminal replacement can cascade-delete a reheat coil that a *different*, independently-drawn coil-targeting event in the same blueprint also targets by node id. Extending the same empirical study (pure graph-level simulation, severities 1-10, 200 seeds each) to all 4 buildings: `sys07_vav_reheat` 0% (sev 1) -> 15% (sev 3) -> 92% (sev 10); `sys05_vav_reheat_dx` (also hydronic zone-embedded reheat coils, just a single-medium plant) 0% -> 6% -> 69% -- nonzero and growing the same way, confirming the risk tracks "does this building have hydronic zone-embedded coils at all," not something particular to sys07; `sys08_vav_parallel_piu` and `sys06_vav_piu_dx` (both electric reheat, no plant connection to cascade-delete) are flat 0% on both. `rewire.build_zone_to_coil_map()` + `scope.filter_collision_events()` -- unchanged code, already building the map generically from whatever terminal/coil classes are present -- drop a colliding event *before* it's ever attempted for all 4 buildings alike. Within this batch's actual 6 seeds/building (severities 1-3, 2 seeds each, far fewer draws than the 200-seed study), exactly 1 event was dropped, on `sys07` (severity 3, one seeded variant) -- the same single case as the prior report. `sys05` drew no colliding event in this particular small seed set despite having nonzero underlying risk at these severities (~6% at severity 3, per the study above) -- consistent with a real but lower-probability risk, not evidence the filter doesn't apply there.

**Cross-medium pump/coil risk: still real on the dual-medium buildings, and structurally impossible on sys05 by construction -- a clean confirming contrast, not a contradiction.** On `sys07` (two pumps: chilled-water and hot-water), two misattribution events in this batch again moved a heating coil onto the *other* pump's loop -- a genuine cross-medium swap, producing **0 severe errors** while the coil silently delivers **exactly 0.0 W of heat, every hour** (confirmed via the January-window baseline-vs-corrupted functional check; both are flagged `functionally dead` in the table below, same as the prior report). On `sys05` (only one pump, hot-water only), this specific failure mode **cannot occur at all**: there is no second medium/pump for a coil to be misattributed onto. This isn't something to fix -- it's the risk correctly *not* materializing where the physical precondition for it (a second incompatible medium) doesn't exist, which is exactly the behavior a physically-grounded check should have.

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
| `sys05_vav_reheat_dx` | 1 | 91301001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys05_vav_reheat_dx` | 1 | 91301002 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys05_vav_reheat_dx` | 2 | 91302001 | 0 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys05_vav_reheat_dx` | 2 | 91302001 | 1 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys05_vav_reheat_dx` | 2 | 91302002 | 0 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys05_vav_reheat_dx` | 2 | 91302002 | 1 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys05_vav_reheat_dx` | 3 | 91303001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys05_vav_reheat_dx` | 3 | 91303001 | 1 | removal | Heating_Coil | clean | 0 | - |
| `sys05_vav_reheat_dx` | 3 | 91303002 | 0 | removal | Heating_Coil | clean | 0 | - |
| `sys05_vav_reheat_dx` | 3 | 91303002 | 1 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys05_vav_reheat_dx` | 3 | 91303002 | 2 | removal | Heating_Coil | clean | 0 | - |
| `sys06_vav_piu_dx` | 1 | 91301001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys06_vav_piu_dx` | 2 | 91302001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys06_vav_piu_dx` | 2 | 91302001 | 1 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys06_vav_piu_dx` | 2 | 91302002 | 0 | removal | HVAC_Zone | clean | 0 | - |
| `sys06_vav_piu_dx` | 2 | 91302002 | 1 | removal | HVAC_Zone | clean | 0 | - |
| `sys06_vav_piu_dx` | 3 | 91303001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys06_vav_piu_dx` | 3 | 91303001 | 1 | removal | HVAC_Zone | clean | 0 | - |
| `sys06_vav_piu_dx` | 3 | 91303001 | 2 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys06_vav_piu_dx` | 3 | 91303002 | 0 | removal | HVAC_Zone | clean | 0 | - |
| `sys06_vav_piu_dx` | 3 | 91303002 | 1 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys06_vav_piu_dx` | 3 | 91303002 | 2 | removal | HVAC_Zone | clean | 0 | - |

**Summary: 39 in-scope events attempted across all 4 buildings (collision-filtered events never reach this table at all -- see the collision note above); 37 clean and functionally confirmed, 2 passed 0-severe-errors but are functionally dead (caught only by the functional-effect check, not by severe_errors), 0 failed to rewire.** Verified: 37 + 2 + 0 == 39. Reported as-is, not rounded up to a clean line or hidden. The 8/48 (17%) still excluded from the full candidate pool (AHU<->Terminal_Unit, structurally inapplicable) never reach this table at all. **0 failed to rewire in this specific batch** -- the DX-coil scope gap found on `sys05` this round (see above) didn't happen to be drawn by these particular seeds, so it doesn't show up as a nonzero count here; it is still a real, recurring case for that building, documented above rather than only visible once a future run's seeds happen to hit it.

## Fault injection: independent performance-fault mechanism

For each blueprint, an `FaultModel:ThermostatOffset` (+5 degC sensor offset) is injected on the TRUE (uncorrupted) model near the corruption site, using the exact locality logic `symptom_flagged_nodes` already defines for the symptom-triggered troubleshooting experiment. **This is a fully independent, separately-toggleable mechanism from the structural corruption above** -- a different model copy, no shared state -- confirming the two were not accidentally fused into one step.

**A real API gap found:** OpenStudio's `openstudio.model` Python API has no wrapper class for any of EnergyPlus's dozen-plus `FaultModel:*` objects (confirmed: nothing case-insensitively matching "fault" in `dir(openstudio.model)`, out of ~4800 names). Faults are injected as raw IDF objects on the post-`ForwardTranslator` `Workspace` instead -- a standard, well-documented EnergyPlus-only pattern, just one level below OpenStudio's typed Model API.

**Coverage gap: pump/coil-only blueprints are blind-mode-only, by decision, not by oversight.** `symptom_flagged_nodes` flags the corruption target plus its immediate neighbors under any relation; for a pump<->coil-only blueprint those neighbors are the AHU/pump side, never a zone, so there's no zone to inject a thermostat-offset fault into. Checked across all 4 buildings in this widened batch, not just re-asserted from the prior report: exactly one blueprint has no fault record for this reason -- `sys07_vav_reheat`, severity 1, the pump/coil removal (same as before). Neither `sys05` nor `sys06` introduced a new instance of this gap in this batch's blueprints -- every blueprint they generated here happened to include at least one zone-side event alongside any coil event. `FaultModel:Fouling:Coil` was investigated as a coil-level substitute and does NOT generalize the way its original single-building validation suggested: the same default fouling factor that gave a moderate +3.4C effect on `sys08`'s central cooling coil instead drops `sys07`'s central cooling coil's output to exactly 0.0 W (complete shutdown, not degradation), and has **zero measurable effect** on `sys07`'s reheat coils at all -- confirmed by comparing `Heating Coil U Factor Times Area Value` against `...Before Fouling` (bit-identical at both the default factor and 100x it). Rather than ship a fault mechanism that produces misleading all-or-nothing results, pump/coil-only blueprints stay blind-mode-only until this is properly investigated -- the code for a coil-level fault call exists in `pipeline.py` (`_run_coil_fault`), unused, as a documented starting point, not a validated mechanism.

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
| `sys05_vav_reheat_dx` | 91301001 | Thermal Zone 8 | True | True | 5.00 | -3.44 |
| `sys05_vav_reheat_dx` | 91301002 | Thermal Zone 10 | True | True | 5.00 | -3.15 |
| `sys05_vav_reheat_dx` | 91302001 | Thermal Zone 2 | True | True | 5.00 | -3.41 |
| `sys05_vav_reheat_dx` | 91302002 | Thermal Zone 4 | True | True | 5.00 | -3.66 |
| `sys05_vav_reheat_dx` | 91303001 | Thermal Zone 1 | True | True | 5.00 | -2.98 |
| `sys05_vav_reheat_dx` | 91303002 | Thermal Zone 5 | True | True | 3.41 | -2.66 |
| `sys06_vav_piu_dx` | 91301001 | Thermal Zone 7 | True | True | 5.01 | -3.76 |
| `sys06_vav_piu_dx` | 91302001 | Thermal Zone 9 | True | True | 5.00 | -3.93 |
| `sys06_vav_piu_dx` | 91302002 | Thermal Zone 5 | True | True | 5.00 | -4.02 |
| `sys06_vav_piu_dx` | 91303001 | Thermal Zone 2 | True | True | 5.00 | -3.82 |
| `sys06_vav_piu_dx` | 91303002 | Thermal Zone 2 | True | True | 5.00 | -3.82 |

All fault runs produced a measurable, localized, non-degenerate temperature deviation (not zero, not NaN, not building-wide) -- a realistic symptom signal a technician could plausibly notice.

## Troubleshooting-against-a-blueprint results (existing Bayesian benchmark, placeholder noise rates)

Everything below is produced by calling `hvac_benchmark.evaluate.troubleshooting_report.build_troubleshooting_section` completely unmodified, on the physics-extracted topologies/blueprints above instead of the real-Brick-model topologies it normally receives -- confirming the existing Bayesian machinery accepts physics-derived graphs without any changes to its own code.

**Read the "Symptom-triggered" rows below with the fault-injection coverage gap above in mind.** `symptom_flagged_nodes` -- the graph-locality function `build_troubleshooting_section` uses to decide which nodes count as "symptom-flagged" -- runs at the abstract graph level for every blueprint uniformly, whether or not this pipeline actually injected a physics-based EnergyPlus fault to back that symptom up. Checked across the full widened batch: exactly one blueprint feeding the rows below (`sys07_vav_reheat`, severity 1, seed 91301001, a pump<->coil-only removal) has no fault record at all (see above) -- pump/coil-only blueprints are blind-mode-only by decision -- yet its trials still appear in the "Symptom-triggered" table, using the abstract locality flag on its own. `sys05_vav_reheat_dx` and `sys06_vav_piu_dx` did not introduce a second such blueprint in this batch. Do not read "Symptom-triggered" coverage here as "every blueprint has a physics-validated fault behind it" -- one still does not.

## Troubleshooting-against-a-blueprint (separate evaluation mode)

**This section is a separate evaluation mode from the full-topology-discovery results above and is never blended with them.** Discovery mode assumes near-zero prior knowledge and measures tests to reconstruct an entire graph from scratch. This mode assumes the opposite starting condition: a trusted blueprint (the true graph, deliberately corrupted at a few points) is already given, and the task is to find the corrupted edge(s) in as few tests as possible -- the day-to-day troubleshooting scenario, not a periodic full audit.

- **4 real topologies** evaluated in this mode: sys05_vav_reheat_dx, sys06_vav_piu_dx, sys07_vav_reheat, sys08_vav_parallel_piu (the same `feeds`-eligible topologies used by the primary discovery benchmark above).
- Corruption severities tested: [1, 2, 3] corrupted edge(s) (an edge = one corruption event; misattribution counts as one event even though it touches two candidate pairs), with 3 independently-seeded corrupted-blueprint variants per (topology, severity), each replayed across 3 tie-break/noise seeds -- a deliberately bounded sample (mirroring the ablation-subset bounding elsewhere in this report), not a statistically powered sweep.

> **Evidence level: small case study, same caveat as the rest of this document.** Numbers below are within-topology variability across corrupted-blueprint variants and seeds, not additional independent buildings or corruption instances beyond what is listed above. No pooled cross-topology number is computed or implied anywhere in this section.

**Belief model reuse:** this mode reuses the exact same Bernoulli update and expected-information-gain machinery as discovery mode (`bayes.update` / `expected_information_gain`), completely unmodified -- only the prior changes (near-certain on blueprint-claimed edges, sparse-floor elsewhere), confirming the two modes did not need a parallel inference system.

**Candidate universe:** identical physically-plausible candidate set as discovery mode's `feeds` benchmark, not just blueprint-claimed edges -- required so an undocumented real connection (a *removal* corruption) can be tested at all. One consequence: **the `full_sweep` baseline only re-tests blueprint-claimed edges, so by construction it can never find a removal-type corruption** -- a structural limitation of that reference baseline, not a bug, visible below wherever removal corruptions appear in a topology's mix.

**Metric:** tests needed until every corrupted candidate is simultaneously flagged (current belief disagrees with the blueprint's own claim), first-reached and sustained-to-end-of-trial, median [range] across variants x seeds, with attainment rate. Also reported: false-positive rate (fraction of genuinely-correct blueprint edges ever incorrectly flagged along the way) and needless-retest count (tests spent on edges that were both blueprint-claimed-true and genuinely correct) -- a technician chasing a phantom problem, or an algorithm ignoring the strong prior it was given, are both counted as real costs here, never as neutral.

### sys05_vav_reheat_dx

Corruption types actually generated for this topology across all variants: fabrication, misattribution, removal.

**Blind verification**

severity = 1 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 15 [1-21] (n=6) | 100% | 15 [1-21] (n=6) | 100% | 0.0% [0.0%-0.0%] | 31 [31-31] (n=6) |
| active | 5% | 16 [2-22] (n=4) | 67% | 16 [2-22] (n=4) | 67% | 0.0% [0.0%-0.0%] | 33 [31-33] (n=6) |
| active | 15% | 23 [3-23] (n=3) | 50% | 23 [3-23] (n=3) | 50% | 0.0% [0.0%-1.2%] | 41 [39-54] (n=6) |
| full_sweep | 0% | 15 [1-21] (n=6) | 100% | 15 [1-21] (n=6) | 100% | 0.0% [0.0%-0.0%] | 31 [31-31] (n=6) |
| full_sweep | 5% | 33 [33-33] (n=4) | 67% | 33 [33-33] (n=4) | 67% | 0.0% [0.0%-0.0%] | 33 [31-33] (n=6) |
| full_sweep | 15% | 40 [38-42] (n=3) | 50% | 40 [38-42] (n=3) | 50% | 0.0% [0.0%-1.2%] | 41 [39-54] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 60 [40-77] (n=6) | 100% | 60 [40-77] (n=6) | 100% | 0.0% [0.0%-0.0%] | 30 [30-30] (n=6) |
| active | 5% | 70 [45-90] (n=6) | 100% | 70 [45-90] (n=6) | 100% | 0.0% [0.0%-0.0%] | 32 [30-32] (n=6) |
| active | 15% | 92 [66-123] (n=4) | 67% | 92 [66-123] (n=4) | 67% | 0.0% [0.0%-1.3%] | 40 [38-53] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 30 [30-30] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 32 [30-32] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-1.3%] | 40 [38-53] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 66 [40-77] (n=6) | 100% | 66 [40-77] (n=6) | 100% | 0.0% [0.0%-0.0%] | 30 [29-30] (n=6) |
| active | 5% | 77 [62-88] (n=5) | 83% | 77 [62-88] (n=5) | 83% | 0.0% [0.0%-0.0%] | 31 [29-32] (n=6) |
| active | 15% | 119 [99-119] (n=3) | 50% | 119 [99-119] (n=3) | 50% | 0.0% [0.0%-1.2%] | 40 [37-53] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 30 [29-30] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 31 [29-32] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-1.2%] | 40 [37-53] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

**Symptom-triggered**

severity = 1 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 2 [1-3] (n=6) | 100% | 2 [1-3] (n=6) | 100% | 0.0% [0.0%-0.0%] | 31 [31-31] (n=6) |
| active | 5% | 2 [1-94] (n=6) | 100% | 2 [1-94] (n=6) | 100% | 0.0% [0.0%-0.0%] | 35 [33-35] (n=6) |
| active | 15% | 8 [1-21] (n=6) | 100% | 2 [1-21] (n=5) | 83% | 1.2% [0.0%-2.5%] | 47 [43-62] (n=6) |
| symptom_naive | 0% | 5 [1-7] (n=6) | 100% | 5 [1-7] (n=6) | 100% | 0.0% [0.0%-0.0%] | 2 [2-2] (n=6) |
| symptom_naive | 5% | 6 [3-23] (n=6) | 100% | 6 [3-23] (n=6) | 100% | 0.0% [0.0%-0.0%] | 4 [4-4] (n=6) |
| symptom_naive | 15% | 14 [3-41] (n=6) | 100% | 5 [3-28] (n=5) | 83% | 1.2% [0.0%-1.2%] | 8 [6-12] (n=6) |
| full_sweep | 0% | 15 [1-21] (n=6) | 100% | 15 [1-21] (n=6) | 100% | 0.0% [0.0%-0.0%] | 31 [31-31] (n=6) |
| full_sweep | 5% | 18 [1-38] (n=6) | 100% | 18 [1-38] (n=6) | 100% | 0.0% [0.0%-0.0%] | 35 [33-35] (n=6) |
| full_sweep | 15% | 28 [1-47] (n=6) | 100% | 15 [1-45] (n=5) | 83% | 1.2% [0.0%-2.5%] | 47 [43-62] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 16 [8-21] (n=6) | 100% | 16 [8-21] (n=6) | 100% | 0.0% [0.0%-0.0%] | 30 [30-30] (n=6) |
| active | 5% | 16 [8-21] (n=6) | 100% | 20 [8-25] (n=6) | 100% | 0.0% [0.0%-1.3%] | 35 [33-35] (n=6) |
| active | 15% | 30 [11-168] (n=6) | 100% | 30 [16-168] (n=6) | 100% | 1.3% [0.0%-1.3%] | 49 [46-63] (n=6) |
| symptom_naive | 0% | 21 [15-22] (n=6) | 100% | 21 [15-22] (n=6) | 100% | 0.0% [0.0%-0.0%] | 3 [3-3] (n=6) |
| symptom_naive | 5% | 21 [15-22] (n=6) | 100% | 21 [15-46] (n=6) | 100% | 0.0% [0.0%-1.3%] | 6 [6-8] (n=6) |
| symptom_naive | 15% | 22 [15-85] (n=6) | 100% | 69 [21-93] (n=6) | 100% | 0.0% [0.0%-1.3%] | 13 [11-15] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 30 [30-30] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-1.3%] | 35 [33-35] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 1.3% [0.0%-1.3%] | 49 [46-63] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 18 [16-21] (n=6) | 100% | 18 [16-21] (n=6) | 100% | 0.0% [0.0%-0.0%] | 30 [29-30] (n=6) |
| active | 5% | 19 [16-88] (n=6) | 100% | 19 [16-88] (n=6) | 100% | 0.0% [0.0%-1.3%] | 42 [40-46] (n=6) |
| active | 15% | 34 [25-40] (n=5) | 83% | 34 [25-40] (n=5) | 83% | 2.5% [1.2%-3.8%] | 67 [59-77] (n=6) |
| symptom_naive | 0% | 14 [6-21] (n=6) | 100% | 14 [6-21] (n=6) | 100% | 0.0% [0.0%-0.0%] | 12 [11-12] (n=6) |
| symptom_naive | 5% | 16 [13-47] (n=6) | 100% | 16 [13-47] (n=6) | 100% | 0.0% [0.0%-1.3%] | 24 [22-28] (n=6) |
| symptom_naive | 15% | 21 [14-56] (n=5) | 83% | 21 [14-56] (n=5) | 83% | 2.5% [1.2%-3.8%] | 43 [37-51] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 30 [29-30] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-1.3%] | 42 [40-46] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 2.5% [1.2%-3.8%] | 67 [59-77] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

### sys06_vav_piu_dx

Corruption types actually generated for this topology across all variants: fabrication, misattribution, removal.

**Blind verification**

severity = 1 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 17 [7-20] (n=3) | 100% | 17 [7-20] (n=3) | 100% | 0.0% [0.0%-0.0%] | 20 [20-20] (n=3) |
| active | 5% | 18 [8-21] (n=3) | 100% | 18 [8-21] (n=3) | 100% | 0.0% [0.0%-0.0%] | 20 [20-24] (n=3) |
| active | 15% | 27 [11-32] (n=3) | 100% | 27 [11-32] (n=3) | 100% | 0.0% [0.0%-1.4%] | 30 [28-34] (n=3) |
| full_sweep | 0% | 17 [7-20] (n=3) | 100% | 17 [7-20] (n=3) | 100% | 0.0% [0.0%-0.0%] | 20 [20-20] (n=3) |
| full_sweep | 5% | 22 [22-22] (n=3) | 100% | 22 [22-22] (n=3) | 100% | 0.0% [0.0%-0.0%] | 20 [20-24] (n=3) |
| full_sweep | 15% | 29 [27-29] (n=3) | 100% | 29 [27-29] (n=3) | 100% | 0.0% [0.0%-1.4%] | 30 [28-34] (n=3) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 54 [30-67] (n=6) | 100% | 54 [30-67] (n=6) | 100% | 0.0% [0.0%-0.0%] | 18 [18-19] (n=6) |
| active | 5% | 64 [39-78] (n=6) | 100% | 64 [39-78] (n=6) | 100% | 0.0% [0.0%-0.0%] | 19 [18-23] (n=6) |
| active | 15% | 71 [56-91] (n=3) | 50% | 77 [56-91] (n=3) | 50% | 0.0% [0.0%-1.5%] | 28 [21-33] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 18 [18-19] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 19 [18-23] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-1.5%] | 28 [21-33] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 64 [40-69] (n=6) | 100% | 64 [40-69] (n=6) | 100% | 0.0% [0.0%-0.0%] | 18 [18-18] (n=6) |
| active | 5% | 73 [47-83] (n=4) | 67% | 73 [47-83] (n=4) | 67% | 0.0% [0.0%-0.0%] | 18 [18-18] (n=6) |
| active | 15% | 100 [95-106] (n=2) | 33% | 100 [95-106] (n=2) | 33% | 0.0% [0.0%-0.0%] | 26 [26-28] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 18 [18-18] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 18 [18-18] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 26 [26-28] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

**Symptom-triggered**

severity = 1 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 3 [1-3] (n=3) | 100% | 3 [1-3] (n=3) | 100% | 0.0% [0.0%-0.0%] | 20 [20-20] (n=3) |
| active | 5% | 3 [1-3] (n=3) | 100% | 3 [1-3] (n=3) | 100% | 0.0% [0.0%-0.0%] | 22 [22-26] (n=3) |
| active | 15% | 3 [1-3] (n=3) | 100% | 3 [1-3] (n=3) | 100% | 0.0% [0.0%-1.4%] | 34 [32-38] (n=3) |
| symptom_naive | 0% | 10 [2-10] (n=3) | 100% | 10 [2-10] (n=3) | 100% | 0.0% [0.0%-0.0%] | 2 [2-2] (n=3) |
| symptom_naive | 5% | 10 [2-10] (n=3) | 100% | 10 [2-10] (n=3) | 100% | 0.0% [0.0%-0.0%] | 4 [4-4] (n=3) |
| symptom_naive | 15% | 10 [2-10] (n=3) | 100% | 10 [2-10] (n=3) | 100% | 0.0% [0.0%-0.0%] | 6 [6-6] (n=3) |
| full_sweep | 0% | 17 [7-20] (n=3) | 100% | 17 [7-20] (n=3) | 100% | 0.0% [0.0%-0.0%] | 20 [20-20] (n=3) |
| full_sweep | 5% | 17 [7-20] (n=3) | 100% | 17 [7-20] (n=3) | 100% | 0.0% [0.0%-0.0%] | 22 [22-26] (n=3) |
| full_sweep | 15% | 17 [7-20] (n=3) | 100% | 17 [7-20] (n=3) | 100% | 0.0% [0.0%-1.4%] | 34 [32-38] (n=3) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 17 [10-19] (n=6) | 100% | 17 [10-19] (n=6) | 100% | 0.0% [0.0%-0.0%] | 18 [18-19] (n=6) |
| active | 5% | 17 [10-19] (n=6) | 100% | 17 [10-19] (n=6) | 100% | 0.0% [0.0%-1.5%] | 23 [20-26] (n=6) |
| active | 15% | 34 [13-65] (n=6) | 100% | 34 [15-65] (n=6) | 100% | 0.7% [0.0%-2.9%] | 34 [29-40] (n=6) |
| symptom_naive | 0% | 18 [15-21] (n=6) | 100% | 18 [15-21] (n=6) | 100% | 0.0% [0.0%-0.0%] | 2 [2-3] (n=6) |
| symptom_naive | 5% | 18 [15-21] (n=6) | 100% | 18 [15-21] (n=6) | 100% | 0.0% [0.0%-1.5%] | 5 [4-10] (n=6) |
| symptom_naive | 15% | 38 [18-91] (n=6) | 100% | 52 [18-91] (n=6) | 100% | 0.7% [0.0%-1.5%] | 10 [6-16] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 18 [18-19] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-1.5%] | 23 [20-26] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.7% [0.0%-2.9%] | 34 [29-40] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 27 [18-31] (n=6) | 100% | 27 [18-31] (n=6) | 100% | 0.0% [0.0%-0.0%] | 18 [18-18] (n=6) |
| active | 5% | 30 [18-111] (n=6) | 100% | 30 [18-111] (n=6) | 100% | 0.0% [0.0%-0.0%] | 24 [22-24] (n=6) |
| active | 15% | 34 [23-38] (n=4) | 67% | 86 [38-135] (n=4) | 67% | 0.0% [0.0%-1.5%] | 38 [36-42] (n=6) |
| symptom_naive | 0% | 28 [22-31] (n=6) | 100% | 28 [22-31] (n=6) | 100% | 0.0% [0.0%-0.0%] | 4 [4-4] (n=6) |
| symptom_naive | 5% | 30 [22-72] (n=6) | 100% | 30 [22-72] (n=6) | 100% | 0.0% [0.0%-0.0%] | 10 [8-10] (n=6) |
| symptom_naive | 15% | 27 [22-31] (n=4) | 67% | 80 [30-133] (n=4) | 67% | 0.0% [0.0%-1.5%] | 16 [14-24] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 18 [18-18] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 24 [22-24] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-1.5%] | 38 [36-42] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

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
