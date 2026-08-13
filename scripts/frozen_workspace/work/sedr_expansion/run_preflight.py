"""Outcome-blind SEDR technical-preflight orchestrator.

This module is deliberately inert unless invoked with ``--execute``.  It runs
the checkpoint worker only in PRELOCK quarantine, never opens a frozen source
H5AD, and permits only same-seed technical partition ARI plus embedding/graph
identity checks.  Reference labels and cross-seed/scientific metrics are out of
scope and fail the static firewall audit.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import adjusted_rand_score


ROOT = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).with_name("run_sedr_checkpoint.py")
INPUT_MANIFEST = (
    ROOT / "outputs" / "PROJECT9_SEDR_EXPANSION" / "technical_inputs"
    / "TECHNICAL_INPUT_MANIFEST.json"
)
OUTPUT_ROOT = ROOT / "outputs" / "PROJECT9_SEDR_EXPANSION"
QUARANTINE = OUTPUT_ROOT / "technical_preflight_quarantine_deterministic"
LOG_DIR = QUARANTINE / "logs"
PRELOCK_SENTINEL = "PRELOCK_TECHNICAL_PREFLIGHT"

# Four distinct representative smoke runs and two independent same-seed
# repeats.  The repeat run IDs, rather than different seeds, are the only
# perturbation permitted in the technical repeatability control.
RUNS = (
    ("151507", 1, "smoke_primary"),
    ("HBCA1", 1, "smoke_primary"),
    ("STARmap_20180505_BY3_1k", 1, "smoke_primary"),
    ("MERFISH_Bregma_m0.14", 1, "smoke_primary"),
    ("151507", 1, "same_seed_repeat"),
    ("STARmap_20180505_BY3_1k", 1, "same_seed_repeat"),
)
REPEAT_DATASETS = ("151507", "STARmap_20180505_BY3_1k")

# Case-insensitive substrings forbidden from the runner source and checkpoint
# metadata during prelock operation.  Technical same-seed ARI is calculated
# only here, after both isolated runs have completed.
FORBIDDEN_SOURCE_TOKENS = (
    "reference_ari", "reference_nmi", "pairwise_partition",
    "iso_accuracy", "marker_jaccard", "marker_reproducibility",
    "winner_probability", "rank_distribution", "consensus_ari",
    "layer_guess", "ground_truth", "manual_annotation",
)
FORBIDDEN_METADATA_TOKENS = FORBIDDEN_SOURCE_TOKENS + (
    "scientific_result", "spatial_map", "p_rank1",
)


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_manifest() -> dict[str, Any]:
    manifest = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("label_blind") is not True:
        raise RuntimeError("Technical input manifest is not label-blind")
    if manifest.get("reference_annotation_values_read") is not False:
        raise RuntimeError("Technical input manifest admits reference values")
    if manifest.get("pass_count") != 19 or manifest.get("entry_count") != 19:
        raise RuntimeError("Expected 19/19 validated technical inputs")
    entries = {row["dataset"]: row for row in manifest["entries"]}
    for dataset, _, _ in RUNS:
        row = entries.get(dataset)
        if not row or row.get("status") != "PASS":
            raise RuntimeError(f"Missing valid technical input: {dataset}")
        path = Path(row["technical_path"]).resolve()
        allowed = (OUTPUT_ROOT / "technical_inputs").resolve()
        if allowed not in path.parents:
            raise RuntimeError(f"Input escapes technical-input root: {path}")
        if path.name.endswith("_frozen.h5ad"):
            raise RuntimeError("Frozen source H5AD passed to preflight")
        if not path.is_file() or sha256(path) != row["technical_sha256"]:
            raise RuntimeError(f"Technical input hash mismatch: {dataset}")
    return manifest


def static_firewall_audit() -> dict[str, Any]:
    if not WORKER.is_file():
        raise FileNotFoundError(f"Checkpoint worker is not available: {WORKER}")
    checked = [WORKER, Path(__file__).resolve()]
    violations: list[str] = []
    for path in checked:
        text = path.read_text(encoding="utf-8").lower()
        for token in FORBIDDEN_SOURCE_TOKENS:
            # This orchestrator necessarily names forbidden tokens in its deny
            # list; only the worker is required not to contain them.
            if path == WORKER and token in text:
                violations.append(f"{path.name}:{token}")
    if violations:
        raise RuntimeError(f"Scientific-firewall source violation: {violations}")
    return {
        "status": "PASS",
        "checked": [str(path) for path in checked],
        "worker_sha256": sha256(WORKER),
        "forbidden_worker_tokens_found": [],
        "reference_inputs_allowed": False,
        "cross_seed_metrics_allowed": False,
        "same_seed_technical_ari_allowed": True,
    }


def run_directory(dataset: str, run_id: str) -> Path:
    return QUARANTINE / dataset / run_id


def worker_command(dataset: str, seed: int, run_id: str) -> list[str]:
    """Intended worker contract for prelock smoke execution."""
    return [
        sys.executable,
        str(WORKER),
        "--dataset", dataset,
        "--seed", str(seed),
        "--output-dir", str(run_directory(dataset, run_id)),
        "--mode", "smoke",
        "--protocol-hash", PRELOCK_SENTINEL,
        "--input-manifest", str(INPUT_MANIFEST),
        "--embedding",
    ]


def run_worker(dataset: str, seed: int, run_id: str) -> None:
    destination = run_directory(dataset, run_id)
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError(
            f"Refusing to overwrite preflight artifact: {destination}"
        )
    destination.mkdir(parents=True, exist_ok=False)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "PYTHONHASHSEED": str(seed),
        "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
        "OMP_NUM_THREADS": "4",
        "MKL_NUM_THREADS": "4",
        "OPENBLAS_NUM_THREADS": "4",
        "NUMEXPR_NUM_THREADS": "4",
        "VECLIB_MAXIMUM_THREADS": "4",
        "SEDR_PREFLIGHT_MODE": PRELOCK_SENTINEL,
    })
    command = worker_command(dataset, seed, run_id)
    completed = subprocess.run(
        command, cwd=ROOT, env=env, text=True, encoding="utf-8",
        errors="replace", capture_output=True, check=False,
    )
    log = (
        "$ " + subprocess.list2cmdline(command) + "\n\n[stdout]\n"
        + completed.stdout + "\n[stderr]\n" + completed.stderr
    )
    atomic_text(LOG_DIR / f"{dataset}__{run_id}.log", log)
    if completed.returncode:
        raise RuntimeError(
            f"Worker failed ({completed.returncode}): {dataset}/{run_id}"
        )


def find_unique(directory: Path, name: str) -> Path:
    found = list(directory.rglob(name))
    if len(found) != 1:
        raise RuntimeError(
            f"Expected exactly one {name} under {directory}; found {len(found)}"
        )
    return found[0]


def validate_checkpoint(dataset: str, run_id: str) -> dict[str, Any]:
    directory = run_directory(dataset, run_id)
    checkpoint_path = find_unique(directory, "checkpoint.json")
    labels_path = find_unique(directory, "labels.csv")
    embedding_path = find_unique(directory, "embedding.npz")
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    encoded = json.dumps(payload, sort_keys=True).lower()
    bad = [token for token in FORBIDDEN_METADATA_TOKENS if token in encoded]
    if bad:
        raise RuntimeError(f"Scientific metadata in {checkpoint_path}: {bad}")
    if payload.get("dataset") != dataset or int(payload.get("seed", -1)) != 1:
        raise RuntimeError(f"Checkpoint identity mismatch: {checkpoint_path}")
    if payload.get("status") not in {
        "PASS", "COMPLETE", "VALID", "VALID_TECHNICAL_CHECKPOINT"
    }:
        raise RuntimeError(f"Incomplete checkpoint: {checkpoint_path}")
    if payload.get("protocol_hash") not in {None, PRELOCK_SENTINEL}:
        raise RuntimeError("A preflight checkpoint claims a locked protocol")
    if payload.get("scientific_unblinding") not in {None, False}:
        raise RuntimeError("Scientific unblinding flag is not false")
    return {
        "dataset": dataset,
        "run_id": run_id,
        "checkpoint_path": str(checkpoint_path.resolve()),
        "labels_path": str(labels_path.resolve()),
        "embedding_path": str(embedding_path.resolve()),
        "checkpoint": payload,
    }


def read_labels(path: Path) -> tuple[list[str], np.ndarray]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or set(rows[0]) != {"observation_id", "cluster_label"}:
        raise RuntimeError(f"Unexpected label schema: {path}")
    ids = [row["observation_id"] for row in rows]
    labels = np.asarray([row["cluster_label"] for row in rows], dtype=str)
    if len(ids) != len(set(ids)) or not np.all(labels != ""):
        raise RuntimeError(f"Invalid labels: {path}")
    return ids, labels


def read_embedding(path: Path) -> np.ndarray:
    with np.load(path, allow_pickle=False) as archive:
        keys = list(archive.files)
        preferred = [key for key in ("embedding", "SEDR", "sedr") if key in keys]
        if len(preferred) == 1:
            array = archive[preferred[0]]
        elif len(keys) == 1:
            array = archive[keys[0]]
        else:
            raise RuntimeError(f"Ambiguous embedding payload: {path}, {keys}")
    array = np.asarray(array)
    if array.ndim != 2 or not np.isfinite(array).all():
        raise RuntimeError(f"Non-finite/invalid embedding: {path}")
    return array


def graph_hash(payload: dict[str, Any]) -> str:
    graph = payload.get("graph") or payload.get("technical", {}).get("graph") or {}
    value = graph.get("hash") or graph.get("sha256") or payload.get("graph_hash")
    if not value:
        raise RuntimeError("Checkpoint does not expose a graph hash")
    return str(value).upper()


def same_seed_control(dataset: str, records: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    first = records[(dataset, "smoke_primary")]
    second = records[(dataset, "same_seed_repeat")]
    ids_a, labels_a = read_labels(Path(first["labels_path"]))
    ids_b, labels_b = read_labels(Path(second["labels_path"]))
    if ids_a != ids_b:
        raise RuntimeError(f"Observation order differs in same-seed control: {dataset}")
    emb_a = read_embedding(Path(first["embedding_path"]))
    emb_b = read_embedding(Path(second["embedding_path"]))
    if emb_a.shape != emb_b.shape or emb_a.shape[0] != len(ids_a):
        raise RuntimeError(f"Embedding shape mismatch: {dataset}")
    difference = np.abs(emb_a.astype(np.float64) - emb_b.astype(np.float64))
    ari = float(adjusted_rand_score(labels_a, labels_b))
    g_a = graph_hash(first["checkpoint"])
    g_b = graph_hash(second["checkpoint"])
    requested_a = int(first["checkpoint"]["requested_k"])
    requested_b = int(second["checkpoint"]["requested_k"])
    observed_a = int(first["checkpoint"]["observed_k"])
    observed_b = int(second["checkpoint"]["observed_k"])
    passed = (
        ari == 1.0 and g_a == g_b and requested_a == requested_b
        and observed_a == observed_b
    )
    return {
        "dataset": dataset,
        "seed": 1,
        "partition_ari_same_seed": ari,
        "graph_hash_primary": g_a,
        "graph_hash_repeat": g_b,
        "graph_identical": g_a == g_b,
        "embedding_shape": "x".join(map(str, emb_a.shape)),
        "embedding_max_abs_diff": float(difference.max(initial=0.0)),
        "embedding_mean_abs_diff": float(difference.mean()),
        "embedding_allclose_rtol_1e-5_atol_1e-7": bool(
            np.allclose(emb_a, emb_b, rtol=1e-5, atol=1e-7)
        ),
        "requested_k_primary": requested_a,
        "requested_k_repeat": requested_b,
        "observed_k_primary": observed_a,
        "observed_k_repeat": observed_b,
        "technical_partition_repeatability_pass": passed,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"No rows for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def extract_metadata(record: dict[str, Any]) -> dict[str, Any]:
    p = record["checkpoint"]
    runtime = p.get("runtime", {})
    resources = p.get("resources", {})
    embedding = p.get("embedding", {})
    graph = p.get("graph", {})
    return {
        "dataset": record["dataset"],
        "seed": 1,
        "run_id": record["run_id"],
        "status": p.get("status"),
        "requested_k": p.get("requested_k"),
        "observed_k": p.get("observed_k"),
        "retained_gene_count": p.get("retained_gene_count") or p.get("preprocessing", {}).get("retained_gene_count"),
        "pca_dimension": p.get("pca_dimension") or p.get("preprocessing", {}).get("pca_dimension"),
        "graph_k": graph.get("k") or p.get("graph_k"),
        "graph_edge_count": graph.get("edge_count") or p.get("graph_edge_count"),
        "graph_hash": graph_hash(p),
        "epoch_count": p.get("epoch_count") or p.get("training", {}).get("total_optimizer_epochs"),
        "embedding_shape": embedding.get("shape") or p.get("embedding_shape"),
        "embedding_finite": embedding.get("finite") if embedding else p.get("embedding_finite"),
        "labels_finite": p.get("labels_finite") or p.get("final_readout", {}).get("labels_finite"),
        "elapsed_seconds": (
            runtime.get("elapsed_seconds") or p.get("elapsed_seconds")
            or p.get("runtime_seconds")
        ),
        "peak_ram_gib": resources.get("peak_ram_gib") or p.get("peak_ram_gib"),
        "peak_gpu_memory_mib": resources.get("peak_gpu_memory_mib") or p.get("peak_gpu_memory_mib"),
        "checkpoint_sha256": sha256(Path(record["checkpoint_path"])),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually invoke the worker; omitted means validate/scaffold only",
    )
    parser.add_argument(
        "--print-plan", action="store_true",
        help="Print worker commands without execution",
    )
    args = parser.parse_args()

    manifest = load_manifest()
    firewall = static_firewall_audit()
    if args.print_plan:
        for dataset, seed, run_id in RUNS:
            print(subprocess.list2cmdline(worker_command(dataset, seed, run_id)))
    if not args.execute:
        print("PREFLIGHT_READY_NOT_EXECUTED")
        return

    QUARANTINE.mkdir(parents=True, exist_ok=True)
    atomic_text(
        QUARANTINE / "PRELOCK_FIREWALL.json",
        json.dumps({
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "sentinel": PRELOCK_SENTINEL,
            "input_manifest_sha256": sha256(INPUT_MANIFEST),
            "input_manifest_label_blind": manifest["label_blind"],
            "firewall": firewall,
        }, indent=2) + "\n",
    )
    for dataset, seed, run_id in RUNS:
        run_worker(dataset, seed, run_id)

    records = {
        (dataset, run_id): validate_checkpoint(dataset, run_id)
        for dataset, _, run_id in RUNS
    }
    metadata = [extract_metadata(records[(dataset, run_id)]) for dataset, _, run_id in RUNS]
    controls = [same_seed_control(dataset, records) for dataset in REPEAT_DATASETS]
    write_csv(OUTPUT_ROOT / "technical_metadata.csv", metadata)
    write_csv(OUTPUT_ROOT / "identical_seed_controls.csv", controls)

    runtime_rows = [{
        "run_count": len(metadata),
        "completed_count": sum(
            row["status"] in {
                "PASS", "COMPLETE", "VALID", "VALID_TECHNICAL_CHECKPOINT"
            } for row in metadata
        ),
        "elapsed_seconds_sum": sum(float(row["elapsed_seconds"] or 0) for row in metadata),
        "elapsed_seconds_median": float(np.median([float(row["elapsed_seconds"] or 0) for row in metadata])),
        "peak_ram_gib_max": max(float(row["peak_ram_gib"] or 0) for row in metadata),
        "peak_gpu_memory_mib_max": max(float(row["peak_gpu_memory_mib"] or 0) for row in metadata),
        "same_seed_controls_passed": sum(bool(row["technical_partition_repeatability_pass"]) for row in controls),
        "same_seed_controls_total": len(controls),
        "scientific_outcomes_computed": False,
    }]
    write_csv(OUTPUT_ROOT / "runtime_summary.csv", runtime_rows)
    if not all(row["technical_partition_repeatability_pass"] for row in controls):
        raise RuntimeError("Identical-seed technical repeatability gate failed")
    print("TECHNICAL_PREFLIGHT_PASS")


if __name__ == "__main__":
    main()
