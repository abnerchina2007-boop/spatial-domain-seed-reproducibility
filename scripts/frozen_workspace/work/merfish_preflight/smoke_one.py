from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import threading
import time
import traceback

import numpy as np
import psutil
import scanpy as sc
import scipy
import scipy.sparse as sp
import torch


# SpaGCN 1.2.7 uses the historical scipy sparse-matrix `.A` alias.  The
# frozen Project 9 environment is scipy 1.13.1, where that alias exists; this
# compatibility shim preserves identical `toarray()` semantics if the host
# interpreter is newer.  It changes no data, graph, model, epoch or seed rule.
SPARSE_A_COMPATIBILITY_SHIM = not hasattr(sp.csr_matrix, "A")
if SPARSE_A_COMPATIBILITY_SHIM:
    sp.csr_matrix.A = property(lambda matrix: matrix.toarray())


WORKSPACE = Path(__file__).resolve().parents[2]
MODULE_PATH = WORKSPACE / "outputs" / "PROJECT9_PHASE1" / "code" / "run_seed_panel.py"
INPUT_ROOT = WORKSPACE / "work" / "merfish_preflight" / "frozen_inputs"
LOG_ROOT = WORKSPACE / "work" / "merfish_preflight" / "smoke_logs"


def load_runner():
    spec = importlib.util.spec_from_file_location("project9_frozen_runner", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def monitor_rss(stop: threading.Event, samples: list[int]) -> None:
    process = psutil.Process()
    while not stop.is_set():
        samples.append(process.memory_info().rss)
        stop.wait(0.1)
    samples.append(process.memory_info().rss)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--section", required=True)
    parser.add_argument("--method", required=True, choices=["GraphST", "STAGATE", "SpaGCN", "BANKSY"])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--epochs", type=int, default=200)
    args = parser.parse_args()

    torch.set_num_threads(int(os.environ.get("PROJECT9_TORCH_THREADS", "4")))
    torch.set_num_interop_threads(1)
    device = torch.device("cpu" if args.method in {"BANKSY", "SpaGCN"} else ("cuda:0" if torch.cuda.is_available() else "cpu"))
    if device.type == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)

    frozen = INPUT_ROOT / args.section / f"{args.section}_frozen.h5ad"
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    out = LOG_ROOT / f"{args.section}__{args.method}__seed{args.seed}.json"
    result = {
        "section": args.section,
        "method": args.method,
        "seed": args.seed,
        "epochs": args.epochs,
        "device": str(device),
        "source_runner": str(MODULE_PATH),
        "scientific_reference_metrics_computed": False,
        "scientific_reference_metrics_inspected": False,
        "prediction_map_saved": False,
        "runtime_scipy_version": scipy.__version__,
        "sparse_A_compatibility_shim": SPARSE_A_COMPATIBILITY_SHIM,
    }
    stop = threading.Event()
    rss_samples: list[int] = []
    monitor = threading.Thread(target=monitor_rss, args=(stop, rss_samples), daemon=True)
    started = time.perf_counter()
    monitor.start()
    try:
        base = sc.read_h5ad(frozen)
        runner = load_runner()
        labels, meta = runner.run_one(base, args.section, args.method, args.seed, args.epochs, device)
        labels = np.asarray(labels)
        result.update(
            {
                "status": "PASS",
                "n_cells": int(base.n_obs),
                "n_genes": int(base.n_vars),
                "n_clusters_observed": int(np.unique(labels).size),
                "required_K": int(base.uns["phase1_dataset"]["k"]),
                "cluster_count_matches_K": bool(np.unique(labels).size == int(base.uns["phase1_dataset"]["k"])),
                "labels_finite": bool(np.isfinite(labels).all()),
                "label_length_matches_cells": bool(labels.size == base.n_obs),
                "graph_edges": meta.get("graph_edges"),
                "graph_hash": meta.get("graph_hash"),
                "coordinate_hash": meta.get("coordinate_hash"),
                "method_parameters": meta.get("method_parameters"),
            }
        )
    except Exception as exc:
        result.update(
            {
                "status": "FAIL",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
    finally:
        stop.set()
        monitor.join(timeout=2)
        result["elapsed_seconds"] = time.perf_counter() - started
        result["peak_rss_gib"] = max(rss_samples, default=0) / (1024**3)
        result["peak_cuda_allocated_gib"] = (
            torch.cuda.max_memory_allocated(device) / (1024**3) if device.type == "cuda" else 0.0
        )
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
