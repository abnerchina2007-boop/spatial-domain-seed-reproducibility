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
METHODS = ["STAGATE", "GraphST", "SpaGCN", "BANKSY"]
MAX_CONCURRENT = 2
MIN_FREE_GIB_FOR_SECOND_SLOT = 6.0
SYSTEM_FAILURE_CODES = {1073807364, 3221226091, 3221225794}


def completed(section: str, method: str, seed: int) -> bool:
    stem = ROOT / "predictions" / section / f"{method}__seed{seed}__primary"
    csv_path = stem.with_suffix(".csv")
    json_path = stem.with_suffix(".json")
    if not csv_path.exists() or not json_path.exists():
        return False
    try:
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
        observed_k = metadata.get("n_clusters_observed")
        return metadata.get("status") == "PASS" and (method == "SpaGCN" or observed_k == 8)
    except (OSError, json.JSONDecodeError):
        return False


def main() -> None:
    queue = deque(
        (section, method, seed)
        for method in METHODS
        for seed in range(1, 21)
        for section in SECTIONS
        if not completed(section, method, seed)
    )
    session_id = time.strftime("recovery_%Y%m%d_%H%M%S")
    run_logs = ROOT / "logs" / "run_queue" / session_id
    run_logs.mkdir(parents=True, exist_ok=True)
    state_path = ROOT / "RUN_QUEUE_STATE.json"
    env = os.environ.copy()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[name] = "4"
    env["PROJECT9_TORCH_THREADS"] = "4"
    active: dict[subprocess.Popen, tuple[tuple[str, str, int], object, float]] = {}
    failures = []
    stop_launching = False

    while queue or active:
        finished = [process for process in active if process.poll() is not None]
        for process in finished:
            task, handle, started = active.pop(process)
            handle.close()
            section, method, seed = task
            if process.returncode != 0 or not completed(section, method, seed):
                failures.append({"section": section, "method": method, "seed": seed,
                                 "returncode": process.returncode})
                if process.returncode in SYSTEM_FAILURE_CODES:
                    stop_launching = True
            state_path.write_text(json.dumps({
                "status": "STOPPING_TECHNICAL_FAILURE" if stop_launching else (
                    "RUNNING" if queue or active else "FINISHED"),
                "remaining": len(queue), "active": [list(x[0]) for x in active.values()],
                "failures": failures, "last_finished": list(task),
                "last_elapsed_seconds": time.time() - started,
                "log_session": session_id,
            }, indent=2), encoding="utf-8")

        if stop_launching and not active:
            break

        while queue and not stop_launching and len(active) < MAX_CONCURRENT:
            available_gib = psutil.virtual_memory().available / (1024 ** 3)
            # Below the safe envelope, do not fill the second slot. If no run is
            # active, one run is still launched so the queue remains resumable.
            if active and available_gib < MIN_FREE_GIB_FOR_SECOND_SLOT:
                break
            section, method, seed = queue.popleft()
            log_path = run_logs / f"{section}__{method}__seed{seed}.log"
            handle = log_path.open("w", encoding="utf-8")
            process = subprocess.Popen(
                [sys.executable, str(WORKER), "--section", section, "--method", method,
                 "--seed", str(seed), "--epochs", "200"],
                cwd=WORKSPACE, env=env, stdout=handle, stderr=subprocess.STDOUT, text=True,
            )
            active[process] = ((section, method, seed), handle, time.time())
            state_path.write_text(json.dumps({
                "status": "RUNNING", "remaining": len(queue),
                "active": [list(x[0]) for x in active.values()], "failures": failures,
                "available_memory_gib_at_launch": available_gib,
                "max_concurrent": MAX_CONCURRENT, "threads_per_run": 4,
                "log_session": session_id,
            }, indent=2), encoding="utf-8")
        time.sleep(1)

    final_status = "PASS" if not failures else (
        "STOPPED_TECHNICAL_FAILURE" if stop_launching else "FAIL")
    state_path.write_text(json.dumps({
        "status": final_status, "completed_expected": 400 - len(failures),
        "expected": 400, "failures": failures, "max_concurrent": MAX_CONCURRENT,
        "threads_per_run": 4, "remaining": len(queue), "log_session": session_id,
    }, indent=2), encoding="utf-8")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
