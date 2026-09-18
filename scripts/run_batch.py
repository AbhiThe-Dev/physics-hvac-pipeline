"""Minimal-scope end-to-end run: 2 topologies x 1 climate zone, 3 corruption
severities x 2 seeded variants each, confirmed with the user based on
Step 0's storage/runtime numbers before running."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from hvac_benchmark.config import DEFAULT_CONFIG
from hvac_benchmark.data.cache import FileCache
from hvac_benchmark.data.ontology import BrickOntology

from physics_pipeline.buildings import BASE_BUILDINGS, CLIMATE_LABEL, WEATHER_FILE
from physics_pipeline.pipeline import run_building

OUT_DIR = Path(__file__).resolve().parents[1] / "results_physics"
RUN_DIR = Path(__file__).resolve().parents[1] / "vendor" / "batch_runs"

SEVERITIES = (1, 2, 3)
N_SEEDS_PER_SEVERITY = 2
BASE_CORRUPTION_SEED = 91300001


def main():
    cache = FileCache(str(Path(__file__).resolve().parents[2] / "data_cache"))
    ontology = BrickOntology.load(cache)

    print(f"Climate: {CLIMATE_LABEL} ({WEATHER_FILE.name})")
    print(f"Buildings: {[b.building_id for b in BASE_BUILDINGS]}")
    print(f"Severities: {SEVERITIES}, seeds/severity: {N_SEEDS_PER_SEVERITY}")
    print()

    bundles = []
    t0 = time.time()
    for building in BASE_BUILDINGS:
        print(f"=== {building.building_id} ===")
        bt0 = time.time()
        bundle = run_building(
            building, DEFAULT_CONFIG, ontology, RUN_DIR / building.building_id,
            SEVERITIES, N_SEEDS_PER_SEVERITY, BASE_CORRUPTION_SEED,
        )
        bt1 = time.time()
        print(f"  nodes={bundle.n_nodes} feeds_edges={bundle.n_feeds_edges} "
              f"node_types={bundle.node_type_counts}")
        print(f"  blueprints generated: {len(bundle.blueprints)}")
        print(f"  trial results: {len(bundle.trial_results)}")
        print(f"  wall time: {bt1 - bt0:.1f}s")
        bundles.append(bundle)
        print()

    t1 = time.time()
    print(f"Total wall time: {t1 - t0:.1f}s")

    import pickle
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "bundles.pkl", "wb") as f:
        pickle.dump(bundles, f)
    print(f"Saved raw bundles to {OUT_DIR / 'bundles.pkl'}")


if __name__ == "__main__":
    main()
