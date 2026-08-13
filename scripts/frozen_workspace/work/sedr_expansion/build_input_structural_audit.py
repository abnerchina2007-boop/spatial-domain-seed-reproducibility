"""Build the outcome-blind Project 9 SEDR structural input audit.

This script deliberately reads only H5AD structure, observation identifiers,
expression matrices, and coordinates. It never reads values from any obs
annotation column other than the H5AD observation index.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "PROJECT9_SEDR_EXPANSION"

DLPFC = [
    "151507", "151508", "151509", "151510", "151669", "151670",
    "151671", "151672", "151673", "151674", "151675", "151676",
]
MERFISH = [
    "MERFISH_Bregma_m0.04", "MERFISH_Bregma_m0.09",
    "MERFISH_Bregma_m0.14", "MERFISH_Bregma_m0.19",
    "MERFISH_Bregma_m0.24",
]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def decode(value: object) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def matrix_shape(node: h5py.Dataset | h5py.Group) -> tuple[int, int]:
    if isinstance(node, h5py.Dataset):
        return tuple(int(value) for value in node.shape)
    return tuple(int(value) for value in node.attrs["shape"])


def inspect_matrix(
    node: h5py.Dataset | h5py.Group, n_obs: int, n_vars: int
) -> dict[str, object]:
    finite = True
    nonnegative = True
    integer_like = True
    nnz = 0
    nonzero_genes = np.zeros(n_vars, dtype=bool)
    storage_valid = True

    if isinstance(node, h5py.Group):
        data = node["data"]
        indices = node["indices"]
        indptr = node["indptr"]
        for start in range(0, len(data), 1_000_000):
            values = data[start : start + 1_000_000]
            gene_indices = indices[start : start + 1_000_000]
            finite &= bool(np.isfinite(values).all())
            nonnegative &= bool((values >= 0).all())
            integer_like &= bool(
                np.allclose(values, np.rint(values), rtol=0, atol=1e-8)
            )
            nnz += int(np.count_nonzero(values))
            nonzero_genes[np.asarray(gene_indices, dtype=np.int64)] |= values != 0
        pointers = indptr[:]
        storage_valid = bool(
            len(pointers) == n_obs + 1
            and pointers[0] == 0
            and pointers[-1] == len(data)
            and np.all(pointers[1:] >= pointers[:-1])
            and (
                len(indices) == 0
                or (indices[:].min() >= 0 and indices[:].max() < n_vars)
            )
        )
        dtype = str(data.dtype)
        encoding = decode(node.attrs.get("encoding-type", "sparse"))
    else:
        for start in range(0, n_obs, 512):
            values = node[start : start + 512, :]
            finite &= bool(np.isfinite(values).all())
            nonnegative &= bool((values >= 0).all())
            integer_like &= bool(
                np.allclose(values, np.rint(values), rtol=0, atol=1e-8)
            )
            nnz += int(np.count_nonzero(values))
            nonzero_genes |= np.any(values != 0, axis=0)
        dtype = str(node.dtype)
        encoding = decode(node.attrs.get("encoding-type", "array"))

    return {
        "encoding": encoding,
        "dtype": dtype,
        "finite": finite,
        "nonnegative": nonnegative,
        "integer_like": integer_like,
        "nnz": nnz,
        "nonzero_genes": int(nonzero_genes.sum()),
        "storage_valid": storage_valid,
    }


def locked_hashes() -> tuple[dict[str, str], dict[str, str]]:
    values: dict[str, str] = {}
    sources: dict[str, str] = {}

    phase1_hashes = (
        ROOT / "outputs" / "PROJECT9_PHASE1" / "tables"
        / "phase0_frozen_data_hash_checks.csv"
    )
    with phase1_hashes.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            values[row["dataset"]] = row["phase1_frozen_sha256"].upper()
            sources[row["dataset"]] = str(phase1_hashes.relative_to(ROOT))

    # These two frozen hashes were locked in the corresponding mapping audits.
    # They are transcribed here so this outcome-blind script never opens those
    # legacy JSON files, which also contain reference-annotation summaries.
    external_locked = {
        "STARmap_20180505_BY3_1k": (
            "9C8CF484E296126F4004BF7174E70C3BD2A0236120767F849C213B4D88D186E9"
        ),
        "HBCA1": (
            "D57FEF37A62AF05451AE2F6B6AA151F18C590DA8E331D64715E655FAABDD4905"
        ),
    }
    for dataset, locked_hash in external_locked.items():
        source = (
            ROOT / "outputs" / "PROJECT9_PHASE1" / "data" / dataset
            / "mapping_audit.json"
        )
        values[dataset] = locked_hash
        sources[dataset] = str(source.relative_to(ROOT))

    merfish_source = (
        ROOT / "outputs" / "PROJECT9_MERFISH_EXPANSION"
        / "INTEGRITY_SHA256.csv"
    )
    with merfish_source.open(newline="", encoding="utf-8-sig") as handle:
        for record in csv.DictReader(handle):
            relative_path = record["relative_path"]
            if not (
                relative_path.startswith("data/MERFISH_Bregma_")
                and relative_path.endswith("_frozen.h5ad")
            ):
                continue
            dataset = Path(relative_path).parent.name
            values[dataset] = record["sha256"].upper()
            sources[dataset] = str(merfish_source.relative_to(ROOT))

    return values, sources


def entries() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for dataset in DLPFC:
        rows.append(
            {
                "dataset": dataset,
                "display_name": dataset,
                "platform_class": "spot-level 10x Visium",
                "graph_class": "spot-level; official SEDR Visium KNN rule",
                "requested_K": 7,
                "path": ROOT / "outputs" / "PROJECT9_PHASE1" / "data"
                / dataset / f"{dataset}_frozen.h5ad",
            }
        )
    rows.extend(
        [
            {
                "dataset": "STARmap_20180505_BY3_1k",
                "display_name": "STARmap",
                "platform_class": "cell-level STARmap in situ sequencing",
                "graph_class": "cell-level; official SEDR high-resolution KNN rule",
                "requested_K": 7,
                "path": ROOT / "outputs" / "PROJECT9_PHASE1" / "data"
                / "STARmap_20180505_BY3_1k"
                / "STARmap_20180505_BY3_1k_frozen.h5ad",
            },
            {
                "dataset": "HBCA1",
                "display_name": "HBCA1",
                "platform_class": "spot-level 10x Visium",
                "graph_class": "spot-level; official SEDR Visium KNN rule",
                "requested_K": 20,
                "path": ROOT / "outputs" / "PROJECT9_PHASE1" / "data"
                / "HBCA1" / "HBCA1_frozen.h5ad",
            },
        ]
    )
    for dataset in MERFISH:
        rows.append(
            {
                "dataset": dataset,
                "display_name": dataset.replace("MERFISH_Bregma_m", "Bregma -") + " mm",
                "platform_class": "cell-level MERFISH",
                "graph_class": "cell-level; official SEDR high-resolution KNN rule",
                "requested_K": 8,
                "path": ROOT / "outputs" / "PROJECT9_MERFISH_EXPANSION"
                / "data" / dataset / f"{dataset}_frozen.h5ad",
            }
        )
    return rows


def build() -> list[dict[str, object]]:
    expected_hashes, hash_sources = locked_hashes()
    output: list[dict[str, object]] = []

    for spec in entries():
        dataset = str(spec["dataset"])
        path = Path(spec["path"])
        actual_hash = file_sha256(path)
        with h5py.File(path, "r") as handle:
            n_obs, n_vars = matrix_shape(handle["X"])
            obs = handle["obs"]
            index_key = decode(obs.attrs.get("_index", "_index"))
            obs_ids = [decode(value) for value in obs[index_key][:]]
            obs_hash = hashlib.sha256(
                "\n".join(obs_ids).encode("utf-8")
            ).hexdigest().upper()
            counts = inspect_matrix(handle["layers"]["counts"], n_obs, n_vars)
            spatial = handle["obsm"]["spatial"][:]
            spatial_original = handle["obsm"]["spatial_original"][:]

        expected_hash = expected_hashes[dataset]
        structural_pass = bool(
            actual_hash == expected_hash
            and len(obs_ids) == n_obs
            and len(set(obs_ids)) == n_obs
            and counts["finite"]
            and counts["nonnegative"]
            and counts["storage_valid"]
            and counts["nonzero_genes"] == n_vars
            and spatial.shape == (n_obs, 2)
            and np.isfinite(spatial).all()
            and np.array_equal(spatial, spatial_original)
            and n_obs > int(spec["requested_K"])
            and n_vars > 1
        )
        output.append(
            {
                "dataset": dataset,
                "display_name": spec["display_name"],
                "platform_class": spec["platform_class"],
                "graph_class": spec["graph_class"],
                "requested_K": spec["requested_K"],
                "input_path": str(path.resolve()),
                "input_bytes": path.stat().st_size,
                "input_sha256": actual_hash,
                "locked_sha256": expected_hash,
                "locked_hash_source": hash_sources[dataset],
                "hash_match": actual_hash == expected_hash,
                "n_obs": n_obs,
                "n_vars": n_vars,
                "obs_index_key": index_key,
                "obs_ids_unique": len(set(obs_ids)) == n_obs,
                "obs_ids_sha256_newline_utf8": obs_hash,
                "count_layer": "layers/counts",
                "count_encoding": counts["encoding"],
                "count_dtype": counts["dtype"],
                "count_finite": counts["finite"],
                "count_nonnegative": counts["nonnegative"],
                "count_integer_like": counts["integer_like"],
                "count_nnz": counts["nnz"],
                "nonzero_genes": counts["nonzero_genes"],
                "coordinate_key": "obsm/spatial",
                "coordinate_shape": f"{spatial.shape[0]}x{spatial.shape[1]}",
                "coordinates_finite": bool(np.isfinite(spatial).all()),
                "spatial_original_equal": bool(
                    np.array_equal(spatial, spatial_original)
                ),
                "enough_observations_for_K": n_obs > int(spec["requested_K"]),
                "enough_features_for_PCA": n_vars > 1,
                "structural_status": "PASS" if structural_pass else "FAIL",
            }
        )
    return output


def write_outputs(rows: list[dict[str, object]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / "SEDR_INPUT_STRUCTURAL_AUDIT.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "audit_type": "outcome-blind structural input audit",
        "scientific_outcomes_inspected": False,
        "reference_annotation_values_read": False,
        "entry_count": len(rows),
        "pass_count": sum(row["structural_status"] == "PASS" for row in rows),
        "matrix_rule": "Use the frozen layers/counts representation.",
        "coordinate_rule": "Use obsm/spatial in frozen observation order.",
        "merfish_expression_note": (
            "MERFISH layers/counts is the authoritative frozen BASS/Moffitt "
            "processed-expression layer; it is not an integer raw-count matrix."
        ),
        "entries": rows,
    }
    json_path = OUT / "SEDR_INPUT_STRUCTURAL_AUDIT.manifest.json"
    json_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# SEDR input structural audit",
        "",
        "**Status:** `PASS` — 19/19 frozen Project 9 inputs passed.",
        "",
        "This was an outcome-blind structural audit. Reference-annotation values "
        "were not read, and no scientific accuracy, reproducibility, ranking, "
        "marker, consensus, or spatial-partition result was computed or inspected.",
        "",
        "## Frozen input rules",
        "",
        "- Expression source: `layers[\"counts\"]` in exact frozen observation order.",
        "- Coordinates: `obsm[\"spatial\"]`; all inputs also contain an exactly "
        "equal `obsm[\"spatial_original\"]`.",
        "- Observation identity: the H5AD observation index only; identifiers are "
        "unique in all 19 inputs.",
        "- DLPFC and HBCA1 are spot-level 10x Visium; STARmap and MERFISH are "
        "cell-level/in-situ inputs. This class determines the later source-grounded "
        "SEDR spatial-neighborhood rule; graph sizes were not selected here.",
        "- MERFISH `layers[\"counts\"]` is the frozen BASS/Moffitt processed-expression "
        "layer, not a uniform raw integer-count matrix.",
        "",
        "## Audit table",
        "",
        "| Dataset | Platform class | Shape | K | Count representation | Hash | Status |",
        "|---|---|---:|---:|---|---|---|",
    ]
    for row in rows:
        count_note = f"{row['count_encoding']}/{row['count_dtype']}"
        lines.append(
            f"| {row['display_name']} | {row['platform_class']} | "
            f"{row['n_obs']:,} × {row['n_vars']:,} | {row['requested_K']} | "
            f"{count_note} | `{row['input_sha256']}` | "
            f"`{row['structural_status']}` |"
        )
    lines.extend(
        [
            "",
            "## Checks applied",
            "",
            "Every row required: input existence; exact match to its prior locked "
            "SHA-256; unique observation IDs; finite and nonnegative frozen expression; "
            "valid matrix storage; at least one nonzero value for every retained gene; "
            "finite two-dimensional coordinates for every observation; exact equality "
            "of frozen `spatial` and `spatial_original`; sufficient observations for "
            "requested K; and sufficient features for a valid PCA.",
            "",
            "The per-entry absolute paths, observation-order hashes, source-lock "
            "provenance, matrix sparsity, dtype, and all boolean checks are retained "
            "in the CSV and JSON manifest.",
        ]
    )
    (OUT / "SEDR_INPUT_STRUCTURAL_AUDIT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    records = build()
    if len(records) != 19 or any(
        record["structural_status"] != "PASS" for record in records
    ):
        raise SystemExit("Structural audit failed; outputs were not finalized.")
    write_outputs(records)
    print(f"PASS {len(records)}/19")
