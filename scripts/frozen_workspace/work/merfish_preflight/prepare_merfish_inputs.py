from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import scanpy as sc
import scipy.io
import scipy.sparse as sp
from scipy.spatial import cKDTree


ROOT = Path("work/merfish_preflight")
SOURCE_ROOT = ROOT / "exported_sections"
FROZEN_ROOT = ROOT / "frozen_inputs"
SECTIONS = ["-0.04", "-0.09", "-0.14", "-0.19", "-0.24"]
K = 8
RADIUS = 150.0


def section_id(bregma: str) -> str:
    return f"MERFISH_Bregma_m{bregma.removeprefix('-')}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def geometry_audit(coords: np.ndarray) -> dict:
    tree = cKDTree(coords)
    nn_distances = tree.query(coords, k=2)[0][:, 1]
    neighbors = tree.query_ball_point(coords, r=RADIUS)
    degrees = np.asarray([len(row) - 1 for row in neighbors], dtype=np.int64)
    directed_edges = int(degrees.sum())
    n = coords.shape[0]
    return {
        "median_nearest_neighbor_distance": float(np.median(nn_distances)),
        "radius": RADIUS,
        "directed_edges": directed_edges,
        "undirected_edges": directed_edges // 2,
        "mean_degree": float(degrees.mean()),
        "min_degree": int(degrees.min()),
        "degree_q05": float(np.quantile(degrees, 0.05)),
        "degree_median": float(np.median(degrees)),
        "degree_q95": float(np.quantile(degrees, 0.95)),
        "max_degree": int(degrees.max()),
        "isolated_cells": int((degrees == 0).sum()),
        "banksy_15_neighbors_valid": bool(n > 15 and np.all(np.isfinite(coords))),
        "graphst_3_neighbors_valid": bool(n > 3 and np.all(np.isfinite(coords))),
        "spagcn_dense_float64_gib": float(n * n * 8 / (1024**3)),
    }


def main() -> None:
    FROZEN_ROOT.mkdir(parents=True, exist_ok=True)
    records = []
    gene_order = None
    for bregma in SECTIONS:
        sid = section_id(bregma)
        source_dir = SOURCE_ROOT / sid
        matrix_path = source_dir / "expression_normalized.mtx"
        cells_path = source_dir / "cells.tsv"
        genes_path = source_dir / "genes.tsv"
        matrix = scipy.io.mmread(matrix_path).tocsr().astype(np.float64)
        cells = pd.read_csv(cells_path, sep="\t", dtype={"cell_id": str})
        genes = pd.read_csv(genes_path, sep="\t")["gene"].astype(str).tolist()
        if gene_order is None:
            gene_order = genes
        if genes != gene_order:
            raise RuntimeError(f"Gene order differs in {sid}")
        if matrix.shape != (len(cells), len(genes)):
            raise RuntimeError((sid, matrix.shape, len(cells), len(genes)))
        if cells["cell_id"].duplicated().any() or len(set(genes)) != len(genes):
            raise RuntimeError(f"Duplicate identifiers in {sid}")

        obs = cells.set_index("cell_id", drop=True)
        var = pd.DataFrame(index=pd.Index(genes, name="gene"))
        adata = ad.AnnData(X=matrix, obs=obs, var=var)
        adata.obs["sample_id"] = sid
        adata.obs["bregma_mm"] = float(bregma)
        adata.obs["manual_layer"] = adata.obs["reference_domain"].astype(str)
        coords = adata.obs[["x", "y"]].to_numpy(dtype=np.float64)
        adata.obsm["spatial_original"] = coords.copy()
        adata.obsm["spatial"] = coords.copy()
        adata.layers["counts"] = adata.X.copy()

        before = adata.n_vars
        sc.pp.filter_genes(adata, min_cells=3)
        after = adata.n_vars
        if before != 155 or after != 155:
            raise RuntimeError(f"Unexpected gene filtering in {sid}: {before}->{after}")
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)
        adata.var["highly_variable"] = True
        sc.pp.scale(adata, zero_center=False, max_value=10)
        adata.uns["phase1_dataset"] = {
            "dataset": sid,
            "k": K,
            "technology": "MERFISH single-cell imaging",
            "reference_field": "manual_layer",
            "graphst_datatype": "Stereo",
            "stagate_radius": RADIUS,
            "spagcn_shape": "hexagon",
            "preprocessing": "min_cells=3; normalize_total=1e4; log1p; all 155 valid targeted genes; scale zero_center=False max=10",
            "source_expression_note": "BASS/Moffitt volume-normalized MERFISH expression; not integer raw transcript counts",
        }
        out_dir = FROZEN_ROOT / sid
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{sid}_frozen.h5ad"
        adata.write_h5ad(out_path, compression="gzip")

        record = {
            "dataset": sid,
            "bregma_mm": float(bregma),
            "n_cells": int(adata.n_obs),
            "n_genes": int(adata.n_vars),
            "K": K,
            "reference_labels": sorted(adata.obs["manual_layer"].unique().tolist()),
            "label_counts": {str(k): int(v) for k, v in adata.obs["manual_layer"].value_counts().sort_index().items()},
            "geometry": geometry_audit(coords),
            "source_files": [
                {"path": str(p), "bytes": p.stat().st_size, "sha256": sha256(p)}
                for p in (matrix_path, cells_path, genes_path)
            ],
            "frozen_h5ad": str(out_path),
            "frozen_h5ad_bytes": out_path.stat().st_size,
            "frozen_h5ad_sha256": sha256(out_path),
        }
        records.append(record)
        (out_dir / "input_audit.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    (ROOT / "prepared_input_audit.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
