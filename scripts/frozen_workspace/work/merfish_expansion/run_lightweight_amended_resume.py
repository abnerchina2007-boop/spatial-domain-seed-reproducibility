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
METHODS = ["GraphST", "SpaGCN", "BANKSY"]
MAX_CONCURRENT = 3
MIN_FREE_GIB = 6.0
PROJECTED_PEAK_GIB = {"GraphST": 1.45, "SpaGCN": 0.86, "BANKSY": 0.47}


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


def main() -> None:
    queue = deque(
        (section, method, seed)
        for method in METHODS
        for seed in range(1, 21)
        for section in SECTIONS
        if not completed(section, method, seed)
    )
    session_id = time.strftime("amended_resume_%Y%m%d_%H%M%S")
    log_dir = ROOT / "logs" / "lightweight_amended_resume" / session_id
    log_dir.mkdir(parents=True, exist_ok=True)
    state_path = ROOT / "AMENDED_RESUME_QUEUE_STATE.json"
    env = os.environ.copy()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[name] = "4"
    env["PROJECT9_TORCH_THREADS"] = "4"
    active: dict[subprocess.Popen, tuple[tuple[str, str, int], object, float]] = {}
    failures: list[dict] = []
    stop_launching = False
    minimum_free_gib = psutil.virtual_memory().available / (1024 ** 3)

    def write_state(status: str, event: str) -> None:
        state_path.write_text(json.dumps({
            "status": status,
            "event": event,
            "remaining": len(queue),
            "active": [list(value[0]) for value in active.values()],
            "failures": failures,
            "max_concurrent": MAX_CONCURRENT,
            "threads_per_process": 4,
            "minimum_required_free_ram_gib": MIN_FREE_GIB,
            "minimum_observed_free_ram_gib": minimum_free_gib,
            "current_free_ram_gib": psutil.virtual_memory().available / (1024 ** 3),
            "spagcn_post_refinement_exact_k_required": False,
            "log_session": session_id,
        }, indent=2), encoding="utf-8")

    while queue or active:
        minimum_free_gib = min(
            minimum_free_gib, psutil.virtual_memory().available / (1024 ** 3)
        )
        for process in [item for item in active if item.poll() is not None]:
            task, handle, _started = active.pop(process)
            handle.close()
            section, method, seed = task
            if process.returncode != 0 or not completed(section, method, seed):
                failures.append({
                    "section": section, "method": method, "seed": seed,
                    "returncode": process.returncode,
                })
                stop_launching = True
            write_state("STOPPING_TECHNICAL_FAILURE" if stop_launching else "RUNNING", "finished")

        if stop_launching and not active:
            break

        while queue and not stop_launching and len(active) < MAX_CONCURRENT:
            section, method, seed = queue[0]
            if completed(section, method, seed):
                queue.popleft()
                continue
            free_gib = psutil.virtual_memory().available / (1024 ** 3)
            minimum_free_gib = min(minimum_free_gib, free_gib)
            if free_gib - PROJECTED_PEAK_GIB[method] < MIN_FREE_GIB:
                break
            queue.popleft()
            log_path = log_dir / f"{section}__{method}__seed{seed}.log"
            handle = log_path.open("w", encoding="utf-8")
            try:
                process = subprocess.Popen(
                    [sys.executable, str(WORKER), "--section", section, "--method", method,
                     "--seed", str(seed), "--epochs", "200"],
                    cwd=WORKSPACE, env=env, stdout=handle, stderr=subprocess.STDOUT, text=True,
                )
            except OSError as exc:
                handle.close()
                failures.append({
                    "section": section, "method": method, "seed": seed,
                    "launch_error": repr(exc),
                })
                stop_launching = True
                break
            active[process] = ((section, method, seed), handle, time.time())
            write_state("RUNNING", "launched")
        time.sleep(0.5)

    final_status = "PASS" if not failures and not queue else "STOPPED_TECHNICAL_FAILURE"
    write_state(final_status, "finished")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
