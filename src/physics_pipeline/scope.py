"""Restricts corruption generation to edge types the rewiring mechanism in
`rewire.py` actually supports, without touching `hvac_benchmark`'s
`generate_blueprint` (which draws from the full candidate/edge universe by
design, and is not ours to modify).

First attempt (kept here as a documented dead end, not repeated): building
a *restricted TopologyGraph* -- dropping out-of-scope nodes/edges before
calling `generate_blueprint` -- doesn't work, because `generate_feeds_
candidates` derives its candidate pool from node-type ancestry via the
ontology, completely independent of which edges exist. Stripping the true
AHU<->Terminal_Unit edges out of the restricted graph (to keep them from
being picked for removal/misattribution) didn't remove them from the
*candidate* pool -- it just made every one of them look "false" (since
`false_candidate_pairs = candidates - true_edges`), turning a
tier that should never be corruptable (a single AHU truly feeds every one
of its terminals) into a large pool of eligible *fabrication* targets.
Confirmed empirically: the first version of this file produced fabrication
events with a VAV target again, worse than the node-type-only filter it
replaced.

What actually works: let `generate_blueprint` run entirely unmodified on
the full, real graph (so its candidate/true-edge accounting stays
internally consistent), then filter its *output events* down to the
in-scope ones and reconstruct `claimed_edges` to match -- mirroring
`generate_blueprint`'s own per-event effect (removal discards a pair,
fabrication adds one, misattribution does both) for exactly the kept
subset. This is the same "may return fewer events than requested severity"
tolerance the unmodified function already documents for its own internal
skips, just applied one level up.
"""

from __future__ import annotations

from hvac_benchmark.data.ontology import BrickOntology
from hvac_benchmark.experiment.blueprint import Blueprint, CorruptionEvent, generate_blueprint
from hvac_benchmark.graph.networkx_build import TopologyGraph

# Edge types `rewire.py` can actually construct/remove today:
#  - a zone-targeted edge whose source is an AHU or a terminal unit
#    (reassign_terminal / remove_zone_service / add_extra_service /
#    set_ahu_direct_service)
#  - a coil-targeted edge whose source is a pump (remove_coil_service /
#    reassign_coil)
# AHU<->Terminal_Unit edges are NOT in scope -- there's only ever one AHU
# per building here, so reassigning "which AHU feeds this terminal" isn't
# a meaningful rewire.
IN_SCOPE_ZONE_SOURCE_TYPES: frozenset[str] = frozenset({"AHU", "VAV", "Terminal_Unit"})
IN_SCOPE_COIL_TARGET_TYPES: frozenset[str] = frozenset({"Cooling_Coil", "Heating_Coil"})
IN_SCOPE_COIL_SOURCE_TYPES: frozenset[str] = frozenset({"Pump"})

# Kept for backward compatibility with anything importing the old name.
IN_SCOPE_SOURCE_TYPES = IN_SCOPE_ZONE_SOURCE_TYPES


def _event_in_scope(tg: TopologyGraph, event: CorruptionEvent) -> bool:
    target_type = tg.node_type(event.target)
    if target_type == "HVAC_Zone":
        return all(tg.node_type(s) in IN_SCOPE_ZONE_SOURCE_TYPES for s, _t in event.discordant_pairs)
    if target_type in IN_SCOPE_COIL_TARGET_TYPES:
        return all(tg.node_type(s) in IN_SCOPE_COIL_SOURCE_TYPES for s, _t in event.discordant_pairs)
    return False


def _apply_event(claimed: set[tuple[str, str]], event: CorruptionEvent) -> None:
    """Mirrors generate_blueprint's own per-event effect on `claimed`
    exactly (see hvac_benchmark/experiment/blueprint.py): removal discards
    the true pair, fabrication adds the false pair, misattribution does
    both (discard the true pair, add the wrong one)."""
    if event.corruption_type == "removal":
        claimed.discard(event.discordant_pairs[0])
    elif event.corruption_type == "fabrication":
        claimed.add(event.discordant_pairs[0])
    elif event.corruption_type == "misattribution":
        claimed.discard(event.discordant_pairs[0])
        claimed.add(event.discordant_pairs[1])


def _rebuild_blueprint(tg: TopologyGraph, blueprint: Blueprint, kept_events: tuple[CorruptionEvent, ...]) -> Blueprint:
    claimed = set(tg.edges_by_relation["feeds"])
    for event in kept_events:
        _apply_event(claimed, event)
    return Blueprint(
        building_id=blueprint.building_id,
        severity=blueprint.severity,
        corruption_seed=blueprint.corruption_seed,
        claimed_edges=frozenset(claimed),
        events=kept_events,
    )


def _zones_destroyed_by_event(tg: TopologyGraph, event: CorruptionEvent) -> set[str]:
    """Zones whose terminal is physically destroyed by this event,
    mirroring `pipeline.py`'s actual rewire dispatch: every zone-targeting
    event replaces the target's terminal; misattribution additionally
    destroys the donor zone's terminal (via `reassign_terminal`, which
    moves that terminal away)."""
    if tg.node_type(event.target) != "HVAC_Zone":
        return set()
    destroyed = {event.target}
    if event.corruption_type == "misattribution":
        (_s_true, _t), (s_wrong, _t2) = event.discordant_pairs
        if tg.node_type(s_wrong) in IN_SCOPE_ZONE_SOURCE_TYPES - {"AHU"}:
            for s, t in tg.edges_by_relation["feeds"]:
                if s == s_wrong and tg.node_type(t) == "HVAC_Zone":
                    destroyed.add(t)
    return destroyed


def filter_collision_events(
    tg: TopologyGraph,
    blueprint: Blueprint,
    zone_to_coil: dict[str, str],
) -> Blueprint:
    """Drops any coil-targeting event whose target coil would be
    cascade-deleted as a side effect of physically applying one of the
    blueprint's OTHER events (a zone-targeting event destroying that
    zone's terminal, which owns the coil) -- found empirically while
    validating the pump/coil addition: `generate_blueprint`'s own
    duplicate-target guard (`used_targets`) can't see this, because the
    two events have different targets (a zone and a coil) that happen to
    share an underlying physical object the graph doesn't represent as
    connected at all. `zone_to_coil` is built once per building via
    `rewire.build_zone_to_coil_map` -- empty on buildings with no hydronic
    reheat coils (e.g. baseline_sys08), where this is always a no-op."""
    if not zone_to_coil or len(blueprint.events) < 2:
        return blueprint

    destroyed_zones: set[str] = set()
    for event in blueprint.events:
        destroyed_zones |= _zones_destroyed_by_event(tg, event)
    destroyed_coils = {zone_to_coil[z] for z in destroyed_zones if z in zone_to_coil}
    if not destroyed_coils:
        return blueprint

    kept_events = tuple(
        e for e in blueprint.events
        if not (tg.node_type(e.target) in IN_SCOPE_COIL_TARGET_TYPES and e.target in destroyed_coils)
    )
    if len(kept_events) == len(blueprint.events):
        return blueprint
    return _rebuild_blueprint(tg, blueprint, kept_events)


def generate_scoped_blueprint(
    tg: TopologyGraph,
    ontology: BrickOntology,
    severity: int,
    corruption_seed: int,
    zone_to_coil: dict[str, str] | None = None,
) -> Blueprint:
    """`generate_blueprint`, called completely unmodified on the full
    graph, with its output events filtered down to the ones `rewire.py`
    can physically construct/remove and `claimed_edges` reconstructed to
    match exactly that kept subset -- so an excluded event is never
    misrepresented as either a corruption OR silently left as some
    half-applied claim. If `zone_to_coil` is given (see
    `rewire.build_zone_to_coil_map`), also drops any coil-targeting event
    that would collide with another event's cascade-deleted coil (see
    `filter_collision_events`) -- optional and defaults to off so existing
    callers that only care about edge-type scoping are unaffected."""
    blueprint = generate_blueprint(tg, ontology, severity, corruption_seed)
    kept_events = tuple(e for e in blueprint.events if _event_in_scope(tg, e))
    if len(kept_events) != len(blueprint.events):
        blueprint = _rebuild_blueprint(tg, blueprint, kept_events)

    if zone_to_coil:
        blueprint = filter_collision_events(tg, blueprint, zone_to_coil)

    return blueprint
