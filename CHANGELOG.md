# Changelog

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
