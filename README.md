# Physics-based test case pipeline (foundation)

A new, **separate** pipeline that generates HVAC topology test cases from
real OpenStudio/EnergyPlus physics simulation, instead of the hand-picked
noise assumptions in the existing pure-Python Bayesian benchmark
(`../src/hvac_benchmark`). Kept fully separate per explicit instruction:
this pipeline does not modify `hvac_benchmark`'s code, only imports and
calls it as a library.

**Status: foundation proven end-to-end, using the existing benchmark's
current placeholder noise rates (0/5/15%). All 10 ASHRAE 90.1 Appendix G
baseline system archetypes are now covered** (widened progressively: 2 ->
4 -> 10), spanning three fundamentally different HVAC architectures: one
shared central AHU serving multiple zones (`sys05`-`08`), zone-level
packaged terminal equipment with no `AirLoopHVAC` at all (`sys01`/`sys02`),
and dedicated single-zone `AirLoopHVAC`s, one per zone (`sys03`/`sys04`/
`sys09`/`sys10`). **Validation depth differs by architecture, and that
difference is stated explicitly rather than folded into one "validated"
claim** -- see "Key findings" below for exactly what generalized cleanly,
what needed genuinely new `rewire.py` mechanisms, and the real bugs
(including one segfault) found along the way. Real noise-rate calibration
from physics and scaling up batch size further remain the deliberately
separate, later steps, not attempted here.

## What this is not (yet)

- Not run against the actual DOE Commercial Prototype Building Models --
  `NREL/OpenStudio-Prototype-Buildings` has no license file and its real
  generator code has moved to `NREL/openstudio-standards` (a Ruby
  toolchain). Sourcing real DOE prototypes was explicitly deferred; see
  "License finding" below.
- Not a noise-rate calibration effort. The troubleshooting trials below
  reuse `hvac_benchmark`'s existing 0%/5%/15% placeholder rates verbatim.
- Not a large batch. Confirmed minimal scope: 10 topologies x 1 climate
  zone, 3 corruption severities x 2 seeded variants each.
- Not extended to central-plant equipment fault types (chiller/boiler/
  tower-level faults) -- explicitly out of scope for the six-system
  extension round, logged as its own backlog item rather than attempted.
- Not extended to AHU<->Terminal_Unit rewiring, even though `sys03`/
  `sys04`/`sys09`/`sys10` (ten independent AHUs each, one per zone) make
  this a genuinely meaningful gap on those four buildings now, not the
  vacuous exclusion it was on every single-AHU building -- see the
  Coverage progression section of `results.md`.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install openstudio rdflib networkx numpy matplotlib pyyaml requests pytest
```

EnergyPlus 25.2.0 (matching this OpenStudio build's
`openstudio.energyplus.ENERGYPLUS_VERSION`) is vendored under `vendor/` --
the pip `openstudio` package ships the SDK/model API and IDF translator
only, not the simulation engine itself. Base building models come from
`NREL/OpenStudio-resources` (BSD-3-Clause), also vendored under `vendor/`.

## Layout

```
src/physics_pipeline/
  buildings.py    Registry of the 10 base buildings + climate/EnergyPlus paths
  extract.py      OpenStudio model -> hvac_benchmark TopologyGraph (real Brick classes, geometry-derived location)
  rewire.py       Physical model-rewiring primitives (terminal<->zone, AHU<->zone-direct, pump<->coil)
  scope.py        Filters generate_blueprint's output to edge types rewire.py actually supports
  faults.py       EnergyPlus Operational Fault injection (raw IDF objects)
  simulate.py     EnergyPlus runner + scoped-output helpers
  pipeline.py     Orchestration: extract -> corrupt -> verify physically -> inject fault -> run Bayesian trial
scripts/
  run_batch.py    The confirmed minimal-scope batch run
  build_report.py Generates results_physics/results.md from the batch's saved bundles
results_physics/  Generated output (results.md, run_summary.json, bundles.pkl)
```

## Running it

```bash
source .venv/bin/activate
PYTHONHASHSEED=0 python3 scripts/run_batch.py     # ~35s, writes results_physics/bundles.pkl
PYTHONHASHSEED=0 python3 scripts/build_report.py  # writes results_physics/results.md
```

`PYTHONHASHSEED=0` matters: `hvac_benchmark.experiment.blueprint.
generate_blueprint` orders its true-edge shuffle from `list(set(...))`,
and Python randomizes string hashing (and therefore set iteration order)
per process by default, so which corruption events get generated is only
reproducible *within* a fixed hash seed, not across arbitrary process
invocations. This is a pre-existing property of the unmodified benchmark
code, not something introduced here.

## Key findings from Step 0 verification (see conversation / commit history for full detail)

- OpenStudio SDK 3.11.0 Python bindings install and run with zero friction.
  EnergyPlus itself (25.2.0) is a separate ~200MB download, not bundled.
- `OpenStudio-Prototype-Buildings` has **no license file**; GitHub's API
  confirms `license: null`. Its README says it moved to
  `openstudio-standards`, which does have a license but is Ruby generator
  code, not ready-made models.
- The extraction pipeline correctly walks `AirLoopHVAC.supplyComponents()`/
  `.demandComponents()` to recover AHU -> terminal -> zone `feeds` edges and
  AHU hasPart coils/fans, with 100% candidate-tier coverage against the
  real cached Brick v1.3.0 ontology once OpenStudio IDD type names are
  mapped to actual Brick class names (not OpenStudio's own naming).
- `AirLoopHVAC.removeBranchForZone()` destroys the terminal object along
  with the branch -- reusing a terminal elsewhere requires cloning it
  *first*; calling a method on the stale wrapper segfaults the process
  rather than raising a Python exception.
- A terminal with a *hydronic* reheat coil (VAV:Reheat on a hot-water loop,
  `baseline_sys07`) needs its coil's plant-loop connection explicitly
  managed around every rewire -- `.clone()` doesn't replumb the water side,
  and `removeBranchForZone` doesn't clean it up. Both were real bugs this
  pipeline's physical-plausibility check caught, not hypothetical.
- OpenStudio's `openstudio.model` Python API has no wrapper class for any
  EnergyPlus `FaultModel:*` object; faults are injected as raw IDF objects
  on the post-translation `Workspace`.
- `AirLoopHVAC.addBranchForZone(zone)` (the single-argument, no-terminal
  overload) does NOT produce a bare AHU-direct connection on an airloop
  that already has terminal-served zones -- it silently auto-clones a
  matching terminal instead, confirmed with three call variants including
  an explicit empty `OptionalStraightComponent`. Genuine AHU-direct service
  needed the explicit 3-argument overload with a hand-built minimal
  `AirTerminalSingleDuctConstantVolumeNoReheat` pass-through terminal.
- `generate_blueprint` can't be filtered by handing it a restricted graph:
  its candidate pool comes from ontology-tier node-type ancestry, not from
  which edges exist, so removing an edge type's *true* edges from the graph
  just makes every one of them look "false" and eligible for fabrication --
  worse than not filtering. The fix that actually works: call it unmodified
  on the full graph, then filter its output *events* to in-scope ones and
  reconstruct `claimed_edges` to match (`scope.py`).
- A coil survives disconnection from its plant loop (unlike a terminal,
  destroyed by `removeBranchForZone`), so moving one between pumps needs no
  cloning. But a coil left on the air side with no water connection is not
  valid EnergyPlus input, unlike a zone (which can validly go
  unconditioned) -- a genuine removal has to fully delete the coil, via one
  of two structurally different paths depending on whether it's a
  standalone AHU-level component or embedded inside a VAV:Reheat terminal
  (`removeFromAirLoopHVAC()` silently returns `False` for the latter).
- Cross-event interaction, quantified and fixed: corruption events in one
  blueprint share one scratch model, applied sequentially. A fabrication
  event's terminal replacement can cascade-delete a reheat coil that a
  different, independently-drawn event in the same blueprint also targets
  by node id -- `generate_blueprint`'s duplicate-target guard can't catch
  this, since the two events have different targets that happen to share
  an underlying object the graph never represents as connected. An
  empirical study (pure graph-level simulation, severities 1-10, 200 seeds
  each) found this is systematic: 0% at severity 1 -> 15% at severity 3 ->
  92% at severity 10 on `sys07_vav_reheat` (every zone has a hydronic
  reheat coil); a flat 0% on `sys08_vav_parallel_piu` (electric reheat, no
  plant connection to cascade-delete). Fixed structurally --
  `rewire.build_zone_to_coil_map()` + `scope.filter_collision_events()`
  drop a colliding event before it's ever attempted, reusing the existing
  filter-and-reconstruct-claimed_edges pattern -- rather than just
  continuing to fail gracefully and report it.
- The cross-medium pump/coil risk (moving a coil onto the wrong water
  medium) DID occur in the confirmed batch, and doesn't fail the way
  initially assumed. A *cooling* coil forced onto hot water (the original
  Step 0 test) produces 2267 `FindRootSimpleController` convergence errors
  -- loud, caught by severe_errors. A *heating* coil forced onto chilled
  water (what the batch actually drew, since both buildings have only one
  pump per medium) produces 0 severe errors while delivering exactly 0.0 W
  of heat, every hour -- a silent failure invisible to the severe-error
  check. Caught by a new season-matched (January for heating coils, July
  for cooling) baseline-vs-corrupted functional-effect check, since
  "0 severe errors" alone was never sufficient evidence of plausibility for
  a pump/coil event.
- `FaultModel:Fouling:Coil`, originally validated on exactly one coil in
  one building, does not generalize: the same default factor that gave a
  moderate effect on `sys08`'s central cooling coil drops `sys07`'s
  central cooling coil's output to exactly 0.0 W (complete shutdown), and
  has zero measurable effect at all on `sys07`'s reheat coils (`Heating
  Coil U Factor Times Area Value` bit-identical to `...Before Fouling` at
  both the default factor and 100x it). Not wired in as a result --
  pump/coil-only blueprints stay blind-mode-only by decision, not
  oversight, until this is properly investigated.
- End to end, all three edge types, on the original 2 buildings: coverage
  on the same 24-event denominator went 10/24 (42%, terminal<->zone) ->
  13/24 (54%, +AHU-direct) -> 18/24 (75%, +pump/coil); the remaining 6/24
  is entirely AHU<->Terminal_Unit (not a meaningful rewire with one AHU per
  building). 17 in-scope events attempted (collision-filtered events never
  reach this count): 15 clean and functionally confirmed, 2 passed 0
  severe errors but are functionally dead (caught only by the functional
  check), 0 failed to rewire. All zone-level fault-injection runs produced
  a measurable, non-degenerate symptom signal (one pump/coil-only
  blueprint has none, by decision -- see above). 693 troubleshooting
  trials through the existing, unmodified Bayesian machinery produced
  sensible results.
- **Widening round: `sys05_vav_reheat_dx` (hydronic VAV-reheat, single
  hot-water plant/pump, DX cooling) and `sys06_vav_piu_dx` (electric
  PIU-reheat, zero plant loops, fully DX/electric) added.** Both reuse the
  same `AirLoopHVAC`/VAV-terminal/`PlantLoop`-pump object classes
  `extract.py`/`rewire.py` already handle, so no rewiring code changes
  were needed to attempt them -- but that didn't mean identical behavior:
  a real, previously-latent bug surfaced. `_handle_coil_event`'s
  unresolved-coil message assumed a failed resolve could only mean
  "destroyed by an earlier event's cross-event collision," true on
  `sys07`/`sys08` where every coil is hydronic, but false on `sys05`,
  whose cooling coil is `Coil:Cooling:DX:TwoSpeed` -- `generate_blueprint`
  still draws fabrication events claiming a pump feeds it (a legitimate
  Brick-tier candidate; Brick doesn't distinguish DX from hydronic), and
  the coil is provably still present, never destroyed, just never
  resolvable as a hydronic coil at all. Fixed by checking whether the raw
  object resolves *before* checking whether it resolves as hydronic, so
  "genuinely destroyed" and "exists but is a type this pipeline's pump/coil
  rewiring doesn't support" are reported distinctly
  (`pipeline._unresolved_coil_reason`). This is a permanent, recurring
  scope gap for any building with a non-hydronic coil (confirmed to recur
  every ~10-20 seeds in a wider sweep), not a transient collision -- it
  happened not to be drawn by this batch's own 6 seeds, so it shows up as
  documentation here rather than as a nonzero `n_failed` in this run's
  table.
- The cross-event collision risk (found on `sys07`) was confirmed to
  generalize along the *hydronic-coil* boundary, not be a sys07-specific
  quirk: `sys05` (also hydronic zone-embedded reheat coils, just one
  medium instead of two) shows the same systematic, growing collision
  rate (0% at severity 1 -> 6% at severity 3 -> 69% at severity 10) as
  `sys07` (0% -> 15% -> 92%); `sys06` (electric reheat, no plant
  connection to cascade-delete) is a flat 0%, matching `sys08`. The
  existing structural fix (`build_zone_to_coil_map` +
  `filter_collision_events`) needed no changes to generalize -- it already
  builds the map from whatever terminal/coil classes are actually present.
- The cross-medium pump/coil risk (a coil forced onto the wrong water
  medium) is structurally *impossible* on `sys05` by construction, not
  just unobserved: `sys05` has only one pump/medium (hot-water only, since
  cooling is DX), so there is no second medium for a coil to be
  misattributed onto. A clean confirming contrast with `sys07` (where the
  risk is real and was observed again this round) rather than a
  contradiction -- the risk correctly doesn't materialize where its
  physical precondition doesn't exist.
- Widened batch totals: 48-event denominator (up from 24), 40/48 (83%) in
  scope, all 8 exclusions still `target is VAV` (no new out-of-scope
  category from the two new buildings). 39 in-scope events attempted: 37
  clean and functionally confirmed, 2 functionally dead (both on `sys07`,
  unchanged from before), 0 failed to rewire in this specific batch (the
  DX-coil gap above is real but wasn't drawn by these seeds). 1386
  troubleshooting trials total = 693 (both original buildings, rerun
  bit-for-bit identical, confirming the widening didn't perturb them) +
  693 (the two new buildings, each numerically matching its structural
  analog's blueprint-survival count: sys05~sys07, sys06~sys08).
- **Six-system extension (sys01/02/03/04/09/10): validation depth differs
  by architecture, stated explicitly rather than folded into one uniform
  claim.** `sys02_pthp` needed zero new code beyond `sys01` (same object
  family, every mechanism generalized directly; its zero-coil-target-
  events/flat-0%-collision status was independently re-derived, not
  assumed). `sys01_ptac` needed a third new rewire.py subsystem (zone-level
  packaged-unit equipment has no `AirLoopHVAC` at all), but its lifetime
  semantics turned out *simpler* than the original VAV-terminal case:
  `.remove()` cleanly cascade-deletes the whole assembly with no orphaning,
  and `.clone()` already re-plumbs the embedded hydronic coil onto the
  plant loop automatically. `sys03`/`sys04`/`sys09`/`sys10` (ten
  independent single-zone AirLoopHVACs each, not one shared central AHU)
  needed the most extensive new work and surfaced four real bugs, all
  found by actually simulating rewired models, not by forward translation
  (which stayed silent every time): (1) a dedicated airloop left with zero
  zones after a branch removal is invalid EnergyPlus input and must be
  deleted outright, not just the branch; (2) its
  `SetpointManager:SingleZone:*` must be *retargeted*, not deleted, when
  the airloop survives with a different zone (deleting it broke a
  *different* setpoint manager that referenced it); (3) a genuine,
  previously-latent bug in `set_ahu_direct_service` -- `addBranchForZone`
  silently auto-moves a zone's connection away from wherever it truly was,
  never observable on `sys05`-`08` (only one AHU total there) -- needed the
  same retarget fix a second time, for a code path outside
  `_remove_branch_safely`; (4) a real segfault (confirmed via process exit
  code 139) from an aliasing case where `reassign_terminal`/
  `add_extra_service` assumed two airloop references were always different
  objects, fixed with a handle-equality guard. Two further collision
  categories (an AHU deleted by an earlier event in the same blueprint; a
  donor zone's terminal already gone) were left gracefully handled but not
  structurally filtered, matching the sys05 DX-coil precedent -- one of
  these was drawn by this batch's own actual seeds (`sys10`, severity 2),
  the first time `n_failed > 0` in an actually-shipped production batch
  rather than only an exploratory sweep. Full denominator across all 10
  systems: 86 attempted, 83 clean, 2 dead, 1 failed (`83+2+1==86`), 3087
  total troubleshooting trials.
