"""Fail-closed integration of the immutable four-method Project 9 results and SEDR.

This module is deliberately a *post-gate* program.  It first performs the same
fresh 380-checkpoint/gate validation used by the exact five-method rank
analysis, then re-hashes every source in the pre-SEDR immutability baseline.
It never modifies an existing Project 9 result.  Candidate files are published
as one new directory only after all row grids, cross-table identities, and
four-method back-filter reconciliations pass.

The program is safe to invoke before the gate opens: it fails before reading a
scientific table and creates no output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import csv
import io
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
EXPANSION = ROOT / "outputs" / "PROJECT9_SEDR_EXPANSION"
OLD_ROOT = ROOT / "outputs" / "PROJECT9_MERFISH_EXPANSION"
DEFAULT_OUTPUT = EXPANSION / "candidate_integration" / "all_outputs"
MARKER_ROOT = EXPANSION / "candidate_integration" / "sedr_markers"
GATE_FILE = EXPANSION / "SCIENTIFIC_GATE_OPEN.json"

METHODS = ("GraphST", "STAGATE", "SpaGCN", "BANKSY", "SEDR")
OLD_METHODS = METHODS[:4]
DATASETS = (
    "151507", "151508", "151509", "151510", "151669", "151670",
    "151671", "151672", "151673", "151674", "151675", "151676",
    "STARmap_20180505_BY3_1k", "HBCA1",
    "MERFISH_Bregma_m0.04", "MERFISH_Bregma_m0.09",
    "MERFISH_Bregma_m0.14", "MERFISH_Bregma_m0.19",
    "MERFISH_Bregma_m0.24",
)
DISPLAY = {
    **{dataset: dataset for dataset in DATASETS[:12]},
    "STARmap_20180505_BY3_1k": "STARmap",
    "HBCA1": "HBCA1",
    "MERFISH_Bregma_m0.04": "Bregma -0.04",
    "MERFISH_Bregma_m0.09": "Bregma -0.09",
    "MERFISH_Bregma_m0.14": "Bregma -0.14",
    "MERFISH_Bregma_m0.19": "Bregma -0.19",
    "MERFISH_Bregma_m0.24": "Bregma -0.24",
}
SEEDS = tuple(range(1, 21))
ISO_THRESHOLDS = (0.01, 0.02, 0.03)
PRIMARY_ISO_THRESHOLD = 0.02
EXPECTED_UNITS = len(DATASETS) * len(METHODS)
EXPECTED_PAIRWISE = EXPECTED_UNITS * 190
# Marker CSVs are intentionally serialized with ``%.10g`` by the frozen
# producer.  A bounded [-1, 1] value can therefore move by at most 5e-11 per
# serialization; reconciliation of a saved aggregate against the same
# aggregate recomputed from separately rounded pair rows can accumulate at
# most 1e-10.  Keep this dedicated absolute-only bound rather than weakening
# any scientific or general numeric check.
MARKER_CSV_RECONCILIATION_ATOL = 1e-10
# Core scientific CSVs use ``%.12g``.  Percentages can be as large as 100,
# giving a worst-case decimal serialization error of 5e-11; this dedicated
# bound reconciles the saved percentage with its exact integer count ratio.
CORE_CSV_PERCENTAGE_ATOL = 5.1e-11

OLD_SOURCES = {
    "seed": OLD_ROOT / "combined_seed_level_accuracy.csv",
    "pairwise": OLD_ROOT / "combined_pairwise_partition_reproducibility.csv",
    "iso": OLD_ROOT / "combined_iso_accuracy_results.csv",
    "unit": OLD_ROOT / "combined_method_dataset_summary.csv",
    "consensus": OLD_ROOT / "combined_consensus_results.csv",
    "marker_unit": OLD_ROOT / "combined_within_unit_marker_correlations.csv",
    "marker_tertile": OLD_ROOT / "combined_marker_tertile_summary.csv",
    "marker_pairs": OLD_ROOT / "combined_marker_reproducibility_all_pairs.csv",
}
SEDR_SOURCES = {
    "seed": EXPANSION / "seed_level_accuracy.csv",
    "pairwise": EXPANSION / "pairwise_partition_reproducibility.csv",
    "iso": EXPANSION / "iso_accuracy_results.csv",
    "unit": EXPANSION / "sedr_unit_summary.csv",
    "consensus": EXPANSION / "consensus_results.csv",
    "marker_unit": MARKER_ROOT / "within_unit_marker_correlations.csv",
    "marker_tertile": MARKER_ROOT / "marker_tertile_summary.csv",
    "marker_pairs": MARKER_ROOT / "marker_reproducibility_all_pairs.csv",
}
MARKER_VALIDATION = MARKER_ROOT / "SEDR_MARKER_ANALYSIS_VALIDATION.json"

KEYS = {
    "seed": ["section", "method", "seed"],
    "pairwise": ["section", "method", "seed_r", "seed_s"],
    "iso": ["section", "method", "threshold"],
    "unit": ["section", "method"],
    "consensus": ["section", "method"],
    "marker_unit": ["section", "method"],
    "marker_tertile": ["section", "method", "partition_ari_tertile"],
    "marker_pairs": ["section", "method", "seed_r", "seed_s"],
}
OUTPUT_NAMES = {
    "seed": "integrated_seed_level_accuracy.csv",
    "pairwise": "integrated_pairwise_reproducibility.csv",
    "iso": "integrated_iso_accuracy.csv",
    "unit": "integrated_method_dataset_summary.csv",
    "consensus": "integrated_consensus_summary.csv",
    "marker_unit": "integrated_marker_unit_summary.csv",
    "marker_tertile": "integrated_marker_tertile_summary.csv",
    "marker_pairs": "integrated_marker_reproducibility_all_pairs.csv",
}


class IntegrationBlocked(RuntimeError):
    """A required gate, provenance, schema, or reconciliation check failed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_five_method_module() -> Any:
    path = WORK / "analyze_five_method.py"
    spec = importlib.util.spec_from_file_location(
        "project9_sedr_five_method_gate_for_integration", path
    )
    if spec is None or spec.loader is None:
        raise IntegrationBlocked(f"Cannot load gate verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise IntegrationBlocked(f"Required source is missing: {path}")
    return pd.read_csv(path, dtype={"section": str, "dataset": str})


def require_columns(frame: pd.DataFrame, columns: Iterable[str], name: str) -> None:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise IntegrationBlocked(f"{name} lacks columns: {sorted(missing)}")


def require_exact_grid(
    frame: pd.DataFrame,
    key_columns: list[str],
    expected: set[tuple[Any, ...]],
    name: str,
) -> None:
    require_columns(frame, key_columns, name)
    keys = set(map(tuple, frame[key_columns].itertuples(index=False, name=None)))
    if len(frame) != len(expected) or frame.duplicated(key_columns).any() or keys != expected:
        raise IntegrationBlocked(f"{name} identity grid is incomplete or duplicated")


def ordered(frame: pd.DataFrame, extra: list[str]) -> pd.DataFrame:
    dataset_order = {value: index for index, value in enumerate(DATASETS)}
    method_order = {value: index for index, value in enumerate(METHODS)}
    result = frame.copy()
    result["__dataset"] = result["section"].map(dataset_order)
    result["__method"] = result["method"].map(method_order)
    if result[["__dataset", "__method"]].isna().any().any():
        raise IntegrationBlocked("Integrated table contains an unexpected dataset/method")
    result.sort_values(["__dataset", "__method", *extra], inplace=True)
    return result.drop(columns=["__dataset", "__method"]).reset_index(drop=True)


def align_to_old_schema(
    sedr: pd.DataFrame,
    old: pd.DataFrame,
    mapping: dict[str, str],
    required_after_mapping: Iterable[str],
    derived: dict[str, Any] | None = None,
) -> pd.DataFrame:
    result = sedr.rename(columns=mapping).copy()
    if derived:
        for column, value in derived.items():
            result[column] = value(result) if callable(value) else value
    require_columns(result, required_after_mapping, "normalized SEDR source")
    missing = set(old.columns) - set(result.columns)
    # Missing columns are allowed only for old technical/provenance fields that
    # have no SEDR analogue.  Scientifically meaningful columns are always in
    # required_after_mapping above.
    for column in missing:
        result[column] = np.nan
    return result[list(old.columns)]


def canonicalize_sedr_display_fields(
    frame: pd.DataFrame, source_name: str
) -> pd.DataFrame:
    """Normalize presentation aliases while preserving every scientific field."""

    result = frame.copy()
    require_columns(result, ["dataset"], f"SEDR {source_name} source")
    for column in ("dataset_display", "section_display"):
        if column not in result.columns:
            continue
        for dataset in DATASETS:
            values = result.loc[
                result["dataset"].eq(dataset), column
            ].dropna().astype(str).unique()
            if len(values) != 1:
                raise IntegrationBlocked(
                    f"SEDR {source_name} has ambiguous {column} for {dataset}: "
                    f"{values}"
                )
            canonical = DISPLAY[dataset]
            allowed = {canonical}
            if dataset.startswith("MERFISH_Bregma_"):
                allowed.add(f"{canonical} mm")
            if str(values[0]) not in allowed:
                raise IntegrationBlocked(
                    f"SEDR {source_name} has unexpected {column} for {dataset}: "
                    f"{values}"
                )
        result[column] = result["dataset"].map(DISPLAY)
    return result


def assert_in_memory_backfilter(
    old: pd.DataFrame, integrated: pd.DataFrame, key_columns: list[str], name: str
) -> None:
    expected = old.sort_values(key_columns).reset_index(drop=True)
    observed = (
        integrated[integrated["method"].isin(OLD_METHODS)][list(old.columns)]
        .sort_values(key_columns).reset_index(drop=True)
    )
    try:
        pd.testing.assert_frame_equal(
            observed, expected, check_dtype=False, check_exact=True,
            check_like=False,
        )
    except AssertionError as error:
        raise IntegrationBlocked(f"{name} four-method in-memory drift: {error}") from error


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(
        index=False, lineterminator="\n", float_format="%.17g"
    ).encode("utf-8")


def canonical_key_token(column: str, value: Any) -> str:
    if column in {"seed", "seed_r", "seed_s"}:
        return str(int(value))
    if column == "threshold":
        return str(float(value))
    return str(value)


def authoritative_tokens(
    name: str,
) -> tuple[list[str], dict[tuple[str, ...], dict[str, str]]]:
    """Read one immutable four-method source without parsing its field tokens."""
    path = OLD_SOURCES[name]
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise IntegrationBlocked(f"Authoritative CSV has no header: {path}")
        fields = list(reader.fieldnames)
        rows: dict[tuple[str, ...], dict[str, str]] = {}
        for raw in reader:
            identity = tuple(
                canonical_key_token(column, raw[column]) for column in KEYS[name]
            )
            if identity in rows:
                raise IntegrationBlocked(
                    f"Duplicate authoritative token identity: {name}/{identity}"
                )
            rows[identity] = dict(raw)
    return fields, rows


def integrated_csv_with_authoritative_tokens(
    name: str, frame: pd.DataFrame
) -> bytes:
    """Serialize SEDR normally but preserve every old field token verbatim."""
    source_fields, source_rows = authoritative_tokens(name)
    output_fields = list(frame.columns)
    if source_fields != output_fields:
        raise IntegrationBlocked(
            f"{name} integrated schema/order differs from authoritative source"
        )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream, fieldnames=output_fields, lineterminator="\n", extrasaction="raise"
    )
    writer.writeheader()
    seen: set[tuple[str, ...]] = set()
    for parsed in frame.to_dict(orient="records"):
        identity = tuple(
            canonical_key_token(column, parsed[column]) for column in KEYS[name]
        )
        row = {
            field: "" if pd.isna(value) else format(value, ".17g")
            if isinstance(value, (float, np.floating)) else str(value)
            for field, value in parsed.items()
        }
        if str(parsed["method"]) in OLD_METHODS:
            if identity not in source_rows:
                raise IntegrationBlocked(
                    f"Unexpected old-method serialized identity: {name}/{identity}"
                )
            row = dict(source_rows[identity])
            seen.add(identity)
        writer.writerow(row)
    if seen != set(source_rows):
        raise IntegrationBlocked(
            f"Not every authoritative {name} row was serialized"
        )
    return stream.getvalue().encode("utf-8")


def exact_serialized_token_audit(name: str, payload: bytes) -> dict[str, Any]:
    source_fields, source_rows = authoritative_tokens(name)
    observed: dict[tuple[str, ...], dict[str, str]] = {}
    with io.StringIO(payload.decode("utf-8"), newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != source_fields:
            raise IntegrationBlocked(f"Serialized {name} schema/order drift")
        for row in reader:
            if row["method"] not in OLD_METHODS:
                continue
            identity = tuple(
                canonical_key_token(column, row[column]) for column in KEYS[name]
            )
            if identity in observed:
                raise IntegrationBlocked(
                    f"Duplicate serialized old identity: {name}/{identity}"
                )
            observed[identity] = dict(row)
    if observed != source_rows:
        raise IntegrationBlocked(
            f"Serialized {name} old-method tokens differ from authoritative CSV"
        )
    return {
        "status": "PASS",
        "rows": len(source_rows),
        "in_memory_source_columns_bit_exact": True,
        "serialized_authoritative_tokens_exact": True,
        "authoritative_fields_exact": source_fields,
        "numeric_tolerance_used_for_old_rows": False,
    }


def validate_marker_provenance() -> dict[str, Any]:
    if not MARKER_VALIDATION.is_file():
        raise IntegrationBlocked(f"SEDR marker validation is missing: {MARKER_VALIDATION}")
    validation = load_json(MARKER_VALIDATION)
    if validation.get("status") != "PASS" or validation.get("dataset_units") != 19:
        raise IntegrationBlocked("SEDR marker validation is not a 19-unit PASS")
    hashes = validation.get("output_sha256")
    if not isinstance(hashes, dict):
        raise IntegrationBlocked("SEDR marker validation lacks output hashes")
    for key in ("marker_unit", "marker_tertile", "marker_pairs"):
        path = SEDR_SOURCES[key]
        if str(hashes.get(path.name, "")).upper() != sha256_file(path):
            raise IntegrationBlocked(f"SEDR marker output hash mismatch: {path.name}")
    if str(validation.get("gate_sha256", "")).upper() != sha256_file(GATE_FILE):
        raise IntegrationBlocked("SEDR marker analysis used a different scientific gate")
    gate = load_json(GATE_FILE)
    for field in (
        "protocol_hash", "input_manifest_sha256", "checkpoint_manifest_sha256"
    ):
        if str(validation.get(field, "")).upper() != str(gate.get(field, "")).upper():
            raise IntegrationBlocked(
                f"SEDR marker validation/gate provenance mismatch: {field}"
            )
    expected_core = validation.get("core_output_sha256")
    if not isinstance(expected_core, dict):
        raise IntegrationBlocked("SEDR marker validation lacks core-output hashes")
    for key in ("seed", "pairwise", "iso", "consensus", "unit"):
        path = SEDR_SOURCES[key]
        if str(expected_core.get(path.name, "")).upper() != sha256_file(path):
            raise IntegrationBlocked(
                f"SEDR core source changed after marker analysis: {path.name}"
            )
    return validation


def normalize_sources(
    old: dict[str, pd.DataFrame], sedr: dict[str, pd.DataFrame]
) -> dict[str, pd.DataFrame]:
    sedr = {
        name: canonicalize_sedr_display_fields(frame, name)
        for name, frame in sedr.items()
    }
    normalized: dict[str, pd.DataFrame] = {}
    common = {"dataset": "section", "dataset_display": "section_display"}

    normalized["seed"] = align_to_old_schema(
        sedr["seed"], old["seed"], common,
        ["section", "method", "seed", "reference_ari", "reference_nmi", "section_display"],
        {"n_spots": lambda x: x["n_observations"],
         "n_cells": lambda x: x["n_observations"],
         "n_clusters": lambda x: x["observed_k"],
         "n_genes": lambda x: x["n_genes_frozen_source"]},
    )
    n_observations = pd.to_numeric(
        sedr["seed"]["n_observations"], errors="raise"
    ).to_numpy(int)
    n_reference = pd.to_numeric(
        sedr["seed"]["n_reference_observations"], errors="raise"
    ).to_numpy(int)
    # DLPFC reference annotations legitimately contain missing manual_layer
    # values.  The frozen core analysis records both counts and computes
    # ARI/NMI on ``reference_series.notna()``.  Reference coverage therefore
    # must be estimable and bounded by the full prediction grid, not equal to
    # it.  Counts must also be invariant across all 20 seeds of an entry.
    if np.any(n_reference < 2) or np.any(n_reference > n_observations):
        raise IntegrationBlocked("SEDR reference-observation counts are invalid")
    count_variation = sedr["seed"].groupby("dataset")[[
        "n_observations", "n_reference_observations"
    ]].nunique(dropna=False)
    if not count_variation.eq(1).all().all():
        raise IntegrationBlocked(
            "SEDR observation counts vary across seeds within an entry"
        )
    normalized["pairwise"] = align_to_old_schema(
        sedr["pairwise"], old["pairwise"], common,
        ["section", "method", "seed_r", "seed_s", "ari_r", "ari_s",
         "abs_reference_ari_difference", "pairwise_partition_ari",
         "pairwise_partition_nmi", "section_display"],
    )
    normalized["iso"] = align_to_old_schema(
        sedr["iso"], old["iso"],
        {**common,
         "n_divergent_partition_ari_lt_0_50": "n_partition_ari_below_0_50",
         "percentage_divergent_partition_ari_lt_0_50": "__percentage"},
        ["section", "section_display", "method", "threshold",
         "n_iso_accuracy_pairs", "median_pairwise_partition_ari",
         "minimum_pairwise_partition_ari", "n_partition_ari_below_0_50",
         "fraction_partition_ari_below_0_50"],
        {"fraction_partition_ari_below_0_50": lambda x: x["__percentage"] / 100.0},
    )
    percentage = pd.to_numeric(
        sedr["iso"]["percentage_divergent_partition_ari_lt_0_50"],
        errors="coerce",
    )
    count = pd.to_numeric(sedr["iso"]["n_iso_accuracy_pairs"], errors="raise")
    divergent = pd.to_numeric(
        sedr["iso"]["n_divergent_partition_ari_lt_0_50"], errors="raise"
    )
    expected_percentage = np.divide(
        100.0 * divergent.to_numpy(float), count.to_numpy(float),
        out=np.full(len(count), np.nan), where=count.to_numpy(float) != 0,
    )
    if not np.allclose(
        percentage.to_numpy(float), expected_percentage,
        rtol=0.0, atol=CORE_CSV_PERCENTAGE_ATOL, equal_nan=True,
    ):
        raise IntegrationBlocked("SEDR iso percentage/count fields disagree")

    pairwise = sedr["pairwise"]
    nmi_summary = pairwise.groupby("dataset", sort=False)["pairwise_partition_nmi"].agg(
        p05_pairwise_partition_nmi=lambda values: np.quantile(values, 0.05),
        minimum_pairwise_partition_nmi="min",
    )
    unit = sedr["unit"].merge(nmi_summary, left_on="dataset", right_index=True,
                               validate="one_to_one")
    normalized["unit"] = align_to_old_schema(
        unit, old["unit"], common,
        ["section", "method", "n_seeds", "median_reference_ari",
         "reference_ari_sd", "reference_ari_min", "reference_ari_max",
         "reference_ari_range", "median_reference_nmi", "reference_nmi_sd",
         "median_pairwise_partition_ari", "p05_pairwise_partition_ari",
         "minimum_pairwise_partition_ari", "median_pairwise_partition_nmi",
         "partition_instability", "section_display",
         "p05_pairwise_partition_nmi", "minimum_pairwise_partition_nmi"],
    )
    normalized["consensus"] = align_to_old_schema(
        sedr["consensus"], old["consensus"],
        {**common,
         "split_half_consensus_partition_ari": "split_half_consensus_ari",
         "median_single_seed_pairwise_partition_ari": "median_single_seed_pairwise_ari",
         "split_half_reproducibility_gain": "split_half_gain_over_median_single_seed_pairwise_ari"},
        ["section", "method", "median_single_seed_reference_ari",
         "best_single_seed_reference_ari", "consensus20_reference_ari",
         "consensus20_reference_nmi", "split_half_consensus_ari", "algorithm",
         "median_single_seed_pairwise_ari",
         "split_half_gain_over_median_single_seed_pairwise_ari", "section_display"],
    )

    tertile = sedr["marker_tertile"].copy()
    wide = tertile.pivot(index="dataset", columns="partition_ari_tertile",
                         values="median_top100_marker_jaccard").reindex(DATASETS)
    if list(wide.columns) != ["High", "Low", "Middle"]:
        # Pivot sorts labels; membership, not display order, is the invariant.
        if set(wide.columns) != {"Low", "Middle", "High"}:
            raise IntegrationBlocked("SEDR marker tertile labels are incomplete")
    correlation = sedr["marker_unit"].copy()
    correlation["dataset_display"] = correlation["dataset"].map(DISPLAY)
    correlation["section_display"] = correlation["dataset"].map(DISPLAY)
    correlation["spearman_partition_ari_vs_marker_jaccard"] = correlation[
        "spearman_partition_ari_vs_top100_marker_jaccard"
    ]
    correlation["spearman_partition_ari_vs_top50_jaccard"] = correlation[
        "spearman_partition_ari_vs_top50_marker_jaccard"
    ]
    for stratum, column in (("Low", "low_tertile_median_marker_jaccard"),
                            ("Middle", "middle_tertile_median_marker_jaccard"),
                            ("High", "high_tertile_median_marker_jaccard")):
        correlation[column] = correlation["dataset"].map(wide[stratum])
    correlation["high_minus_low_marker_jaccard"] = (
        correlation["high_tertile_median_marker_jaccard"]
        - correlation["low_tertile_median_marker_jaccard"]
    )
    normalized["marker_unit"] = align_to_old_schema(
        correlation, old["marker_unit"], {"dataset": "section"},
        ["section", "dataset_display", "method", "n_iso_accuracy_pairs",
         "spearman_partition_ari_vs_marker_jaccard",
         "spearman_partition_ari_vs_top50_jaccard",
         "spearman_partition_ari_vs_marker_rank_spearman", "section_display",
         "low_tertile_median_marker_jaccard",
         "middle_tertile_median_marker_jaccard",
         "high_tertile_median_marker_jaccard", "high_minus_low_marker_jaccard"],
    )
    tertile["dataset_display"] = tertile["dataset"].map(DISPLAY)
    tertile["section_display"] = tertile["dataset"].map(DISPLAY)
    normalized["marker_tertile"] = align_to_old_schema(
        tertile, old["marker_tertile"], {"dataset": "section"},
        ["section", "dataset_display", "method", "partition_ari_tertile",
         "n_pairs", "median_pairwise_partition_ari",
         "median_top100_marker_jaccard", "median_top50_marker_jaccard",
         "median_marker_rank_spearman", "section_display"],
    )
    marker_pairs = sedr["marker_pairs"].copy()
    marker_pairs["dataset_display"] = marker_pairs["dataset"].map(DISPLAY)
    marker_pairs["section_display"] = marker_pairs["dataset"].map(DISPLAY)
    marker_pairs["marker_pipeline_source"] = "frozen Project 9 SEDR marker pipeline"
    normalized["marker_pairs"] = align_to_old_schema(
        marker_pairs, old["marker_pairs"], {"dataset": "section"},
        ["section", "dataset_display", "method", "seed_r", "seed_s",
         "abs_reference_ari_difference", "pairwise_partition_ari",
         "top50_marker_jaccard", "top100_marker_jaccard",
         "marker_rank_spearman", "aligned_domains_compared_n",
         "aligned_domains_compared", "marker_pipeline_source",
         "partition_ari_tertile", "section_display", "marker_set_size"],
    )
    return normalized


def validate_sedr_cross_table(sedr: dict[str, pd.DataFrame]) -> None:
    for name, frame in sedr.items():
        require_columns(frame, ["method"], f"SEDR {name} source")
        if not frame["method"].astype(str).eq("SEDR").all():
            raise IntegrationBlocked(f"SEDR {name} source contains another method")
    unit_grid = {(dataset, "SEDR") for dataset in DATASETS}
    seed_grid = {(dataset, "SEDR", seed) for dataset in DATASETS for seed in SEEDS}
    pair_grid = {
        (dataset, "SEDR", first, second) for dataset in DATASETS
        for first in SEEDS for second in SEEDS if first < second
    }
    iso_grid = {(dataset, "SEDR", threshold) for dataset in DATASETS
                for threshold in ISO_THRESHOLDS}
    require_exact_grid(sedr["seed"], ["dataset", "method", "seed"], seed_grid,
                       "SEDR seed source")
    require_exact_grid(sedr["pairwise"],
                       ["dataset", "method", "seed_r", "seed_s"], pair_grid,
                       "SEDR pairwise source")
    require_exact_grid(sedr["iso"], ["dataset", "method", "threshold"], iso_grid,
                       "SEDR iso source")
    for name in ("unit", "consensus", "marker_unit"):
        require_exact_grid(sedr[name], ["dataset", "method"], unit_grid,
                           f"SEDR {name} source")
    tertile_grid = {(dataset, "SEDR", label) for dataset in DATASETS
                    for label in ("Low", "Middle", "High")}
    require_exact_grid(sedr["marker_tertile"],
                       ["dataset", "method", "partition_ari_tertile"],
                       tertile_grid, "SEDR marker-tertile source")
    if sedr["marker_pairs"].duplicated(
        ["dataset", "method", "seed_r", "seed_s"]
    ).any():
        raise IntegrationBlocked("SEDR marker-pair source contains duplicates")

    core = sedr["pairwise"].copy()
    eligible = core[
        core["abs_reference_ari_difference"] <= PRIMARY_ISO_THRESHOLD + 1e-12
    ]
    expected_marker_keys = set(map(tuple, eligible[
        ["dataset", "method", "seed_r", "seed_s"]
    ].itertuples(index=False, name=None)))
    actual_marker_keys = set(map(tuple, sedr["marker_pairs"][
        ["dataset", "method", "seed_r", "seed_s"]
    ].itertuples(index=False, name=None)))
    if actual_marker_keys != expected_marker_keys or len(sedr["marker_pairs"]) != len(eligible):
        raise IntegrationBlocked("SEDR marker pairs do not exactly equal primary iso pairs")
    primary = sedr["iso"][np.isclose(sedr["iso"]["threshold"], PRIMARY_ISO_THRESHOLD)]
    declared = primary.set_index("dataset")["n_iso_accuracy_pairs"].reindex(DATASETS)
    derived = eligible.groupby("dataset").size().reindex(DATASETS, fill_value=0)
    marker_counts = sedr["marker_unit"].set_index("dataset")[
        "n_iso_accuracy_pairs"
    ].reindex(DATASETS)
    if not (np.array_equal(declared.to_numpy(int), derived.to_numpy(int)) and
            np.array_equal(marker_counts.to_numpy(int), derived.to_numpy(int))):
        raise IntegrationBlocked("SEDR core/marker primary iso counts do not reconcile")

    correlation_fields = [
        "spearman_partition_ari_vs_top100_marker_jaccard",
        "spearman_partition_ari_vs_top50_marker_jaccard",
        "spearman_partition_ari_vs_marker_rank_spearman",
    ]
    tertile_fields = [
        "median_pairwise_partition_ari", "median_top100_marker_jaccard",
        "median_top50_marker_jaccard", "median_marker_rank_spearman",
    ]
    require_columns(
        sedr["marker_unit"], correlation_fields,
        "SEDR marker-unit source",
    )
    require_columns(
        sedr["marker_tertile"], ["n_pairs", *tertile_fields],
        "SEDR marker-tertile source",
    )
    for dataset in DATASETS:
        pair_group = sedr["marker_pairs"][
            sedr["marker_pairs"]["dataset"].eq(dataset)
        ].sort_values(["pairwise_partition_ari", "seed_r", "seed_s"])
        expected_codes = np.minimum(
            np.floor(np.arange(len(pair_group)) * 3 / len(pair_group)).astype(int), 2
        ) if len(pair_group) else np.asarray([], dtype=int)
        expected_labels = np.asarray(
            [("Low", "Middle", "High")[code] for code in expected_codes]
        )
        if not np.array_equal(
            pair_group["partition_ari_tertile"].astype(str).to_numpy(),
            expected_labels,
        ):
            raise IntegrationBlocked(
                f"SEDR marker-pair deterministic tertiles disagree: {dataset}"
            )

        unit_row = sedr["marker_unit"][
            sedr["marker_unit"]["dataset"].eq(dataset)
        ].iloc[0]
        response_fields = {
            "spearman_partition_ari_vs_top100_marker_jaccard":
                "top100_marker_jaccard",
            "spearman_partition_ari_vs_top50_marker_jaccard":
                "top50_marker_jaccard",
            "spearman_partition_ari_vs_marker_rank_spearman":
                "marker_rank_spearman",
        }
        for correlation_field, response_field in response_fields.items():
            finite = (
                np.isfinite(pd.to_numeric(
                    pair_group["pairwise_partition_ari"], errors="coerce"
                ).to_numpy(float))
                & np.isfinite(pd.to_numeric(
                    pair_group[response_field], errors="coerce"
                ).to_numpy(float))
            )
            complete = pair_group.loc[finite]
            nonestimable = bool(
                len(complete) < 2
                or complete["pairwise_partition_ari"].nunique() < 2
                or complete[response_field].nunique() < 2
            )
            expected = (
                np.nan if nonestimable else float(
                    complete["pairwise_partition_ari"].corr(
                        complete[response_field], method="spearman"
                    )
                )
            )
            observed = float(unit_row[correlation_field])
            if not np.isclose(
                observed, expected, rtol=0.0,
                atol=MARKER_CSV_RECONCILIATION_ATOL, equal_nan=True,
            ):
                raise IntegrationBlocked(
                    f"SEDR marker correlation differs from finite complete pairs: "
                    f"{dataset}/{correlation_field}"
                )
        tertile_group = sedr["marker_tertile"][
            sedr["marker_tertile"]["dataset"].eq(dataset)
        ]
        if int(pd.to_numeric(tertile_group["n_pairs"], errors="raise").sum()) != len(pair_group):
            raise IntegrationBlocked(
                f"SEDR marker-tertile counts do not sum to unit pairs: {dataset}"
            )
        for row in tertile_group.itertuples(index=False):
            n_pairs = int(row.n_pairs)
            stratum_pairs = pair_group[
                pair_group["partition_ari_tertile"].eq(row.partition_ari_tertile)
            ]
            if n_pairs != len(stratum_pairs):
                raise IntegrationBlocked(
                    f"SEDR marker tertile count differs from pair rows: "
                    f"{dataset}/{row.partition_ari_tertile}"
                )
            field_sources = {
                "median_pairwise_partition_ari": "pairwise_partition_ari",
                "median_top100_marker_jaccard": "top100_marker_jaccard",
                "median_top50_marker_jaccard": "top50_marker_jaccard",
                "median_marker_rank_spearman": "marker_rank_spearman",
            }
            for field, source in field_sources.items():
                finite_values = pd.to_numeric(
                    stratum_pairs[source], errors="coerce"
                ).dropna().to_numpy(float)
                expected = float(np.median(finite_values)) if len(finite_values) else np.nan
                observed = float(getattr(row, field))
                if not np.isclose(
                    observed, expected, rtol=0.0,
                    atol=MARKER_CSV_RECONCILIATION_ATOL, equal_nan=True,
                ):
                    raise IntegrationBlocked(
                        f"SEDR marker tertile finite-value median differs: "
                        f"{dataset}/{row.partition_ari_tertile}/{field}"
                    )

    unit = sedr["unit"].set_index("dataset")
    consensus = sedr["consensus"].set_index("dataset")
    checks = (
        (unit["median_pairwise_partition_ari"],
         consensus["median_single_seed_pairwise_partition_ari"]),
        (unit["split_half_consensus_partition_ari"],
         consensus["split_half_consensus_partition_ari"]),
        (unit["split_half_reproducibility_gain"],
         consensus["split_half_reproducibility_gain"]),
    )
    for left, right in checks:
        if not np.allclose(left.reindex(DATASETS), right.reindex(DATASETS),
                           rtol=0.0, atol=1e-12):
            raise IntegrationBlocked("SEDR unit and consensus summaries disagree")


def validate_integrated_grids(frames: dict[str, pd.DataFrame]) -> None:
    units = {(dataset, method) for dataset in DATASETS for method in METHODS}
    seeds = {(dataset, method, seed) for dataset in DATASETS
             for method in METHODS for seed in SEEDS}
    pairs = {(dataset, method, first, second) for dataset in DATASETS
             for method in METHODS for first in SEEDS for second in SEEDS
             if first < second}
    isos = {(dataset, method, threshold) for dataset in DATASETS
            for method in METHODS for threshold in ISO_THRESHOLDS}
    require_exact_grid(frames["seed"], KEYS["seed"], seeds, "integrated seed")
    require_exact_grid(frames["pairwise"], KEYS["pairwise"], pairs,
                       "integrated pairwise")
    require_exact_grid(frames["iso"], KEYS["iso"], isos, "integrated iso")
    for name in ("unit", "consensus", "marker_unit"):
        require_exact_grid(frames[name], KEYS[name], units, f"integrated {name}")
    tertiles = {(dataset, method, label) for dataset in DATASETS
                for method in METHODS for label in ("Low", "Middle", "High")}
    require_exact_grid(frames["marker_tertile"], KEYS["marker_tertile"], tertiles,
                       "integrated marker tertile")
    if len(frames["seed"]) != 1900 or len(frames["pairwise"]) != EXPECTED_PAIRWISE:
        raise IntegrationBlocked("Integrated structural totals are not 1900/18050")
    if len(frames["iso"]) != 285 or any(len(frames[name]) != 95 for name in
                                         ("unit", "consensus", "marker_unit")):
        raise IntegrationBlocked("Integrated summary totals are not 285/95")
    # ``section_display`` is the authoritative presentation field shared by
    # all eight immutable four-method schemas.  Require one canonical label
    # for each stable identity in every new additive table.  Other legacy
    # presentation columns remain byte-for-byte untouched on old rows.
    for name, frame in frames.items():
        require_columns(
            frame, ["section", "section_display"], f"integrated {name}"
        )
        for dataset in DATASETS:
            values = frame.loc[
                frame["section"].eq(dataset), "section_display"
            ].dropna().astype(str).unique()
            if len(values) != 1 or str(values[0]) != DISPLAY[dataset]:
                raise IntegrationBlocked(
                    f"Integrated {name} display is noncanonical for {dataset}: "
                    f"{values}"
                )
    primary = frames["iso"][np.isclose(frames["iso"]["threshold"], 0.02)]
    primary_counts = primary.set_index(["section", "method"])[
        "n_iso_accuracy_pairs"
    ].sort_index()
    marker_counts = frames["marker_unit"].set_index(["section", "method"])[
        "n_iso_accuracy_pairs"
    ].sort_index()
    if not np.array_equal(
        primary_counts.to_numpy(int), marker_counts.to_numpy(int)
    ):
        raise IntegrationBlocked(
            "Integrated core and marker primary iso counts do not reconcile"
        )
    pairwise = frames["pairwise"]
    eligible_keys = set(map(tuple, pairwise[
        pairwise["abs_reference_ari_difference"] <= 0.02 + 1e-12
    ][["section", "method", "seed_r", "seed_s"]].itertuples(
        index=False, name=None
    )))
    marker_pair_keys = set(map(tuple, frames["marker_pairs"][[
        "section", "method", "seed_r", "seed_s"
    ]].itertuples(index=False, name=None)))
    if marker_pair_keys != eligible_keys or len(frames["marker_pairs"]) != len(
        eligible_keys
    ):
        raise IntegrationBlocked(
            "Integrated marker pairs do not exactly equal primary iso pairs"
        )


def finite_summary(values: pd.Series) -> dict[str, Any]:
    numeric = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    if not np.isfinite(numeric).all():
        raise IntegrationBlocked("Headline statistic contains a non-finite value")
    return {
        "n_estimable": int(len(numeric)),
        "median": float(np.median(numeric)) if len(numeric) else None,
        "q25": float(np.quantile(numeric, 0.25)) if len(numeric) else None,
        "q75": float(np.quantile(numeric, 0.75)) if len(numeric) else None,
    }


def nullable_percentage(numerator: int | float, denominator: int | float) -> float | None:
    denominator_float = float(denominator)
    if denominator_float == 0:
        return None
    return 100.0 * float(numerator) / denominator_float


def headline_summary(frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    units = frames["unit"]
    low_sd_high = (
        (units["reference_ari_sd"] <= 0.02 + 1e-12)
        & (units["partition_instability"] >= 0.30 - 1e-12)
    )
    primary = frames["iso"][np.isclose(frames["iso"]["threshold"], 0.02)]
    eligible = int(primary["n_iso_accuracy_pairs"].sum())
    divergent = int(primary["n_partition_ari_below_0_50"].sum())
    marker = frames["marker_unit"]
    rho = pd.to_numeric(
        marker["spearman_partition_ari_vs_marker_jaccard"], errors="coerce"
    )
    consensus = frames["consensus"]
    gain = pd.to_numeric(
        consensus["split_half_gain_over_median_single_seed_pairwise_ari"],
        errors="raise",
    )
    tertiles = frames["marker_tertile"].pivot(
        index=["section", "method"], columns="partition_ari_tertile",
        values="median_top100_marker_jaccard",
    )
    return {
        "structural_totals": {
            "dataset_entries": len(DATASETS), "methods": len(METHODS),
            "method_dataset_units": len(units), "seed_specific_runs": len(frames["seed"]),
            "pairwise_seed_comparisons": len(frames["pairwise"]),
        },
        "low_sd_high_instability": {
            "definition": "reference ARI SD <= 0.02 and PartitionInstability >= 0.30",
            "count": int(low_sd_high.sum()), "denominator_units": len(units),
        },
        "primary_iso_accuracy": {
            "absolute_reference_ari_threshold": 0.02,
            "eligible_pairs": eligible, "divergent_partition_ari_lt_0_50": divergent,
            "fraction_divergent": (
                nullable_percentage(divergent, eligible) / 100.0
                if eligible else None
            ),
            "percentage_divergent": nullable_percentage(divergent, eligible),
            "affected_units": int((primary["n_partition_ari_below_0_50"] > 0).sum()),
        },
        "within_unit_partition_to_marker": {
            **finite_summary(rho), "positive_units": int((rho.dropna() > 0).sum()),
        },
        "marker_tertiles": {
            "low": finite_summary(tertiles["Low"]),
            "middle": finite_summary(tertiles["Middle"]),
            "high": finite_summary(tertiles["High"]),
            "high_minus_low": finite_summary(tertiles["High"] - tertiles["Low"]),
        },
        "consensus": {
            "improved_units": int((gain > 0).sum()), "denominator_units": len(gain),
            "gain": finite_summary(gain),
            "median_single_seed_pairwise_ari": finite_summary(
                consensus["median_single_seed_pairwise_ari"]),
            "split_half_consensus_ari": finite_summary(
                consensus["split_half_consensus_ari"]),
        },
    }


def write_package(output_dir: Path, files: dict[str, bytes], manifest: dict[str, Any]) -> None:
    target = output_dir.resolve()
    if target.exists():
        raise IntegrationBlocked(f"Refusing to overwrite output directory: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + f".tmp-{os.getpid()}-{uuid.uuid4().hex}")
    staging.mkdir()
    try:
        records = []
        for name, payload in files.items():
            (staging / name).write_bytes(payload)
            records.append({"path": name, "bytes": len(payload),
                            "sha256": sha256_bytes(payload)})
        manifest["outputs"] = records
        (staging / "INTEGRATION_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(staging, target)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def analyze(args: argparse.Namespace) -> None:
    # First data-dependent operation: no scientific source path is touched
    # before this fresh 380/380 gate verification returns successfully.
    gate_module = load_five_method_module()
    protocol_hash, checkpoint_hashes = gate_module.verify_scientific_gate()
    gate_module.verify_immutable_four_method_sources()
    marker_validation = validate_marker_provenance()

    old = {name: read_csv(path) for name, path in OLD_SOURCES.items()}
    sedr = {name: read_csv(path) for name, path in SEDR_SOURCES.items()}
    validate_sedr_cross_table(sedr)
    normalized = normalize_sources(old, sedr)

    integrated: dict[str, pd.DataFrame] = {}
    extra_sort = {
        "seed": ["seed"], "pairwise": ["seed_r", "seed_s"],
        "iso": ["threshold"], "unit": [], "consensus": [], "marker_unit": [],
        "marker_tertile": ["partition_ari_tertile"],
        "marker_pairs": ["seed_r", "seed_s"],
    }
    for name in old:
        combined = pd.concat([old[name], normalized[name]], ignore_index=True)
        integrated[name] = ordered(combined, extra_sort[name])
        assert_in_memory_backfilter(old[name], integrated[name], KEYS[name], name)
    validate_integrated_grids(integrated)

    payloads = {OUTPUT_NAMES[name]: integrated_csv_with_authoritative_tokens(name, frame)
                for name, frame in integrated.items()}
    reconciliations: dict[str, Any] = {}
    for name, frame in old.items():
        reconciliations[name] = {
            **exact_serialized_token_audit(name, payloads[OUTPUT_NAMES[name]]),
            "authoritative_source": OLD_SOURCES[name].relative_to(ROOT).as_posix(),
            "authoritative_source_sha256": sha256_file(OLD_SOURCES[name]),
        }
    headline = headline_summary(integrated)
    payloads["integrated_headline_summary.json"] = (
        json.dumps(headline, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")

    # Fresh closing verification catches gate/checkpoint drift during integration.
    closing_protocol, closing_checkpoints = gate_module.verify_scientific_gate()
    if closing_protocol != protocol_hash or closing_checkpoints != checkpoint_hashes:
        raise IntegrationBlocked("Gate/checkpoint signature changed during integration")
    gate_module.verify_immutable_four_method_sources()
    manifest = {
        "schema_version": 1,
        "analysis": "complete additive five-method Project 9 integration",
        "status": "PASS",
        "scientific_gate_sha256": sha256_file(GATE_FILE),
        "protocol_hash": protocol_hash,
        "checkpoint_manifest_sha256": gate_module.canonical_checkpoint_digest([
            {"dataset": dataset, "seed": seed, **checkpoint_hashes[(dataset, seed)]}
            for dataset in DATASETS for seed in SEEDS
        ]),
        "methods": list(METHODS), "datasets": list(DATASETS),
        "row_counts": {name: len(frame) for name, frame in integrated.items()},
        "expected_pairwise_rows": EXPECTED_PAIRWISE,
        "expected_method_dataset_units": EXPECTED_UNITS,
        "four_method_backfilter_reconciliation": reconciliations,
        "four_method_sources_modified": False,
        "sedr_source_sha256": {name: sha256_file(path)
                               for name, path in SEDR_SOURCES.items()},
        "sedr_marker_validation_sha256": sha256_file(MARKER_VALIDATION),
        "sedr_marker_checkpoint_manifest_sha256": marker_validation.get(
            "checkpoint_manifest_sha256"
        ),
        "headline_summary_file": "integrated_headline_summary.json",
    }
    write_package(args.output_dir, payloads, manifest)
    print(json.dumps({
        "status": "FIVE_METHOD_ALL_OUTPUT_INTEGRATION_PASS",
        "output_dir": str(args.output_dir.resolve()),
        "integrated_pairwise_rows": len(integrated["pairwise"]),
        "integrated_method_dataset_units": len(integrated["unit"]),
        "four_method_sources_reconciled": len(reconciliations),
    }, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate-protected complete five-method Project 9 integration"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help="New candidate directory; existing paths are refused")
    args = parser.parse_args()
    try:
        analyze(args)
        return 0
    except Exception as error:
        print(f"INTEGRATION_BLOCKED: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
