# Changelog

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
