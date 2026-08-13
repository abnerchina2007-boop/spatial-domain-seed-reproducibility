from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import scanpy as sc
import scipy.sparse as sp
import torch
from sklearn.decomposition import PCA
from sklearn.mixture import GaussianMixture


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "environment" / "sources"
PACKAGE_ROOT = ROOT / "environment" / "python_packages"
sys.path.insert(0, str(SOURCE_ROOT / "STAGATE_pyG-main"))
sys.path.insert(0, str(SOURCE_ROOT / "GraphST"))
sys.path.insert(0, str(SOURCE_ROOT / "SpaGCN" / "SpaGCN_package"))
sys.path.insert(0, str(PACKAGE_ROOT))

PRED_DIR = ROOT / "predictions"
LOG_DIR = ROOT / "logs"
DEFAULT_K = 7


def dataset_config(base) -> dict:
    config = dict(base.uns.get("phase1_dataset", {}))
    config.setdefault("k", DEFAULT_K)
    config.setdefault("technology", "10x Visium")
    config.setdefault("graphst_datatype", "10X")
    config.setdefault("stagate_radius", 150.0)
    config.setdefault("spagcn_shape", "hexagon")
    return config


def hash_array(array: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(array)
    return hashlib.sha256(contiguous.view(np.uint8)).hexdigest()


def hash_sparse_or_dense(matrix) -> str:
    if sp.issparse(matrix):
        matrix = matrix.tocsr()
        digest = hashlib.sha256()
        for array in (matrix.indptr, matrix.indices, matrix.data):
            digest.update(np.ascontiguousarray(array).view(np.uint8))
        return digest.hexdigest()
    return hash_array(np.asarray(matrix))


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def cluster_embedding(embedding: np.ndarray, seed: int, reduce_to: int | None, k: int) -> tuple[np.ndarray, dict]:
    matrix = np.asarray(embedding, dtype=np.float64)
    pca_meta = None
    if reduce_to is not None and matrix.shape[1] > reduce_to:
        pca = PCA(n_components=reduce_to, svd_solver="arpack", random_state=0)
        matrix = pca.fit_transform(matrix)
        pca_meta = {
            "n_components": reduce_to,
            "explained_variance_ratio_sum": float(pca.explained_variance_ratio_.sum()),
            "random_state": 0,
        }
    mixture = GaussianMixture(
        n_components=k,
        covariance_type="tied",
        random_state=seed,
        n_init=5,
        max_iter=500,
        reg_covar=1e-6,
    )
    labels = mixture.fit_predict(matrix).astype(np.int64)
    return labels, {
        "clusterer": "sklearn GaussianMixture",
        "covariance_type": "tied (mclust EEE analogue)",
        "n_components": k,
        "n_init": 5,
        "random_state": seed,
        "converged": bool(mixture.converged_),
        "iterations": int(mixture.n_iter_),
        "pca": pca_meta,
    }


def graph_edge_hash_from_stagate(spatial_net: pd.DataFrame, obs_names: pd.Index) -> tuple[str, int]:
    ids = pd.Series(np.arange(len(obs_names), dtype=np.int64), index=obs_names)
    first = spatial_net["Cell1"].map(ids).to_numpy(dtype=np.int64)
    second = spatial_net["Cell2"].map(ids).to_numpy(dtype=np.int64)
    edges = np.column_stack((first, second))
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    edges = np.ascontiguousarray(edges[order])
    return hash_array(edges), int(edges.shape[0])


def banksy_embedding(base, section: str) -> tuple[np.ndarray, dict]:
    cache_dir = ROOT / "environment" / "banksy_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{section}_lambda0.2_k15_pca20_varfilter_v2.npy"
    meta_path = cache.with_suffix(".json")
    if cache.exists() and meta_path.exists():
        return np.load(cache), json.loads(meta_path.read_text(encoding="utf-8"))

    from banksy.embed_banksy import generate_banksy_matrix
    from banksy.initialize_banksy import initialize_banksy

    adata = base[:, base.var["highly_variable"]].copy()
    coords = np.asarray(adata.obsm["spatial_original"], dtype=np.float64)
    adata.obsm["spatial"] = coords.copy()
    adata.obs["x"] = coords[:, 0]
    adata.obs["y"] = coords[:, 1]
    banksy_dict = initialize_banksy(
        adata,
        coord_keys=("x", "y", "spatial"),
        num_neighbours=15,
        nbr_weight_decay="scaled_gaussian",
        max_m=0,
        plt_edge_hist=False,
        plt_nbr_weights=False,
        plt_agf_angles=False,
        plt_theta=False,
    )
    graph = banksy_dict["scaled_gaussian"]["weights"][0].tocsr()
    graph_hash = hash_sparse_or_dense(graph)
    # BANKSY z-scores both own and neighborhood expression. Its reference
    # zscore implementation converts infinite values from zero-variance
    # columns to extreme finite values, which can overflow PCA. Exclude only
    # columns that are numerically constant in either matrix before BANKSY;
    # this is fixed, label-free preprocessing and is identical across seeds.
    own = adata.X.toarray() if sp.issparse(adata.X) else np.asarray(adata.X)
    neighborhood = graph @ own
    own_variance = np.var(own, axis=0)
    neighborhood_variance = np.var(neighborhood, axis=0)
    keep = (
        np.isfinite(own_variance)
        & np.isfinite(neighborhood_variance)
        & (own_variance > 1e-12)
        & (neighborhood_variance > 1e-12)
    )
    adata = adata[:, keep].copy()
    banksy_dict, matrix = generate_banksy_matrix(
        adata,
        banksy_dict,
        lambda_list=[0.2],
        max_m=0,
        variance_balance=False,
        verbose=False,
    )
    x = matrix.X
    if sp.issparse(x):
        x = x.toarray()
    pca = PCA(n_components=20, svd_solver="arpack", random_state=0)
    embedding = pca.fit_transform(np.asarray(x, dtype=np.float64))
    np.save(cache, embedding)
    meta = {
        "implementation": "pybanksy 1.3.5 deterministic BANKSY feature transform",
        "num_neighbours": 15,
        "nbr_weight_decay": "scaled_gaussian",
        "max_m": 0,
        "lambda": 0.2,
        "pca_components": 20,
        "pca_solver": "arpack",
        "pca_random_state": 0,
        "explained_variance_ratio_sum": float(pca.explained_variance_ratio_.sum()),
        "graph_hash": graph_hash,
        "graph_edges": int(graph.nnz),
        "embedding_hash": hash_array(embedding),
        "input_hvg_count": int(keep.size),
        "nonconstant_own_and_neighborhood_gene_count": int(keep.sum()),
        "zero_variance_filter": "variance > 1e-12 in both own and neighborhood expression; label-free; fixed across seeds",
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return embedding, meta


def run_one(base, section: str, method: str, seed: int, epochs: int, device: torch.device):
    set_seed(seed)
    config = dataset_config(base)
    k = int(config["k"])
    adata = base.copy()
    adata.obsm["spatial"] = np.asarray(base.obsm["spatial_original"], dtype=np.float64).copy()
    graph_hash = None
    graph_edges = None

    if method == "STAGATE":
        import STAGATE_pyG as STAGATE

        radius = float(config["stagate_radius"])
        STAGATE.Cal_Spatial_Net(adata, rad_cutoff=radius, model="Radius", verbose=False)
        graph_hash, graph_edges = graph_edge_hash_from_stagate(adata.uns["Spatial_Net"], adata.obs_names)
        adata = STAGATE.train_STAGATE(
            adata,
            hidden_dims=[512, 30],
            n_epochs=epochs,
            lr=0.001,
            weight_decay=0.0001,
            random_seed=seed,
            verbose=False,
            device=device,
        )
        embedding = adata.obsm["STAGATE"]
        labels, cluster_meta = cluster_embedding(embedding, seed, reduce_to=None, k=k)
        method_meta = {
            "graph": "radius graph on frozen full-resolution pixel coordinates",
            "rad_cutoff": radius,
            "hidden_dims": [512, 30],
            "epochs": epochs,
            "learning_rate": 0.001,
            "weight_decay": 0.0001,
            "embedding_shape": list(embedding.shape),
            "cluster": cluster_meta,
        }
    elif method == "GraphST":
        from GraphST.GraphST import GraphST

        model = GraphST(
            adata,
            device=device,
            epochs=epochs,
            random_seed=seed,
            datatype=str(config["graphst_datatype"]),
        )
        adjacency = np.asarray(model.adata.obsm["adj"], dtype=np.uint8)
        graph_hash = hash_array(adjacency)
        graph_edges = int(adjacency.sum())
        adata = model.train()
        embedding = adata.obsm["emb"]
        labels, cluster_meta = cluster_embedding(embedding, seed, reduce_to=20, k=k)
        method_meta = {
            "graph": f"official GraphST {config['graphst_datatype']} spatial graph",
            "n_neighbors": 3,
            "epochs": epochs,
            "learning_rate": 0.001,
            "dim_output": 64,
            "embedding_shape": list(embedding.shape),
            "cluster": cluster_meta,
        }
    elif method == "BANKSY":
        embedding, banksy_meta = banksy_embedding(base, section)
        labels, cluster_meta = cluster_embedding(embedding, seed, reduce_to=None, k=k)
        graph_hash = banksy_meta["graph_hash"]
        graph_edges = banksy_meta["graph_edges"]
        method_meta = {
            **banksy_meta,
            "cluster": cluster_meta,
            "note": "BANKSY representation is deterministic; the common fixed-K readout receives the varied seed.",
        }
    elif method == "SpaGCN":
        import SpaGCN as spg

        # Official SpaGCN preprocessing philosophy: library-size normalization
        # and log1p on the frozen HVG universe. K is enforced through the
        # package's documented k-means initialization so resolution is not
        # re-tuned across seeds.
        hvg = np.asarray(base.var["highly_variable"], dtype=bool)
        adata = base[:, hvg].copy()
        adata.X = base.layers["counts"][:, hvg].copy()
        adata.uns.pop("log1p", None)
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)
        coords = np.asarray(base.obsm["spatial_original"], dtype=np.float64)
        cache_dir = ROOT / "environment" / "spagcn_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        adj_path = cache_dir / f"{section}_adj_xy.npy"
        l_path = cache_dir / f"{section}_l_p0.5.json"
        if adj_path.exists():
            adj = np.load(adj_path)
        else:
            adj = spg.calculate_adj_matrix(x=coords[:, 0], y=coords[:, 1], histology=False)
            np.save(adj_path, adj)
        if l_path.exists():
            l_value = float(json.loads(l_path.read_text(encoding="utf-8"))["l"])
        else:
            l_value = float(spg.search_l(0.5, adj, start=0.01, end=1000, tol=0.01, max_run=100))
            l_path.write_text(json.dumps({"p": 0.5, "l": l_value}, indent=2), encoding="utf-8")
        graph_hash = hash_array(np.asarray(adj, dtype=np.float64))
        graph_edges = int(np.sum(adj > 0) - adj.shape[0])
        clf = spg.SpaGCN()
        clf.set_l(l_value)
        clf.train(
            adata,
            adj,
            num_pcs=min(50, adata.n_vars, adata.n_obs - 1),
            lr=0.05,
            max_epochs=epochs,
            init_spa=True,
            init="kmeans",
            n_clusters=k,
            tol=5e-3,
        )
        raw_labels, _ = clf.predict()
        labels = np.asarray(
            spg.refine(
                sample_id=adata.obs_names.astype(str).tolist(),
                pred=np.asarray(raw_labels, dtype=int).tolist(),
                dis=adj,
                shape=str(config["spagcn_shape"]),
            ),
            dtype=np.int64,
        )
        method_meta = {
            "implementation": "SpaGCN 1.2.7 official package",
            "preprocessing": "frozen HVGs; counts normalize_total(1e4); log1p",
            "adjacency": "official calculate_adj_matrix on frozen coordinates; histology=False",
            "p": 0.5,
            "l": l_value,
            "num_pcs": min(50, adata.n_vars, adata.n_obs - 1),
            "epochs": epochs,
            "learning_rate": 0.05,
            "init": "official supported kmeans initialization",
            "n_clusters": k,
            "tol": 5e-3,
            "refinement": str(config["spagcn_shape"]),
            "seed_controls": "Python random, NumPy, PyTorch and CUDA seeds all set to the primary seed",
        }
    else:
        raise ValueError(method)

    return labels, {
        "coordinate_hash": hash_array(np.asarray(base.obsm["spatial_original"], dtype=np.float64)),
        "graph_hash": graph_hash,
        "graph_edges": graph_edges,
        "method_parameters": method_meta,
    }


def main() -> None:
    torch_threads = int(os.environ.get("PROJECT9_TORCH_THREADS", "0"))
    if torch_threads > 0:
        torch.set_num_threads(torch_threads)
        torch.set_num_interop_threads(1)
    parser = argparse.ArgumentParser()
    parser.add_argument("--section", required=True)
    parser.add_argument("--method", choices=["STAGATE", "GraphST", "SpaGCN", "BANKSY"], required=True)
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(1, 21)))
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--run-id", default="primary")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    frozen = ROOT / "data" / args.section / f"{args.section}_frozen.h5ad"
    if not frozen.exists():
        raise FileNotFoundError(frozen)
    output_dir = PRED_DIR / args.section
    output_dir.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / f"{args.section}_{args.method}_{args.run_id}.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    base = sc.read_h5ad(frozen)
    feature_matrix = base[:, base.var["highly_variable"]].X
    feature_hash = hash_sparse_or_dense(feature_matrix)

    if args.device == "cpu" or args.method in {"BANKSY", "SpaGCN"}:
        device = torch.device("cpu")
    elif args.device == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but unavailable")
        device = torch.device("cuda:0")
    else:
        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    logging.info(
        "section=%s method=%s run_id=%s device=%s feature_hash=%s",
        args.section, args.method, args.run_id, device, feature_hash,
    )

    for seed in args.seeds:
        stem = f"{args.method}__seed{seed}__{args.run_id}"
        pred_path = output_dir / f"{stem}.csv"
        meta_path = output_dir / f"{stem}.json"
        if pred_path.exists() and meta_path.exists() and not args.force:
            logging.info("skip completed %s", stem)
            continue
        logging.info("start %s", stem)
        started = time.time()
        labels, meta = run_one(base, args.section, args.method, seed, args.epochs, device)
        elapsed = time.time() - started
        prediction = pd.DataFrame(
            {
                "dataset": args.section,
                "method": args.method,
                "seed": seed,
                "run_id": args.run_id,
                "barcode": base.obs_names.astype(str),
                "cluster": labels,
            }
        )
        prediction.to_csv(pred_path, index=False)
        meta.update(
            {
                "dataset": args.section,
                "method": args.method,
                "seed": seed,
                "run_id": args.run_id,
                "n_spots": int(base.n_obs),
                "n_clusters_observed": int(np.unique(labels).size),
                "feature_hash": feature_hash,
                "elapsed_seconds": elapsed,
                "device": str(device),
                "torch_version": torch.__version__,
                "cuda_version": torch.version.cuda,
            }
        )
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        logging.info("finish %s elapsed=%.2fs graph=%s", stem, elapsed, meta["graph_hash"])
        del labels, prediction
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
