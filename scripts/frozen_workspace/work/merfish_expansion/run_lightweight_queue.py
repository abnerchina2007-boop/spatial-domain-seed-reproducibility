from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil


WORKSPACE = Path(__file__).resolve().parents[2]
ROOT = WORKSPACE / "outputs" / "PROJECT9_MERFISH_EXPANSION"
WORKER = Path(__file__).with_name("run_seed.py")
SECTIONS = [
    "MERFISH_Bregma_m0.04", "MERFISH_Bregma_m0.09", "MERFISH_Bregma_m0.14",
    "MERFISH_Bregma_m0.19", "MERFISH_Bregma_m0.24",
]
# Frozen smoke-test ordering: GraphST first, then the lower-footprint/faster
# BANKSY, then SpaGCN. This affects scheduling only.
METHODS = ["GraphST", "BANKSY", "SpaGCN"]
PROJECTED_PEAK_GIB = {"GraphST": 1.45, "BANKSY": 0.47, "SpaGCN": 0.86}
SMOKE_MAX_SECONDS = {"GraphST": 58.1, "BANKSY": 2.0, "SpaGCN": 33.8}
MIN_FREE_AFTER_LAUNCH_GIB = 6.0
CONTENTION_MULTIPLIER = 1.75


def completed(section: str, method: str, seed: int) -> bool:
    stem = ROOT / "predictions" / section / f"{method}__seed{seed}__primary"
    csv_path, json_path = stem.with_suffix(".csv"), stem.with_suffix(".json")
    if not csv_path.exists() or not json_path.exists():
        return False
    try:
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
        observed_k = metadata.get("n_clusters_observed")
        return metadata.get("status") == "PASS" and (method == "SpaGCN" or observed_k == 8)
    except (OSError, json.JSONDecodeError):
        return False


def active_seed_workers() -> list[dict]:
    workers = []
    for process in psutil.process_iter(["pid", "cmdline", "memory_info"]):
        try:
            command = process.info["cmdline"] or []
            joined = " ".join(command)
            if "merfish_expansion" not in joined or "run_seed.py" not in joined:
                continue
            method = next((name for name in ("STAGATE", "GraphST", "BANKSY", "SpaGCN") if f"--method {name}" in joined), "unknown")
            workers.append({"pid": process.info["pid"], "method": method,
                            "rss_gib": process.info["memory_info"].rss / (1024 ** 3)})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return workers


def allowed_total_workers(stagate_count: int) -> int:
    if stagate_count >= 2:
        return 3
    if stagate_count == 1:
        return 3
    return 4


def write_state(path: Path, queue, active, failures, event: str, extra=None) -> None:
    workers = active_seed_workers()
    payload = {
        "status": "RUNNING", "event": event, "remaining_lightweight": len(queue),
        "active_auxiliary": [list(value[0]) for value in active.values()],
        "active_all_workers": workers,
        "active_stagate": sum(worker["method"] == "STAGATE" for worker in workers),
        "free_memory_gib": psutil.virtual_memory().available / (1024 ** 3),
        "active_worker_rss_gib": sum(worker["rss_gib"] for worker in workers),
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "failures": failures,
        "threads_per_process": 4,
        "minimum_projected_free_memory_gib": MIN_FREE_AFTER_LAUNCH_GIB,
    }
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    queue = deque(
        (section, method, seed)
        for method in METHODS
        for seed in range(1, 21)
        for section in SECTIONS
        if not completed(section, method, seed)
    )
    log_dir = ROOT / "logs" / "lightweight_queue"
    log_dir.mkdir(parents=True, exist_ok=True)
    state_path = ROOT / "LIGHTWEIGHT_QUEUE_STATE.json"
    env = os.environ.copy()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[name] = "4"
    env["PROJECT9_TORCH_THREADS"] = "4"
    active: dict[subprocess.Popen, tuple[tuple[str, str, int], object, float]] = {}
    failures = []
    contention_stop = False

    while queue or active:
        for process in [item for item in active if item.poll() is not None]:
            task, handle, started = active.pop(process)
            handle.close()
            section, method, seed = task
            elapsed = time.time() - started
            if process.returncode != 0 or not completed(section, method, seed):
                failures.append({"section": section, "method": method, "seed": seed,
                                 "returncode": process.returncode})
            # If a lightweight checkpoint slows far beyond its frozen smoke
            # envelope while two STAGATE jobs are present, stop adding extra
            # jobs and hand all remaining checkpoints back to the original
            # resumable queue. Active jobs are never terminated.
            stagate_count = sum(worker["method"] == "STAGATE" for worker in active_seed_workers())
            if stagate_count >= 2 and elapsed > SMOKE_MAX_SECONDS[method] * CONTENTION_MULTIPLIER:
                contention_stop = True
            write_state(state_path, queue, active, failures, "finished", {
                "last_finished": list(task), "last_elapsed_seconds": elapsed,
                "contention_stop": contention_stop,
            })

        if contention_stop and not active:
            break

        workers = active_seed_workers()
        stagate_count = sum(worker["method"] == "STAGATE" for worker in workers)
        capacity = allowed_total_workers(stagate_count)
        free_gib = psutil.virtual_memory().available / (1024 ** 3)
        cpu_percent = psutil.cpu_percent(interval=0.2)
        if queue and len(workers) < capacity and cpu_percent < 85.0:
            section, method, seed = queue[0]
            if completed(section, method, seed):
                queue.popleft()
                continue
            if free_gib - PROJECTED_PEAK_GIB[method] >= MIN_FREE_AFTER_LAUNCH_GIB:
                queue.popleft()
                log_path = log_dir / f"{section}__{method}__seed{seed}.log"
                handle = log_path.open("w", encoding="utf-8")
                process = subprocess.Popen(
                    [sys.executable, str(WORKER), "--section", section, "--method", method,
                     "--seed", str(seed), "--epochs", "200"],
                    cwd=WORKSPACE, env=env, stdout=handle, stderr=subprocess.STDOUT, text=True,
                )
                active[process] = ((section, method, seed), handle, time.time())
                write_state(state_path, queue, active, failures, "launched", {
                    "last_launched": [section, method, seed],
                    "projected_free_memory_after_launch_gib": free_gib - PROJECTED_PEAK_GIB[method],
                    "contention_stop": contention_stop,
                })
        time.sleep(1)

    status = "PASS" if not failures and not contention_stop else ("REVERTED_TO_BASE_CONCURRENCY" if contention_stop and not failures else "FAIL")
    state_path.write_text(json.dumps({
        "status": status, "remaining_lightweight": len(queue), "failures": failures,
        "contention_stop": contention_stop, "threads_per_process": 4,
        "completed_lightweight_checkpoints": 300 - len(queue) - len(failures),
    }, indent=2), encoding="utf-8")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
