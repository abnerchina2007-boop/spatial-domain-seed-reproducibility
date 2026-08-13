from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import scanpy as sc


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ALL_SECTIONS = [
    "151507", "151508", "151509", "151510",
    "151669", "151670", "151671", "151672",
    "151673", "151674", "151675", "151676",
]
LABEL_SOURCE = DATA / "151507" / "barcode_level_layer_map_all.tsv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    if destination.exists() and destination.stat().st_size > 0:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    print(f"download {url} -> {destination}", flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as out:
        shutil.copyfileobj(response, out, length=1 << 20)
    temporary.replace(destination)


def prepare(section: str, force: bool = False) -> None:
    section_dir = DATA / section
    section_dir.mkdir(parents=True, exist_ok=True)
    h5 = section_dir / f"{section}_filtered_feature_bc_matrix.h5"
    positions = section_dir / "tissue_positions_list.txt"
    labels_path = section_dir / "barcode_level_layer_map_all.tsv"
    frozen = section_dir / f"{section}_frozen.h5ad"
    audit_path = section_dir / "mapping_audit.json"

    if frozen.exists() and audit_path.exists() and not force:
        print(f"skip prepared {section}", flush=True)
        return

    download(
        f"https://spatial-dlpfc.s3.us-east-2.amazonaws.com/h5/{section}_filtered_feature_bc_matrix.h5",
        h5,
    )
    download(
        f"https://raw.githubusercontent.com/LieberInstitute/HumanPilot/master/10X/{section}/tissue_positions_list.txt",
        positions,
    )
    if not labels_path.exists():
        if not LABEL_SOURCE.exists():
            raise FileNotFoundError(f"manual label map missing: {LABEL_SOURCE}")
        shutil.copy2(LABEL_SOURCE, labels_path)

    adata = sc.read_10x_h5(h5)
    adata.var_names_make_unique()
    original_barcodes = adata.obs_names.astype(str).tolist()
    pos = pd.read_csv(
        positions,
        header=None,
        names=[
            "barcode", "in_tissue", "array_row", "array_col",
            "pxl_row_in_fullres", "pxl_col_in_fullres",
        ],
        dtype={"barcode": str},
    ).set_index("barcode")
    label_map = pd.read_csv(
        labels_path,
        sep="\t",
        header=None,
        names=["barcode", "sample_id", "manual_layer"],
        dtype=str,
    )
    label_map = label_map.loc[label_map["sample_id"] == section].set_index("barcode")

    checks = {
        "section": section,
        "expression_barcode_unique": bool(adata.obs_names.is_unique),
        "position_barcode_unique": bool(pos.index.is_unique),
        "manual_label_barcode_unique": bool(label_map.index.is_unique),
        "expression_n_spots": int(adata.n_obs),
        "position_n_rows": int(pos.shape[0]),
        "manual_label_n_rows": int(label_map.shape[0]),
        "expression_missing_positions": int((~adata.obs_names.isin(pos.index)).sum()),
        "positions_not_in_expression": int((~pos.index.isin(adata.obs_names)).sum()),
        "expression_missing_manual_label": int((~adata.obs_names.isin(label_map.index)).sum()),
    }
    required = [
        checks["expression_barcode_unique"],
        checks["position_barcode_unique"],
        checks["manual_label_barcode_unique"],
        checks["expression_missing_positions"] == 0,
    ]
    if not all(required):
        raise RuntimeError(f"barcode mapping audit failed for {section}: {checks}")

    aligned_pos = pos.loc[adata.obs_names]
    aligned_labels = label_map.reindex(adata.obs_names)
    checks["position_order_matches_expression_after_loc"] = bool(
        aligned_pos.index.tolist() == original_barcodes
    )
    checks["manual_label_order_matches_expression_after_reindex"] = bool(
        aligned_labels.index.tolist() == original_barcodes
    )

    for column in aligned_pos.columns:
        adata.obs[column] = aligned_pos[column].to_numpy()
    adata.obs["sample_id"] = section
    adata.obs["manual_layer"] = aligned_labels["manual_layer"].to_numpy()
    adata.obsm["spatial_original"] = aligned_pos[
        ["pxl_col_in_fullres", "pxl_row_in_fullres"]
    ].to_numpy(dtype=np.float64)
    adata.obsm["spatial"] = adata.obsm["spatial_original"].copy()
    adata.layers["counts"] = adata.X.copy()

    sc.pp.filter_genes(adata, min_cells=3)
    genes_after_filter = adata.var_names.astype(str).tolist()
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    sc.pp.highly_variable_genes(adata, flavor="seurat", n_top_genes=3000)
    hvg_names = adata.var_names[adata.var["highly_variable"]].astype(str).tolist()
    sc.pp.scale(adata, zero_center=False, max_value=10)

    checks.update(
        {
            "final_n_spots": int(adata.n_obs),
            "final_n_genes": int(adata.n_vars),
            "n_hvg": int(adata.var["highly_variable"].sum()),
            "spot_order_unchanged": bool(adata.obs_names.astype(str).tolist() == original_barcodes),
            "genes_after_filter_sha256": hashlib.sha256("\n".join(genes_after_filter).encode()).hexdigest(),
            "hvg_names_sha256": hashlib.sha256("\n".join(hvg_names).encode()).hexdigest(),
            "input_h5_sha256": sha256(h5),
            "positions_sha256": sha256(positions),
            "labels_sha256": sha256(labels_path),
            "manual_layer_counts": {
                str(k): int(v) for k, v in adata.obs["manual_layer"].value_counts(dropna=False).items()
            },
            "preprocessing": {
                "spot_filter": "none",
                "gene_filter": "min_cells=3",
                "normalization": "normalize_total(target_sum=10000)",
                "transform": "log1p",
                "hvg": "seurat flavor, n_top_genes=3000; selected without manual labels",
                "scale": "zero_center=False, max_value=10",
            },
        }
    )
    adata.uns["project9_mapping_audit"] = checks
    adata.write_h5ad(frozen, compression="gzip")
    checks["frozen_h5ad_sha256"] = sha256(frozen)
    audit_path.write_text(json.dumps(checks, indent=2), encoding="utf-8")
    print(json.dumps(checks, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sections", nargs="+", default=["151507"])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    sections = ALL_SECTIONS if args.all else args.sections
    invalid = sorted(set(sections) - set(ALL_SECTIONS))
    if invalid:
        raise ValueError(f"unknown DLPFC sections: {invalid}")
    for section in sections:
        prepare(section, force=args.force)


if __name__ == "__main__":
    main()
