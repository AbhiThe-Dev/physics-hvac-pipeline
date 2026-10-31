# Changelog

## 2026-09-20 -- `extract_topology`: VAV:Reheat reheat coil -> terminal `hasPart` edge

Added `coil -hasPart-> terminal` for `AirTerminal:SingleDuct:VAV:Reheat` (same part -> whole direction as AHU coils and PTAC/PTHP coils). Only sys05 and sys07 change (+10 `hasPart` edges each); nodes, `feeds` edges and candidate universes are unchanged for all 10 buildings. `results_physics/` was not regenerated. Motivated by `symptom_pipeline` (see its CHANGELOG 0.2.3).

## 2026-09-18 — Six-system extension complete: sys04/sys09/sys10 done, round closed

Closes out the six-system extension (PTAC, PTHP, four single-zone non-VAV systems). `results.md` and `README.md` have both been fully rewritten to reflect all 10 systems; see those for the complete narrative. This entry covers what changed since the sys01/02/03 checkpoint below.

**sys04 (PSZ-HP)** confirmed, not assumed, that every sys03 rewire.py fix carries over directly -- same architecture (ten dedicated single-zone AirLoopHVACs, `AirTerminal:SingleDuct:ConstantVolume:NoReheat`, zero PlantLoop), different coils (DX heating + electric backup instead of gas). Full sweep clean at production scope (severities 1-3); the same two already-documented collision categories appear at wider seed ranges, not new ones. Denominator: 6 attempted, 6 clean, 0 dead, 0 failed.

**sys09 (gas furnace) and sys10 (electric furnace)** are simpler than sys03/04 (heating-only, no cooling coil) but sys10 surfaced a **fourth variant of the setpoint-manager bug**, and this one landed on an actual production-scope seed (severity 3), not just an exploratory sweep -- the round wasn't done until this was found and fixed. `set_ahu_direct_service`'s own zone-move (`addBranchForZone`'s auto-move mechanism) was found to invalidate the *original* airloop's `SetpointManager:SingleZone:Reheat` the same way `removeBranchForZone` does, but this code path doesn't go through `_remove_branch_safely` (which already had the capture-before-move-and-retarget fix from the sys03 round) -- `set_ahu_direct_service`'s own `original_airloop` handling only ever *deleted* it when empty, with no retarget path for when it survives with a different remaining zone (possible once an earlier event in the same blueprint has already added a second zone to it). Fixed with a new shared helper, `_reconcile_airloop_after_zone_departure`, used by both code paths so the fix isn't duplicated. Re-verified across all 10 buildings after this fix (field-by-field regression diff, not just a summary-count check) -- clean.

**Final denominator across all 10 systems: 86 attempted, 83 clean, 2 dead, 1 failed.** `83 + 2 + 1 == 86`. The 1 failure (`sys10_furnace_electric`, severity 2, one seeded variant, a cross-event AHU collision) is the first time this number has been nonzero in an actually-shipped production batch in this project's history, not just an exploratory sweep -- reported plainly in `results.md`'s summary table, not smoothed into a clean line. **3087 total troubleshooting trials** (1386 from the 4 previously-validated buildings, confirmed bit-for-bit unchanged; 1701 from the six new ones).

**Explicitly out of scope for this round, logged as backlog items, not attempted:**
- Central-plant equipment fault types (chiller/boiler/tower-level faults) -- never touched, as instructed at the start of this round.
- AHU<->Terminal_Unit rewiring. `sys03`/`sys04`/`sys09`/`sys10`'s ten independent AHUs each make this a genuinely meaningful gap now (25 excluded candidates in the coverage comparison), not the vacuous exclusion it was on every single-AHU building -- worth a dedicated future round, not squeezed into this one.
- Coil-level fault injection (`_run_coil_fault`) -- unchanged from the prior round, still unused.
- Real noise-rate calibration from physics -- unchanged, still not started.

## 2026-09-18 — Six-system extension, in progress: sys01/sys02/sys03 done, three remaining

**sys02 (PTHP)** cleared all six checks with no new code beyond what sys01 required. Extraction, `find_packaged_unit_for_zone`, and the rewire dispatch all generalized directly (same object family, `ZoneHVACPackagedTerminalHeatPump` alongside `PackagedTerminalAirConditioner`). Confirmed independently, not inherited from either sys01 or sys06: zero coil-target events drawn across 105 exploratory blueprint attempts (structural proof -- `_event_in_scope`'s Pump-only source-type check plus zero Pump nodes in sys02's graph), and a flat 0% collision rate across the same 200-seed/severity study used elsewhere. Denominator: 12 attempted, 12 clean, 0 dead, 0 failed.

**sys03 (PSZ-AC) needed real, non-drop-in `rewire.py` work**, and surfaced the most significant new bugs of this round -- all found by actually simulating rewired models, not by forward-translation (which stayed silent every time):

1. A dedicated single-zone `AirLoopHVAC` (one per zone, not a shared central AHU -- confirmed via direct inspection) left with zero zones after a branch removal is invalid EnergyPlus input ("An outlet node in AirLoopHVAC=... is not connected to any zone", Fatal). Fixed: the whole airloop is deleted (`_delete_airloop_if_now_zoneless`), not just the branch, when the removal was its last zone -- but only where nothing gets added back to that same airloop object in the same operation (`remove_zone_service`; the `target_airloop`/`to_airloop` side of `add_extra_service`/`reassign_terminal`).
2. Its `SetpointManager:SingleZone:Reheat` referencing the removed zone goes stale the same way -- but the fix isn't uniform: when the airloop is fully deleted, nothing further is needed (cascades away); when the airloop *survives* with a different zone (`reassign_terminal`'s `from_airloop`, or a zone temporarily doubled up by `set_ahu_direct_service`), the setpoint manager must be *retargeted* (`setControlZone`), not removed -- removing it instead broke a *different* setpoint manager (`SetpointManager:MixedAir`) that references it as its own setpoint source. Found by actually simulating, not just translating, three times before landing on the right fix.
3. **A genuine bug in the pre-existing `set_ahu_direct_service`**, latent since it was written and only now exercised: `AirLoopHVAC.addBranchForZone` silently auto-moves a zone's connection away from wherever it truly was, which was never observable before because sys05-08 have only one AHU total (a zone's "true" airloop and the "fabricated" one were always the same object). On sys03's ten independent AHUs this leaves the zone's *original* airloop's setpoint manager dangling. Fixed by capturing the zone's original airloop before the move and cleaning it up after.
4. **A real segfault** (confirmed via exit code 139, not just a hang): `reassign_terminal`/`add_extra_service` assumed `from_airloop`/`to_airloop` (or `donor_airloop`/`target_airloop`) are always different objects -- true everywhere else, but not once a fabrication event can put two zones on one airloop (fix #3's mechanism). When they alias, deleting the "to" airloop for being zone-less destroys the exact object the very next line calls `.addBranchForZone()` on. Fixed with a handle-equality guard before every such deletion.
5. Two further collision categories were found and left gracefully handled but *not* structurally filtered, matching the precedent already set for sys05's DX-coil case: an AHU that a fabrication/misattribution event references can be deleted by an *earlier* event in the same blueprint (fixed the resulting crash defensively -- `pipeline._resolve_airloop` -- rather than building a new structural filter), and a donor zone's terminal can likewise already be gone. Neither appears in the actual 2-seed production batch; both are real and reproducible at wider seed ranges (confirmed, not assumed).

`build_zone_to_coil_map` confirmed a correct flat-0% no-op for sys03 (zero PlantLoops). **Denominator, severities 1-3 (production scope): 6 attempted, 6 clean, 0 dead, 0 failed.** Regression check (bit-for-bit field comparison, all 6 prior buildings) clean after every fix in this entry, not just the final one.

**Running total across 7 systems: 69 attempted, 67 clean, 2 dead, 0 failed.** `67+2+0 == 69`.

### Remaining for this round
- `sys04`: same one-zone-per-AirLoopHVAC / `AirTerminal:SingleDuct:ConstantVolume:NoReheat` architecture as sys03 (confirmed via direct inspection), different coil types (DX heating instead of gas) -- expect the sys03 rewire fixes to carry over directly, but still needs its own full verification pass, not an assumed pass.
- `sys09`/`sys10`: not yet investigated.

## 2026-09-18 — Six-system extension, in progress: sys01 (PTAC) done, five remaining

Extending the pipeline to the six systems scoped out in the prior widening round (PTAC, PTHP, and four single-zone non-VAV systems), one at a time per the established discipline -- full verification per system before moving to the next. This entry covers `sys01_ptac` only; `README.md`/`results.md` will get their full rewrite once all six systems clear, not after each one, to avoid rewriting the same narrative six times.

**sys01 (PTAC) needed genuinely new code, not a drop-in reuse -- in three places, not just `extract.py` as originally scoped:**

1. **`extract.py`**: new walk for `ZoneHVAC:PackagedTerminalAirConditioner`/`PackagedTerminalHeatPump` (no `AirLoopHVAC` exists for these at all). Found, before writing this, that the *existing* plant-loop-walking code already silently produced 10 orphaned `Heating_Coil` nodes with zero zone connection when run against sys01 unmodified -- a live, previously undetected bug that would have corrupted the graph the moment this building was added without matching terminal extraction.
2. **`rewire.py`**: `remove_zone_service`/`reassign_terminal`/`add_extra_service` were entirely built on `find_airloop_for_zone`, which returns `None` for every PTAC zone -- confirmed empirically that every terminal-unit<->zone corruption event on sys01 would have failed 100% of the time, gracefully but uselessly. Added a packaged-unit dispatch path. Verified empirically (not assumed from the VAV-terminal precedent) that PTAC's lifetime semantics are actually *simpler*: `.remove()` cleanly cascade-deletes the whole assembly (unit + both coils + fan) in one call with no orphaning, and `.clone()` already re-plumbs the cloned hydronic coil onto the plant loop automatically -- neither of VAV:Reheat's segfault-risk or clone-orphaning issues apply here.
3. **`remove_coil_service`**: PTAC's heating coil hit neither of the two existing branches (not a standalone AHU-level coil, not embedded in a VAV:Reheat terminal) -- a third case found by auditing this function against sys01 rather than assuming the existing two covered it. Since `ZoneHVAC:PackagedTerminalAirConditioner` requires a heating coil field (there's no "PTAC:NoReheat"), the fix swaps in a fresh `Coil:Heating:Electric` via `setHeatingCoil()` and deletes the old hydronic coil, rather than deleting the whole unit.
4. **`build_zone_to_coil_map`**: extended to recognize PTAC's embedded heating coil for collision-safety tracking -- checked explicitly (per instruction) rather than assumed to inherit from sys06's zero-plant-loop proof, since PTAC/PTHP still have coils where sys06 effectively didn't. Confirmed the collision-rate profile is real and systematic here too (0% at severity 1 -> 89.5% at severity 10, 200-seed study), matching sys05/sys07's shape.

**Denominator for sys01 (severities 1-3, 2 seeds each): 12 attempted, 12 clean, 0 dead, 0 failed.** Confirmed the same DX-coil-fabrication failure mode found on sys05 also exists here (sys01's cooling coil is DX, same `_unresolved_coil_reason` diagnostic fires correctly, no new code needed) -- found via a wider seed sweep, not drawn by this specific batch's seeds, same as sys05's case.

**Regression check on sys05-sys08, proven not assumed:** re-ran the full existing batch after all the above changes and diffed the resulting bundle field-by-field against the pre-change baseline (node counts, edge counts, node type counts, blueprint events, claimed edges, every plausibility record's rewired/severe_errors/functionally_dead) -- bit-for-bit identical across all four buildings.

**Found but explicitly out of scope for this pass, logged as its own backlog item:** `add_thermostat_offset_fault`'s default schedule names (`"Always_On"`) don't match any schedule OpenStudio actually generates (`"Always On Discrete"`, with a space) -- confirmed this is a pre-existing, project-wide mismatch present in every building's fault-injection run, not sys01-specific. EnergyPlus evidently falls back to an always-active default when the reference fails to resolve (the measured thermostat-offset deviation matches the intended 5 degC almost exactly on both sys01 and sys07), so this hasn't been corrupting results -- but it's a wrong reference that happens to fail safe, not a correct one, and deserves its own fix rather than being bundled into this pass.

### Remaining for this round
- `sys02_pthp`: same object family as PTAC but confirmed fully DX (zero PlantLoops, zero pumps) -- the new rewire.py packaged-unit dispatch should carry over directly, but its own collision/coil-audit checks still need to be run per the same discipline, not assumed from either sys01 or sys06.
- `sys03`/`sys04`/`sys09`/`sys10`: single-zone, `AirTerminal:SingleDuct:Uncontrolled` terminals -- not yet investigated at all.

## 2026-09-17 — Coil-fouling fault: root cause found and fixed, factor recalibrated, still unwired

Diagnosis-then-fix round on `FaultModel:Fouling:Coil`'s previously-inconsistent behavior (no effect on `sys07`'s reheat coil, complete shutdown on its central cooling coil).

**Root cause**, confirmed against EnergyPlus 25.2.0's own `WaterCoils.cc` source at the pinned version: `add_coil_fouling_fault` never set the `FoulingFactor` method's `Outside Coil Surface Area`/`Inside-to-Outside Ratio` IDD fields, which the `Rfoul = rwater/(Aout*Aratio) + rair/Aout` formula divides by. The identical missing input produces `Rfoul = inf` on `Coil:Cooling:Water` (hard collapse to 0 W) and `Rfoul = 0` exactly on `Coil:Heating:Water` (silent no-op) -- one bug, two different EnergyPlus-internal failure modes, not two independent coil-type gaps.

**Fix**: `faults.py` now derives `Aout`/ratio per-coil from that coil's own EnergyPlus sizing output (`estimate_coil_surface_area`, using EnergyPlus's own `EstimateHEXSurfaceArea` correlation, Nigusse/FSEC 2010 -- the same correlation behind the IDD's own 0.07 ratio default) instead of leaving them unset; `add_coil_fouling_fault` now requires `outside_coil_surface_area` explicitly, no default, closing off the exact silently-omitted-field failure mode. **Confidence differs by coil type**: the cooling-coil derivation is bit-exact-verified against EnergyPlus's own published "Nominal Coil Surface Area" in `eplusout.eio`; the heating-coil derivation applies the same correlation "by hand" (EnergyPlus's own source never extends this reporting to heating coils), validated only by producing sane degradation curves, not by independent ground truth. Treat the heating-coil branch as open/lower-confidence -- see `results_physics/results.md` for the full writeup.

**Fouling-factor default recalibrated**: checked first whether a severity-to-fault-magnitude convention already exists in this codebase to calibrate against -- it does not (`severity` means "number of corruption events" everywhere; the one existing physical fault, thermostat offset, uses a fixed 5 degC regardless of severity). Recalibrated to a single fixed 0.005 m2-K/W (old default 0.0005 was tuned against the broken math and gave a sub-1% effect once fixed), matching the existing one-fixed-magnitude convention. Validated end-to-end on three structurally different coils: sys07 reheat 44.8% reduction, sys08 central cooling 8.0%, sys05 reheat (different building) 50.4% -- all clearly detectable, none functionally dead, zero severe errors.

**Still not wired into `pipeline.py`'s dispatch** (`_run_coil_fault` remains unused) -- that decision is unchanged from the prior round.

## 2026-09-17 — Verification: sys06's zero-collision-risk result is proven, not just unobserved

Follow-up to the widening round below, prompted by the question of whether "same object classes, no code changes needed" (true for sys05/sys06) also means "identical behavior verified," which the DX-coil finding already showed it doesn't. Confirmed by forcing `scope.filter_collision_events`'s logic to run anyway on a real `sys06_vav_piu_dx` production blueprint (bypassing its own early return and its caller's `if zone_to_coil:` guard) that the empty-map short-circuit is a proven-equivalent optimization, not an untested assumption; and confirmed, via two independent guarantees (`_event_in_scope`'s Pump-only source-type check plus sys06 having zero Pump-type nodes), that `pipeline._handle_coil_event`/`reassign_coil`/`remove_coil_service` are structurally unreachable for sys06, not merely unexercised by this batch's seeds. No code behavior changed; see `results_physics/results.md` (new paragraph next to the sys05 DX-coil caveat) and the two guard sites in `scope.py`, now commented with this proof.

## 2026-09-17 — Batch widened to 4 buildings: sys05 + sys06, DX-coil scope-gap fix

Widened the validation batch from 2 buildings (`sys07_vav_reheat`,
`sys08_vav_parallel_piu`) to 4, adding `sys05_vav_reheat_dx` (hydronic
VAV-reheat, single hot-water plant/pump, DX cooling) and
`sys06_vav_piu_dx` (electric PIU-reheat, zero plant loops, fully
DX/electric) -- genuinely new plant/coil topologies (single-medium and
zero-plant-loop), not just more seeds on the same two buildings. Full
detail in `results_physics/results.md`; summary below.

**Scope decision, confirmed with the user before running anything:** of
the 10 ASHRAE 90.1 baseline system archetypes vendored, `sys05`/`sys06`
were chosen because they reuse the exact `AirLoopHVAC`/VAV-terminal/
`PlantLoop`-pump object classes `extract.py`/`rewire.py` already handle,
needing no extraction-code changes. `sys01`/`sys02` (PTAC/PTHP, no
`AirLoopHVAC` at all) and `sys03`/`sys04`/`sys09`/`sys10` (single-zone,
`AirTerminal:SingleDuct:Uncontrolled` terminals) were explicitly scoped
out as a separate future round -- see "Open items" below.

**A real bug found by widening, not by hypothesizing:** `sys05`'s cooling
coil is DX (`Coil:Cooling:DX:TwoSpeed`), not hydronic. `generate_blueprint`
still draws pump<->coil fabrication events targeting it (Brick doesn't
distinguish DX from hydronic coils), but this pipeline's coil rewiring
only ever understood `Coil:Cooling:Water`/`Coil:Heating:Water`. The
existing failure message for an unresolvable coil assumed the *only*
possible cause -- true on `sys07`/`sys08`, where every coil is hydronic --
was cross-event collision (an earlier event in the same blueprint
destroying the coil). On `sys05` that assumption is false: the DX coil is
never destroyed, it's simply never resolvable as hydronic. Fixed in
`pipeline.py` (`_unresolved_coil_reason`) to check whether the raw object
resolves at all before checking whether it resolves as hydronic, so the
two causes are reported distinctly. This is a permanent, recurring scope
gap for any building with a non-hydronic coil target (confirmed to recur
roughly every 10-20 seeds in a wider sweep), not a transient collision --
it just didn't happen to be drawn by this batch's own 6 seeds per
building, so it shows up as `n_failed=0` in this run's table with the gap
documented in prose rather than as a nonzero count.

**Collision-risk generalization confirmed empirically, not assumed:**
extended the existing 200-seed-per-severity Monte Carlo study to all 4
buildings. `sys05` (hydronic zone-embedded coils, one medium) shows the
same systematic, growing collision rate as `sys07` (0% -> 6% -> 69% at
severities 1/3/10, vs. `sys07`'s 0% -> 15% -> 92%); `sys06` (electric
reheat, nothing to cascade-delete) is flat 0%, matching `sys08`. The
existing structural fix needed zero code changes to generalize.

**Cross-medium risk: a clean confirming contrast.** `sys05` has only one
pump/medium (hot-water; cooling is DX), so the cross-medium
misattribution failure mode found on `sys07` is structurally impossible
there -- correctly absent, not silently missed.

**Widened totals:** 48-event denominator (up from 24), 40/48 (83%) in
scope (up from 18/24, 75%), all 8 exclusions still `target is VAV` (no
new out-of-scope category). 39 in-scope events attempted: 37 clean, 2
functionally dead (both pre-existing, on `sys07`), 0 failed to rewire in
this specific batch. 1386 total troubleshooting trials = 693 (both
original buildings, rerun bit-for-bit identical) + 693 (the two new
buildings). `n_clean + n_dead + n_failed == n_attempted` re-verified on
the full widened batch (37 + 2 + 0 == 39), asserted in code now
(`build_report.py`), not just eyeballed.

**Docs updated:** `results_physics/results.md` (full rewrite reflecting
the widened batch, not just re-run with the old prose), `README.md`
("Key findings" section extended, buildings/scope counts updated).

### Open items for a future round

- `sys01`/`sys02` (zone-level PTAC/PTHP, no `AirLoopHVAC`) and
  `sys03`/`sys04`/`sys09`/`sys10` (single-zone, non-VAV `Uncontrolled`
  terminals) need real `extract.py` changes before they can be added --
  not a drop-in extension like sys05/sys06 was.
- `_run_coil_fault` still exists but is unused -- coil-level fault
  injection still needs real investigation before it can be wired in
  (unchanged from the prior round).
- Collision risk is well-quantified on all 4 buildings but severity is
  still capped at 3 in the confirmed batch; revisit before pushing
  severity higher.
- Real DOE prototype buildings still deferred (license question,
  unresolved).
- Noise-rate calibration from physics: not started, deliberately out of
  scope so far.

## 2026-09-17 — Pump/coil audit round: functional-effect check, collision fix, coil-fault correction

Three fixes applied following the pump/coil corruption-type work, plus a
consistency pass on the resulting docs. Closing summary below (source of
truth for what changed and why; `results_physics/results.md` and
`README.md` carry the full technical detail).

### Fix 1 — coil-output plausibility check

Added a season-matched (January for heating coils, July for cooling)
baseline-vs-corrupted comparison, independent of the severe-error check.
Re-audited both previously-"clean" coil misattribution events: both now
show 0.0 W delivered, every hour, against an 11-14 kW baseline — flagged
`functionally_dead` in the data instead of passing silently on
`severe_errors == 0` alone.

### Fix 2 — structural collision fix

Built `rewire.build_zone_to_coil_map()` + `scope.filter_collision_events()`.
An empirical study (severities 1-10, 200 seeds each, pure graph-level
simulation) confirmed the cross-event collision risk is systematic, not
coincidental: 0% at severity 1 -> 15% at severity 3 -> 92% at severity 10
on `sys07_vav_reheat` (hydronic reheat coils); a flat 0% on
`sys08_vav_parallel_piu` (electric reheat, nothing to cascade-delete). The
known collision case in the confirmed batch is now filtered out before
it's ever attempted: 0 failed-to-rewire events, down from 1.

### Fix 3 — coil fouling fault: investigated, NOT shipped

Testing `FaultModel:Fouling:Coil` against `sys07` (the "already validated"
claim only covered one coil on `sys08`) found it does not generalize: zero
measurable effect on `sys07`'s reheat coils (`Heating Coil U Factor Times
Area Value` bit-identical to `...Before Fouling` at both the default
factor and 100x it), and complete shutdown (not moderate degradation) on
`sys07`'s central cooling coil. Per decision: pump/coil-only blueprints
stay blind-mode-only. The investigated-but-unused code (`_run_coil_fault`
in `pipeline.py`) is kept as a documented starting point, not something
running in the pipeline.

### Incidental fix found along the way

The SQL query behind fault-injection deviation numbers had no
`EnvironmentPeriodIndex` filter, silently averaging the real run period
together with EnergyPlus's 7 sizing/design-day environments. Fixed when
`run_fault_injection` was refactored to share the new `_query_series`
helper built for Fix 1. Deviation numbers shifted slightly as a result
(e.g. `sys08` seed 91301001: -4.50C before, -3.82C now) — both were
non-degenerate and directionally correct; the new numbers are accurate.

**Audit, closing this round:** grepped the entire `src/`/`scripts/` tree
for every SQL touchpoint — exactly one `sqlite3.connect()` call site
exists in the whole codebase (`_query_series`), and it already carries the
correct filter. The missing-filter bug was real but singular; no other
unaudited instance exists.

**Consistency pass on the docs:**
- Verified `n_clean + n_dead + n_failed == n_attempted` (15 + 2 + 0 = 17)
  in the structural-corruption summary, and that "clean" and "functionally
  dead" are kept as separate counts, never folded together — already
  correct, no change needed.
- Found and fixed a real gap: the Troubleshooting-against-a-blueprint
  section's "Symptom-triggered" tables include one `sys07_vav_reheat`
  blueprint (severity 1, seed 91301001, pump/coil-only removal) with no
  physics-injected fault behind it at all, since `symptom_flagged_nodes`
  operates at the abstract graph level regardless of whether a real fault
  was separately validated. Added an explicit note immediately before that
  section naming the exact blueprint, so a reader can't assume "symptom-
  triggered" coverage implies a physics-validated fault for every row.

### Open items for a future round

- `_run_coil_fault` exists but is unused — coil-level fault injection
  needs real investigation (why does `FaultModel:Fouling:Coil` behave so
  differently by coil/plant topology?) before it can be wired in.
- Collision risk is well-quantified but severity is currently capped at 3
  in the confirmed batch; revisit before pushing severity higher or adding
  buildings with hydronic reheat architecture like `sys07`.
- Real DOE prototype buildings still deferred (license question on
  `OpenStudio-Prototype-Buildings`, unresolved).
- Noise-rate calibration from physics: not started, deliberately out of
  scope so far.
