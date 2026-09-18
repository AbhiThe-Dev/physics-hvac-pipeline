import sys
sys.path.insert(0, "/Users/abhinavakula/BuildingMapping/src")
sys.path.insert(0, "src")

import openstudio
from physics_pipeline.extract import extract_topology, to_hvac_benchmark_graph
from hvac_benchmark.data.ontology import BrickOntology
from hvac_benchmark.data.cache import FileCache
from hvac_benchmark.experiment.candidates import generate_feeds_candidates, candidate_coverage

cache = FileCache("/Users/abhinavakula/BuildingMapping/data_cache")
ontology = BrickOntology.load(cache)

for fname, bid in [("baseline_sys08.osm", "sys08_vav_parallel_piu"), ("baseline_sys07.osm", "sys07_vav_reheat")]:
    path = f"vendor/OpenStudio-resources/model/simulationtests/{fname}"
    model = openstudio.osversion.VersionTranslator().loadModel(openstudio.path(path)).get()
    building_id, config_type, nx_graph, edges_by_relation, extraction = extract_topology(model, bid, "synthetic_physics")
    tg = to_hvac_benchmark_graph(building_id, config_type, nx_graph, edges_by_relation)

    print(f"=== {bid} ===")
    print("nodes:", tg.nx_graph.number_of_nodes())
    print("feeds edges:", len(tg.edges_by_relation["feeds"]))
    print("hasPart edges:", len(tg.edges_by_relation["hasPart"]))
    type_counts = {}
    for n in tg.nodes():
        t = tg.node_type(n)
        type_counts[t] = type_counts.get(t, 0) + 1
    print("node type counts:", type_counts)

    candidates = generate_feeds_candidates(tg, ontology)
    coverage = candidate_coverage(candidates, tg.edges_by_relation["feeds"])
    print(f"candidate coverage: {coverage.n_covered}/{coverage.n_true_edges} (missed: {coverage.n_missed})")
    if coverage.missed_edges:
        print("  missed:", coverage.missed_edges)
    locs = {tg.node_location(n) for n in tg.nodes()}
    print("distinct locations seen:", locs)
    print()
