"""Empirical study of the cross-event collision rate: how often does a
zone-targeting event's terminal destruction cascade-delete a reheat coil
that a different, independently-drawn coil-targeting event in the same
blueprint also targets? Pure graph-level simulation, no OpenStudio/
EnergyPlus calls needed after the one-time zone->coil mapping is built.
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import openstudio
from hvac_benchmark.data.cache import FileCache
from hvac_benchmark.data.ontology import BrickOntology

from physics_pipeline.buildings import get_building
from physics_pipeline.pipeline import load_and_extract
from physics_pipeline.scope import generate_scoped_blueprint


def build_zone_to_coil_map(building):
    model = openstudio.osversion.VersionTranslator().loadModel(openstudio.path(str(building.osm_path))).get()
    zone_to_coil = {}
    for airloop in model.getAirLoopHVACs():
        demand = airloop.demandComponents()
        i = 0
        while i < len(demand):
            c = demand[i]
            coil = None
            if c.iddObjectType().valueName() == "OS_AirTerminal_SingleDuct_VAV_Reheat":
                coil_opt = c.to_AirTerminalSingleDuctVAVReheat().get().reheatCoil().to_CoilHeatingWater()
                coil = str(coil_opt.get().handle()) if coil_opt.is_initialized() else None
            elif c.iddObjectType().valueName() == "OS_AirTerminal_SingleDuct_ParallelPIU_Reheat":
                coil_opt = c.to_AirTerminalSingleDuctParallelPIUReheat().get().reheatCoil().to_CoilHeatingElectric()
                coil = None  # electric reheat coil has no plant connection -> not a Pump/Coil candidate at all
            if coil:
                j = i + 1
                while j < len(demand) and demand[j].iddObjectType().valueName() != "OS_ThermalZone":
                    j += 1
                if j < len(demand):
                    zone = demand[j].to_ThermalZone().get()
                    zone_to_coil[str(zone.handle())] = coil
            i += 1
    return zone_to_coil


def destroyed_terminals_for_event(tg, event, node_type_of) -> set[str]:
    """Zones whose terminal gets physically destroyed by this event,
    mirroring pipeline.py's actual rewire dispatch exactly."""
    destroyed_zones = set()
    if event.target != event.target:  # placeholder, unused
        pass
    target_type = node_type_of(event.target)
    if target_type != "HVAC_Zone":
        return destroyed_zones  # coil-targeting event: doesn't destroy any terminal itself

    destroyed_zones.add(event.target)  # every zone-targeting event replaces the target's terminal
    if event.corruption_type == "misattribution":
        (_s_true, _t), (s_wrong, _t2) = event.discordant_pairs
        if node_type_of(s_wrong) in ("VAV", "Terminal_Unit"):
            # reassign_terminal also destroys the donor zone's original terminal
            for s, t in tg.edges_by_relation["feeds"]:
                if s == s_wrong and node_type_of(t) == "HVAC_Zone":
                    destroyed_zones.add(t)
    return destroyed_zones


def simulate(building_id, severities, n_seeds, base_seed=91300001, verbose=False):
    building = get_building(building_id)
    zone_to_coil = build_zone_to_coil_map(building)
    cache = FileCache(str(Path(__file__).resolve().parents[2] / "data_cache"))
    ontology = BrickOntology.load(cache)
    _, tg, _ = load_and_extract(building)
    node_type_of = tg.node_type

    coil_to_zone = {c: z for z, c in zone_to_coil.items()}

    results = {}
    for severity in severities:
        n_blueprints = 0
        n_with_collision = 0
        n_events_total = 0
        n_coil_events_total = 0
        for seed in range(base_seed, base_seed + n_seeds):
            bp = generate_scoped_blueprint(tg, ontology, severity, seed)
            if not bp.events:
                continue
            n_blueprints += 1
            n_events_total += len(bp.events)

            destroyed_zones = set()
            coil_targets = []
            for e in bp.events:
                destroyed_zones |= destroyed_terminals_for_event(tg, e, node_type_of)
                if node_type_of(e.target) in ("Cooling_Coil", "Heating_Coil"):
                    coil_targets.append(e.target)

            n_coil_events_total += len(coil_targets)
            destroyed_coils = {zone_to_coil[z] for z in destroyed_zones if z in zone_to_coil}
            collided = any(c in destroyed_coils for c in coil_targets)
            if collided:
                n_with_collision += 1
                if verbose:
                    print(f"  COLLISION severity={severity} seed={seed}: "
                          f"destroyed_zones={len(destroyed_zones)} coil_targets={len(coil_targets)}")

        results[severity] = (n_blueprints, n_with_collision, n_events_total, n_coil_events_total)
    return results


if __name__ == "__main__":
    for bid in ["sys07_vav_reheat", "sys08_vav_parallel_piu"]:
        print(f"=== {bid} ===")
        results = simulate(bid, severities=range(1, 11), n_seeds=200, verbose=False)
        for sev, (nbp, ncoll, nev, ncoil) in results.items():
            rate = ncoll / nbp if nbp else float("nan")
            print(f"  severity={sev}: blueprints={nbp}, avg_events/bp={nev/nbp if nbp else 0:.2f}, "
                  f"avg_coil_events/bp={ncoil/nbp if nbp else 0:.2f}, collision_rate={rate:.1%}")
        print()
