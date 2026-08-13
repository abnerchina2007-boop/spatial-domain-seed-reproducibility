from __future__ import annotations

import argparse
import gc
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import time

import numpy as np
import pandas as pd
import scanpy as sc
import scipy.sparse as sp
import torch


# Exact compatibility semantics for SpaGCN 1.2.7 when the host scipy is newer
# than the frozen 1.13.1 environment. This restores the historical `.A` alias
# only; it does not alter the method, input or parameters.
if not hasattr(sp.csr_matrix, "A"):
    sp.csr_matrix.A = property(lambda matrix: matrix.toarray())


WORKSPACE = Path(__file__).resolve().parents[2]
EXPANSION_ROOT = WORKSPACE / "outputs" / "PROJECT9_MERFISH_EXPANSION"
FROZEN_RUNNER = WORKSPACE / "outputs" / "PROJECT9_PHASE1" / "code" / "run_seed_panel.py"
METHODS = ("GraphST", "STAGATE", "SpaGCN", "BANKSY")


def load_runner():
    spec = importlib.util.spec_from_file_location("project9_frozen_runner", FROZEN_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load frozen runner: {FROZEN_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Keep the exact imported methods while placing deterministic caches inside
    # the MERFISH expansion rather than the locked Phase 1 directory.
    module.ROOT = EXPANSION_ROOT
    return module


def matrix_hash(matrix) -> str:
    digest = hashlib.sha256()
    if sp.issparse(matrix):
        matrix = matrix.tocsr()
        for array in (matrix.indptr, matrix.indices, matrix.data):
            digest.update(np.ascontiguousarray(array).view(np.uint8))
    else:
        digest.update(np.ascontiguousarray(np.asarray(matrix)).view(np.uint8))
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--section", required=True)
    parser.add_argument("--method", required=True, choices=METHODS)
    parser.add_argument("--seed", required=True, type=int, choices=range(1, 21))
    parser.add_argument("--epochs", type=int, default=200)
    args = parser.parse_args()

    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "4"
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)

    input_path = EXPANSION_ROOT / "data" / args.section / f"{args.section}_frozen.h5ad"
    output_dir = EXPANSION_ROOT / "predictions" / args.section
    log_dir = EXPANSION_ROOT / "logs"
    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.method}__seed{args.seed}__primary"
    prediction_path = output_dir / f"{stem}.csv"
    metadata_path = output_dir / f"{stem}.json"
    if prediction_path.exists() and metadata_path.exists():
        prior = json.loads(metadata_path.read_text(encoding="utf-8"))
        prior_k = prior.get("n_clusters_observed")
        prior_valid_k = args.method == "SpaGCN" or prior_k == 8
        if prior.get("status") == "PASS" and prior_valid_k:
            print(json.dumps({"status": "ALREADY_PASS", "section": args.section, "method": args.method, "seed": args.seed}))
            return

    base = sc.read_h5ad(input_path)
    runner = load_runner()
    device = torch.device(
        "cpu" if args.method in {"BANKSY", "SpaGCN"}
        else ("cuda:0" if torch.cuda.is_available() else "cpu")
    )
    started = time.perf_counter()
    pre_refinement_observed_k = None
    if args.method == "SpaGCN":
        spg = importlib.import_module("SpaGCN")
        frozen_refine = spg.refine

        def audited_refine(*refine_args, **refine_kwargs):
            nonlocal pre_refinement_observed_k
            pred = refine_kwargs.get("pred")
            if pred is None and len(refine_args) >= 2:
                pred = refine_args[1]
            if pred is not None:
                pre_refinement_observed_k = int(np.unique(np.asarray(pred)).size)
            return frozen_refine(*refine_args, **refine_kwargs)

        spg.refine = audited_refine
        try:
            labels, method_meta = runner.run_one(
                base, args.section, args.method, args.seed, args.epochs, device)
        finally:
            spg.refine = frozen_refine
    else:
        labels, method_meta = runner.run_one(
            base, args.section, args.method, args.seed, args.epochs, device)
    labels = np.asarray(labels, dtype=np.int16)
    required_k = int(base.uns["phase1_dataset"]["k"])
    observed_k = int(np.unique(labels).size)
    if labels.shape != (base.n_obs,) or not np.isfinite(labels).all():
        raise RuntimeError("Frozen run did not return one finite label per expected cell")
    if args.method != "SpaGCN" and observed_k != required_k:
        raise RuntimeError("Frozen fixed-K readout did not return exactly K=8")

    prediction = pd.DataFrame({
        "dataset": args.section,
        "method": args.method,
        "seed": args.seed,
        "run_id": "primary",
        "barcode": base.obs_names.astype(str),
        "cluster": labels,
    })
    feature_matrix = base[:, np.asarray(base.var["highly_variable"], dtype=bool)].X
    metadata = {
        "status": "PASS",
        "dataset": args.section,
        "method": args.method,
        "seed": args.seed,
        "run_id": "primary",
        "epochs": args.epochs,
        "n_cells": int(base.n_obs),
        "n_genes": int(base.n_vars),
        "n_clusters_observed": observed_k,
        "required_K": required_k,
        "feature_hash": matrix_hash(feature_matrix),
        "elapsed_seconds": time.perf_counter() - started,
        "device": str(device),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        **method_meta,
    }
    if args.method == "SpaGCN":
        metadata.update({
            "requested_K": required_k,
            "pre_refinement_observed_K": pre_refinement_observed_k,
            "post_refinement_observed_K": observed_k,
            "refinement_cluster_count_reduced": observed_k < required_k,
            "spagcn_validity_rule": "post-refinement observed K may be below requested K",
        })
        if args.section == "MERFISH_Bregma_m0.19" and args.seed == 19:
            metadata.update({
                "checkpoint_provenance": "reconstruction rerun after prior wrapper discard",
                "historical_execution_training_completed": True,
                "historical_execution_post_refinement_K": "<8 (exact count unavailable)",
                "historical_execution_labels_persisted": False,
            })
    tmp_csv = prediction_path.with_suffix(".csv.tmp")
    tmp_json = metadata_path.with_suffix(".json.tmp")
    prediction.to_csv(tmp_csv, index=False)
    tmp_json.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    tmp_csv.replace(prediction_path)
    tmp_json.replace(metadata_path)
    print(json.dumps({"status": "PASS", "section": args.section, "method": args.method,
                      "seed": args.seed, "elapsed_seconds": metadata["elapsed_seconds"]}))
    del prediction, labels, base
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
