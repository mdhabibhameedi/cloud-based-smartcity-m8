"""Run the Newvale capacity and recovery checks without connecting to AWS."""

import csv
import hashlib
import json
from collections import deque
from math import ceil
from pathlib import Path
from runpy import run_path
from unittest.mock import patch

import boto3
from botocore.exceptions import ClientError


ROOT = Path(__file__).resolve().parents[1]
ARRIVALS = (1,) * 6 + (6,) * 8 + (1,) * 6
QUEUE_TARGET = 2
MAX_WORKERS = 6
SCALE_DOWN_IDLE_TICKS = 3


def capacity_test(arrivals, elastic):
    """Model FIFO jobs that each occupy one worker for one tick."""
    queue = deque()
    delays = []
    worker_loads = [0] * MAX_WORKERS
    workers = 1
    next_worker = 0
    idle_ticks = 0
    trace = []
    tick = 0
    while tick < len(arrivals) or queue or (elastic and workers > 1):
        incoming = arrivals[tick] if tick < len(arrivals) else 0
        queue.extend([tick] * incoming)
        pending = len(queue)
        if elastic:
            if pending > workers * QUEUE_TARGET:
                workers = min(MAX_WORKERS, ceil(pending / QUEUE_TARGET))
            if pending == 0:
                idle_ticks += 1
                if idle_ticks >= SCALE_DOWN_IDLE_TICKS:
                    workers = 1
            else:
                idle_ticks = 0

        served = min(workers, pending)
        for _ in range(served):
            worker = next_worker % workers
            worker_loads[worker] += 1
            next_worker = worker + 1
            delays.append(tick - queue.popleft() + 1)
        trace.append({
            "tick": tick, "arrivals": incoming, "active_workers": workers,
            "queued_before_service": pending, "completed": served,
            "queued_after_service": len(queue),
        })
        tick += 1

    peak_workers = max(row["active_workers"] for row in trace)
    return {
        "arrivals": sum(arrivals),
        "completed": len(delays),
        "peak_workers": peak_workers,
        "final_workers": workers,
        "peak_backlog_after_service": max(row["queued_after_service"] for row in trace),
        "p95_completion_ticks": sorted(delays)[ceil(.95 * len(delays)) - 1],
        "worker_service_slots": sum(row["active_workers"] for row in trace),
        "jobs_by_worker": worker_loads[:peak_workers],
    }, trace


class InMemoryS3:
    """Model the conditional PUT operations used by the deployed handler."""

    def __init__(self):
        self.objects = {}
        self.interrupt_processed_write = True

    def put_object(self, *, Bucket, Key, Body, ContentType, IfNoneMatch):
        if Bucket != "newvale-smartcity-m8" or IfNoneMatch != "*" or ContentType != "application/json":
            raise AssertionError("Unexpected S3 PUT configuration")
        if self.interrupt_processed_write and Key.startswith("processed-data/"):
            self.interrupt_processed_write = False
            raise ClientError({"Error": {"Code": "InternalError"}}, "PutObject")
        if Key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[Key] = json.loads(Body)


def recovery_test():
    with (ROOT / "data/raw/traffic_synthetic.csv").open(encoding="utf-8-sig", newline="") as source:
        row = next(csv.DictReader(source))
    event = {
        "sensor_type": "traffic",
        "timestamp": row["timestamp_utc"],
        "record_id": row["record_id"],
        "zone_id": row["zone_id"],
        "vehicle_count": int(row["vehicle_count"]),
        "is_synthetic": True,
    }
    expected_id = hashlib.sha256(
        json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    raw_key = f"raw-sensor-data/traffic/{expected_id}.json"
    processed_key = f"processed-data/traffic/{expected_id}.json"
    storage = InMemoryS3()
    handler_path = ROOT / "deployment/lambda/lambda_function.py"
    with patch.object(boto3, "client", return_value=storage):
        first_worker = run_path(str(handler_path))["lambda_handler"]
        retry_worker = run_path(str(handler_path))["lambda_handler"]
    try:
        first_worker(event, None)
    except ClientError as error:
        if error.response["Error"]["Code"] != "InternalError":
            raise
    else:
        raise AssertionError("Injected error should propagate")
    keys_after_failure = list(storage.objects)
    assert keys_after_failure == [raw_key]

    retry = retry_worker(event, None)
    replay = retry_worker(event, None)
    retry_body = json.loads(retry["body"])
    replay_body = json.loads(replay["body"])
    assert retry["statusCode"] == replay["statusCode"] == 200
    assert retry_body["record_id"] == replay_body["record_id"] == expected_id
    assert not retry_body["duplicate"] and replay_body["duplicate"]
    assert set(storage.objects) == {raw_key, processed_key}
    assert storage.objects[raw_key] == storage.objects[processed_key]["data"] == event

    try:
        retry_worker({**event, "vehicle_count": -1}, None)
    except ValueError as error:
        assert str(error) == "Invalid vehicle_count"
    else:
        raise AssertionError("Invalid traffic count should fail")
    assert set(storage.objects) == {raw_key, processed_key}
    return {
        "objects_after_interruption": len(keys_after_failure),
        "objects_after_retry_and_replay": len(storage.objects),
        "missing_objects_after_retry": 0,
        "retry_marked_duplicate": retry_body["duplicate"],
        "identical_replay_marked_duplicate": replay_body["duplicate"],
        "invalid_record_rejected_without_new_objects": True,
    }


def main():
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    results = {}
    trace = []
    for workload, arrivals in [("steady", (1,) * len(ARRIVALS)), ("burst", ARRIVALS)]:
        for policy, elastic in [("fixed", False), ("elastic", True)]:
            summary, rows = capacity_test(arrivals, elastic)
            assert summary["completed"] == summary["arrivals"]
            results[f"{workload}_{policy}"] = summary
            trace.extend({"workload": workload, "policy": policy, **row} for row in rows)
    assert results["steady_fixed"]["p95_completion_ticks"] == results["steady_elastic"]["p95_completion_ticks"]
    assert results["burst_elastic"]["p95_completion_ticks"] < results["burst_fixed"]["p95_completion_ticks"]
    assert results["burst_elastic"]["peak_workers"] > results["burst_elastic"]["final_workers"] == 1
    output = {
        "scope": "Local deterministic simulation and offline handler test with in-memory S3",
        "capacity_model": {
            "arrivals_per_tick": {"steady": [1] * len(ARRIVALS), "burst": list(ARRIVALS)},
            "initial_workers": 1, "maximum_workers": MAX_WORKERS,
            "target_pending_jobs_per_worker": QUEUE_TARGET,
            "idle_ticks_to_scale_down": SCALE_DOWN_IDLE_TICKS,
            "jobs_per_worker_per_tick": 1,
            "limitations": "Workers start immediately. Tick durations and S3 behaviour are modelled.",
        },
        "capacity": results,
        "recovery": recovery_test(),
    }
    (results_dir / "scaling_recovery_summary.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    with (results_dir / "scaling_recovery_trace.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(trace[0]))
        writer.writeheader()
        writer.writerows(trace)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
