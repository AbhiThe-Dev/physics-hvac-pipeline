# Physics-based test case pipeline: foundation run

**These are synthetic, physics-simulated test buildings, not real occupied buildings, and not the DOE Commercial Prototype Building Models.** They are small ASHRAE 90.1 Appendix G baseline-system test fixtures from `NREL/OpenStudio-resources` (BSD-3-Clause, same license as the OpenStudio SDK). The `OpenStudio-Prototype-Buildings` repo has no license file and its real generator code has moved to `openstudio-standards` (a Ruby toolchain); sourcing real DOE prototypes was deferred by explicit decision, documented in this run's provenance, in favor of proving the pipeline end to end first.

**Scope of this run:** 10 topologies x 1 climate zone (Chicago-OHare_TMY3_ASHRAE-CZ5A-cold, weather file `USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw`), 3087 total troubleshooting trials, run with the EXISTING Bayesian benchmark's current placeholder noise rates (['0%', '5%', '15%']) -- purely to confirm this new physics pipeline produces sensible, non-degenerate results end to end through the existing troubleshooting-mode machinery, unmodified. **No noise-rate calibration from physics was attempted; that is explicitly out of scope for this run.**

**Trial-count reconciliation, before presenting the number above:** the previous (sys05/sys06-widening) run, on 4 buildings, reported 1386 trials; this run, extended to all 10 ASHRAE 90.1 Appendix G baseline systems, reports 3087. The multiplier per blueprint is unchanged (63 = 7 policies x 3 noise levels x 3 tie-break seeds). All 4 previously-validated buildings reran bit-for-bit identical this time (confirmed by a field-by-field diff of every plausibility record after each of this round's code changes, not just at the end) -- `sys08_vav_parallel_piu` 315, `sys07_vav_reheat` 378, `sys05_vav_reheat_dx` 378, `sys06_vav_piu_dx` 315, together the same 1386 as before. The six new buildings add: `sys01_ptac` 378, `sys02_pthp` 378, `sys03_psz_ac` 252, `sys04_psz_hp` 252, `sys09_furnace_gas` 189, `sys10_furnace_electric` 252. 3087 = 1386 (unchanged) + 1701 (six new buildings). (For the full 756->630->693->1386 history before this round, see `CHANGELOG.md`.)

## Six-system extension: PTAC, PTHP, and four single-zone non-VAV systems

This round extended the pipeline to the six systems previously scoped out as needing real `extract.py`/`rewire.py` work, not the drop-in reuse `sys05`/`sys06` got. **Coverage and validation effort differed substantially across the six, and that difference is preserved here rather than folded into one uniform "validated" claim:**

- **`sys02_pthp` needed no new code beyond what `sys01` required.** Same object family as `sys01` (`ZoneHVAC:PackagedTerminalHeatPump` alongside `PackagedTerminalAirConditioner`), and every mechanism (extraction, rewiring, collision behavior) generalized directly. Its zero-coil-target-events and flat-0%-collision status were independently confirmed -- 105 exploratory blueprint attempts drew zero coil-target events (a structural certainty, not a sampling artifact: `_event_in_scope` requires a Pump-typed source for any coil-target event, and `sys02`'s graph has zero Pump nodes), not assumed from either `sys01` (which does have a real hydronic coil) or `sys06` (a different object family entirely).

- **`sys01_ptac` needed a third new subsystem beyond extraction**, found by auditing `rewire.py`'s zone-service functions against it rather than assuming they'd generalize: every one was built on `find_airloop_for_zone`, which returns `None` for every PTAC zone (there is no `AirLoopHVAC` at all -- confirmed via direct model inspection, not assumed from the system name). A new packaged-unit dispatch path was added, verified empirically to have *simpler* lifetime semantics than the original VAV-terminal case: `.remove()` cleanly cascade-deletes the whole PTAC assembly (unit + both coils + fan) in one call with no orphaning, and `.clone()` already re-plumbs the cloned hydronic coil onto the plant loop automatically -- neither of VAV:Reheat's segfault-risk or clone-orphaning issues apply here. A real, previously-latent bug was also found and fixed in the existing plant-loop-walking extraction code, which silently produced 10 orphaned, zone-disconnected coil nodes when run against `sys01` unmodified.

- **`sys03_psz_ac`/`sys04_psz_hp`/`sys09_furnace_gas`/`sys10_furnace_electric` needed the most extensive new `rewire.py` work of this round, and surfaced four real bugs, all found by actually simulating rewired models (forward translation stayed silent every time):**
  1. A dedicated single-zone `AirLoopHVAC` (one per zone, not a shared central AHU -- confirmed via direct inspection) left with zero zones after a branch removal is invalid EnergyPlus input. Fixed by deleting the whole airloop, not just the branch, when nothing else will be added back to it in the same operation.
  2. Its `SetpointManager:SingleZone:*` goes stale the same way, but the fix isn't uniform -- when the airloop survives with a *different* zone (rather than being deleted outright), the setpoint manager must be *retargeted*, not removed (removing it broke a *different* setpoint manager that referenced it as its own setpoint source).
  3. A genuine bug in the pre-existing `set_ahu_direct_service`, latent since it was written and only now exercised: `AirLoopHVAC.addBranchForZone` silently auto-moves a zone's connection away from wherever it truly was -- never observable on `sys05`-`08`, which have only one AHU total (a zone's true airloop and the fabricated one were always the same object). This same retarget-vs-delete fix was needed a *second* time here, for a code path `_remove_branch_safely`'s callers don't go through -- found on a genuine production-scope seed (severity 3), not just an exploratory sweep.
  4. **A real segfault** (confirmed via process exit code 139, not inferred): `reassign_terminal`/`add_extra_service` assumed the "from"/"to" (or "donor"/"target") airloops are always different objects -- true everywhere else, but not once a fabrication event can put two zones on one airloop (mechanism #3 above). When they alias, deleting one for being zone-less destroys the exact object the very next line calls a method on. Fixed with a handle-equality guard before every such deletion.

Two further collision categories were found across these four buildings and left gracefully handled but *not* structurally filtered, matching the precedent already set for `sys05`'s DX-coil case: an AHU that a fabrication/misattribution event references can be deleted by an earlier event in the same blueprint (fixed the resulting crash defensively, not by building a new structural filter), and a donor zone's terminal can likewise already be gone. **One of these appeared in this batch's own actual seeds** (`sys10_furnace_electric`, severity 2, one seeded variant) -- the first time in this project that `n_failed > 0` in an actually-shipped production batch, not just an exploratory sweep. Reported as-is in the summary table below, not smoothed over.

## Topologies extracted

| building_id | description | HVAC | nodes | feeds edges | node types |
|---|---|---|---|---|---|
| `sys08_vav_parallel_piu` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 1 AHU (VAV fan, chilled-water cooling coil, electric heating coil) -> 10 Parallel-PIU-Reheat VAV terminals -> 10 zones; chilled-water plant with 1 pump/chiller | 25 | 21 | AHU=1, Cooling_Coil=1, Fan=1, HVAC_Zone=10, Heating_Coil=1, Pump=1, VAV=10 |
| `sys07_vav_reheat` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 1 AHU (VAV fan, chilled-water cooling coil) -> 10 VAV-Reheat terminals (hot-water reheat coils) -> 10 zones; separate chilled-water and hot-water plants (chiller + condenser loop, boiler) | 36 | 32 | AHU=1, Cooling_Coil=1, Fan=1, HVAC_Zone=10, Heating_Coil=11, Pump=2, VAV=10 |
| `sys05_vav_reheat_dx` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 1 AHU (VAV fan, DX cooling coil) -> 10 VAV-Reheat terminals (hot-water reheat coils) -> 10 zones; a single hot-water plant (1 pump/boiler) -- the cooling coil is DX, not on any plant loop, so this building has only ONE medium/pump, unlike sys07's two | 35 | 31 | AHU=1, Cooling_Coil=1, Fan=1, HVAC_Zone=10, Heating_Coil=11, Pump=1, VAV=10 |
| `sys06_vav_piu_dx` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 1 AHU (VAV fan, DX cooling coil, electric heating coil) -> 10 Parallel-PIU-Reheat VAV terminals (electric reheat) -> 10 zones; NO plant loop and NO pump anywhere in the building -- fully DX/electric | 24 | 20 | AHU=1, Cooling_Coil=1, Fan=1, HVAC_Zone=10, Heating_Coil=1, VAV=10 |
| `sys01_ptac` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 10 zone-level Packaged Terminal Air Conditioners (PTAC), NO AirLoopHVAC at all -- each unit: DX cooling coil (no plant loop) + hydronic heating coil, all 10 sharing ONE hot-water plant (1 pump/boiler). Required new extract.py/rewire.py code paths, not a drop-in reuse of the AirLoopHVAC-based mechanisms sys05-sys08 share. | 51 | 20 | Cooling_Coil=10, Fan=10, HVAC_Zone=10, Heating_Coil=10, Pump=1, Terminal_Unit=10 |
| `sys02_pthp` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 10 zone-level Packaged Terminal Heat Pumps (PTHP), NO AirLoopHVAC at all -- each unit: DX cooling coil AND DX heating coil, zero PlantLoops/pumps anywhere in the building. Reuses sys01's new packaged-unit extract.py/rewire.py code paths directly; its own zero-collision-risk/zero-coil-target-events status was independently confirmed, not inherited from sys01 or sys06. | 50 | 10 | Cooling_Coil=10, Fan=10, HVAC_Zone=10, Heating_Coil=10, Terminal_Unit=10 |
| `sys03_psz_ac` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 10 dedicated single-zone AirLoopHVACs (PSZ-AC), one per zone, not one shared central AHU -- each with its own DX cooling coil, gas heating coil, fan, and AirTerminal:SingleDuct:ConstantVolume:NoReheat pass-through terminal. NO PlantLoop anywhere. Required new rewire.py handling for single-zone-per-airloop topology: a dedicated AHU left with zero zones after a branch removal is invalid EnergyPlus input (the whole airloop must be deleted, not just the branch); its SetpointManager:SingleZone:* must be retargeted (not deleted) when the airloop survives with a different zone, and a from/to-airloop aliasing case (two zones temporarily sharing one airloop) that segfaulted before being fixed. | 60 | 20 | AHU=10, Cooling_Coil=10, Fan=10, HVAC_Zone=10, Heating_Coil=10, Terminal_Unit=10 |
| `sys04_psz_hp` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 10 dedicated single-zone AirLoopHVACs (PSZ-HP), same architecture as sys03 -- each with DX cooling, DX heating, electric backup heating, a fan, and an AirTerminal:SingleDuct:ConstantVolume:NoReheat pass-through terminal. NO PlantLoop anywhere. All sys03 rewire.py fixes (airloop deletion, setpoint-manager retarget, aliasing guard) confirmed to carry over directly -- verified with its own full sweep, not assumed. | 70 | 20 | AHU=10, Cooling_Coil=10, Fan=10, HVAC_Zone=10, Heating_Coil=20, Terminal_Unit=10 |
| `sys09_furnace_gas` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 10 dedicated single-zone AirLoopHVACs, same architecture as sys03/04 but heating-only (gas furnace, no cooling coil at all) -- each with a Coil:Heating:Gas, a fan, and an AirTerminal:SingleDuct:ConstantVolume:NoReheat pass-through terminal. NO PlantLoop anywhere. Same rewire.py fixes as sys03/04 apply directly. | 50 | 20 | AHU=10, Fan=10, HVAC_Zone=10, Heating_Coil=10, Terminal_Unit=10 |
| `sys10_furnace_electric` | 10-zone, 2-story ASHRAE 90.1 Appendix G baseline test building (NREL/OpenStudio-resources, BSD-3-Clause) | 10 dedicated single-zone AirLoopHVACs, same architecture as sys09 but electric resistance heat instead of gas -- each with a Coil:Heating:Electric, a fan, and an AirTerminal:SingleDuct:ConstantVolume:NoReheat pass-through terminal. NO PlantLoop anywhere. Surfaced a fourth variant of the setpoint-manager issue found on sys03 -- `set_ahu_direct_service`'s own AHU-direct move (not just `_remove_branch_safely`'s callers) needed the same capture-before-move-and-retarget fix, found on an actual production-scope seed (severity 3), not just an exploratory one. | 50 | 20 | AHU=10, Fan=10, HVAC_Zone=10, Heating_Coil=10, Terminal_Unit=10 |

## Structural corruption: physical rewiring plausibility

All three real edge types identified in the original exclusion breakdown are now in scope: **terminal-unit<->zone** reassignment (original mechanism), **AHU<->zone-direct** (prior addition), and **pump<->coil**, new in this run -- a heating/cooling coil misconnected to the wrong plant loop/pump, or falsely claimed connected/disconnected. `generate_blueprint` is still called completely unmodified on the full graph; `physics_pipeline/scope.py` filters its output events down to these three edge types and reconstructs `claimed_edges` to match -- the same approach proven for AHU-direct, not the restricted-input-graph approach that failed earlier (see `scope.py`'s docstring for why).

**Coverage progression:** the denominator itself grows with the batch, since it's drawn fresh from whichever buildings are in `BASE_BUILDINGS` -- 10/24 (42%) on the original 2-building batch, through 18/24 (75%) adding pump<->coil, 40/48 (83%) widened to 4 buildings, and now **87/120 (72%)** across all 10 ASHRAE 90.1 baseline systems. The remaining 33 (28%) are structurally inapplicable -- but **a genuinely new exclusion category appeared this round, not just more of the old one**, worth stating plainly rather than folding into the same "structurally inapplicable" line as before:

- 25x target is Terminal_Unit (not a zone or coil edge type this pipeline rewires)
- 8x target is VAV (not a zone or coil edge type this pipeline rewires)

The `target is VAV` count (AHU<->Terminal_Unit) is unchanged in kind from before -- still structurally inapplicable on every building with only one AHU. The new `target is Terminal_Unit` count is different: `sys03`/`sys04`/`sys09`/`sys10` each have **ten** independent AHUs (one per zone, not one shared central AHU), so "which AHU feeds this terminal" is no longer a vacuous question on these four buildings the way it was everywhere else -- there are genuinely different AHUs a terminal's parent could be misattributed to. This pipeline still doesn't implement AHU<->Terminal_Unit rewiring at all (out of scope for this round, same as always), so these candidates are excluded the same way -- but unlike the old `target is VAV` count, this one represents a real, newly-meaningful gap on these four buildings specifically, not a vacuous exclusion. Logged as its own backlog item, not attempted here. (Being "in scope" means this pipeline *attempts* the rewire, not that it's guaranteed to succeed -- see the DX-coil and cross-event-collision findings for real cases where an in-scope event still fails.)

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
| `sys01_ptac` | 1 | 91301001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys01_ptac` | 1 | 91301002 | 0 | removal | HVAC_Zone | clean | 0 | - |
| `sys01_ptac` | 2 | 91302001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys01_ptac` | 2 | 91302001 | 1 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys01_ptac` | 2 | 91302002 | 0 | removal | Heating_Coil | clean | 0 | - |
| `sys01_ptac` | 2 | 91302002 | 1 | removal | Heating_Coil | clean | 0 | - |
| `sys01_ptac` | 3 | 91303001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys01_ptac` | 3 | 91303001 | 1 | removal | HVAC_Zone | clean | 0 | - |
| `sys01_ptac` | 3 | 91303001 | 2 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys01_ptac` | 3 | 91303002 | 0 | removal | HVAC_Zone | clean | 0 | - |
| `sys01_ptac` | 3 | 91303002 | 1 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys01_ptac` | 3 | 91303002 | 2 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys02_pthp` | 1 | 91301001 | 0 | removal | HVAC_Zone | clean | 0 | - |
| `sys02_pthp` | 1 | 91301002 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys02_pthp` | 2 | 91302001 | 0 | removal | HVAC_Zone | clean | 0 | - |
| `sys02_pthp` | 2 | 91302001 | 1 | removal | HVAC_Zone | clean | 0 | - |
| `sys02_pthp` | 2 | 91302002 | 0 | removal | HVAC_Zone | clean | 0 | - |
| `sys02_pthp` | 2 | 91302002 | 1 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys02_pthp` | 3 | 91303001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys02_pthp` | 3 | 91303001 | 1 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys02_pthp` | 3 | 91303001 | 2 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys02_pthp` | 3 | 91303002 | 0 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys02_pthp` | 3 | 91303002 | 1 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys02_pthp` | 3 | 91303002 | 2 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys03_psz_ac` | 1 | 91301001 | 0 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys03_psz_ac` | 2 | 91302001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys03_psz_ac` | 2 | 91302001 | 1 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys03_psz_ac` | 2 | 91302002 | 0 | removal | HVAC_Zone | clean | 0 | - |
| `sys03_psz_ac` | 3 | 91303001 | 0 | removal | HVAC_Zone | clean | 0 | - |
| `sys03_psz_ac` | 3 | 91303001 | 1 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys04_psz_hp` | 2 | 91302001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys04_psz_hp` | 2 | 91302001 | 1 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys04_psz_hp` | 2 | 91302002 | 0 | removal | HVAC_Zone | clean | 0 | - |
| `sys04_psz_hp` | 3 | 91303001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys04_psz_hp` | 3 | 91303001 | 1 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys04_psz_hp` | 3 | 91303002 | 0 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys09_furnace_gas` | 2 | 91302001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys09_furnace_gas` | 2 | 91302001 | 1 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys09_furnace_gas` | 2 | 91302002 | 0 | removal | HVAC_Zone | clean | 0 | - |
| `sys09_furnace_gas` | 3 | 91303001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys10_furnace_electric` | 2 | 91302001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys10_furnace_electric` | 2 | 91302001 | 1 | fabrication | HVAC_Zone | rewire failed (see note) | - | - |
| `sys10_furnace_electric` | 2 | 91302002 | 0 | removal | HVAC_Zone | clean | 0 | - |
| `sys10_furnace_electric` | 2 | 91302002 | 1 | removal | HVAC_Zone | clean | 0 | - |
| `sys10_furnace_electric` | 3 | 91303001 | 0 | fabrication | HVAC_Zone | clean | 0 | - |
| `sys10_furnace_electric` | 3 | 91303001 | 1 | misattribution | HVAC_Zone | clean | 0 | - |
| `sys10_furnace_electric` | 3 | 91303002 | 0 | misattribution | HVAC_Zone | clean | 0 | - |

**Summary: 86 in-scope events attempted across all 10 buildings (collision-filtered events never reach this table at all -- see the collision note above); 83 clean and functionally confirmed, 2 passed 0-severe-errors but are functionally dead (caught only by the functional-effect check, not by severe_errors), 1 failed to rewire.** Verified: 83 + 2 + 1 == 86. Reported as-is, not rounded up to a clean line or hidden. The 33/120 (28%) still excluded from the full candidate pool (AHU<->Terminal_Unit, structurally inapplicable) never reach this table at all. **1 failed to rewire in this specific batch -- the first time that number is nonzero in an actually-shipped production batch, not just an exploratory sweep.** `sys10_furnace_electric` (severity 2, one seeded variant) drew a genuine cross-event AHU collision: an AHU-direct fabrication/misattribution event referenced an AHU that an earlier event in the same blueprint had already deleted (single-zone-per-airloop buildings only -- see the six-system extension section above). Handled gracefully (a clear reason, not a crash), reported here rather than smoothed into a clean 0. The DX-coil scope gap found on `sys05` (see the prior round) also remains real but, as before, wasn't drawn by these particular seeds.

## Fault injection: independent performance-fault mechanism

For each blueprint, an `FaultModel:ThermostatOffset` (+5 degC sensor offset) is injected on the TRUE (uncorrupted) model near the corruption site, using the exact locality logic `symptom_flagged_nodes` already defines for the symptom-triggered troubleshooting experiment. **This is a fully independent, separately-toggleable mechanism from the structural corruption above** -- a different model copy, no shared state -- confirming the two were not accidentally fused into one step.

**A real API gap found:** OpenStudio's `openstudio.model` Python API has no wrapper class for any of EnergyPlus's dozen-plus `FaultModel:*` objects (confirmed: nothing case-insensitively matching "fault" in `dir(openstudio.model)`, out of ~4800 names). Faults are injected as raw IDF objects on the post-`ForwardTranslator` `Workspace` instead -- a standard, well-documented EnergyPlus-only pattern, just one level below OpenStudio's typed Model API.

**Coverage gap: pump/coil-only blueprints are blind-mode-only, by decision, not by oversight.** `symptom_flagged_nodes` flags the corruption target plus its immediate neighbors under any relation; for a pump<->coil-only blueprint those neighbors are the AHU/pump side, never a zone, so there's no zone to inject a thermostat-offset fault into. Checked across all 10 buildings in this batch, not just re-asserted from the prior report: exactly two blueprints have no fault record for this reason -- `sys07_vav_reheat` (severity 1, the pump/coil removal, same as before) and, new this round, `sys01_ptac` (severity 2, seed 91302002) -- `sys01`'s hydronic pump/coil edges make it the second building where a pump/coil-only blueprint is even possible, and this batch's seeds drew one. `sys02`/`sys03`/`sys04`/`sys09`/`sys10` introduced no new instances (either zero pump/coil edges exist there at all, or every blueprint drawn happened to include a zone-side event alongside any coil event). `FaultModel:Fouling:Coil` remains unwired (`pipeline._run_coil_fault` exists but is not called), but the root cause of its earlier inconsistent behavior has now been found, fixed, and recalibrated -- see the two items immediately below.

**Root cause found and fixed: `add_coil_fouling_fault` never set two IDD fields the fault formula requires, causing two different EnergyPlus-internal failure modes on the two coil types, not two separate coil-type-specific gaps.** `FaultModel:Fouling:Coil`'s `FoulingFactor` method computes `Rfoul = rwater/(Aout*Aratio) + rair/Aout` (Engineering Reference 11.2.3.2); `Outside Coil Surface Area` (`Aout`) and `Inside-to-Outside Ratio` were never set, defaulting to 0.0. Confirmed directly against EnergyPlus 25.2.0's own `WaterCoils.cc` source at the pinned version: the identical missing-input misconfiguration produces `Rfoul = inf` on `Coil:Cooling:Water` (`Coil Fouling Factor` output variable read literal `inf` at every tested factor from 1e-7 to 1e-2, collapsing UA to exactly 0 -- the earlier-reported "complete shutdown"), and `Rfoul = 0` exactly on `Coil:Heating:Water` (read `0.0` at all 72 hourly timesteps of a 3-day window including 70 active-heating hours -- the earlier-reported "zero measurable effect"). **Fixed** by deriving `Aout`/ratio from each coil's own EnergyPlus sizing output instead of leaving them unset -- see the next item for the two different derivation paths and their very different confidence levels. `add_coil_fouling_fault` (`faults.py`) now requires `outside_coil_surface_area` as an explicit parameter with no default, closing off a silently-omitted-field bug from recurring the same way again.

**Surface-area derivation: bit-exact-verified for cooling coils, an explicit, lower-confidence extrapolation for heating coils -- these two branches are NOT equally settled, and should not be read that way.** Both use the same fixed conversion (EnergyPlus's own `WaterCoils::EstimateHEXSurfaceArea`, Nigusse/FSEC 2010: a 'typical hydronic coil' correlation -- 2 m/s tube water velocity, ~0.5in tube ID, Ai/Ao=0.07, 92% fin efficiency, 140 W/m2C air-side film coefficient -- reducing to `Area = UA * 0.0101426 m2-K/W`, confirmed the source of the IDD's own 0.07 default for that field, not a coincidence). For `Coil:Cooling:Water`, EnergyPlus already computes and PUBLISHES this exact area itself in `eplusout.eio`'s "Water Cooling Coil Capacity Information" line -- parsed directly, and confirmed bit-exact against an independent hand-computation of the same formula (907.08 m2 for an 89,433.17 W/K coil, matching to the reported decimal). **For `Coil:Heating:Water`, there is no such independent ground truth to check against -- EnergyPlus's own source only extends this reporting to cooling coils, never heating.** The fix applies the identical fixed correlation "by hand" to the heating coil's own sized `U-Factor Times Area Value` from `eplusout.eio`'s "Component Sizing Information" section, on the assumption that a hydronic heating coil's tube-and-fin construction shares the same geometry the correlation was built for -- a physically reasonable assumption (both are hydronic tube-and-fin heat exchangers), but genuinely just an assumption, not something EnergyPlus itself validates for this coil type anywhere. This branch is validated here only indirectly, by producing sane-looking, smooth, non-degenerate degradation curves on every heating coil tested -- not by an independent confirmation that the resulting area number is itself physically correct. Treat the heating-coil branch as open/lower-confidence relative to the cooling-coil branch, which is settled.

**Fouling-factor default recalibrated, and validated against the same convention the rest of this pipeline's fault mechanisms already use -- not chosen as a standalone number.** Checked first whether a severity(1-10)-to-fault-magnitude convention already exists anywhere in this codebase to calibrate against, as the coil-fouling factor should land in the same range other fault types use at a given severity, if such a range exists. It does not: `severity` means "number of structural corruption events" everywhere in `hvac_benchmark`/`physics_pipeline` (confirmed via a full grep of both packages), and the one existing physical fault (`add_thermostat_offset_fault`) uses a single fixed 5 degC offset regardless of corruption severity -- there is no severity-scaled effect-size table to match. The old default (0.0005 m2-K/W, labeled "moderate, clearly-detectable") was tuned against the broken math above and, once fixed, produced a sub-1% effect -- nowhere near moderate. Recalibrated to a single fixed 0.005 m2-K/W, matching the existing one-fixed-magnitude convention (not severity-scaled), and validated end to end (through `add_coil_fouling_fault`'s actual shipped default, not a manually-constructed IDF object) on three structurally different coils -- not just the one that originally surfaced the bug:

| coil | building | type | Aout derivation | Aout (m2) | baseline output | faulted output | % reduction | severe errors |
|---|---|---|---|---|---|---|---|---|
| reheat (small) | `sys07_vav_reheat` | Coil:Heating:Water | formula (from sized UA) | 11.33 | 11227.3 W | 6197.3 W | 44.8% | 0 |
| central cooling (large) | `sys08_vav_parallel_piu` | Coil:Cooling:Water | direct eio parse | 907.08 | 69283.0 W | 63760.4 W | 8.0% | 0 |
| reheat (different building) | `sys05_vav_reheat_dx` | Coil:Heating:Water | formula (from sized UA) | 7.17 | 8423.6 W | 4178.7 W | 50.4% | 0 |

All three: clearly detectable, none functionally dead (>50W floor), none collapse toward 0, zero severe errors. The spread (8% to 50%) is expected, not a calibration failure -- a single fixed *physical* fouling deposit (m2-K/W) naturally produces different *relative* impact on differently sized coils, the same way a fixed 5 degC thermostat offset has different relative impact on different zones; this mirrors the existing convention's shape rather than fighting it. Still not wired into `pipeline.py`'s dispatch in this pass.

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
| `sys01_ptac` | 91301001 | Story 2 Core Thermal Zone | True | True | 5.00 | -3.74 |
| `sys01_ptac` | 91301002 | Story 1 North Perimeter Thermal Zone | True | True | 5.00 | -3.87 |
| `sys01_ptac` | 91302001 | Story 1 North Perimeter Thermal Zone | True | True | 5.00 | -3.87 |
| `sys01_ptac` | 91303001 | Story 2 East Perimeter Thermal Zone | True | True | 5.00 | -3.75 |
| `sys01_ptac` | 91303002 | Story 1 North Perimeter Thermal Zone | True | True | 5.00 | -3.87 |
| `sys02_pthp` | 91301001 | Thermal Zone 6 | True | True | 5.00 | -3.91 |
| `sys02_pthp` | 91301002 | Thermal Zone 3 | True | True | 5.00 | -3.75 |
| `sys02_pthp` | 91302001 | Thermal Zone 10 | True | True | 5.00 | -3.91 |
| `sys02_pthp` | 91302002 | Thermal Zone 6 | True | True | 5.00 | -3.91 |
| `sys02_pthp` | 91303001 | Thermal Zone 10 | True | True | 5.00 | -3.91 |
| `sys02_pthp` | 91303002 | Thermal Zone 8 | True | True | 5.00 | -3.23 |
| `sys03_psz_ac` | 91301001 | Thermal Zone 1 | True | True | 5.01 | -3.35 |
| `sys03_psz_ac` | 91302001 | Thermal Zone 2 | True | True | 5.00 | -3.30 |
| `sys03_psz_ac` | 91302002 | Thermal Zone 6 | True | True | 5.01 | -3.38 |
| `sys03_psz_ac` | 91303001 | Thermal Zone 1 | True | True | 5.01 | -3.35 |
| `sys04_psz_hp` | 91302001 | Story 2 West Perimeter Thermal Zone | True | True | 5.00 | -3.38 |
| `sys04_psz_hp` | 91302002 | Story 2 South Perimeter Thermal Zone | True | True | 5.01 | -3.36 |
| `sys04_psz_hp` | 91303001 | Story 1 Core Thermal Zone | True | True | 5.00 | -3.64 |
| `sys04_psz_hp` | 91303002 | Story 1 Core Thermal Zone | True | True | 5.00 | -3.64 |
| `sys09_furnace_gas` | 91302001 | Thermal Zone 7 | True | True | 0.93 | -0.11 |
| `sys09_furnace_gas` | 91302002 | Thermal Zone 1 | True | True | 4.97 | -1.20 |
| `sys09_furnace_gas` | 91303001 | Thermal Zone 5 | True | True | 4.49 | -1.08 |
| `sys10_furnace_electric` | 91302001 | Thermal Zone 10 | True | True | 5.00 | -1.56 |
| `sys10_furnace_electric` | 91302002 | Thermal Zone 3 | True | True | 4.49 | -1.08 |
| `sys10_furnace_electric` | 91303001 | Thermal Zone 9 | True | True | 1.81 | -0.22 |
| `sys10_furnace_electric` | 91303002 | Thermal Zone 7 | True | True | 1.61 | -0.27 |

All fault runs produced a measurable, localized, non-degenerate temperature deviation (not zero, not NaN, not building-wide) -- a realistic symptom signal a technician could plausibly notice.

## Troubleshooting-against-a-blueprint results (existing Bayesian benchmark, placeholder noise rates)

Everything below is produced by calling `hvac_benchmark.evaluate.troubleshooting_report.build_troubleshooting_section` completely unmodified, on the physics-extracted topologies/blueprints above instead of the real-Brick-model topologies it normally receives -- confirming the existing Bayesian machinery accepts physics-derived graphs without any changes to its own code.

**Read the "Symptom-triggered" rows below with the fault-injection coverage gap above in mind.** `symptom_flagged_nodes` -- the graph-locality function `build_troubleshooting_section` uses to decide which nodes count as "symptom-flagged" -- runs at the abstract graph level for every blueprint uniformly, whether or not this pipeline actually injected a physics-based EnergyPlus fault to back that symptom up. Checked across the full 10-building batch: exactly two blueprints feeding the rows below have no fault record at all (see above) -- `sys07_vav_reheat` (severity 1, seed 91301001) and `sys01_ptac` (severity 2, seed 91302002), both pump<->coil-only -- yet their trials still appear in the "Symptom-triggered" table, using the abstract locality flag on its own. No other building introduced a further instance in this batch. Do not read "Symptom-triggered" coverage here as "every blueprint has a physics-validated fault behind it" -- two still do not.

## Troubleshooting-against-a-blueprint (separate evaluation mode)

**This section is a separate evaluation mode from the full-topology-discovery results above and is never blended with them.** Discovery mode assumes near-zero prior knowledge and measures tests to reconstruct an entire graph from scratch. This mode assumes the opposite starting condition: a trusted blueprint (the true graph, deliberately corrupted at a few points) is already given, and the task is to find the corrupted edge(s) in as few tests as possible -- the day-to-day troubleshooting scenario, not a periodic full audit.

- **10 real topologies** evaluated in this mode: sys01_ptac, sys02_pthp, sys03_psz_ac, sys04_psz_hp, sys05_vav_reheat_dx, sys06_vav_piu_dx, sys07_vav_reheat, sys08_vav_parallel_piu, sys09_furnace_gas, sys10_furnace_electric (the same `feeds`-eligible topologies used by the primary discovery benchmark above).
- Corruption severities tested: [1, 2, 3] corrupted edge(s) (an edge = one corruption event; misattribution counts as one event even though it touches two candidate pairs), with 3 independently-seeded corrupted-blueprint variants per (topology, severity), each replayed across 3 tie-break/noise seeds -- a deliberately bounded sample (mirroring the ablation-subset bounding elsewhere in this report), not a statistically powered sweep.

> **Evidence level: small case study, same caveat as the rest of this document.** Numbers below are within-topology variability across corrupted-blueprint variants and seeds, not additional independent buildings or corruption instances beyond what is listed above. No pooled cross-topology number is computed or implied anywhere in this section.

**Belief model reuse:** this mode reuses the exact same Bernoulli update and expected-information-gain machinery as discovery mode (`bayes.update` / `expected_information_gain`), completely unmodified -- only the prior changes (near-certain on blueprint-claimed edges, sparse-floor elsewhere), confirming the two modes did not need a parallel inference system.

**Candidate universe:** identical physically-plausible candidate set as discovery mode's `feeds` benchmark, not just blueprint-claimed edges -- required so an undocumented real connection (a *removal* corruption) can be tested at all. One consequence: **the `full_sweep` baseline only re-tests blueprint-claimed edges, so by construction it can never find a removal-type corruption** -- a structural limitation of that reference baseline, not a bug, visible below wherever removal corruptions appear in a topology's mix.

**Metric:** tests needed until every corrupted candidate is simultaneously flagged (current belief disagrees with the blueprint's own claim), first-reached and sustained-to-end-of-trial, median [range] across variants x seeds, with attainment rate. Also reported: false-positive rate (fraction of genuinely-correct blueprint edges ever incorrectly flagged along the way) and needless-retest count (tests spent on edges that were both blueprint-claimed-true and genuinely correct) -- a technician chasing a phantom problem, or an algorithm ignoring the strong prior it was given, are both counted as real costs here, never as neutral.

### sys01_ptac

Corruption types actually generated for this topology across all variants: fabrication, misattribution, removal.

**Blind verification**

severity = 1 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 31 [3-45] (n=6) | 100% | 31 [3-45] (n=6) | 100% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| active | 5% | 32 [4-48] (n=6) | 100% | 33 [4-48] (n=6) | 100% | 0.0% [0.0%-0.0%] | 20 [19-22] (n=6) |
| active | 15% | 51 [5-75] (n=4) | 67% | 51 [5-75] (n=4) | 67% | 0.0% [0.0%-0.0%] | 25 [23-46] (n=6) |
| full_sweep | 0% | 15 [3-19] (n=3) | 50% | 15 [3-19] (n=3) | 50% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| full_sweep | 5% | 22 [22-22] (n=3) | 50% | 22 [22-24] (n=3) | 50% | 0.0% [0.0%-0.0%] | 20 [19-22] (n=6) |
| full_sweep | 15% | 36 [25-46] (n=2) | 33% | 36 [25-46] (n=2) | 33% | 0.0% [0.0%-0.0%] | 25 [23-46] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 44 [27-67] (n=6) | 100% | 44 [27-67] (n=6) | 100% | 0.0% [0.0%-0.0%] | 18 [18-19] (n=6) |
| active | 5% | 57 [30-72] (n=5) | 83% | 57 [30-72] (n=5) | 83% | 0.0% [0.0%-0.0%] | 19 [18-21] (n=6) |
| active | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 24 [20-45] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 18 [18-19] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 19 [18-21] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 24 [20-45] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 56 [42-58] (n=6) | 100% | 56 [42-58] (n=6) | 100% | 0.0% [0.0%-0.0%] | 18 [18-19] (n=6) |
| active | 5% | 58 [49-69] (n=4) | 67% | 58 [49-69] (n=4) | 67% | 0.0% [0.0%-0.0%] | 18 [18-19] (n=6) |
| active | 15% | 76 [71-106] (n=3) | 50% | 76 [71-106] (n=3) | 50% | 0.0% [0.0%-0.0%] | 24 [20-45] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 18 [18-19] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 18 [18-19] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 24 [20-45] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

**Symptom-triggered**

severity = 1 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 3 [1-5] (n=6) | 100% | 3 [1-5] (n=6) | 100% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| active | 5% | 3 [1-5] (n=6) | 100% | 3 [1-5] (n=6) | 100% | 0.0% [0.0%-0.0%] | 21 [19-23] (n=6) |
| active | 15% | 6 [1-22] (n=6) | 100% | 6 [1-24] (n=6) | 100% | 0.0% [0.0%-0.0%] | 29 [23-48] (n=6) |
| symptom_naive | 0% | 5 [1-8] (n=6) | 100% | 5 [1-8] (n=6) | 100% | 0.0% [0.0%-0.0%] | 0 [0-1] (n=6) |
| symptom_naive | 5% | 5 [1-8] (n=6) | 100% | 5 [1-8] (n=6) | 100% | 0.0% [0.0%-0.0%] | 1 [0-2] (n=6) |
| symptom_naive | 15% | 6 [1-24] (n=6) | 100% | 6 [1-41] (n=6) | 100% | 0.0% [0.0%-0.0%] | 2 [0-5] (n=6) |
| full_sweep | 0% | 15 [3-19] (n=3) | 50% | 15 [3-19] (n=3) | 50% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| full_sweep | 5% | 15 [3-19] (n=3) | 50% | 15 [3-19] (n=3) | 50% | 0.0% [0.0%-0.0%] | 21 [19-23] (n=6) |
| full_sweep | 15% | 19 [3-30] (n=3) | 50% | 19 [3-37] (n=3) | 50% | 0.0% [0.0%-0.0%] | 29 [23-48] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 12 [7-29] (n=6) | 100% | 12 [7-29] (n=6) | 100% | 0.0% [0.0%-0.0%] | 18 [18-19] (n=6) |
| active | 5% | 19 [7-77] (n=6) | 100% | 22 [11-77] (n=6) | 100% | 0.0% [0.0%-0.0%] | 25 [20-32] (n=6) |
| active | 15% | 72 [19-130] (n=6) | 100% | 72 [27-130] (n=6) | 100% | 1.5% [0.0%-7.4%] | 52 [25-68] (n=6) |
| symptom_naive | 0% | 13 [6-27] (n=6) | 100% | 13 [6-27] (n=6) | 100% | 0.0% [0.0%-0.0%] | 6 [1-10] (n=6) |
| symptom_naive | 5% | 18 [6-33] (n=6) | 100% | 24 [6-35] (n=6) | 100% | 0.0% [0.0%-0.0%] | 11 [2-22] (n=6) |
| symptom_naive | 15% | 76 [11-101] (n=6) | 100% | 76 [43-101] (n=6) | 100% | 1.5% [0.0%-7.4%] | 28 [3-52] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 18 [18-19] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 25 [20-32] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 1.5% [0.0%-7.4%] | 52 [25-68] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 20 [13-22] (n=6) | 100% | 20 [13-22] (n=6) | 100% | 0.0% [0.0%-0.0%] | 18 [18-19] (n=6) |
| active | 5% | 22 [13-95] (n=6) | 100% | 26 [14-95] (n=6) | 100% | 0.0% [0.0%-0.0%] | 21 [19-21] (n=6) |
| active | 15% | 43 [23-63] (n=6) | 100% | 43 [23-63] (n=6) | 100% | 0.7% [0.0%-1.5%] | 30 [25-49] (n=6) |
| symptom_naive | 0% | 20 [14-22] (n=6) | 100% | 20 [14-22] (n=6) | 100% | 0.0% [0.0%-0.0%] | 2 [1-2] (n=6) |
| symptom_naive | 5% | 22 [14-51] (n=6) | 100% | 36 [14-52] (n=6) | 100% | 0.0% [0.0%-0.0%] | 4 [2-4] (n=6) |
| symptom_naive | 15% | 38 [14-70] (n=6) | 100% | 68 [14-98] (n=6) | 100% | 0.7% [0.0%-1.5%] | 8 [3-12] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 18 [18-19] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 21 [19-21] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.7% [0.0%-1.5%] | 30 [25-49] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

### sys02_pthp

Corruption types actually generated for this topology across all variants: fabrication, misattribution, removal.

**Blind verification**

severity = 1 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 10 [4-47] (n=6) | 100% | 10 [4-47] (n=6) | 100% | 0.0% [0.0%-0.0%] | 10 [9-10] (n=6) |
| active | 5% | 9 [7-53] (n=5) | 83% | 11 [7-53] (n=5) | 83% | 0.0% [0.0%-2.0%] | 10 [9-14] (n=6) |
| active | 15% | 34 [12-71] (n=4) | 67% | 34 [12-71] (n=4) | 67% | 0.0% [0.0%-2.0%] | 12 [9-19] (n=6) |
| full_sweep | 0% | 6 [4-8] (n=3) | 50% | 6 [4-8] (n=3) | 50% | 0.0% [0.0%-0.0%] | 10 [9-10] (n=6) |
| full_sweep | 5% | 12 [12-13] (n=3) | 50% | 13 [12-14] (n=3) | 50% | 0.0% [0.0%-2.0%] | 10 [9-14] (n=6) |
| full_sweep | 15% | 15 [15-15] (n=2) | 33% | 15 [15-15] (n=2) | 33% | 0.0% [0.0%-2.0%] | 12 [9-19] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 34 [23-47] (n=6) | 100% | 34 [23-47] (n=6) | 100% | 0.0% [0.0%-0.0%] | 8 [8-8] (n=6) |
| active | 5% | 39 [29-59] (n=5) | 83% | 39 [29-59] (n=5) | 83% | 0.0% [0.0%-2.1%] | 8 [8-12] (n=6) |
| active | 15% | 60 [43-83] (n=5) | 83% | 60 [43-83] (n=5) | 83% | 0.0% [0.0%-2.1%] | 10 [8-17] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 8 [8-8] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-2.1%] | 8 [8-12] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-2.1%] | 10 [8-17] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 33 [19-47] (n=6) | 100% | 33 [19-47] (n=6) | 100% | 0.0% [0.0%-0.0%] | 8 [8-9] (n=6) |
| active | 5% | 50 [26-59] (n=5) | 83% | 50 [26-59] (n=5) | 83% | 0.0% [0.0%-2.2%] | 9 [8-13] (n=6) |
| active | 15% | 94 [94-94] (n=1) | 17% | 94 [94-94] (n=1) | 17% | 0.0% [0.0%-2.2%] | 11 [8-18] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 8 [8-9] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-2.2%] | 9 [8-13] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-2.2%] | 11 [8-18] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

**Symptom-triggered**

severity = 1 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 2 [1-8] (n=6) | 100% | 2 [1-8] (n=6) | 100% | 0.0% [0.0%-0.0%] | 10 [9-10] (n=6) |
| active | 5% | 2 [2-8] (n=5) | 83% | 2 [2-8] (n=5) | 83% | 0.0% [0.0%-2.0%] | 10 [9-15] (n=6) |
| active | 15% | 2 [2-10] (n=5) | 83% | 7 [2-20] (n=5) | 83% | 0.0% [0.0%-2.0%] | 12 [9-21] (n=6) |
| symptom_naive | 0% | 5 [1-8] (n=6) | 100% | 5 [1-8] (n=6) | 100% | 0.0% [0.0%-0.0%] | 0 [0-1] (n=6) |
| symptom_naive | 5% | 6 [4-8] (n=5) | 83% | 6 [4-8] (n=5) | 83% | 0.0% [0.0%-0.0%] | 1 [0-2] (n=6) |
| symptom_naive | 15% | 6 [4-8] (n=5) | 83% | 6 [4-33] (n=5) | 83% | 0.0% [0.0%-0.0%] | 2 [0-3] (n=6) |
| full_sweep | 0% | 6 [4-8] (n=3) | 50% | 6 [4-8] (n=3) | 50% | 0.0% [0.0%-0.0%] | 10 [9-10] (n=6) |
| full_sweep | 5% | 6 [4-8] (n=3) | 50% | 6 [4-8] (n=3) | 50% | 0.0% [0.0%-2.0%] | 10 [9-15] (n=6) |
| full_sweep | 15% | 6 [4-8] (n=3) | 50% | 6 [4-17] (n=3) | 50% | 0.0% [0.0%-2.0%] | 12 [9-21] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 14 [7-17] (n=6) | 100% | 14 [7-17] (n=6) | 100% | 0.0% [0.0%-0.0%] | 8 [8-8] (n=6) |
| active | 5% | 14 [7-17] (n=5) | 83% | 14 [7-17] (n=5) | 83% | 0.0% [0.0%-2.1%] | 8 [8-12] (n=6) |
| active | 15% | 17 [12-27] (n=5) | 83% | 17 [12-27] (n=5) | 83% | 0.0% [0.0%-2.1%] | 10 [8-17] (n=6) |
| symptom_naive | 0% | 14 [7-17] (n=6) | 100% | 14 [7-17] (n=6) | 100% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| symptom_naive | 5% | 14 [7-17] (n=5) | 83% | 14 [7-17] (n=5) | 83% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| symptom_naive | 15% | 14 [7-17] (n=5) | 83% | 14 [7-17] (n=5) | 83% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 8 [8-8] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-2.1%] | 8 [8-12] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-2.1%] | 10 [8-17] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 18 [9-23] (n=6) | 100% | 18 [9-23] (n=6) | 100% | 0.0% [0.0%-0.0%] | 8 [8-9] (n=6) |
| active | 5% | 21 [9-60] (n=6) | 100% | 22 [9-60] (n=6) | 100% | 0.0% [0.0%-2.2%] | 11 [9-17] (n=6) |
| active | 15% | 44 [19-127] (n=6) | 100% | 48 [21-129] (n=6) | 100% | 0.0% [0.0%-2.2%] | 15 [10-28] (n=6) |
| symptom_naive | 0% | 22 [17-25] (n=6) | 100% | 22 [17-25] (n=6) | 100% | 0.0% [0.0%-0.0%] | 2 [1-2] (n=6) |
| symptom_naive | 5% | 22 [17-55] (n=6) | 100% | 22 [17-55] (n=6) | 100% | 0.0% [0.0%-0.0%] | 3 [2-6] (n=6) |
| symptom_naive | 15% | 56 [22-95] (n=6) | 100% | 94 [23-113] (n=6) | 100% | 0.0% [0.0%-0.0%] | 4 [3-12] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 8 [8-9] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-2.2%] | 11 [9-17] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-2.2%] | 15 [10-28] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

### sys03_psz_ac

Corruption types actually generated for this topology across all variants: fabrication, misattribution, removal.

**Blind verification**

severity = 1 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 123 [57-239] (n=3) | 100% | 123 [57-239] (n=3) | 100% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=3) |
| active | 5% | 142 [66-256] (n=3) | 100% | 142 [66-256] (n=3) | 100% | 0.0% [0.0%-0.0%] | 19 [19-21] (n=3) |
| active | 15% | 179 [95-313] (n=3) | 100% | 179 [97-315] (n=3) | 100% | 0.0% [0.0%-0.0%] | 23 [21-31] (n=3) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=3) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 19 [19-21] (n=3) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 23 [21-31] (n=3) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 84 [12-177] (n=6) | 100% | 84 [12-177] (n=6) | 100% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| active | 5% | 91 [17-200] (n=6) | 100% | 91 [17-200] (n=6) | 100% | 0.0% [0.0%-0.0%] | 20 [19-22] (n=6) |
| active | 15% | 127 [26-249] (n=4) | 67% | 214 [40-249] (n=3) | 50% | 0.0% [0.0%-0.0%] | 24 [21-32] (n=6) |
| full_sweep | 0% | 19 [12-22] (n=3) | 50% | 19 [12-22] (n=3) | 50% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| full_sweep | 5% | 24 [24-25] (n=3) | 50% | 24 [24-25] (n=3) | 50% | 0.0% [0.0%-0.0%] | 20 [19-22] (n=6) |
| full_sweep | 15% | 33 [32-34] (n=2) | 33% | 34 [34-34] (n=1) | 17% | 0.0% [0.0%-0.0%] | 24 [21-32] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 124 [56-239] (n=3) | 100% | 124 [56-239] (n=3) | 100% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=3) |
| active | 5% | 143 [65-256] (n=3) | 100% | 143 [65-256] (n=3) | 100% | 0.0% [0.0%-0.0%] | 19 [19-21] (n=3) |
| active | 15% | 180 [92-311] (n=3) | 100% | 180 [94-313] (n=3) | 100% | 0.0% [0.0%-0.0%] | 23 [21-31] (n=3) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=3) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 19 [19-21] (n=3) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 23 [21-31] (n=3) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |

**Symptom-triggered**

severity = 1 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 17 [6-28] (n=3) | 100% | 17 [6-28] (n=3) | 100% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=3) |
| active | 5% | 17 [6-28] (n=3) | 100% | 17 [6-28] (n=3) | 100% | 0.0% [0.0%-0.0%] | 20 [20-22] (n=3) |
| active | 15% | 22 [9-41] (n=3) | 100% | 22 [9-41] (n=3) | 100% | 0.0% [0.0%-0.0%] | 27 [23-33] (n=3) |
| symptom_naive | 0% | 26 [16-28] (n=3) | 100% | 26 [16-28] (n=3) | 100% | 0.0% [0.0%-0.0%] | 1 [1-1] (n=3) |
| symptom_naive | 5% | 26 [16-28] (n=3) | 100% | 26 [16-28] (n=3) | 100% | 0.0% [0.0%-0.0%] | 2 [2-2] (n=3) |
| symptom_naive | 15% | 26 [16-28] (n=3) | 100% | 72 [16-84] (n=3) | 100% | 0.0% [0.0%-0.0%] | 3 [3-5] (n=3) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=3) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 20 [20-22] (n=3) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 27 [23-33] (n=3) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 11 [4-21] (n=6) | 100% | 11 [4-21] (n=6) | 100% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| active | 5% | 11 [4-21] (n=6) | 100% | 11 [4-21] (n=6) | 100% | 0.0% [0.0%-0.4%] | 23 [20-26] (n=6) |
| active | 15% | 24 [8-84] (n=6) | 100% | 27 [9-84] (n=5) | 83% | 0.2% [0.0%-0.4%] | 32 [23-40] (n=6) |
| symptom_naive | 0% | 30 [16-58] (n=6) | 100% | 30 [16-58] (n=6) | 100% | 0.0% [0.0%-0.0%] | 2 [1-4] (n=6) |
| symptom_naive | 5% | 30 [16-58] (n=6) | 100% | 30 [16-58] (n=6) | 100% | 0.0% [0.0%-0.4%] | 5 [2-10] (n=6) |
| symptom_naive | 15% | 50 [19-160] (n=6) | 100% | 58 [19-160] (n=5) | 83% | 0.2% [0.0%-0.4%] | 12 [3-18] (n=6) |
| full_sweep | 0% | 19 [12-22] (n=3) | 50% | 19 [12-22] (n=3) | 50% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| full_sweep | 5% | 19 [12-22] (n=3) | 50% | 19 [12-22] (n=3) | 50% | 0.0% [0.0%-0.4%] | 23 [20-26] (n=6) |
| full_sweep | 15% | 22 [12-33] (n=3) | 50% | 28 [22-33] (n=2) | 33% | 0.2% [0.0%-0.4%] | 32 [23-40] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 28 [12-54] (n=3) | 100% | 28 [12-54] (n=3) | 100% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=3) |
| active | 5% | 28 [12-54] (n=3) | 100% | 28 [12-54] (n=3) | 100% | 0.0% [0.0%-0.0%] | 22 [22-24] (n=3) |
| active | 15% | 39 [21-69] (n=3) | 100% | 39 [21-69] (n=3) | 100% | 0.0% [0.0%-0.8%] | 31 [27-39] (n=3) |
| symptom_naive | 0% | 45 [9-54] (n=3) | 100% | 45 [9-54] (n=3) | 100% | 0.0% [0.0%-0.0%] | 3 [3-3] (n=3) |
| symptom_naive | 5% | 45 [9-54] (n=3) | 100% | 45 [9-54] (n=3) | 100% | 0.0% [0.0%-0.0%] | 6 [6-6] (n=3) |
| symptom_naive | 15% | 45 [9-54] (n=3) | 100% | 45 [9-54] (n=3) | 100% | 0.0% [0.0%-0.8%] | 11 [9-17] (n=3) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=3) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 22 [22-24] (n=3) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.8%] | 31 [27-39] (n=3) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |

### sys04_psz_hp

Corruption types actually generated for this topology across all variants: fabrication, misattribution, removal.

**Blind verification**

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 68 [12-200] (n=6) | 100% | 68 [12-200] (n=6) | 100% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| active | 5% | 76 [15-222] (n=6) | 100% | 76 [15-222] (n=6) | 100% | 0.0% [0.0%-0.0%] | 21 [19-22] (n=6) |
| active | 15% | 32 [24-297] (n=5) | 83% | 32 [24-297] (n=5) | 83% | 0.0% [0.0%-0.0%] | 24 [21-26] (n=6) |
| full_sweep | 0% | 18 [12-22] (n=3) | 50% | 18 [12-22] (n=3) | 50% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| full_sweep | 5% | 25 [24-25] (n=3) | 50% | 25 [24-25] (n=3) | 50% | 0.0% [0.0%-0.0%] | 21 [19-22] (n=6) |
| full_sweep | 15% | 32 [30-35] (n=3) | 50% | 32 [30-35] (n=3) | 50% | 0.0% [0.0%-0.0%] | 24 [21-26] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 191 [29-231] (n=6) | 100% | 191 [29-231] (n=6) | 100% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=6) |
| active | 5% | 227 [34-254] (n=5) | 83% | 227 [34-254] (n=5) | 83% | 0.0% [0.0%-0.0%] | 21 [19-21] (n=6) |
| active | 15% | 285 [51-320] (n=5) | 83% | 287 [51-320] (n=5) | 83% | 0.0% [0.0%-0.0%] | 25 [21-25] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 21 [19-21] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 25 [21-25] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

**Symptom-triggered**

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 8 [4-22] (n=6) | 100% | 8 [4-22] (n=6) | 100% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| active | 5% | 8 [4-22] (n=6) | 100% | 8 [4-22] (n=6) | 100% | 0.0% [0.0%-0.4%] | 24 [20-28] (n=6) |
| active | 15% | 18 [7-51] (n=6) | 100% | 18 [7-53] (n=6) | 100% | 0.0% [0.0%-0.8%] | 32 [23-38] (n=6) |
| symptom_naive | 0% | 32 [10-58] (n=6) | 100% | 32 [10-58] (n=6) | 100% | 0.0% [0.0%-0.0%] | 2 [1-4] (n=6) |
| symptom_naive | 5% | 32 [10-58] (n=6) | 100% | 32 [10-58] (n=6) | 100% | 0.0% [0.0%-0.4%] | 6 [2-10] (n=6) |
| symptom_naive | 15% | 46 [20-68] (n=6) | 100% | 50 [20-162] (n=6) | 100% | 0.0% [0.0%-0.8%] | 10 [3-22] (n=6) |
| full_sweep | 0% | 18 [12-22] (n=3) | 50% | 18 [12-22] (n=3) | 50% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| full_sweep | 5% | 18 [12-22] (n=3) | 50% | 18 [12-22] (n=3) | 50% | 0.0% [0.0%-0.4%] | 24 [20-28] (n=6) |
| full_sweep | 15% | 18 [12-22] (n=3) | 50% | 22 [12-37] (n=3) | 50% | 0.0% [0.0%-0.8%] | 32 [23-38] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 24 [4-53] (n=6) | 100% | 24 [4-53] (n=6) | 100% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=6) |
| active | 5% | 24 [4-290] (n=6) | 100% | 24 [4-290] (n=6) | 100% | 0.0% [0.0%-0.0%] | 22 [20-24] (n=6) |
| active | 15% | 37 [5-99] (n=6) | 100% | 37 [7-99] (n=6) | 100% | 0.0% [0.0%-0.4%] | 28 [23-31] (n=6) |
| symptom_naive | 0% | 36 [21-53] (n=6) | 100% | 36 [21-53] (n=6) | 100% | 0.0% [0.0%-0.0%] | 2 [1-3] (n=6) |
| symptom_naive | 5% | 36 [21-120] (n=6) | 100% | 36 [21-120] (n=6) | 100% | 0.0% [0.0%-0.0%] | 4 [2-6] (n=6) |
| symptom_naive | 15% | 36 [21-149] (n=6) | 100% | 56 [22-149] (n=6) | 100% | 0.0% [0.0%-0.4%] | 8 [3-13] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 22 [20-24] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.4%] | 28 [23-31] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

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

### sys09_furnace_gas

Corruption types actually generated for this topology across all variants: fabrication, removal.

**Blind verification**

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 58 [11-220] (n=6) | 100% | 58 [11-220] (n=6) | 100% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| active | 5% | 66 [14-233] (n=6) | 100% | 68 [14-233] (n=6) | 100% | 0.0% [0.0%-0.0%] | 21 [19-22] (n=6) |
| active | 15% | 41 [23-312] (n=5) | 83% | 83 [27-312] (n=4) | 67% | 0.0% [0.0%-0.0%] | 22 [21-32] (n=6) |
| full_sweep | 0% | 19 [11-22] (n=3) | 50% | 19 [11-22] (n=3) | 50% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| full_sweep | 5% | 25 [24-29] (n=3) | 50% | 29 [24-31] (n=3) | 50% | 0.0% [0.0%-0.0%] | 21 [19-22] (n=6) |
| full_sweep | 15% | 34 [32-44] (n=3) | 50% | 41 [38-44] (n=2) | 33% | 0.0% [0.0%-0.0%] | 22 [21-32] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 12 [2-14] (n=3) | 100% | 12 [2-14] (n=3) | 100% | 0.0% [0.0%-0.0%] | 20 [20-20] (n=3) |
| active | 5% | 3 [3-3] (n=1) | 33% | 3 [3-3] (n=1) | 33% | 0.0% [0.0%-0.0%] | 22 [20-22] (n=3) |
| active | 15% | 4 [4-4] (n=1) | 33% | 4 [4-4] (n=1) | 33% | 0.0% [0.0%-0.0%] | 22 [22-32] (n=3) |
| full_sweep | 0% | 12 [2-14] (n=3) | 100% | 12 [2-14] (n=3) | 100% | 0.0% [0.0%-0.0%] | 20 [20-20] (n=3) |
| full_sweep | 5% | 22 [22-22] (n=1) | 33% | 22 [22-22] (n=1) | 33% | 0.0% [0.0%-0.0%] | 22 [20-22] (n=3) |
| full_sweep | 15% | 24 [24-24] (n=1) | 33% | 24 [24-24] (n=1) | 33% | 0.0% [0.0%-0.0%] | 22 [22-32] (n=3) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |

**Symptom-triggered**

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 10 [4-25] (n=6) | 100% | 10 [4-25] (n=6) | 100% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| active | 5% | 10 [4-25] (n=6) | 100% | 14 [4-63] (n=6) | 100% | 0.0% [0.0%-0.4%] | 24 [20-26] (n=6) |
| active | 15% | 12 [5-35] (n=6) | 100% | 14 [5-53] (n=6) | 100% | 0.0% [0.0%-0.4%] | 32 [23-42] (n=6) |
| symptom_naive | 0% | 34 [14-58] (n=6) | 100% | 34 [14-58] (n=6) | 100% | 0.0% [0.0%-0.0%] | 2 [1-4] (n=6) |
| symptom_naive | 5% | 34 [14-58] (n=6) | 100% | 34 [14-120] (n=6) | 100% | 0.0% [0.0%-0.4%] | 6 [2-8] (n=6) |
| symptom_naive | 15% | 34 [14-58] (n=6) | 100% | 50 [14-164] (n=6) | 100% | 0.0% [0.0%-0.4%] | 11 [3-21] (n=6) |
| full_sweep | 0% | 19 [11-22] (n=3) | 50% | 19 [11-22] (n=3) | 50% | 0.0% [0.0%-0.0%] | 20 [19-20] (n=6) |
| full_sweep | 5% | 19 [11-22] (n=3) | 50% | 22 [11-31] (n=3) | 50% | 0.0% [0.0%-0.4%] | 24 [20-26] (n=6) |
| full_sweep | 15% | 19 [11-22] (n=3) | 50% | 22 [11-38] (n=3) | 50% | 0.0% [0.0%-0.4%] | 32 [23-42] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 1 [1-3] (n=3) | 100% | 1 [1-3] (n=3) | 100% | 0.0% [0.0%-0.0%] | 20 [20-20] (n=3) |
| active | 5% | 266 [1-276] (n=3) | 100% | 266 [1-276] (n=3) | 100% | 0.0% [0.0%-0.0%] | 24 [22-24] (n=3) |
| active | 15% | 39 [1-390] (n=3) | 100% | 39 [1-390] (n=3) | 100% | 0.0% [0.0%-0.0%] | 30 [26-36] (n=3) |
| symptom_naive | 0% | 14 [2-21] (n=3) | 100% | 14 [2-21] (n=3) | 100% | 0.0% [0.0%-0.0%] | 2 [2-2] (n=3) |
| symptom_naive | 5% | 61 [2-61] (n=3) | 100% | 61 [2-61] (n=3) | 100% | 0.0% [0.0%-0.0%] | 4 [4-4] (n=3) |
| symptom_naive | 15% | 72 [2-103] (n=3) | 100% | 72 [2-103] (n=3) | 100% | 0.0% [0.0%-0.0%] | 6 [6-10] (n=3) |
| full_sweep | 0% | 12 [2-14] (n=3) | 100% | 12 [2-14] (n=3) | 100% | 0.0% [0.0%-0.0%] | 20 [20-20] (n=3) |
| full_sweep | 5% | 25 [2-27] (n=3) | 100% | 25 [2-27] (n=3) | 100% | 0.0% [0.0%-0.0%] | 24 [22-24] (n=3) |
| full_sweep | 15% | 30 [2-31] (n=3) | 100% | 30 [2-31] (n=3) | 100% | 0.0% [0.0%-0.0%] | 30 [26-36] (n=3) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=3) |

### sys10_furnace_electric

Corruption types actually generated for this topology across all variants: fabrication, misattribution, removal.

**Blind verification**

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 67 [13-186] (n=6) | 100% | 67 [13-186] (n=6) | 100% | 0.0% [0.0%-0.0%] | 19 [18-20] (n=6) |
| active | 5% | 117 [27-211] (n=5) | 83% | 117 [27-211] (n=5) | 83% | 0.0% [0.0%-0.0%] | 22 [20-24] (n=6) |
| active | 15% | 156 [39-210] (n=3) | 50% | 156 [39-210] (n=3) | 50% | 0.0% [0.0%-0.4%] | 30 [26-34] (n=6) |
| full_sweep | 0% | 21 [13-22] (n=3) | 50% | 21 [13-22] (n=3) | 50% | 0.0% [0.0%-0.0%] | 19 [18-20] (n=6) |
| full_sweep | 5% | 25 [25-25] (n=2) | 33% | 25 [25-25] (n=2) | 33% | 0.0% [0.0%-0.0%] | 22 [20-24] (n=6) |
| full_sweep | 15% | 34 [34-34] (n=1) | 17% | 34 [34-34] (n=1) | 17% | 0.0% [0.0%-0.4%] | 30 [26-34] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 104 [75-205] (n=6) | 100% | 104 [75-205] (n=6) | 100% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=6) |
| active | 5% | 130 [130-131] (n=2) | 33% | 130 [130-131] (n=2) | 33% | 0.0% [0.0%-0.0%] | 19 [19-23] (n=6) |
| active | 15% | 166 [162-169] (n=2) | 33% | 166 [162-169] (n=2) | 33% | 0.0% [0.0%-0.4%] | 29 [23-31] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 19 [19-23] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.4%] | 29 [23-31] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

**Symptom-triggered**

severity = 2 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 16 [5-42] (n=6) | 100% | 16 [5-42] (n=6) | 100% | 0.0% [0.0%-0.0%] | 19 [18-20] (n=6) |
| active | 5% | 25 [5-290] (n=6) | 100% | 25 [5-290] (n=6) | 100% | 0.0% [0.0%-0.0%] | 25 [22-28] (n=6) |
| active | 15% | 63 [8-428] (n=6) | 100% | 63 [8-428] (n=6) | 100% | 0.2% [0.0%-0.8%] | 38 [30-46] (n=6) |
| symptom_naive | 0% | 40 [24-57] (n=6) | 100% | 40 [24-57] (n=6) | 100% | 0.0% [0.0%-0.0%] | 3 [2-4] (n=6) |
| symptom_naive | 5% | 42 [24-120] (n=6) | 100% | 42 [24-120] (n=6) | 100% | 0.0% [0.0%-0.0%] | 6 [4-10] (n=6) |
| symptom_naive | 15% | 88 [24-203] (n=6) | 100% | 126 [24-203] (n=6) | 100% | 0.0% [0.0%-0.4%] | 11 [6-18] (n=6) |
| full_sweep | 0% | 21 [13-22] (n=3) | 50% | 21 [13-22] (n=3) | 50% | 0.0% [0.0%-0.0%] | 19 [18-20] (n=6) |
| full_sweep | 5% | 22 [21-31] (n=3) | 50% | 22 [21-31] (n=3) | 50% | 0.0% [0.0%-0.0%] | 25 [22-28] (n=6) |
| full_sweep | 15% | 42 [21-50] (n=3) | 50% | 50 [21-52] (n=3) | 50% | 0.2% [0.0%-0.8%] | 38 [30-46] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |

severity = 3 corrupted edge(s):

| policy | noise | first-flag (all corrupted) | rate | sustained | rate | false-positive rate | needless retests |
|---|---|---|---|---|---|---|---|
| active | 0% | 20 [10-49] (n=6) | 100% | 20 [10-49] (n=6) | 100% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=6) |
| active | 5% | 286 [10-340] (n=6) | 100% | 286 [22-340] (n=6) | 100% | 0.0% [0.0%-0.0%] | 22 [20-26] (n=6) |
| active | 15% | 93 [15-490] (n=6) | 100% | 93 [15-490] (n=6) | 100% | 0.0% [0.0%-0.4%] | 33 [27-41] (n=6) |
| symptom_naive | 0% | 27 [10-47] (n=6) | 100% | 27 [10-47] (n=6) | 100% | 0.0% [0.0%-0.0%] | 2 [1-3] (n=6) |
| symptom_naive | 5% | 62 [10-119] (n=6) | 100% | 62 [22-119] (n=6) | 100% | 0.0% [0.0%-0.0%] | 4 [2-6] (n=6) |
| symptom_naive | 15% | 109 [10-211] (n=6) | 100% | 109 [22-227] (n=6) | 100% | 0.0% [0.0%-0.0%] | 8 [3-13] (n=6) |
| full_sweep | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 19 [19-19] (n=6) |
| full_sweep | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 22 [20-26] (n=6) |
| full_sweep | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.4%] | 33 [27-41] (n=6) |
| blueprint_literal | 0% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 5% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
| blueprint_literal | 15% | n/a (0 attained) | 0% | n/a (0 attained) | 0% | 0.0% [0.0%-0.0%] | 0 [0-0] (n=6) |
