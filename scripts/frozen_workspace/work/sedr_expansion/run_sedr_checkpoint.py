"""Run one outcome-blind SEDR technical checkpoint.

Only the label-free technical H5AD view is accepted.  The worker performs the
pinned official preprocessing, graph construction, 200+200 clustering-mode
training, and one R mclust EEE readout.  It contains no scientific scoring or
cross-run comparison code.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import random
import sys
import threading
import time
import traceback
import types
from pathlib import Path
from typing import Any

import anndata as ad
import numpy as np
import psutil
import scanpy as sc
import scipy
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from sklearn.decomposition import PCA
import sklearn
import torch

import SEDR


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = (
    ROOT / "outputs" / "PROJECT9_SEDR_EXPANSION" / "technical_inputs"
    / "TECHNICAL_INPUT_MANIFEST.json"
)
OFFICIAL_REPO = ROOT / "work" / "sedr_audit"
OFFICIAL_COMMIT = "EF4836059A4EA49BE3BF7C67008A44FFC16A2A0E"
PRELOCK_SENTINEL = "PRELOCK_TECHNICAL_PREFLIGHT"
SPOT_DATASETS = {
    "151507", "151508", "151509", "151510", "151669", "151670",
    "151671", "151672", "151673", "151674", "151675", "151676",
    "HBCA1",
}
CELL_DATASETS = {
    "STARmap_20180505_BY3_1k", "MERFISH_Bregma_m0.04",
    "MERFISH_Bregma_m0.09", "MERFISH_Bregma_m0.14",
    "MERFISH_Bregma_m0.19", "MERFISH_Bregma_m0.24",
}
REQUESTED_K = {
    **{name: 7 for name in SPOT_DATASETS if name != "HBCA1"},
    "HBCA1": 20,
    "STARmap_20180505_BY3_1k": 7,
    **{name: 8 for name in CELL_DATASETS if name.startswith("MERFISH_")},
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def ordered_hash(values: list[str]) -> str:
    return sha256_bytes("\n".join(values).encode("utf-8"))


def atomic_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def git_value(*args: str) -> str:
    import subprocess
    result = subprocess.run(
        ["git", "-C", str(OFFICIAL_REPO), *args], capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=True,
    )
    return result.stdout.strip()


class ResourceMonitor:
    def __init__(self) -> None:
        self.process = psutil.Process(os.getpid())
        self.peak_rss = self.process.memory_info().rss
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop_event.wait(0.1):
            try:
                self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)
            except psutil.Error:
                return

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)
        try:
            self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)
        except psutil.Error:
            pass


def load_manifest(path: Path, dataset: str) -> tuple[dict[str, Any], str]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (
        manifest.get("label_blind") is not True
        or manifest.get("entry_count") != 19
        or manifest.get("pass_count") != 19
    ):
        raise RuntimeError("The technical-input manifest did not pass its firewall")
    rows = {row["dataset"]: row for row in manifest["entries"]}
    if dataset not in rows or rows[dataset].get("status") != "PASS":
        raise RuntimeError(f"No validated technical input for {dataset}")
    return rows[dataset], sha256_file(path)


def set_seeds(seed: int) -> None:
    os.environ["PYTHONHASHSEED"] = str(seed)
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    random.seed(seed)
    np.random.seed(seed)
    SEDR.fix_seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    # The pinned official helper requests deterministic cuDNN behavior.  On
    # current PyTorch/CUDA, extend that same intent to every available kernel
    # and disable reduced-precision TF32 matmul.  This controls execution only;
    # it does not change model parameters, losses, graph, epochs, or seeds.
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.set_float32_matmul_precision("highest")
    torch.set_num_threads(4)


def compatible_mask_generator(self: Any, N: int = 1) -> torch.Tensor:
    """Pinned-source operation with only modern integer-index syntax.

    The official numeric randperm values are preserved exactly.  In
    particular, they are not remapped through the non-neighbour vector.
    """
    index = self.adj_label.indices()
    selected: list[torch.Tensor] = []
    for i in range(self.cell_num):
        neighbor = index[1, torch.where(index[0, :] == i)[0]]
        n_selected = len(neighbor) * N
        total_index = torch.arange(
            0, self.cell_num, dtype=torch.long, device=self.device
        )
        non_neighbor = total_index[~torch.isin(total_index, neighbor)]
        permutation = torch.randperm(
            len(non_neighbor), dtype=torch.long, device=self.device
        )
        selected.append(permutation[:n_selected])
    x_index = torch.repeat_interleave(index[0], N)
    y_index = torch.concat(selected)
    combined_index = torch.concat(
        [index, torch.stack([x_index, y_index])], axis=1
    )
    values = torch.concat([
        self.adj_label.values(),
        torch.zeros(len(x_index), dtype=torch.float32, device=self.device),
    ])
    return torch.sparse_coo_tensor(
        combined_index, values, self.adj_label.shape, device=self.device
    ).coalesce()


def preprocess(adata: ad.AnnData, regime: str) -> tuple[np.ndarray, dict[str, Any]]:
    if sparse.issparse(adata.X):
        adata.X = adata.X.tocsr().astype(np.float32)
    else:
        adata.X = np.asarray(adata.X, dtype=np.float32)
    original_gene_count = int(adata.n_vars)
    if regime == "spot":
        adata.layers["count"] = adata.X.copy()
        sc.pp.filter_genes(adata, min_cells=50)
        sc.pp.filter_genes(adata, min_counts=10)
        sc.pp.normalize_total(adata, target_sum=1e6)
        sc.pp.highly_variable_genes(
            adata, flavor="seurat_v3", layer="count", n_top_genes=2000
        )
        adata = adata[:, np.asarray(adata.var["highly_variable"], dtype=bool)].copy()
    else:
        sc.pp.normalize_total(adata, target_sum=1e6)
    retained_gene_count = int(adata.n_vars)
    pca_dimension = min(200, retained_gene_count - 1, adata.n_obs - 1)
    if pca_dimension < 1:
        raise RuntimeError("No mathematically valid PCA dimension")
    sc.pp.scale(adata)
    matrix = np.asarray(adata.X, dtype=np.float32)
    if not np.isfinite(matrix).all():
        raise RuntimeError("Preprocessed feature matrix is not finite")
    representation = PCA(
        n_components=pca_dimension, random_state=42
    ).fit_transform(matrix).astype(np.float32, copy=False)
    if not np.isfinite(representation).all():
        raise RuntimeError("PCA representation is not finite")
    adata.obsm["X_pca"] = representation
    return representation, {
        "original_gene_count": original_gene_count,
        "retained_gene_count": retained_gene_count,
        "pca_dimension": pca_dimension,
        "finite": True,
        "gene_filter_min_cells": 50 if regime == "spot" else None,
        "gene_filter_min_counts": 10 if regime == "spot" else None,
        "hvg_flavor": "seurat_v3" if regime == "spot" else None,
        "hvg_requested": 2000 if regime == "spot" else None,
        "complete_panel": regime == "cell",
        "target_sum": 1_000_000,
        "log_transform": False,
        "scale": "scanpy defaults",
        "pca_random_state": 42,
    }


def graph_metadata(graph: dict[str, Any], graph_k: int, n_obs: int) -> dict[str, Any]:
    label = graph["adj_label"].coalesce().cpu()
    index = label.indices().numpy()
    keep = index[0] != index[1]
    row = index[0, keep]
    col = index[1, keep]
    matrix = sparse.csr_matrix(
        (np.ones(len(row), dtype=np.uint8), (row, col)), shape=(n_obs, n_obs)
    )
    matrix = matrix.maximum(matrix.T)
    matrix.setdiag(0)
    matrix.eliminate_zeros()
    degrees = np.asarray(matrix.sum(axis=1)).ravel()
    components, _ = connected_components(matrix, directed=False)
    coo = matrix.tocoo()
    upper = np.column_stack((coo.row[coo.row < coo.col], coo.col[coo.row < coo.col]))
    upper = np.asarray(upper, dtype="<i8")
    digest = hashlib.sha256()
    digest.update(np.asarray([n_obs, graph_k], dtype="<i8").tobytes())
    digest.update(np.ascontiguousarray(upper).tobytes())
    return {
        "k": graph_k,
        "edge_count": int(matrix.nnz // 2),
        "isolates": int(np.sum(degrees == 0)),
        "connected_components": int(components),
        "hash": digest.hexdigest().upper(),
        "finite": True,
        "completed": True,
        "distance": "Euclidean",
        "symmetrization": "undirected union",
    }


def mclust_once(embedding: np.ndarray, requested_k: int, seed: int) -> tuple[np.ndarray, str, bool]:
    r_home_value = os.environ.get("R_HOME")
    if not r_home_value:
        raise RuntimeError("R_HOME must point to the R installation used for mclust")
    r_home = Path(r_home_value)
    r_bin_x64 = str(r_home / "bin" / "x64")
    r_bin = str(r_home / "bin")
    current_path = os.environ.get("PATH", "")
    if r_bin_x64.lower() not in current_path.lower():
        os.environ["PATH"] = os.pathsep.join([r_bin_x64, r_bin, current_path])
    from rpy2 import robjects as ro
    from rpy2.robjects.vectors import FloatVector

    values = np.asfortranarray(embedding, dtype=np.float64)
    r_matrix = ro.r["matrix"](
        FloatVector(values.ravel(order="F")),
        nrow=values.shape[0], ncol=values.shape[1],
    )
    ro.r("suppressPackageStartupMessages(library(mclust))")
    wrapper = ro.r(
        "function(x, G, modelNames) "
        "mclust::Mclust(x, G=G, modelNames=modelNames, verbose=FALSE)"
    )
    ro.r["set.seed"](seed)
    result = wrapper(r_matrix, requested_k, "EEE")
    labels = np.asarray(result.rx2("classification"), dtype=np.int64)
    model = str(result.rx2("modelName")[0])
    log_likelihood = np.asarray(result.rx2("loglik"), dtype=np.float64)
    normal = bool(np.isfinite(log_likelihood).all())
    return labels, model, normal


def write_labels(path: Path, ids: list[str], labels: np.ndarray) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["observation_id", "cluster_label"])
        writer.writerows(zip(ids, labels.tolist()))
    os.replace(temporary, path)


def write_embedding(path: Path, embedding: np.ndarray) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, embedding=embedding.astype(np.float32, copy=False))
    os.replace(temporary, path)


def run(args: argparse.Namespace) -> None:
    if args.dataset not in REQUESTED_K:
        raise RuntimeError(f"Unknown dataset: {args.dataset}")
    if not 1 <= args.seed <= 20:
        raise RuntimeError("Seed must be in 1..20")
    if args.mode == "smoke":
        if args.protocol_hash != PRELOCK_SENTINEL:
            raise RuntimeError("Smoke mode requires the pre-lock sentinel")
    elif len(args.protocol_hash) != 64 or any(c not in "0123456789abcdefABCDEF" for c in args.protocol_hash):
        raise RuntimeError("Final mode requires a SHA-256 protocol hash")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise RuntimeError(f"Refusing to overwrite nonempty checkpoint directory: {output_dir}")

    manifest_row, manifest_hash = load_manifest(args.input_manifest, args.dataset)
    technical_path = Path(manifest_row["technical_path"]).resolve()
    allowed_root = (
        ROOT / "outputs" / "PROJECT9_SEDR_EXPANSION" / "technical_inputs"
    ).resolve()
    if allowed_root not in technical_path.parents or technical_path.name.endswith("_frozen.h5ad"):
        raise RuntimeError("Only a label-free technical input is allowed")
    if sha256_file(technical_path) != manifest_row["technical_sha256"]:
        raise RuntimeError("Technical input hash mismatch")

    monitor = ResourceMonitor()
    started = time.perf_counter()
    monitor.start()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    set_seeds(args.seed)

    base = ad.read_h5ad(technical_path)
    ids = [str(value) for value in base.obs_names]
    if (
        base.n_obs != manifest_row["obs_count"]
        or base.n_vars != manifest_row["var_count"]
        or ordered_hash(ids) != manifest_row["obs_order_sha256_newline_utf8"]
        or list(base.obs.columns)
        or list(base.var.columns)
        or list(base.obsm.keys()) != ["spatial"]
    ):
        raise RuntimeError("Technical input structure/order failed revalidation")

    regime = "spot" if args.dataset in SPOT_DATASETS else "cell"
    graph_k = 12 if regime == "spot" else 6
    requested_k = REQUESTED_K[args.dataset]
    pca, preprocessing = preprocess(base, regime)
    graph = SEDR.graph_construction(base, graph_k)
    graph_info = graph_metadata(graph, graph_k, base.n_obs)

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    network = SEDR.Sedr(pca, graph, mode="clustering", device=device)
    network.mask_generator = types.MethodType(compatible_mask_generator, network)
    network.train_with_dec(epochs=200, dec_interval=20, dec_tol=0.00, N=1)
    embedding, _, _, _ = network.process()
    embedding = np.asarray(embedding, dtype=np.float32)
    if embedding.shape != (base.n_obs, 32) or not np.isfinite(embedding).all():
        raise RuntimeError("Training returned an invalid embedding")

    labels, model_name, clustering_normal = mclust_once(
        embedding, requested_k, args.seed
    )
    if (
        labels.shape != (base.n_obs,)
        or not np.isfinite(labels).all()
        or not clustering_normal
    ):
        raise RuntimeError("Final clustering did not return one finite label per observation")
    observed_k = int(np.unique(labels).size)

    labels_path = output_dir / "labels.csv"
    write_labels(labels_path, ids, labels)
    embedding_path = output_dir / "embedding.npz"
    if args.embedding:
        write_embedding(embedding_path, embedding)

    monitor.stop()
    elapsed = time.perf_counter() - started
    peak_gpu = (
        float(torch.cuda.max_memory_allocated() / (1024 ** 2))
        if torch.cuda.is_available() else 0.0
    )
    source_files = [
        OFFICIAL_REPO / "SEDR" / name for name in (
            "SEDR_module.py", "SEDR_model.py", "graph_func.py",
            "utils_func.py", "clustering_func.py",
        )
    ]
    outputs: dict[str, Any] = {
        "labels_path": labels_path.name,
        "labels_bytes": labels_path.stat().st_size,
        "labels_sha256": sha256_file(labels_path),
        "embedding_path": embedding_path.name if args.embedding else None,
        "embedding_bytes": embedding_path.stat().st_size if args.embedding else None,
        "embedding_sha256": sha256_file(embedding_path) if args.embedding else None,
        "embedding_shape": list(embedding.shape) if args.embedding else None,
        "embedding_finite": True if args.embedding else None,
    }
    checkpoint = {
        "schema_version": 1,
        "status": "VALID_TECHNICAL_CHECKPOINT",
        "mode": args.mode,
        "dataset": args.dataset,
        "seed": args.seed,
        "requested_k": requested_k,
        "observed_k": observed_k,
        "protocol_hash": args.protocol_hash.upper(),
        "scientific_unblinding": False,
        "input": {
            "technical_path": str(technical_path),
            "bytes": technical_path.stat().st_size,
            "sha256": manifest_row["technical_sha256"],
            "manifest_sha256": manifest_hash,
            "source_sha256": manifest_row["source_sha256"],
            "obs_count": base.n_obs,
            "var_count": manifest_row["var_count"],
            "obs_order_sha256_newline_utf8": manifest_row["obs_order_sha256_newline_utf8"],
        },
        "implementation": {
            "repository": "JinmiaoChenLab/SEDR",
            "package_version": "1.0.0",
            "commit": git_value("rev-parse", "HEAD").upper(),
            "source_sha256": {path.name: sha256_file(path) for path in source_files},
        },
        "parameters": {
            "platform_regime": regime,
            "graph_k": graph_k,
            "requested_k": requested_k,
            "target_sum": 1_000_000,
            "pca_random_state": 42,
            "pretraining_epochs": 200,
            "dec_epochs": 200,
            "internal_dec_k": 10,
            "model_mode": "clustering with DEC",
            "architecture": "feature 64-16; GCN 64-16; latent 32",
            "dropout": 0.2,
            "weights": {"reconstruction": 10, "gcn": 0.1, "self": 1, "dec_kl": 1},
            "optimizer": "Adam",
            "learning_rate": 0.01,
            "weight_decay": 0.01,
            "dec_interval": 20,
            "dec_tolerance": 0.0,
            "internal_kmeans_random_state": 42,
        },
        "preprocessing": preprocessing,
        "graph": graph_info,
        "training": {
            "completed": True,
            "pretraining_epochs_completed": 200,
            "dec_epochs_completed": 200,
            "total_optimizer_epochs": 400,
            "embedding_shape": list(embedding.shape),
            "embedding_finite": True,
            "device": device,
        },
        "final_readout": {
            "model": "mclust EEE",
            "calls": 1,
            "requested_k": requested_k,
            "observed_k": observed_k,
            "labels_count": int(labels.size),
            "labels_finite": True,
            "normal_completion": clustering_normal,
            "r_seed": args.seed,
        },
        "outputs": outputs,
        "runtime_seconds": elapsed,
        "resources": {
            "peak_ram_gib": monitor.peak_rss / (1024 ** 3),
            "peak_gpu_memory_mib": peak_gpu,
            "cpu_thread_limit": 4,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "scanpy": sc.__version__,
            "anndata": ad.__version__,
            "sklearn": sklearn.__version__,
            "torch": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "r": "4.3.1",
            "mclust": "6.1.3",
            "rpy2": "3.5.17",
        },
        "compatibility": {
            "r_home_externalized": True,
            "rpy2_matrix_bridge": "explicit R matrix plus named wrapper",
            "modern_torch_index_dtype": "long; values/order unchanged",
            "deterministic_algorithms_enforced": True,
            "tf32_disabled_for_repeatability": True,
            "official_scientific_parameters_changed": False,
        },
    }
    if checkpoint["implementation"]["commit"] != OFFICIAL_COMMIT:
        raise RuntimeError("Official source commit changed")
    atomic_text(
        output_dir / "checkpoint.json",
        json.dumps(checkpoint, indent=2, ensure_ascii=False) + "\n",
    )
    print(json.dumps({
        "status": checkpoint["status"], "dataset": args.dataset,
        "seed": args.seed, "runtime_seconds": elapsed,
        "peak_ram_gib": checkpoint["resources"]["peak_ram_gib"],
        "peak_gpu_memory_mib": peak_gpu,
    }))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("smoke", "final"))
    parser.add_argument("--protocol-hash", required=True)
    parser.add_argument("--input-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--embedding", action="store_true")
    args = parser.parse_args()
    try:
        run(args)
        return 0
    except Exception as error:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        failure = {
            "status": "TECHNICAL_FAILURE", "dataset": args.dataset,
            "seed": args.seed, "error_type": type(error).__name__,
            "error": str(error), "scientific_unblinding": False,
        }
        atomic_text(
            args.output_dir / "failure.json",
            json.dumps(failure, indent=2, ensure_ascii=False) + "\n",
        )
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
