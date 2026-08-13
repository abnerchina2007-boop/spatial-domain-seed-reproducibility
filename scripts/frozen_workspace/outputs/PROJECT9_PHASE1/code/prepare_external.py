from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import scanpy as sc


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def freeze_common(adata, dataset: str, k: int, technology: str, reference: str,
                  graphst_datatype: str, stagate_radius: float, spagcn_shape: str,
                  source_files: list[Path], mapping_checks: dict) -> None:
    adata.var_names_make_unique()
    adata.layers["counts"] = adata.X.copy()
    before = adata.n_vars
    sc.pp.filter_genes(adata, min_cells=3)
    after = adata.n_vars
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    if adata.n_vars <= 3000:
        adata.var["highly_variable"] = True
        hvg_rule = "all genes after min_cells=3 because n_vars<=3000"
    else:
        sc.pp.highly_variable_genes(adata, flavor="seurat", n_top_genes=3000)
        hvg_rule = "scanpy seurat 3000 HVGs, matching Phase 0"
    hvg_n = int(adata.var["highly_variable"].sum())
    sc.pp.scale(adata, zero_center=False, max_value=10)
    adata.uns["phase1_dataset"] = {
        "dataset": dataset,
        "k": int(k),
        "technology": technology,
        "reference_field": reference,
        "graphst_datatype": graphst_datatype,
        "stagate_radius": float(stagate_radius),
        "spagcn_shape": spagcn_shape,
        "preprocessing": "min_cells=3; normalize_total=1e4; log1p; HVG; scale zero_center=False max=10",
    }
    audit = {
        "dataset": dataset,
        "n_spots": int(adata.n_obs),
        "genes_before_filter": int(before),
        "genes_after_filter": int(after),
        "hvg_count": hvg_n,
        "hvg_rule": hvg_rule,
        "reference_field": reference,
        "reference_categories": sorted(adata.obs["manual_layer"].dropna().astype(str).unique().tolist()),
        "k": int(k),
        "mapping_checks": mapping_checks,
        "sources": [{"path": str(p), "sha256": sha256(p)} for p in source_files],
    }
    out_dir = ROOT / "data" / dataset
    out = out_dir / f"{dataset}_frozen.h5ad"
    adata.write_h5ad(out, compression="gzip")
    audit["frozen_h5ad_sha256"] = sha256(out)
    (out_dir / "mapping_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps(audit, indent=2))


def prepare_starmap() -> None:
    dataset = "STARmap_20180505_BY3_1k"
    base = ROOT / "data" / dataset / "raw" / "extracted" / "STARmap_mouse_visual_cortex"
    source = base / "STARmap_20180505_BY3_1k.h5ad"
    annotation = base / "gt" / "Annotation_STARmap_20180505_BY3_1k.txt"
    adata = sc.read_h5ad(source)
    original = adata.obs_names.astype(str).tolist()
    ann = pd.read_csv(annotation, sep="\t", index_col=0)
    checks = {
        "source_obs_unique": bool(adata.obs_names.is_unique),
        "annotation_index_unique": bool(ann.index.is_unique),
        "annotation_covers_source": set(original).issubset(set(ann.index.astype(str))),
        "embedded_reference_has_7_categories": int(adata.obs["label"].nunique()) == 7,
        "embedded_coordinates_match_XY": bool(np.allclose(np.asarray(adata.obsm["spatial"]), adata.obs[["X", "Y"]].to_numpy())),
    }
    if not all(checks.values()):
        raise RuntimeError(checks)
    adata.obs["sample_id"] = dataset
    adata.obs["manual_layer"] = adata.obs["label"].astype(str).to_numpy()
    adata.obs["fine_original_annotation"] = ann.reindex(original)["Annotation"].astype(str).to_numpy()
    adata.obsm["spatial_original"] = np.asarray(adata.obsm["spatial"], dtype=np.float64).copy()
    freeze_common(adata, dataset, 7, "STARmap in situ sequencing", "manual_layer",
                  "Stereo", 150.0, "hexagon", [source, annotation], checks)


def prepare_hbca1() -> None:
    dataset = "HBCA1"
    base = ROOT / "data" / dataset / "raw"
    h5 = base / "filtered_feature_bc_matrix.h5"
    meta_path = base / "metadata.tsv"
    pos_path = base / "spatial_extract" / "spatial" / "tissue_positions_list.csv"
    adata = sc.read_10x_h5(h5)
    adata.var_names_make_unique()
    meta = pd.read_csv(meta_path, sep="\t", index_col=0)
    pos = pd.read_csv(pos_path, header=None, index_col=0,
                      names=["barcode", "in_tissue", "array_row", "array_col", "pxl_row_in_fullres", "pxl_col_in_fullres"])
    original = adata.obs_names.astype(str).tolist()
    checks = {
        "expression_obs_unique": bool(adata.obs_names.is_unique),
        "metadata_index_unique": bool(meta.index.is_unique),
        "positions_index_unique": bool(pos.index.is_unique),
        "metadata_exact_barcode_set": set(original) == set(meta.index.astype(str)),
        "positions_cover_expression": set(original).issubset(set(pos.index.astype(str))),
        "fine_reference_has_20_categories": int(meta["fine_annot_type"].nunique()) == 20,
    }
    if not all(checks.values()):
        raise RuntimeError(checks)
    meta = meta.reindex(original); pos = pos.reindex(original)
    for col in pos.columns:
        adata.obs[col] = pos[col].to_numpy()
    adata.obs["sample_id"] = dataset
    adata.obs["annot_type"] = meta["annot_type"].astype(str).to_numpy()
    adata.obs["manual_layer"] = meta["fine_annot_type"].astype(str).to_numpy()
    adata.obsm["spatial_original"] = pos[["pxl_col_in_fullres", "pxl_row_in_fullres"]].to_numpy(dtype=np.float64)
    adata.obsm["spatial"] = adata.obsm["spatial_original"].copy()
    freeze_common(adata, dataset, 20, "10x Visium human breast cancer", "manual_layer",
                  "10X", 150.0, "hexagon", [h5, meta_path, pos_path], checks)


if __name__ == "__main__":
    prepare_starmap()
    prepare_hbca1()
