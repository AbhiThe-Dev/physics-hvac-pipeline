"""Extraction pipeline: walk an OpenStudio model's HVAC system and zone/space
structure via the Python API and produce a `TopologyGraph` in the exact
format `hvac_benchmark` already uses (node `brick_type`/`location` attrs,
`edges_by_relation` sets of (source, target) pairs keyed by relation), so it
can be handed to the existing discovery/troubleshooting experiment code
unmodified.

Only "feeds" edges that fall under a compatibility tier already defined in
`hvac_benchmark.experiment.candidates.FEEDS_COMPATIBILITY_TIERS` are
extracted (AHU->Terminal_Unit, Terminal_Unit->Location/Zone, Pump->Coil).
A condenser-water loop's pump/cooling-tower/chiller chain, for example, has
no covering tier in the current candidate rules and is out of scope here --
the same "never silently absorb an uncovered true edge" philosophy the
existing benchmark documents, just applied at extraction time instead of
after the fact.
"""

from __future__ import annotations

import networkx as nx
import openstudio

# IDD type names of terminal units this extraction recognizes on an
# AirLoopHVAC's demand side, immediately preceding the ThermalZone they serve
# in `demandComponents()` order (splitter -> node -> terminal -> node -> zone
# -> node -> mixer, verified in Step 0 against baseline_sys07/sys08).
_TERMINAL_IDD_TYPES: dict[str, str] = {
    "OS_AirTerminal_SingleDuct_ParallelPIU_Reheat": "VAV",
    "OS_AirTerminal_SingleDuct_VAV_Reheat": "VAV",
    "OS_AirTerminal_SingleDuct_VAV_NoReheat": "VAV",
    "OS_AirTerminal_SingleDuct_ConstantVolume_Reheat": "Terminal_Unit",
    "OS_AirTerminal_SingleDuct_ConstantVolume_NoReheat": "Terminal_Unit",
    "OS_AirTerminal_SingleDuct_SeriesPIU_Reheat": "VAV",
}

_COIL_OR_FAN_MARKERS = ("Coil", "Fan")


def _brick_equipment_type(idd_type_name: str) -> str:
    """Map an OpenStudio IDD type name to a real Brick ontology class local
    name (never OpenStudio's own naming, which is not a Brick class and
    would silently fail every ancestor lookup in candidates.py -- verified
    against the cached Brick v1.3.0 ontology's `known_classes()`)."""
    if "Coil" in idd_type_name:
        return "Cooling_Coil" if "Cooling" in idd_type_name else "Heating_Coil"
    if "Fan" in idd_type_name:
        return "Fan"
    if "Pump" in idd_type_name:
        return "Pump"
    return idd_type_name.replace("OS_", "")


def _handle_str(obj) -> str:
    return str(obj.handle())


def _obj_name(obj) -> str | None:
    return obj.name().get() if obj.name().is_initialized() else None


def _zone_location(zone: "openstudio.model.ThermalZone") -> str | None:
    """Geometry-derived location: the building story of the zone's (first)
    space, falling back to None if unassigned -- never guessed."""
    spaces = zone.spaces()
    if not spaces:
        return None
    space = spaces[0]
    story = space.buildingStory()
    return story.get().name().get() if story.is_initialized() else None


# ZoneHVAC "packaged terminal" unit types this extraction recognizes -- no
# AirLoopHVAC at all, the whole air-side package (fan + coils) sits directly
# on the zone. Confirmed via direct model inspection (not assumed from the
# system name) that PTAC (baseline_sys01) and PTHP (baseline_sys02) are
# materially different cases, not two instances of the same thing: EVERY
# PTAC unit's heating coil is Coil:Heating:Water on a real, shared hot-water
# PlantLoop with an actual pump (so pump<->coil corruption is meaningful
# here, the same as a VAV-reheat building), while EVERY PTHP unit is fully
# Coil:Heating:DX:SingleSpeed/Coil:Cooling:DX:SingleSpeed with zero
# PlantLoops and zero pumps in the whole model (no pump<->coil edge is even
# possible here, structurally, the same way sys06 has none -- but confirmed
# independently for this different object type, not inherited from sys06's
# proof).
_PACKAGED_ZONE_HVAC_GETTERS: tuple[str, ...] = (
    "getZoneHVACPackagedTerminalAirConditioners",
    "getZoneHVACPackagedTerminalHeatPumps",
)


class TopologyExtraction:
    """Extraction result plus the raw geometry facts used to derive
    `location`, kept alongside the `TopologyGraph` for reporting/inspection
    (not consumed by the existing benchmark code, which only reads
    `TopologyGraph`)."""

    def __init__(self):
        self.node_geometry: dict[str, dict] = {}


def extract_topology(model: "openstudio.model.Model", building_id: str, config_type: str):
    """Returns a `hvac_benchmark.graph.networkx_build.TopologyGraph`-shaped
    object (constructed directly here to avoid importing the main benchmark
    package as a hard dependency of this module; callers that need the exact
    class for isinstance checks should use `to_hvac_benchmark_graph`)."""
    nx_graph = nx.MultiDiGraph()
    edges_by_relation: dict[str, set[tuple[str, str]]] = {"feeds": set(), "hasPoint": set(), "hasPart": set()}
    geometry: dict[str, dict] = {}

    def add_node(obj, brick_type: str, location: str | None = None, **geom) -> str:
        nid = _handle_str(obj)
        if nid not in nx_graph:
            nx_graph.add_node(nid)
        nx_graph.nodes[nid]["brick_type"] = brick_type
        nx_graph.nodes[nid]["brick_types"] = [brick_type]
        nx_graph.nodes[nid]["location"] = location
        nx_graph.nodes[nid]["name"] = _obj_name(obj)
        if geom:
            geometry[nid] = geom
        return nid

    def add_edge(s: str, t: str, relation: str) -> None:
        nx_graph.add_edge(s, t, relation=relation)
        edges_by_relation[relation].add((s, t))

    def add_zone_node(zone: "openstudio.model.ThermalZone") -> str:
        story = _zone_location(zone)
        space = zone.spaces()[0] if zone.spaces() else None
        return add_node(
            zone,
            "HVAC_Zone",
            location=story,
            floor_area_m2=round(space.floorArea(), 1) if space else None,
            x_origin=space.xOrigin() if space else None,
            y_origin=space.yOrigin() if space else None,
            building_story=story,
        )

    # --- air loops: AHU -> [Terminal_Unit] -> Zone, AHU hasPart coils/fans ---
    for airloop in model.getAirLoopHVACs():
        ahu_id = add_node(airloop, "AHU")

        for c in airloop.supplyComponents():
            t = c.iddObjectType().valueName()
            if any(marker in t for marker in _COIL_OR_FAN_MARKERS):
                part_id = add_node(c, _brick_equipment_type(t))
                add_edge(part_id, ahu_id, "hasPart")

        demand = airloop.demandComponents()
        i = 0
        while i < len(demand):
            c = demand[i]
            t = c.iddObjectType().valueName()
            if t in _TERMINAL_IDD_TYPES:
                term_id = add_node(c, _TERMINAL_IDD_TYPES[t])
                add_edge(ahu_id, term_id, "feeds")
                j = i + 1
                while j < len(demand) and demand[j].iddObjectType().valueName() != "OS_ThermalZone":
                    j += 1
                if j < len(demand):
                    zone = demand[j].to_ThermalZone().get()
                    zone_id = add_zone_node(zone)
                    add_edge(term_id, zone_id, "feeds")
                    # the terminal physically sits with the zone it serves
                    nx_graph.nodes[term_id]["location"] = nx_graph.nodes[zone_id]["location"]
                # A VAV:Reheat terminal owns its reheat coil. Emitted as
                # `coil -hasPart-> terminal` (part -> whole), the same
                # direction already used for AHU coils/fans -> AHU and
                # PTAC/PTHP coils -> unit above. Scoped to
                # AirTerminal:SingleDuct:VAV:Reheat only; without this edge
                # the coil's only relation is `pump -feeds-> coil`, so
                # sibling coils under one pump are structurally identical.
                if t == "OS_AirTerminal_SingleDuct_VAV_Reheat":
                    reheat = c.to_AirTerminalSingleDuctVAVReheat().get().reheatCoil()
                    coil_id = add_node(reheat, _brick_equipment_type(reheat.iddObjectType().valueName()))
                    add_edge(coil_id, term_id, "hasPart")
            i += 1

    # --- zone-level packaged terminal units (PTAC/PTHP): no AirLoopHVAC at
    # all, so this is a separate walk, not a special case of the one above.
    # Each unit is its own self-contained Terminal_Unit -> Zone feeds edge,
    # with its own embedded coils/fan as hasPart -- structurally the same
    # role a VAV terminal plays, just never routed through a central AHU.
    for getter_name in _PACKAGED_ZONE_HVAC_GETTERS:
        for unit in getattr(model, getter_name)():
            if not unit.thermalZone().is_initialized():
                continue
            zone = unit.thermalZone().get()
            zone_id = add_zone_node(zone)
            unit_id = add_node(unit, "Terminal_Unit", location=nx_graph.nodes[zone_id]["location"])
            add_edge(unit_id, zone_id, "feeds")

            cooling_coil = unit.coolingCoil()
            heating_coil = unit.heatingCoil()
            fan = unit.supplyAirFan()
            for component in (cooling_coil, heating_coil, fan):
                t = component.iddObjectType().valueName()
                part_id = add_node(component, _brick_equipment_type(t))
                add_edge(part_id, unit_id, "hasPart")

    # --- plant loops: Pump -> Coil, restricted to tiers candidates.py covers ---
    for plant in model.getPlantLoops():
        pumps = [c for c in plant.supplyComponents() if "Pump" in c.iddObjectType().valueName()]
        coils = [c for c in plant.demandComponents() if "Coil" in c.iddObjectType().valueName()]
        if not pumps or not coils:
            continue
        pump_id = add_node(pumps[0], "Pump")
        for coil in coils:
            coil_id = _handle_str(coil)
            if coil_id not in nx_graph:
                # coil wasn't already added as an AHU hasPart (shouldn't
                # normally happen for these two test buildings, but stay
                # honest rather than silently dropping it)
                t = coil.iddObjectType().valueName()
                add_node(coil, _brick_equipment_type(t))
            add_edge(pump_id, coil_id, "feeds")

    extraction = TopologyExtraction()
    extraction.node_geometry = geometry
    return building_id, config_type, nx_graph, edges_by_relation, extraction


def to_hvac_benchmark_graph(building_id: str, config_type: str, nx_graph: nx.MultiDiGraph,
                             edges_by_relation: dict[str, set[tuple[str, str]]]):
    """Wrap the extracted structure in the actual `TopologyGraph` dataclass
    from `hvac_benchmark`, so downstream code (candidates, blueprint,
    troubleshooting runner) consumes it completely unmodified."""
    from hvac_benchmark.graph.networkx_build import TopologyGraph

    return TopologyGraph(
        building_id=building_id,
        config_type=config_type,
        nx_graph=nx_graph,
        edges_by_relation=edges_by_relation,
    )
