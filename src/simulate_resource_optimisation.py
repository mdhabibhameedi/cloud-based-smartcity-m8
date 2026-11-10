import json
import time
from collections import OrderedDict
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
RESULTS = BASE / "results"
DATA = BASE / "data" / "raw"

RESULTS.mkdir(exist_ok=True)

# Load the existing Newvale traffic dataset.
traffic = pd.read_csv(DATA / "traffic_synthetic.csv")

# Create reproducible dashboard-style queries.
zones = sorted(traffic["zone_id"].unique())

requests = [
    zones[i % len(zones)]
    for i in range(200)
]


def process_request(zone):
    # Simulate a processing cost.
    time.sleep(0.002)

    data = traffic.loc[
        traffic["zone_id"] == zone,
        "vehicle_count"
    ]

    return float(data.mean())


def without_cache():
    start = time.perf_counter()

    for zone in requests:
        process_request(zone)

    return time.perf_counter() - start


def with_cache():
    cache = OrderedDict()
    hits = 0
    misses = 0

    start = time.perf_counter()

    for zone in requests:
        if zone in cache:
            hits += 1
            cache.move_to_end(zone)
        else:
            misses += 1
            cache[zone] = process_request(zone)

            if len(cache) > 4:
                cache.popitem(last=False)

    return time.perf_counter() - start, hits, misses


def simulate_load_balancing(worker_count):
    worker_loads = [0] * worker_count

    for i, _ in enumerate(requests):
        worker_loads[i % worker_count] += 1

    return worker_loads


uncached_time = without_cache()
cached_time, hits, misses = with_cache()

single_worker = simulate_load_balancing(1)
two_workers = simulate_load_balancing(2)

summary = {
    "project": "Newvale Smart City",
    "stage": "Resource Optimisation",
    "request_count": len(requests),
    "cache": {
        "uncached_seconds": round(uncached_time, 4),
        "cached_seconds": round(cached_time, 4),
        "cache_hits": hits,
        "cache_misses": misses,
        "cache_hit_percentage": round(
            hits / len(requests) * 100, 2
        )
    },
    "load_balancing": {
        "single_worker": single_worker,
        "two_workers": two_workers,
        "strategy": "Round-robin request distribution"
    },
    "notes": [
        "Local simulation, not deployed AWS load balancing",
        "Processing delay includes simulated work",
        "Worker distribution does not establish throughput gains",
        "Caching results apply to this controlled workload"
    ]
}

with open(
    RESULTS / "resource_optimisation_summary.json",
    "w",
    encoding="utf-8"
) as f:
    json.dump(summary, f, indent=2)

print("\nSTAGE 10 - RESOURCE OPTIMISATION")
print("SIMULATION COMPLETED")
print(json.dumps(summary, indent=2))