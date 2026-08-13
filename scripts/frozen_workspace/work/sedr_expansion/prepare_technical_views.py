"""Create label-blind technical AnnData views for the SEDR preflight.

The HDF5 read allow-list is intentionally narrow:

* layers/counts
* obsm/spatial
* the obs index dataset named by obs.attrs['_index']
* the var index dataset named by var.attrs['_index']

No other obs/var values are opened. No normalization, filtering, feature
selection, PCA, graph construction, or model computation is performed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import anndata as ad
import h5py
import numpy as np
import pandas as pd
from scipy import sparse


ROOT = Path(__file__).resolve().parents[2]
AUDIT_CSV = (
    ROOT / "outputs" / "PROJECT9_SEDR_EXPANSION"
    / "SEDR_INPUT_STRUCTURAL_AUDIT.csv"
)
OUT_DIR = (
    ROOT / "outputs" / "PROJECT9_SEDR_EXPANSION" / "technical_inputs"
)
MANIFEST = OUT_DIR / "TECHNICAL_INPUT_MANIFEST.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def decode(value: object) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def string_vector(node: h5py.Dataset) -> list[str]:
    return [decode(value) for value in node[:]]


def ordered_string_hash(values: list[str]) -> str:
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest().upper()


def array_hash(values: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(values)
    return hashlib.sha256(contiguous.tobytes(order="C")).hexdigest().upper()


def sparse_canonical_hash(matrix: sparse.spmatrix) -> str:
    canonical = sparse.csr_matrix(matrix, copy=True)
    canonical.sum_duplicates()
    canonical.sort_indices()
    digest = hashlib.sha256()
    digest.update(np.asarray(canonical.shape, dtype="<i8").tobytes())
    digest.update(np.ascontiguousarray(canonical.indptr).tobytes())
    digest.update(np.ascontiguousarray(canonical.indices).tobytes())
    digest.update(np.ascontiguousarray(canonical.data).tobytes())
    return digest.hexdigest().upper()


def dense_canonical_hash(matrix: np.ndarray) -> str:
    values = np.ascontiguousarray(matrix)
    digest = hashlib.sha256()
    digest.update(np.asarray(values.shape, dtype="<i8").tobytes())
    digest.update(values.tobytes(order="C"))
    return digest.hexdigest().upper()


def matrix_hash(matrix: np.ndarray | sparse.spmatrix) -> str:
    if sparse.issparse(matrix):
        return sparse_canonical_hash(matrix)
    return dense_canonical_hash(np.asarray(matrix))


def read_allowed_source(path: Path) -> dict[str, Any]:
    """Read only the explicitly permitted HDF5 datasets."""
    with h5py.File(path, "r") as handle:
        obs_index_key = decode(handle["obs"].attrs.get("_index", "_index"))
        var_index_key = decode(handle["var"].attrs.get("_index", "_index"))

        # The only obs/var datasets opened are their designated indices.
        obs_names = string_vector(handle["obs"][obs_index_key])
        var_names = string_vector(handle["var"][var_index_key])
        spatial = np.asarray(handle["obsm"]["spatial"][:])

        counts_node = handle["layers"]["counts"]
        if isinstance(counts_node, h5py.Group):
            encoding = decode(counts_node.attrs.get("encoding-type", "csr_matrix"))
            shape = tuple(int(value) for value in counts_node.attrs["shape"])
            data = np.asarray(counts_node["data"][:])
            indices = np.asarray(counts_node["indices"][:])
            indptr = np.asarray(counts_node["indptr"][:])
            if encoding == "csr_matrix":
                counts: np.ndarray | sparse.spmatrix = sparse.csr_matrix(
                    (data, indices, indptr), shape=shape
                )
            elif encoding == "csc_matrix":
                counts = sparse.csc_matrix(
                    (data, indices, indptr), shape=shape
                ).tocsr()
            else:
                raise ValueError(f"Unsupported counts encoding: {encoding}")
        else:
            encoding = decode(counts_node.attrs.get("encoding-type", "array"))
            counts = np.asarray(counts_node[:])
            shape = tuple(int(value) for value in counts.shape)

    if shape != (len(obs_names), len(var_names)):
        raise ValueError(
            f"Source shape/index mismatch for {path}: "
            f"{shape}, {len(obs_names)}, {len(var_names)}"
        )
    if spatial.shape != (len(obs_names), 2):
        raise ValueError(f"Invalid spatial shape for {path}: {spatial.shape}")

    return {
        "counts": counts,
        "counts_encoding": encoding,
        "obs_names": obs_names,
        "var_names": var_names,
        "obs_index_key": obs_index_key,
        "var_index_key": var_index_key,
        "spatial": spatial,
    }


def validate_written(
    output_path: Path,
    expected: dict[str, Any],
) -> dict[str, Any]:
    with h5py.File(output_path, "r") as handle:
        top_keys = sorted(handle.keys())
        obs_keys = sorted(handle["obs"].keys())
        var_keys = sorted(handle["var"].keys())
        obsm_keys = sorted(handle["obsm"].keys())
        layer_keys = sorted(handle["layers"].keys())

    # AnnData creates its standard empty containers, but obs and var must each
    # contain only their index dataset and obsm must contain only spatial.
    if len(obs_keys) != 1 or len(var_keys) != 1:
        raise ValueError(
            f"Non-index obs/var fields detected in {output_path}: "
            f"obs={obs_keys}, var={var_keys}"
        )
    if obsm_keys != ["spatial"] or layer_keys:
        raise ValueError(
            f"Unexpected technical-view content in {output_path}: "
            f"obsm={obsm_keys}, layers={layer_keys}"
        )

    view = ad.read_h5ad(output_path, backed="r")
    try:
        obs_names = [str(value) for value in view.obs_names]
        var_names = [str(value) for value in view.var_names]
        spatial = np.asarray(view.obsm["spatial"])
        # A backed sparse dataset is not itself recognized by scipy.issparse,
        # but slicing it materializes the intended CSR matrix.
        materialized_x = view.X[:]
        if sparse.issparse(materialized_x):
            counts = materialized_x
        else:
            counts = np.asarray(materialized_x)
    finally:
        view.file.close()

    checks = {
        "shape_match": tuple(counts.shape) == tuple(expected["counts"].shape),
        "obs_order_match": obs_names == expected["obs_names"],
        "var_order_match": var_names == expected["var_names"],
        "obs_hash_match": (
            ordered_string_hash(obs_names)
            == ordered_string_hash(expected["obs_names"])
        ),
        "var_hash_match": (
            ordered_string_hash(var_names)
            == ordered_string_hash(expected["var_names"])
        ),
        "counts_hash_match": matrix_hash(counts) == matrix_hash(expected["counts"]),
        "spatial_hash_match": array_hash(spatial) == array_hash(expected["spatial"]),
        "obs_only_index": len(obs_keys) == 1,
        "var_only_index": len(var_keys) == 1,
        "obsm_only_spatial": obsm_keys == ["spatial"],
        "no_layers": not layer_keys,
    }
    checks["valid"] = all(checks.values())
    checks["top_level_keys"] = top_keys
    checks["obs_keys"] = obs_keys
    checks["var_keys"] = var_keys
    checks["obsm_keys"] = obsm_keys
    return checks


def build_one(audit_row: dict[str, str]) -> dict[str, Any]:
    dataset = audit_row["dataset"]
    source_path = Path(audit_row["input_path"])
    if sha256_file(source_path) != audit_row["locked_sha256"]:
        raise ValueError(f"Locked source hash mismatch: {dataset}")

    source = read_allowed_source(source_path)
    output_path = OUT_DIR / f"{dataset}_SEDR_technical.h5ad"
    temporary_path = output_path.with_suffix(".h5ad.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    technical = ad.AnnData(
        X=source["counts"],
        obs=pd.DataFrame(index=pd.Index(source["obs_names"])),
        var=pd.DataFrame(index=pd.Index(source["var_names"])),
        obsm={"spatial": source["spatial"]},
    )
    technical.write_h5ad(temporary_path, compression="gzip")
    pre_replace_validation = validate_written(temporary_path, source)
    if not pre_replace_validation["valid"]:
        raise ValueError(f"Temporary technical input failed validation: {dataset}")
    os.replace(temporary_path, output_path)
    final_validation = validate_written(output_path, source)
    if not final_validation["valid"]:
        raise ValueError(f"Final technical input failed validation: {dataset}")

    return {
        "dataset": dataset,
        "source_path": str(source_path.resolve()),
        "source_bytes": source_path.stat().st_size,
        "source_sha256": sha256_file(source_path),
        "locked_source_sha256": audit_row["locked_sha256"],
        "source_hash_match": True,
        "technical_path": str(output_path.resolve()),
        "technical_bytes": output_path.stat().st_size,
        "technical_sha256": sha256_file(output_path),
        "shape": list(source["counts"].shape),
        "source_counts_encoding": source["counts_encoding"],
        "output_X_encoding": (
            "csr_matrix" if sparse.issparse(source["counts"]) else "array"
        ),
        "obs_index_source_key": source["obs_index_key"],
        "var_index_source_key": source["var_index_key"],
        "obs_count": len(source["obs_names"]),
        "var_count": len(source["var_names"]),
        "obs_order_sha256_newline_utf8": ordered_string_hash(
            source["obs_names"]
        ),
        "var_order_sha256_newline_utf8": ordered_string_hash(
            source["var_names"]
        ),
        "counts_canonical_sha256": matrix_hash(source["counts"]),
        "spatial_rawbytes_sha256": array_hash(source["spatial"]),
        "read_allowlist": [
            "layers/counts",
            f"obs/{source['obs_index_key']}",
            f"var/{source['var_index_key']}",
            "obsm/spatial",
        ],
        "validation": final_validation,
        "status": "PASS",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--audit-csv", type=Path, default=AUDIT_CSV,
        help="Outcome-blind structural audit CSV",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with args.audit_csv.open(newline="", encoding="utf-8-sig") as handle:
        audit_rows = list(csv.DictReader(handle))
    if len(audit_rows) != 19:
        raise SystemExit(f"Expected 19 structural-audit rows, found {len(audit_rows)}")
    if any(row["structural_status"] != "PASS" for row in audit_rows):
        raise SystemExit("Refusing to build from a failed structural audit")

    records = [build_one(row) for row in audit_rows]
    manifest = {
        "artifact": "Project 9 SEDR label-blind technical input views",
        "entry_count": len(records),
        "pass_count": sum(record["status"] == "PASS" for record in records),
        "label_blind": True,
        "reference_annotation_values_read": False,
        "scientific_preprocessing_performed": False,
        "scientific_outcomes_computed_or_inspected": False,
        "read_allowlist": [
            "layers/counts",
            "obs/<H5AD designated index>",
            "var/<H5AD designated index>",
            "obsm/spatial",
        ],
        "write_contract": (
            "X is an exact CSR/dense copy of frozen layers/counts; obs and var "
            "contain only their ordered indices; obsm contains only spatial."
        ),
        "atomic_write": "temporary .h5ad.tmp validated, then os.replace",
        "entries": records,
    }
    temporary_manifest = MANIFEST.with_suffix(".json.tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_manifest, MANIFEST)
    print(f"PASS {manifest['pass_count']}/{manifest['entry_count']}")


if __name__ == "__main__":
    main()
