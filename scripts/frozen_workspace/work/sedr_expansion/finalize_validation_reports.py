"""Validate and report the completed Project 9 SEDR expansion.

This is the final, read-mostly orchestrator.  It never trains a model or
recomputes a scientific result table.  It runs only after the scientific gate
and all three post-gate producers (core SEDR, marker, and five-method ranking)
have completed.  Before pandas, NumPy, or SciPy is imported, it invokes the
core analyzer's fail-closed fresh 380/380 gate audit.

Validation includes:

* exact 19 x 20 SEDR seed and 19 x 190 pair grids;
* exact reconciliation of iso-accuracy, consensus, and unit summaries;
* exact marker-pair membership and deterministic within-unit summaries;
* an independent streamed re-enumeration of all 19 x 20^5 rank combinations;
* exact four-method back-filter reconciliation;
* byte-level revalidation of the pre-SEDR immutability baseline.

No report is overwritten.  With ``--execute``, six requested reports are
published as a rollback-protected transaction only after every check passes.
Without ``--execute``, the same validation runs but writes nothing.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import itertools
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
EXPANSION = ROOT / "outputs" / "PROJECT9_SEDR_EXPANSION"
MERFISH = ROOT / "outputs" / "PROJECT9_MERFISH_EXPANSION"
CORE_ANALYZER = WORK / "analyze_scientific.py"
GATE_FILE = EXPANSION / "SCIENTIFIC_GATE_OPEN.json"
LOCK_FILE = EXPANSION / "LOCK_ADD_SEDR.json"
PROTOCOL = EXPANSION / "SEDR_FROZEN_PROTOCOL.md"
IMMUTABILITY_BASELINE = (
    EXPANSION / "provenance" / "EXISTING_PROJECT9_IMMUTABILITY_BASELINE.json"
)

CORE_FILES = {
    "seed": EXPANSION / "seed_level_accuracy.csv",
    "pair": EXPANSION / "pairwise_partition_reproducibility.csv",
    "iso": EXPANSION / "iso_accuracy_results.csv",
    "consensus": EXPANSION / "consensus_results.csv",
    "unit": EXPANSION / "sedr_unit_summary.csv",
}
MARKER_DIR = EXPANSION / "candidate_integration" / "sedr_markers"
MARKER_FILES = {
    "pair": MARKER_DIR / "marker_reproducibility_all_pairs.csv",
    "correlation": MARKER_DIR / "within_unit_marker_correlations.csv",
    "tertile": MARKER_DIR / "marker_tertile_summary.csv",
    "paired_test": MARKER_DIR / "paired_high_vs_low_test.json",
    "validation": MARKER_DIR / "SEDR_MARKER_ANALYSIS_VALIDATION.json",
}
FIVE_DIR = EXPANSION / "candidate_integration" / "five_method"
FIVE_FILES = {
    "integrated_seed": FIVE_DIR / "integrated_seed_level_accuracy.csv",
    "rank_distribution": FIVE_DIR / "five_method_rank_distributions.csv",
    "rank_summary": FIVE_DIR / "five_method_rank_summary.csv",
    "winner": FIVE_DIR / "five_method_winner_probabilities.csv",
    "superiority": FIVE_DIR / "five_method_pairwise_superiority.csv",
    "uncertainty": FIVE_DIR / "five_method_dataset_uncertainty.csv",
    "reconciliation": FIVE_DIR / "four_method_reconciliation.json",
    "manifest": FIVE_DIR / "analysis_manifest.json",
}
ALL_DIR = EXPANSION / "candidate_integration" / "all_outputs"
ALL_FILES = {
    "seed": ALL_DIR / "integrated_seed_level_accuracy.csv",
    "pairwise": ALL_DIR / "integrated_pairwise_reproducibility.csv",
    "iso": ALL_DIR / "integrated_iso_accuracy.csv",
    "unit": ALL_DIR / "integrated_method_dataset_summary.csv",
    "consensus": ALL_DIR / "integrated_consensus_summary.csv",
    "marker_unit": ALL_DIR / "integrated_marker_unit_summary.csv",
    "marker_tertile": ALL_DIR / "integrated_marker_tertile_summary.csv",
    "marker_pairs": ALL_DIR / "integrated_marker_reproducibility_all_pairs.csv",
    "headline": ALL_DIR / "integrated_headline_summary.json",
    "manifest": ALL_DIR / "INTEGRATION_MANIFEST.json",
}
OLD_FILES = {
    "seed": MERFISH / "combined_seed_level_accuracy.csv",
    "pair": MERFISH / "combined_pairwise_partition_reproducibility.csv",
    "iso": MERFISH / "combined_iso_accuracy_results.csv",
    "unit": MERFISH / "combined_method_dataset_summary.csv",
    "marker_pair": MERFISH / "combined_marker_reproducibility_all_pairs.csv",
    "marker_correlation": MERFISH / "combined_within_unit_marker_correlations.csv",
    "marker_tertile": MERFISH / "combined_marker_tertile_summary.csv",
    "marker_test": MERFISH / "combined_paired_tertile_test.json",
    "consensus": MERFISH / "combined_consensus_results.csv",
}
OLD_BY_INTEGRATION_KEY = {
    "seed": OLD_FILES["seed"],
    "pairwise": OLD_FILES["pair"],
    "iso": OLD_FILES["iso"],
    "unit": OLD_FILES["unit"],
    "consensus": OLD_FILES["consensus"],
    "marker_unit": OLD_FILES["marker_correlation"],
    "marker_tertile": OLD_FILES["marker_tertile"],
    "marker_pairs": OLD_FILES["marker_pair"],
}
ALL_KEYS = {
    "seed": ["dataset", "method", "seed"],
    "pairwise": ["dataset", "method", "seed_r", "seed_s"],
    "iso": ["dataset", "method", "threshold"],
    "unit": ["dataset", "method"],
    "consensus": ["dataset", "method"],
    "marker_unit": ["dataset", "method"],
    "marker_tertile": ["dataset", "method", "partition_ari_tertile"],
    "marker_pairs": ["dataset", "method", "seed_r", "seed_s"],
}
REPORTS = {
    "final": EXPANSION / "FINAL_SEDR_REPORT.md",
    "assessment": EXPANSION / "SEDR_GENERALIZATION_ASSESSMENT.md",
    "five_method": EXPANSION / "FIVE_METHOD_INTEGRATION_SUMMARY.md",
    "implications": EXPANSION / "MANUSCRIPT_IMPLICATIONS_ONLY.md",
    "validation": EXPANSION / "VALIDATION_REPORT.md",
    "summary": EXPANSION / "FINAL_SUMMARY.json",
}
ROOT_SCIENTIFIC_ALIASES = {
    EXPANSION / "marker_reproducibility_all_pairs.csv": MARKER_FILES["pair"],
    EXPANSION / "within_unit_marker_correlations.csv": MARKER_FILES["correlation"],
    EXPANSION / "marker_tertile_summary.csv": MARKER_FILES["tertile"],
    EXPANSION / "integrated_seed_level_accuracy.csv": ALL_FILES["seed"],
    EXPANSION / "integrated_pairwise_reproducibility.csv": ALL_FILES["pairwise"],
    EXPANSION / "integrated_iso_accuracy.csv": ALL_FILES["iso"],
    EXPANSION / "integrated_marker_unit_summary.csv": ALL_FILES["marker_unit"],
    EXPANSION / "integrated_consensus_summary.csv": ALL_FILES["consensus"],
    EXPANSION / "five_method_winner_probabilities.csv": FIVE_FILES["winner"],
    EXPANSION / "five_method_rank_distributions.csv": FIVE_FILES["rank_distribution"],
    EXPANSION / "five_method_pairwise_superiority.csv": FIVE_FILES["superiority"],
}

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
METHODS = ("GraphST", "STAGATE", "SpaGCN", "BANKSY", "SEDR")
OLD_METHODS = METHODS[:4]
SEEDS = tuple(range(1, 21))
THRESHOLDS = (0.01, 0.02, 0.03)
STRATA = ("Low", "Middle", "High")
EXPECTED_CHECKPOINTS = 380
EXPECTED_SEDR_PAIRS = 19 * math.comb(20, 2)
COMBINATIONS_PER_DATASET = 20 ** 5
TOTAL_COMBINATIONS = 19 * COMBINATIONS_PER_DATASET
WINNER_SCALE = math.lcm(1, 2, 3, 4, 5)
HEX64 = re.compile(r"^[0-9A-F]{64}$")
FLOAT_RTOL = 5e-9
FLOAT_ATOL = 5e-10
# The core producer intentionally uses ``%.12g``.  Reconstructing a difference
# from two separately rounded ARIs can accumulate up to 1.5e-12 absolute error
# on the bounded ARI scale.  Keep a dedicated, much tighter bound for this one
# derived-field identity check instead of weakening the general validator.
CORE_CSV_DERIVED_ATOL = 2e-12
INTEGRATOR_SHA256 = "CBCC01ED29341862A787E420FB89E8BD5BAF051A2C9863A0ED4129CE582927FF"
INTEGRATOR = WORK / "integrate_all_outputs.py"

COMPONENT_LABELS = {
    "SUPPORTS_EXISTING_PATTERN", "HETEROGENEOUS", "DOES_NOT_SUPPORT",
    "NOT_ESTIMABLE",
}
OVERALL_LABELS = {
    "STRONG_METHOD_GENERALIZATION", "PARTIAL_METHOD_GENERALIZATION",
    "LIMITED_METHOD_GENERALIZATION", "CONTRASTING_STOCHASTIC_PROFILE",
}


class FinalizationBlocked(RuntimeError):
    """A prerequisite, integrity check, or scientific reconciliation failed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def normalize_hash(value: object, field: str) -> str:
    text = str(value).strip().upper()
    if not HEX64.fullmatch(text):
        raise FinalizationBlocked(f"{field} is not a valid SHA-256")
    return text


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_core_gate_auditor() -> Any:
    if not CORE_ANALYZER.is_file():
        raise FinalizationBlocked(f"Core analyzer is missing: {CORE_ANALYZER}")
    spec = importlib.util.spec_from_file_location(
        "sedr_core_analyzer_for_final_validation", CORE_ANALYZER
    )
    if spec is None or spec.loader is None:
        raise FinalizationBlocked("Cannot load the core gate auditor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fresh_gate_audit() -> dict[str, Any]:
    """Fail before any scientific-table library is imported."""

    module = load_core_gate_auditor()
    audit = module.verify_gate_and_fresh_scan()
    if len(audit.get("checkpoints", [])) != EXPECTED_CHECKPOINTS:
        raise FinalizationBlocked("Fresh core gate audit is not 380/380")
    return audit


def stable_records_digest(records: list[dict[str, Any]]) -> str:
    stable = [
        {
            "path": str(row["path"]),
            "bytes": int(row["bytes"]),
            "sha256": normalize_hash(row["sha256"], "baseline file hash"),
        }
        for row in records
    ]
    encoded = json.dumps(
        stable, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(encoded)


def verify_immutability_baseline() -> dict[str, Any]:
    if not IMMUTABILITY_BASELINE.is_file():
        raise FinalizationBlocked(
            f"Immutability baseline is missing: {IMMUTABILITY_BASELINE}"
        )
    baseline = load_json(IMMUTABILITY_BASELINE)
    if (
        not isinstance(baseline, dict)
        or baseline.get("schema_version") != 1
        or baseline.get("hash_algorithm") != "SHA-256"
        or baseline.get("baseline_type")
        != "PROJECT9_EXISTING_PUBLICATION_AND_FOUR_METHOD_IMMUTABILITY"
    ):
        raise FinalizationBlocked("Immutability baseline schema is invalid")

    lock = load_json(LOCK_FILE)
    baseline_time = datetime.fromisoformat(
        str(baseline["created_utc"]).replace("Z", "+00:00")
    )
    lock_time = datetime.fromisoformat(
        str(lock["locked_at"]).replace("Z", "+00:00")
    )
    if baseline_time.tzinfo is None or lock_time.tzinfo is None:
        raise FinalizationBlocked("Baseline/lock timestamps lack timezones")
    if baseline_time.astimezone(timezone.utc) >= lock_time.astimezone(timezone.utc):
        raise FinalizationBlocked("Immutability baseline was not captured before lock")

    publication = baseline.get("protected_publication_package", {})
    sources = baseline.get("authoritative_four_method_sources", {})
    publication_records = publication.get("files")
    source_records = sources.get("files")
    if not isinstance(publication_records, list) or not isinstance(source_records, list):
        raise FinalizationBlocked("Immutability baseline file lists are missing")
    if len(source_records) != 14:
        raise FinalizationBlocked("Four-method baseline does not contain 14 sources")

    publication_root = ROOT / str(publication.get("root", ""))
    if not publication_root.is_dir():
        raise FinalizationBlocked("Protected publication package is missing")
    expected_publication_paths = {str(row["path"]) for row in publication_records}
    actual_publication_paths = {
        path.relative_to(ROOT).as_posix()
        for path in publication_root.rglob("*") if path.is_file()
    }
    if actual_publication_paths != expected_publication_paths:
        missing = sorted(expected_publication_paths - actual_publication_paths)
        added = sorted(actual_publication_paths - expected_publication_paths)
        raise FinalizationBlocked(
            f"Protected publication file set changed; missing={missing[:5]}, "
            f"added={added[:5]}"
        )

    for scope, records in (
        ("publication", publication_records), ("four-method source", source_records)
    ):
        for row in records:
            path = ROOT / str(row["path"])
            if (
                not path.is_file()
                or path.stat().st_size != int(row["bytes"])
                or sha256_file(path)
                != normalize_hash(row["sha256"], f"{scope} baseline hash")
            ):
                raise FinalizationBlocked(f"Immutable {scope} changed: {path}")

    publication_digest = stable_records_digest(publication_records)
    source_digest = stable_records_digest(source_records)
    if publication_digest != normalize_hash(
        publication.get("canonical_file_manifest_sha256", ""),
        "publication manifest digest",
    ):
        raise FinalizationBlocked("Publication baseline manifest digest failed")
    if source_digest != normalize_hash(
        sources.get("canonical_file_manifest_sha256", ""),
        "source manifest digest",
    ):
        raise FinalizationBlocked("Four-method source manifest digest failed")
    combined = sha256_bytes(
        f"{publication_digest}\n{source_digest}\n".encode("ascii")
    )
    if combined != normalize_hash(
        baseline.get("combined_protected_scope_sha256", ""),
        "combined protected-scope digest",
    ):
        raise FinalizationBlocked("Combined immutability digest failed")
    return {
        "status": "PASS",
        "baseline_sha256": sha256_file(IMMUTABILITY_BASELINE),
        "publication_files": len(publication_records),
        "four_method_source_files": len(source_records),
        "publication_manifest_sha256": publication_digest,
        "four_method_sources_manifest_sha256": source_digest,
        "combined_protected_scope_sha256": combined,
    }


def require_files(paths: Iterable[Path], label: str) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FinalizationBlocked(f"Missing {label}: {missing}")


def require_columns(frame: Any, columns: set[str], label: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise FinalizationBlocked(f"{label} lacks columns: {missing}")


def require_finite(frame: Any, columns: list[str], label: str, np: Any) -> None:
    values = frame[columns].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise FinalizationBlocked(f"{label} contains non-finite values")


def close(a: object, b: object, np: Any, field: str) -> None:
    def missing(value: object) -> bool:
        if value is None:
            return True
        try:
            return math.isnan(float(value))
        except (TypeError, ValueError):
            return False

    if missing(a) and missing(b):
        return
    if missing(a) != missing(b):
        raise FinalizationBlocked(f"{field} missingness mismatch")
    try:
        a_float = float(a)
        b_float = float(b)
    except (TypeError, ValueError) as error:
        raise FinalizationBlocked(f"{field} is not numeric") from error
    if not np.isclose(
        a_float, b_float, rtol=FLOAT_RTOL, atol=FLOAT_ATOL,
        equal_nan=True,
    ):
        raise FinalizationBlocked(f"{field} mismatch: {a_float} != {b_float}")


def nullable_finite_median(values: Any, np: Any) -> float | None:
    numeric = np.asarray(values, dtype=float)
    numeric = numeric[np.isfinite(numeric)]
    return float(np.median(numeric)) if len(numeric) else None


def nullable_percentage(numerator: int | float, denominator: int | float) -> float | None:
    denominator_float = float(denominator)
    if denominator_float == 0:
        return None
    return 100.0 * float(numerator) / denominator_float


def normalize_dataset_column(frame: Any, label: str) -> Any:
    if "dataset" in frame.columns:
        return frame
    if "section" in frame.columns:
        return frame.rename(columns={"section": "dataset"})
    raise FinalizationBlocked(f"{label} has neither dataset nor section")


def validate_canonical_display(frame: Any, label: str) -> None:
    """Require frozen publication labels without conflating them with identity."""

    require_columns(frame, {"dataset", "section_display"}, label)
    for dataset in DATASETS:
        values = frame.loc[
            frame["dataset"].astype(str).eq(dataset), "section_display"
        ].dropna().astype(str).unique()
        if len(values) != 1 or str(values[0]) != DISPLAY[dataset]:
            raise FinalizationBlocked(
                f"{label} display is noncanonical for {dataset}: {values}"
            )


def canonicalize_prespecified_thresholds(frame: Any, label: str, np: Any) -> Any:
    """Map round-tripped CSV floats to the three exact prespecified keys."""

    require_columns(frame, {"threshold"}, label)
    result = frame.copy()
    values = result["threshold"].to_numpy(float)
    choices = np.asarray(THRESHOLDS, dtype=float)
    distances = np.abs(values[:, None] - choices[None, :])
    nearest = np.argmin(distances, axis=1)
    if np.any(distances[np.arange(len(values)), nearest] > 1e-15):
        raise FinalizationBlocked(f"{label} contains a non-prespecified threshold")
    result["threshold"] = choices[nearest]
    return result


def strict_bool(value: object, field: str) -> bool:
    """Parse a serialized Boolean without treating nonempty text as true."""

    if isinstance(value, bool):
        return value
    # NumPy booleans deliberately avoid a top-level NumPy import.
    if type(value).__name__ == "bool_":
        return bool(value)
    text = str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    raise FinalizationBlocked(f"{field} is not an exact Boolean: {value!r}")


def bool_series_sum(series: Any, field: str) -> int:
    return sum(strict_bool(value, field) for value in series.tolist())


def verify_serialized_four_method_back_filter(
    observed: Any, expected: Any, pd: Any, np: Any,
) -> dict[str, Any]:
    """Verify the five-method CSV's immutable four-method back-filter.

    The producer proves bit-exact equality in memory before serialization.
    Re-parsing an identical decimal token through pandas can land one ULP from
    a previously parsed IEEE-754 value.  Text, missingness, keys, and all
    integer-valued columns therefore remain exact, while finite floating
    values use the producer's frozen sub-machine-scale bound.
    """

    keys = ["dataset", "method", "seed"]
    expected = expected.sort_values(keys).reset_index(drop=True)
    observed = observed.sort_values(keys).reset_index(drop=True)
    if list(observed.columns) != list(expected.columns):
        raise FinalizationBlocked(
            "Serialized four-method back-filter columns changed"
        )
    if len(observed) != len(expected):
        raise FinalizationBlocked(
            "Serialized four-method back-filter row count changed"
        )
    numeric_atol = 5e-16
    numeric_rtol = 1e-15
    maximum = 0.0
    numeric_columns: list[str] = []
    exact_columns: list[str] = []
    for column in expected.columns:
        left = expected[column]
        right = observed[column]
        left_numeric = pd.to_numeric(left, errors="coerce")
        right_numeric = pd.to_numeric(right, errors="coerce")
        nonmissing = left.notna()
        numeric = bool((~nonmissing | left_numeric.notna()).all())
        if numeric:
            if not np.array_equal(
                left.isna().to_numpy(), right.isna().to_numpy()
            ):
                raise FinalizationBlocked(
                    f"Serialized four-method NA pattern changed: {column}"
                )
            mask = nonmissing.to_numpy()
            left_values = left_numeric.to_numpy(float)[mask]
            right_values = right_numeric.to_numpy(float)[mask]
            difference = np.abs(left_values - right_values)
            scale = np.maximum(np.abs(left_values), np.abs(right_values))
            allowed = numeric_atol + numeric_rtol * scale
            if not np.isfinite(difference).all() or np.any(difference > allowed):
                maximum_observed = float(difference.max(initial=0.0))
                raise FinalizationBlocked(
                    f"Serialized four-method numeric drift in {column}: "
                    f"{maximum_observed:.3g} exceeds atol={numeric_atol:.3g}, "
                    f"rtol={numeric_rtol:.3g}"
                )
            maximum = max(maximum, float(difference.max(initial=0.0)))
            numeric_columns.append(column)
        else:
            if not np.array_equal(
                left.fillna("<NA>").astype(str).to_numpy(),
                right.fillna("<NA>").astype(str).to_numpy(),
            ):
                raise FinalizationBlocked(
                    f"Serialized four-method text changed: {column}"
                )
            exact_columns.append(column)
    return {
        "serialized_non_numeric_columns_exact": exact_columns,
        "serialized_numeric_columns": numeric_columns,
        "serialized_numeric_atol": numeric_atol,
        "serialized_numeric_rtol": numeric_rtol,
        "serialized_max_abs_difference": maximum,
    }


def canonical_csv_key(column: str, value: str) -> str:
    if column in {"seed", "seed_r", "seed_s"}:
        return str(int(value))
    if column == "threshold":
        return str(float(value))
    return str(value)


def authoritative_token_map(
    path: Path, key_columns: list[str], label: str,
) -> tuple[list[str], dict[tuple[str, ...], dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise FinalizationBlocked(f"{label} lacks a CSV header")
        fields = list(reader.fieldnames)
        rows: dict[tuple[str, ...], dict[str, str]] = {}
        for raw in reader:
            identity = tuple(
                canonical_csv_key(column, raw[column]) for column in key_columns
            )
            if identity in rows:
                raise FinalizationBlocked(
                    f"Duplicate authoritative token identity: {label}/{identity}"
                )
            rows[identity] = dict(raw)
    return fields, rows


def verify_exact_old_tokens_in_integrated(
    key: str, integrated_path: Path,
) -> dict[str, Any]:
    old_path = OLD_BY_INTEGRATION_KEY[key]
    key_columns = [
        "section" if value == "dataset" else value for value in ALL_KEYS[key]
    ]
    source_fields, source_rows = authoritative_token_map(
        old_path, key_columns, f"authoritative {key}"
    )
    observed: dict[tuple[str, ...], dict[str, str]] = {}
    with integrated_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != source_fields:
            raise FinalizationBlocked(
                f"Integrated {key} schema/order differs from authoritative source"
            )
        for row in reader:
            if row["method"] not in OLD_METHODS:
                continue
            identity = tuple(
                canonical_csv_key(column, row[column]) for column in key_columns
            )
            if identity in observed:
                raise FinalizationBlocked(
                    f"Duplicate integrated old token identity: {key}/{identity}"
                )
            observed[identity] = dict(row)
    if observed != source_rows:
        raise FinalizationBlocked(
            f"Integrated {key} old-method field tokens are not authoritative-exact"
        )
    return {
        "status": "PASS",
        "rows": len(source_rows),
        "serialized_authoritative_tokens_exact": True,
        "numeric_tolerance_used_for_old_rows": False,
        "authoritative_source_sha256": sha256_file(old_path),
    }


def validate_core_outputs(
    audit: dict[str, Any], pd: Any, np: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    require_files(CORE_FILES.values(), "core SEDR scientific output")
    seed = pd.read_csv(CORE_FILES["seed"], dtype={"dataset": str})
    pair = pd.read_csv(CORE_FILES["pair"], dtype={"dataset": str})
    iso = pd.read_csv(CORE_FILES["iso"], dtype={"dataset": str})
    consensus = pd.read_csv(CORE_FILES["consensus"], dtype={"dataset": str})
    unit = pd.read_csv(CORE_FILES["unit"], dtype={"dataset": str})

    require_columns(seed, {
        "dataset", "method", "seed", "reference_ari", "reference_nmi",
        "checkpoint_sha256", "labels_sha256", "protocol_hash",
        "requested_k", "observed_k",
    }, "SEDR seed-level accuracy")
    expected_seed = {
        (dataset, "SEDR", value)
        for dataset in DATASETS for value in SEEDS
    }
    actual_seed = set(zip(
        seed["dataset"].astype(str), seed["method"].astype(str),
        seed["seed"].astype(int),
    ))
    if len(seed) != EXPECTED_CHECKPOINTS or actual_seed != expected_seed:
        raise FinalizationBlocked("SEDR seed output is not exact 19 x 20")
    require_finite(seed, ["reference_ari", "reference_nmi"], "SEDR seed output", np)
    if not seed["reference_ari"].between(-1, 1).all() or not seed[
        "reference_nmi"
    ].between(0, 1).all():
        raise FinalizationBlocked("SEDR reference metric is outside its bounds")
    if not seed["protocol_hash"].astype(str).str.upper().eq(
        audit["protocol_hash"]
    ).all():
        raise FinalizationBlocked("SEDR seed output protocol provenance failed")
    checkpoint_map = {
        (row["dataset"], int(row["seed"])): row
        for row in audit["checkpoints"]
    }
    for row in seed.itertuples(index=False):
        technical = checkpoint_map[(str(row.dataset), int(row.seed))]
        if (
            normalize_hash(row.checkpoint_sha256, "core checkpoint hash")
            != technical["checkpoint_sha256"]
            or normalize_hash(row.labels_sha256, "core label hash")
            != technical["labels_sha256"]
            or int(row.requested_k) != int(technical["requested_k"])
            or int(row.observed_k) != int(technical["observed_k"])
        ):
            raise FinalizationBlocked(
                f"SEDR seed provenance mismatch: {row.dataset}/seed{row.seed}"
            )

    require_columns(pair, {
        "dataset", "method", "seed_r", "seed_s", "ari_r", "ari_s",
        "abs_reference_ari_difference", "pairwise_partition_ari",
        "pairwise_partition_nmi", "iso_accuracy_0_01",
        "iso_accuracy_0_02", "iso_accuracy_0_03",
    }, "SEDR pairwise output")
    if len(pair) != EXPECTED_SEDR_PAIRS:
        raise FinalizationBlocked("SEDR pairwise output is not 3,610 rows")
    seed_lookup = seed.set_index(["dataset", "seed"])
    for dataset in DATASETS:
        group = pair[pair["dataset"].eq(dataset)]
        observed_pairs = set(zip(
            group["seed_r"].astype(int), group["seed_s"].astype(int)
        ))
        if observed_pairs != set(itertools.combinations(SEEDS, 2)) or len(group) != 190:
            raise FinalizationBlocked(f"Pair grid failed: {dataset}")
        for row in group.itertuples(index=False):
            ari_r = float(seed_lookup.loc[(dataset, int(row.seed_r)), "reference_ari"])
            ari_s = float(seed_lookup.loc[(dataset, int(row.seed_s)), "reference_ari"])
            close(row.ari_r, ari_r, np, "pair ari_r")
            close(row.ari_s, ari_s, np, "pair ari_s")
            difference = abs(ari_r - ari_s)
            if not np.isclose(
                float(row.abs_reference_ari_difference), difference,
                rtol=0.0, atol=CORE_CSV_DERIVED_ATOL,
            ):
                raise FinalizationBlocked(
                    "pair reference-ARI difference mismatch beyond "
                    "12-significant-digit CSV rounding"
                )
            for threshold, column in (
                (0.01, "iso_accuracy_0_01"),
                (0.02, "iso_accuracy_0_02"),
                (0.03, "iso_accuracy_0_03"),
            ):
                observed = strict_bool(
                    getattr(row, column), f"pair threshold flag {column}"
                )
                if observed != (difference <= threshold + 1e-12):
                    raise FinalizationBlocked(f"Pair threshold flag failed: {column}")
    require_finite(pair, [
        "ari_r", "ari_s", "abs_reference_ari_difference",
        "pairwise_partition_ari", "pairwise_partition_nmi",
    ], "SEDR pairwise output", np)
    if not pair["pairwise_partition_ari"].between(-1, 1).all() or not pair[
        "pairwise_partition_nmi"
    ].between(0, 1).all():
        raise FinalizationBlocked("SEDR pair metric is outside its bounds")

    require_columns(iso, {
        "dataset", "method", "threshold", "n_total_seed_pairs",
        "n_iso_accuracy_pairs", "n_divergent_partition_ari_lt_0_50",
        "percentage_divergent_partition_ari_lt_0_50",
        "contains_divergent_pair", "median_pairwise_partition_ari",
        "minimum_pairwise_partition_ari",
    }, "SEDR iso-accuracy summary")
    if len(iso) != 57 or set(iso["dataset"].astype(str)) != set(DATASETS):
        raise FinalizationBlocked("SEDR iso summary is not 19 x 3")
    for dataset in DATASETS:
        dataset_iso = iso[iso["dataset"].eq(dataset)]
        if set(np.round(dataset_iso["threshold"].to_numpy(float), 8)) != set(THRESHOLDS):
            raise FinalizationBlocked(f"Iso thresholds failed: {dataset}")
        dataset_pairs = pair[pair["dataset"].eq(dataset)]
        for row in dataset_iso.itertuples(index=False):
            eligible = dataset_pairs[
                dataset_pairs["abs_reference_ari_difference"]
                <= float(row.threshold) + 1e-12
            ]
            count = len(eligible)
            divergent = int((eligible["pairwise_partition_ari"] < 0.50).sum())
            if (
                int(row.n_total_seed_pairs) != 190
                or int(row.n_iso_accuracy_pairs) != count
                or int(row.n_divergent_partition_ari_lt_0_50) != divergent
                or strict_bool(
                    row.contains_divergent_pair, "iso contains-divergent flag"
                ) != bool(divergent)
            ):
                raise FinalizationBlocked(f"Iso count reconciliation failed: {dataset}")
            expected_percentage = nullable_percentage(divergent, count)
            close(
                row.percentage_divergent_partition_ari_lt_0_50,
                expected_percentage, np, "iso divergent percentage",
            )
            close(
                row.median_pairwise_partition_ari,
                nullable_finite_median(
                    eligible["pairwise_partition_ari"], np
                ), np,
                "iso median partition ARI",
            )
            close(
                row.minimum_pairwise_partition_ari,
                (
                    float(eligible["pairwise_partition_ari"].min())
                    if len(eligible) else None
                ), np,
                "iso minimum partition ARI",
            )

    require_columns(consensus, {
        "dataset", "method", "n_seeds", "requested_k",
        "median_single_seed_reference_ari", "consensus20_reference_ari",
        "consensus20_reference_nmi",
        "median_single_seed_pairwise_partition_ari",
        "split_half_consensus_partition_ari",
        "split_half_reproducibility_gain", "split_half_improved",
    }, "SEDR consensus summary")
    if len(consensus) != 19 or consensus["dataset"].nunique() != 19:
        raise FinalizationBlocked("SEDR consensus summary is not 19 rows")
    require_finite(consensus, [
        "median_single_seed_reference_ari", "consensus20_reference_ari",
        "consensus20_reference_nmi",
        "median_single_seed_pairwise_partition_ari",
        "split_half_consensus_partition_ari",
        "split_half_reproducibility_gain",
    ], "SEDR consensus summary", np)
    for row in consensus.itertuples(index=False):
        dataset_seed = seed[seed["dataset"].eq(row.dataset)]
        dataset_pair = pair[pair["dataset"].eq(row.dataset)]
        median_seed = float(dataset_seed["reference_ari"].median())
        median_pair = float(dataset_pair["pairwise_partition_ari"].median())
        close(row.median_single_seed_reference_ari, median_seed, np, "consensus median seed")
        close(
            row.median_single_seed_pairwise_partition_ari, median_pair, np,
            "consensus median pair",
        )
        gain = float(row.split_half_consensus_partition_ari) - median_pair
        close(row.split_half_reproducibility_gain, gain, np, "consensus gain")
        if strict_bool(
            row.split_half_improved, "consensus split-half-improved flag"
        ) != (gain > 0):
            raise FinalizationBlocked("Consensus improvement flag failed")

    require_columns(unit, {
        "dataset", "method", "n_seeds", "n_seed_pairs",
        "median_reference_ari", "reference_ari_sd", "reference_ari_min",
        "reference_ari_max", "median_reference_nmi", "reference_nmi_sd",
        "median_pairwise_partition_ari", "p05_pairwise_partition_ari",
        "minimum_pairwise_partition_ari", "partition_instability",
        "low_sd_high_instability", "n_primary_iso_accuracy_pairs",
        "n_primary_iso_divergent_lt_0_50",
        "split_half_consensus_partition_ari",
        "split_half_reproducibility_gain",
    }, "SEDR unit summary")
    if len(unit) != 19 or unit["dataset"].nunique() != 19:
        raise FinalizationBlocked("SEDR unit summary is not 19 rows")
    for row in unit.itertuples(index=False):
        dataset_seed = seed[seed["dataset"].eq(row.dataset)]
        dataset_pair = pair[pair["dataset"].eq(row.dataset)]
        dataset_iso = iso[
            iso["dataset"].eq(row.dataset)
            & np.isclose(iso["threshold"], 0.02)
        ].iloc[0]
        dataset_consensus = consensus[consensus["dataset"].eq(row.dataset)].iloc[0]
        ari = dataset_seed["reference_ari"].to_numpy(float)
        nmi = dataset_seed["reference_nmi"].to_numpy(float)
        partitions = dataset_pair["pairwise_partition_ari"].to_numpy(float)
        expectations = {
            "median_reference_ari": np.median(ari),
            "reference_ari_sd": np.std(ari, ddof=1),
            "reference_ari_min": np.min(ari),
            "reference_ari_max": np.max(ari),
            "median_reference_nmi": np.median(nmi),
            "reference_nmi_sd": np.std(nmi, ddof=1),
            "median_pairwise_partition_ari": np.median(partitions),
            "p05_pairwise_partition_ari": np.quantile(partitions, 0.05),
            "minimum_pairwise_partition_ari": np.min(partitions),
            "partition_instability": 1 - np.median(partitions),
        }
        for field, expected in expectations.items():
            close(getattr(row, field), expected, np, f"unit {field}")
        expected_flag = expectations["reference_ari_sd"] <= 0.02 and expectations[
            "partition_instability"
        ] >= 0.30
        if strict_bool(
            row.low_sd_high_instability, "unit low-SD/high-instability flag"
        ) != expected_flag:
            raise FinalizationBlocked("Low-SD/high-instability flag failed")
        if (
            int(row.n_primary_iso_accuracy_pairs)
            != int(dataset_iso["n_iso_accuracy_pairs"])
            or int(row.n_primary_iso_divergent_lt_0_50)
            != int(dataset_iso["n_divergent_partition_ari_lt_0_50"])
        ):
            raise FinalizationBlocked("Unit primary iso summary failed")
        close(
            row.split_half_consensus_partition_ari,
            dataset_consensus["split_half_consensus_partition_ari"], np,
            "unit split-half consensus",
        )

    hashes = {name: sha256_file(path) for name, path in CORE_FILES.items()}
    return {
        "seed": seed, "pair": pair, "iso": iso,
        "consensus": consensus, "unit": unit,
    }, {"status": "PASS", "row_counts": {
        "seed_level_accuracy": len(seed),
        "pairwise_partition_reproducibility": len(pair),
        "iso_accuracy_results": len(iso),
        "consensus_results": len(consensus),
        "sedr_unit_summary": len(unit),
    }, "sha256": hashes}


def validate_marker_outputs(
    audit: dict[str, Any], core: dict[str, Any], pd: Any, np: Any, stats: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    require_files(MARKER_FILES.values(), "SEDR marker output")
    validation = load_json(MARKER_FILES["validation"])
    if validation.get("status") != "PASS" or validation.get("dataset_units") != 19:
        raise FinalizationBlocked("Marker validation manifest is not 19-unit PASS")
    provenance_expected = {
        "protocol_hash": audit["protocol_hash"],
        "input_manifest_sha256": audit["input_manifest_hash"],
        "checkpoint_manifest_sha256": audit["checkpoint_manifest_hash"],
        "gate_sha256": audit["gate_sha256"],
    }
    for field, expected in provenance_expected.items():
        if normalize_hash(validation.get(field, ""), f"marker {field}") != expected:
            raise FinalizationBlocked(f"Marker provenance mismatch: {field}")
    output_hashes = validation.get("output_sha256")
    if not isinstance(output_hashes, dict):
        raise FinalizationBlocked("Marker output-hash manifest is missing")
    for name in ("pair", "correlation", "tertile", "paired_test"):
        path = MARKER_FILES[name]
        if sha256_file(path) != normalize_hash(
            output_hashes.get(path.name, ""), f"marker {path.name} hash"
        ):
            raise FinalizationBlocked(f"Marker output hash failed: {path.name}")

    pair = pd.read_csv(MARKER_FILES["pair"], dtype={"dataset": str})
    correlation = pd.read_csv(
        MARKER_FILES["correlation"], dtype={"dataset": str}
    )
    tertile = pd.read_csv(MARKER_FILES["tertile"], dtype={"dataset": str})
    paired_test = load_json(MARKER_FILES["paired_test"])
    require_columns(pair, {
        "dataset", "method", "seed_r", "seed_s",
        "abs_reference_ari_difference", "pairwise_partition_ari",
        "top100_marker_jaccard", "top50_marker_jaccard",
        "marker_rank_spearman", "partition_ari_tertile",
    }, "SEDR marker pairs")
    core_primary = core["pair"][
        core["pair"]["abs_reference_ari_difference"] <= 0.02 + 1e-12
    ].copy()
    expected_keys = set(zip(
        core_primary["dataset"].astype(str),
        core_primary["seed_r"].astype(int),
        core_primary["seed_s"].astype(int),
    ))
    actual_keys = set(zip(
        pair["dataset"].astype(str), pair["seed_r"].astype(int),
        pair["seed_s"].astype(int),
    ))
    if len(pair) != len(core_primary) or actual_keys != expected_keys:
        raise FinalizationBlocked("Marker pairs are not the complete primary iso set")
    if int(validation.get("iso_accuracy_pairs", -1)) != len(pair):
        raise FinalizationBlocked("Marker validation pair count failed")
    require_columns(pair, {
        "aligned_domains_compared_n", "aligned_domains_compared",
    }, "SEDR marker pairs")
    require_finite(pair, [
        "abs_reference_ari_difference", "pairwise_partition_ari",
    ], "SEDR marker pair identity metrics", np)
    marker_bounds = {
        "top100_marker_jaccard": (0.0, 1.0),
        "top50_marker_jaccard": (0.0, 1.0),
        "marker_rank_spearman": (-1.0, 1.0),
    }
    for row in pair.itertuples(index=False):
        aligned_n = int(row.aligned_domains_compared_n)
        marker_values = {
            field: float(getattr(row, field)) for field in marker_bounds
        }
        if aligned_n < 0:
            raise FinalizationBlocked("Marker aligned-domain count is negative")
        if aligned_n == 0:
            if not all(np.isnan(value) for value in marker_values.values()):
                raise FinalizationBlocked(
                    "Zero-domain marker pair must contain three NA metrics"
                )
            if not pd.isna(row.aligned_domains_compared) and str(
                row.aligned_domains_compared
            ) != "":
                raise FinalizationBlocked(
                    "Zero-domain marker pair must have an empty domain list"
                )
        else:
            for field, value in marker_values.items():
                lower, upper = marker_bounds[field]
                if not np.isfinite(value) or value < lower or value > upper:
                    raise FinalizationBlocked(
                        f"Positive-domain marker pair has invalid {field}"
                    )
    core_lookup = core_primary.set_index(["dataset", "seed_r", "seed_s"])
    for row in pair.itertuples(index=False):
        source = core_lookup.loc[
            (str(row.dataset), int(row.seed_r), int(row.seed_s))
        ]
        close(
            row.abs_reference_ari_difference,
            source["abs_reference_ari_difference"], np,
            "marker/core reference gap",
        )
        close(
            row.pairwise_partition_ari,
            source["pairwise_partition_ari"], np,
            "marker/core partition ARI",
        )

    require_columns(correlation, {
        "dataset", "method", "n_iso_accuracy_pairs",
        "spearman_partition_ari_vs_top100_marker_jaccard",
        "spearman_partition_ari_vs_top50_marker_jaccard",
        "spearman_partition_ari_vs_marker_rank_spearman",
    }, "SEDR marker correlations")
    require_columns(tertile, {
        "dataset", "method", "partition_ari_tertile", "n_pairs",
        "median_pairwise_partition_ari", "median_top100_marker_jaccard",
        "median_top50_marker_jaccard", "median_marker_rank_spearman",
    }, "SEDR marker tertiles")
    if len(correlation) != 19 or correlation["dataset"].nunique() != 19:
        raise FinalizationBlocked("Marker correlations are not 19 rows")
    if len(tertile) != 57:
        raise FinalizationBlocked("Marker tertile summary is not 57 rows")
    stratified: list[Any] = []
    for dataset in DATASETS:
        group = pair[pair["dataset"].eq(dataset)].sort_values(
            ["pairwise_partition_ari", "seed_r", "seed_s"]
        ).copy()
        codes = (
            np.minimum(
                np.floor(np.arange(len(group)) * 3 / len(group)).astype(int), 2
            )
            if len(group) else np.asarray([], dtype=int)
        )
        expected_tertile = np.asarray([STRATA[index] for index in codes])
        if not np.array_equal(
            group["partition_ari_tertile"].astype(str).to_numpy(),
            expected_tertile,
        ):
            raise FinalizationBlocked(f"Deterministic marker tertile failed: {dataset}")
        stratified.append(group)
        corr_row = correlation[correlation["dataset"].eq(dataset)]
        if len(corr_row) != 1 or int(corr_row.iloc[0]["n_iso_accuracy_pairs"]) != len(group):
            raise FinalizationBlocked(f"Marker correlation count failed: {dataset}")
        corr_row = corr_row.iloc[0]
        def expected_spearman(right_field: str) -> float:
            left = group["pairwise_partition_ari"].to_numpy(float)
            right = group[right_field].to_numpy(float)
            complete = np.isfinite(left) & np.isfinite(right)
            left = left[complete]
            right = right[complete]
            if (
                len(left) < 2
                or (len(left) and np.all(left == left[0]))
                or (len(right) and np.all(right == right[0]))
            ):
                return float("nan")
            value = float(stats.spearmanr(left, right).statistic)
            return value if np.isfinite(value) else float("nan")

        correlation_expectations = {
            "spearman_partition_ari_vs_top100_marker_jaccard": expected_spearman(
                "top100_marker_jaccard"
            ),
            "spearman_partition_ari_vs_top50_marker_jaccard": expected_spearman(
                "top50_marker_jaccard"
            ),
            "spearman_partition_ari_vs_marker_rank_spearman": expected_spearman(
                "marker_rank_spearman"
            ),
        }
        for field, expected in correlation_expectations.items():
            close(corr_row[field], expected, np, f"marker correlation {field}")
        dataset_tertile = tertile[tertile["dataset"].eq(dataset)]
        if set(dataset_tertile["partition_ari_tertile"].astype(str)) != set(STRATA):
            raise FinalizationBlocked(f"Marker tertile set failed: {dataset}")
        for stratum in STRATA:
            subset = group[group["partition_ari_tertile"].eq(stratum)]
            summary = dataset_tertile[
                dataset_tertile["partition_ari_tertile"].eq(stratum)
            ].iloc[0]
            if int(summary["n_pairs"]) != len(subset):
                raise FinalizationBlocked("Marker tertile count failed")
            for field, source_field in (
                ("median_pairwise_partition_ari", "pairwise_partition_ari"),
                ("median_top100_marker_jaccard", "top100_marker_jaccard"),
                ("median_top50_marker_jaccard", "top50_marker_jaccard"),
                ("median_marker_rank_spearman", "marker_rank_spearman"),
            ):
                close(
                    summary[field], nullable_finite_median(
                        subset[source_field], np
                    ), np,
                    f"marker tertile {field}",
                )

    wide = tertile.pivot(
        index="dataset", columns="partition_ari_tertile",
        values="median_top100_marker_jaccard",
    ).reindex(index=DATASETS, columns=STRATA)
    paired = wide.dropna(subset=["Low", "High"])
    differences = (paired["High"] - paired["Low"]).to_numpy(float)
    paired_expectations = {
        "n_units": 19,
        "n_estimable_units": len(paired),
        "median_low": nullable_finite_median(paired["Low"], np),
        "median_middle": nullable_finite_median(wide["Middle"], np),
        "median_high": nullable_finite_median(paired["High"], np),
        "median_paired_high_minus_low": nullable_finite_median(differences, np),
        "units_high_greater_than_low": int(np.sum(differences > 0)),
        "units_equal": int(np.sum(differences == 0)),
        "units_high_less_than_low": int(np.sum(differences < 0)),
    }
    for field, expected in paired_expectations.items():
        if isinstance(expected, int):
            if int(paired_test.get(field, -1)) != expected:
                raise FinalizationBlocked(f"Marker paired test failed: {field}")
        else:
            close(paired_test.get(field), expected, np, f"marker paired {field}")
    expected_estimable = bool(len(differences) and np.any(differences != 0))
    if paired_test.get("estimable") is not expected_estimable:
        raise FinalizationBlocked("Marker paired-test estimability flag failed")
    if expected_estimable:
        expected_test = stats.wilcoxon(
            paired["High"], paired["Low"], alternative="greater",
            zero_method="wilcox", method="auto",
        )
        close(
            paired_test.get("wilcoxon_statistic"), expected_test.statistic,
            np, "marker Wilcoxon statistic",
        )
        close(
            paired_test.get("wilcoxon_p_value_one_sided"), expected_test.pvalue,
            np, "marker Wilcoxon P value",
        )
    elif (
        paired_test.get("wilcoxon_statistic") is not None
        or paired_test.get("wilcoxon_p_value_one_sided") is not None
    ):
        raise FinalizationBlocked(
            "Nonestimable marker paired test must have null statistic and P value"
        )

    hashes = {name: sha256_file(path) for name, path in MARKER_FILES.items()}
    return {
        "pair": pair, "correlation": correlation, "tertile": tertile,
        "paired_test": paired_test, "validation": validation,
    }, {"status": "PASS", "row_counts": {
        "marker_pairs": len(pair), "within_unit_correlations": len(correlation),
        "marker_tertiles": len(tertile),
    }, "sha256": hashes}


def verify_analysis_manifest_outputs(manifest: dict[str, Any]) -> None:
    if manifest.get("status") != "PASS":
        raise FinalizationBlocked("Five-method manifest is not PASS")
    records = manifest.get("outputs")
    if not isinstance(records, list) or len(records) != 7:
        raise FinalizationBlocked("Five-method output manifest is incomplete")
    expected_names = {
        path.name for key, path in FIVE_FILES.items() if key != "manifest"
    }
    observed_names = {str(row.get("path")) for row in records}
    if observed_names != expected_names:
        raise FinalizationBlocked("Five-method output file set differs from manifest")
    for row in records:
        path = FIVE_DIR / str(row["path"])
        if (
            not path.is_file()
            or path.stat().st_size != int(row["bytes"])
            or sha256_file(path)
            != normalize_hash(row["sha256"], "five-method output hash")
        ):
            raise FinalizationBlocked(f"Five-method output hash failed: {path}")


def exact_rank_reenumeration(
    integrated: Any, distribution: Any, rank_summary: Any, winner: Any,
    superiority: Any, uncertainty: Any, pd: Any, np: Any, chunk_size: int,
) -> None:
    method_index = {method: index for index, method in enumerate(METHODS)}
    for dataset in DATASETS:
        arrays: list[Any] = []
        for method in METHODS:
            values = integrated[
                integrated["dataset"].eq(dataset)
                & integrated["method"].eq(method)
            ].sort_values("seed")["reference_ari"].to_numpy(np.float64)
            if values.shape != (20,) or not np.isfinite(values).all():
                raise FinalizationBlocked(
                    f"Exact rank input is not 20 finite values: {dataset}/{method}"
                )
            arrays.append(values)
        rank_counts = np.zeros((5, 11), dtype=np.int64)
        winner_scaled = np.zeros(5, dtype=np.int64)
        strides = np.asarray([20 ** (4 - index) for index in range(5)], dtype=np.int64)
        processed = 0
        for start in range(0, COMBINATIONS_PER_DATASET, chunk_size):
            stop = min(COMBINATIONS_PER_DATASET, start + chunk_size)
            flat = np.arange(start, stop, dtype=np.int64)
            scores = np.empty((len(flat), 5), dtype=np.float64)
            for index in range(5):
                scores[:, index] = arrays[index][(flat // strides[index]) % 20]
            maxima = scores.max(axis=1)
            tied_maxima = scores == maxima[:, None]
            tie_sizes = tied_maxima.sum(axis=1).astype(np.int64)
            for index in range(5):
                focal = scores[:, index, None]
                greater = np.sum(scores > focal, axis=1, dtype=np.uint8)
                equal_other = np.sum(scores == focal, axis=1, dtype=np.uint8) - 1
                rank_x2 = 2 + 2 * greater + equal_other
                rank_counts[index] += np.bincount(rank_x2, minlength=11)[:11]
                selected = tie_sizes[tied_maxima[:, index]]
                winner_scaled[index] += int(
                    np.sum(WINNER_SCALE // selected, dtype=np.int64)
                )
            processed += len(flat)
        if processed != COMBINATIONS_PER_DATASET:
            raise FinalizationBlocked(f"Exact enumeration incomplete: {dataset}")
        if not np.all(rank_counts.sum(axis=1) == COMBINATIONS_PER_DATASET):
            raise FinalizationBlocked(f"Exact rank totals failed: {dataset}")
        if winner_scaled.sum() != WINNER_SCALE * COMBINATIONS_PER_DATASET:
            raise FinalizationBlocked(f"Exact winner credits failed: {dataset}")
        probabilities = winner_scaled / (WINNER_SCALE * COMBINATIONS_PER_DATASET)
        positive = probabilities[probabilities > 0]
        entropy = float(-np.sum(positive * np.log2(positive)))
        maximum = float(probabilities.max())

        for index, method in enumerate(METHODS):
            dist = distribution[
                distribution["dataset"].eq(dataset)
                & distribution["method"].eq(method)
            ].sort_values("rank_x2")
            if len(dist) != 9 or tuple(dist["rank_x2"].astype(int)) != tuple(range(2, 11)):
                raise FinalizationBlocked(f"Rank support failed: {dataset}/{method}")
            expected_counts = rank_counts[index, 2:11]
            if not np.array_equal(dist["count"].to_numpy(np.int64), expected_counts):
                raise FinalizationBlocked(f"Exact rank counts differ: {dataset}/{method}")
            if not np.allclose(
                dist["probability"].to_numpy(float),
                expected_counts / COMBINATIONS_PER_DATASET,
                rtol=0, atol=1e-15,
            ):
                raise FinalizationBlocked(f"Exact rank probabilities differ: {dataset}/{method}")
            summary = rank_summary[
                rank_summary["dataset"].eq(dataset)
                & rank_summary["method"].eq(method)
            ].iloc[0]
            counts = rank_counts[index]
            cumulative = np.cumsum(counts)
            median_x2 = int(np.flatnonzero(
                cumulative >= math.ceil(COMBINATIONS_PER_DATASET / 2)
            )[0])
            expected_rank = sum(
                rank_x2 * int(counts[rank_x2]) for rank_x2 in range(2, 11)
            ) / (2 * COMBINATIONS_PER_DATASET)
            expectations = {
                "empirical_p_rank1": probabilities[index],
                "empirical_expected_rank": expected_rank,
                "empirical_median_rank": median_x2 / 2,
                "empirical_p_top2": counts[:5].sum() / COMBINATIONS_PER_DATASET,
                "empirical_p_top3": counts[:7].sum() / COMBINATIONS_PER_DATASET,
            }
            for field, expected in expectations.items():
                close(summary[field], expected, np, f"exact rank summary {field}")
            win = winner[
                winner["dataset"].eq(dataset) & winner["method"].eq(method)
            ].iloc[0]
            if int(win["winner_credit_scaled_60"]) != int(winner_scaled[index]):
                raise FinalizationBlocked("Exact scaled winner credit differs")
            close(win["p_rank1"], probabilities[index], np, "exact p(rank1)")
            close(win["max_winner_probability"], maximum, np, "max p(rank1)")
            close(win["winner_entropy_bits"], entropy, np, "winner entropy")

        dataset_summary = uncertainty[uncertainty["dataset"].eq(dataset)].iloc[0]
        if int(dataset_summary["enumerated_combinations"]) != COMBINATIONS_PER_DATASET:
            raise FinalizationBlocked("Dataset enumeration count differs")
        close(dataset_summary["maximum_p_rank1"], maximum, np, "dataset max p(rank1)")
        expected_winners = ";".join(
            METHODS[index] for index in np.flatnonzero(
                np.isclose(probabilities, maximum, rtol=0, atol=0)
            )
        )
        if str(dataset_summary["most_probable_winner"]) != expected_winners:
            raise FinalizationBlocked("Most-probable winner differs")
        close(dataset_summary["winner_entropy_bits"], entropy, np, "dataset entropy")

        for first, second in itertools.combinations(range(5), 2):
            method_a, method_b = METHODS[first], METHODS[second]
            row = superiority[
                superiority["dataset"].eq(dataset)
                & superiority["method_A"].eq(method_a)
                & superiority["method_B"].eq(method_b)
            ].iloc[0]
            greater = int(np.count_nonzero(arrays[first][:, None] > arrays[second][None, :]))
            less = int(np.count_nonzero(arrays[first][:, None] < arrays[second][None, :]))
            ties = 400 - greater - less
            if (
                int(row["count_A_gt_B_20x20"]) != greater
                or int(row["count_B_gt_A_20x20"]) != less
                or int(row["tie_count_20x20"]) != ties
            ):
                raise FinalizationBlocked("Exact pairwise superiority counts differ")
            close(row["p_A_gt_B"], greater / 400, np, "pairwise superiority A")
            close(row["p_B_gt_A"], less / 400, np, "pairwise superiority B")
            close(row["tie_probability"], ties / 400, np, "pairwise superiority tie")


def validate_five_method_outputs(
    audit: dict[str, Any], core: dict[str, Any], pd: Any, np: Any,
    chunk_size: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    require_files(FIVE_FILES.values(), "five-method integration output")
    manifest = load_json(FIVE_FILES["manifest"])
    verify_analysis_manifest_outputs(manifest)
    if (
        normalize_hash(manifest.get("protocol_hash", ""), "five-method protocol")
        != audit["protocol_hash"]
        or normalize_hash(
            manifest.get("checkpoint_manifest_sha256", ""),
            "five-method checkpoint manifest",
        ) != audit["checkpoint_manifest_hash"]
        or normalize_hash(
            manifest.get("scientific_gate_sha256", ""),
            "five-method gate hash",
        ) != audit["gate_sha256"]
    ):
        raise FinalizationBlocked("Five-method provenance failed")
    if (
        int(manifest.get("combinations_per_dataset", -1))
        != COMBINATIONS_PER_DATASET
        or int(manifest.get("total_enumerated_combinations", -1))
        != TOTAL_COMBINATIONS
        or manifest.get("enumeration") != "exact streamed Cartesian product"
        or manifest.get("combinations_are_independent_experiments") is not False
    ):
        raise FinalizationBlocked("Five-method exact-enumeration manifest failed")

    frames = {
        name: normalize_dataset_column(
            pd.read_csv(path, dtype={"section": str, "dataset": str}), name
        )
        for name, path in FIVE_FILES.items()
        if name not in {"manifest", "reconciliation"}
    }
    integrated = frames["integrated_seed"]
    distribution = frames["rank_distribution"]
    rank_summary = frames["rank_summary"]
    winner = frames["winner"]
    superiority = frames["superiority"]
    uncertainty = frames["uncertainty"]
    expected_grid = {
        (dataset, method, seed)
        for dataset in DATASETS for method in METHODS for seed in SEEDS
    }
    actual_grid = set(zip(
        integrated["dataset"].astype(str), integrated["method"].astype(str),
        integrated["seed"].astype(int),
    ))
    if len(integrated) != 1900 or actual_grid != expected_grid:
        raise FinalizationBlocked("Integrated accuracy is not exact 19 x 5 x 20")
    validate_canonical_display(integrated, "integrated five-method accuracy")
    for name in (
        "rank_distribution", "rank_summary", "winner", "superiority",
        "uncertainty",
    ):
        validate_canonical_display(frames[name], f"five-method {name}")
    require_finite(
        integrated, ["reference_ari", "reference_nmi"],
        "integrated accuracy", np,
    )
    expected_counts = {
        "rank_distribution": 855, "rank_summary": 95, "winner": 95,
        "superiority": 190, "uncertainty": 19,
    }
    for name, count in expected_counts.items():
        if len(frames[name]) != count:
            raise FinalizationBlocked(f"Five-method row count failed: {name}")

    old = pd.read_csv(OLD_FILES["seed"], dtype={"section": str})
    old = normalize_dataset_column(old, "immutable four-method seed source")
    old_filtered = integrated[integrated["method"].isin(OLD_METHODS)][
        list(old.columns)
    ].sort_values(["dataset", "method", "seed"]).reset_index(drop=True)
    old_expected = old.sort_values(["dataset", "method", "seed"]).reset_index(drop=True)
    serialized_reconciliation = verify_serialized_four_method_back_filter(
        old_filtered, old_expected, pd, np,
    )
    sedr_integrated = integrated[integrated["method"].eq("SEDR")].set_index(
        ["dataset", "seed"]
    )
    for row in core["seed"].itertuples(index=False):
        observed = sedr_integrated.loc[(str(row.dataset), int(row.seed))]
        close(observed["reference_ari"], row.reference_ari, np, "integrated SEDR ARI")
        close(observed["reference_nmi"], row.reference_nmi, np, "integrated SEDR NMI")
        if (
            normalize_hash(observed["checkpoint_sha256"], "integrated checkpoint")
            != normalize_hash(row.checkpoint_sha256, "core checkpoint")
            or normalize_hash(observed["labels_sha256"], "integrated labels")
            != normalize_hash(row.labels_sha256, "core labels")
        ):
            raise FinalizationBlocked("Integrated SEDR provenance failed")

    reconciliation = load_json(FIVE_FILES["reconciliation"])
    if (
        reconciliation.get("status") != "PASS"
        or reconciliation.get("original_method_rows_observed_after_filter") != 1520
        or reconciliation.get("source_columns_exact_after_filter") is not True
        or reconciliation.get("existing_source_modified") is not False
    ):
        raise FinalizationBlocked("Four-method reconciliation record failed")

    exact_rank_reenumeration(
        integrated, distribution, rank_summary, winner, superiority,
        uncertainty, pd, np, chunk_size,
    )
    hashes = {name: sha256_file(path) for name, path in FIVE_FILES.items()}
    return {
        "integrated_seed": integrated, "rank_distribution": distribution,
        "rank_summary": rank_summary, "winner": winner,
        "superiority": superiority, "uncertainty": uncertainty,
        "manifest": manifest, "reconciliation": reconciliation,
    }, {"status": "PASS", "row_counts": {
        "integrated_seed_level_accuracy": len(integrated),
        "rank_distributions": len(distribution),
        "rank_summary": len(rank_summary),
        "winner_probabilities": len(winner),
        "pairwise_superiority": len(superiority),
        "dataset_uncertainty": len(uncertainty),
    }, "exact_combinations_per_dataset": COMBINATIONS_PER_DATASET,
        "exact_combinations_total": TOTAL_COMBINATIONS,
        "four_method_back_filter": "PASS",
        "four_method_serialized_reconciliation": serialized_reconciliation,
        "sha256": hashes}


def compare_sedr_integrated_columns(
    integrated: Any, source: Any, key_columns: list[str],
    column_mapping: dict[str, str], label: str, pd: Any, np: Any,
) -> None:
    observed = integrated[integrated["method"].eq("SEDR")].copy()
    expected = source.copy()
    observed.set_index(key_columns, inplace=True)
    expected.set_index(key_columns, inplace=True)
    if not observed.index.is_unique or not expected.index.is_unique:
        raise FinalizationBlocked(f"{label} SEDR key is duplicated")
    if set(observed.index) != set(expected.index):
        raise FinalizationBlocked(f"{label} SEDR key grid differs from source")
    observed = observed.sort_index()
    expected = expected.sort_index()
    for integrated_column, source_column in column_mapping.items():
        left = pd.to_numeric(observed[integrated_column], errors="coerce")
        right = pd.to_numeric(expected[source_column], errors="coerce")
        if not np.array_equal(left.isna().to_numpy(), right.isna().to_numpy()):
            raise FinalizationBlocked(
                f"{label} SEDR missingness differs: {integrated_column}"
            )
        mask = left.notna().to_numpy()
        if not np.allclose(
            left.to_numpy(float)[mask], right.to_numpy(float)[mask],
            rtol=FLOAT_RTOL, atol=FLOAT_ATOL, equal_nan=True,
        ):
            raise FinalizationBlocked(
                f"{label} SEDR values differ: {integrated_column}"
            )


def validate_all_outputs(
    audit: dict[str, Any], core: dict[str, Any], marker: dict[str, Any],
    pd: Any, np: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Independently validate the complete eight-table additive integration."""

    require_files(ALL_FILES.values(), "complete five-method integration output")
    if not INTEGRATOR.is_file() or sha256_file(INTEGRATOR) != INTEGRATOR_SHA256:
        raise FinalizationBlocked("Complete integration implementation hash changed")
    manifest = load_json(ALL_FILES["manifest"])
    if (
        manifest.get("status") != "PASS"
        or manifest.get("schema_version") != 1
        or manifest.get("analysis")
        != "complete additive five-method Project 9 integration"
        or manifest.get("methods") != list(METHODS)
        or manifest.get("datasets") != list(DATASETS)
        or manifest.get("four_method_sources_modified") is not False
        or int(manifest.get("expected_pairwise_rows", -1)) != 18050
        or int(manifest.get("expected_method_dataset_units", -1)) != 95
    ):
        raise FinalizationBlocked("Complete integration manifest contract failed")
    provenance = {
        "scientific_gate_sha256": audit["gate_sha256"],
        "protocol_hash": audit["protocol_hash"],
        "checkpoint_manifest_sha256": audit["checkpoint_manifest_hash"],
    }
    for field, expected in provenance.items():
        if normalize_hash(
            manifest.get(field, ""), f"all-output {field}"
        ) != expected:
            raise FinalizationBlocked(
                f"Complete integration provenance failed: {field}"
            )

    output_records = manifest.get("outputs")
    expected_output_names = {
        path.name for key, path in ALL_FILES.items() if key != "manifest"
    }
    if not isinstance(output_records, list) or {
        str(row.get("path")) for row in output_records
    } != expected_output_names:
        raise FinalizationBlocked("Complete integration output manifest is incomplete")
    for row in output_records:
        path = ALL_DIR / str(row["path"])
        if (
            not path.is_file()
            or path.stat().st_size != int(row["bytes"])
            or sha256_file(path)
            != normalize_hash(row["sha256"], "complete integration output hash")
        ):
            raise FinalizationBlocked(
                f"Complete integration output hash failed: {path.name}"
            )

    expected_sedr_sources = {
        "seed": CORE_FILES["seed"],
        "pairwise": CORE_FILES["pair"],
        "iso": CORE_FILES["iso"],
        "unit": CORE_FILES["unit"],
        "consensus": CORE_FILES["consensus"],
        "marker_unit": MARKER_FILES["correlation"],
        "marker_tertile": MARKER_FILES["tertile"],
        "marker_pairs": MARKER_FILES["pair"],
    }
    declared_sources = manifest.get("sedr_source_sha256")
    if not isinstance(declared_sources, dict):
        raise FinalizationBlocked("Complete integration lacks SEDR source hashes")
    for key, path in expected_sedr_sources.items():
        if normalize_hash(
            declared_sources.get(key, ""), f"integrated SEDR {key} source"
        ) != sha256_file(path):
            raise FinalizationBlocked(
                f"Complete integration SEDR source hash failed: {key}"
            )
    if normalize_hash(
        manifest.get("sedr_marker_validation_sha256", ""),
        "integrated marker-validation hash",
    ) != sha256_file(MARKER_FILES["validation"]):
        raise FinalizationBlocked("Complete integration marker validation changed")
    if normalize_hash(
        manifest.get("sedr_marker_checkpoint_manifest_sha256", ""),
        "integrated marker checkpoint digest",
    ) != audit["checkpoint_manifest_hash"]:
        raise FinalizationBlocked("Complete integration marker checkpoint digest failed")

    frames = {
        key: normalize_dataset_column(
            pd.read_csv(path, dtype={"section": str}), f"integrated {key}"
        )
        for key, path in ALL_FILES.items()
        if key not in {"headline", "manifest"}
    }
    frames["iso"] = canonicalize_prespecified_thresholds(
        frames["iso"], "complete integrated iso", np
    )
    expected_rows = {
        "seed": 1900, "pairwise": 18050, "iso": 285, "unit": 95,
        "consensus": 95, "marker_unit": 95, "marker_tertile": 285,
        "marker_pairs": len(pd.read_csv(OLD_FILES["marker_pair"]))
        + len(marker["pair"]),
    }
    declared_rows = manifest.get("row_counts")
    if not isinstance(declared_rows, dict):
        raise FinalizationBlocked("Complete integration row counts are missing")
    for key, expected in expected_rows.items():
        if len(frames[key]) != expected or int(declared_rows.get(key, -1)) != expected:
            raise FinalizationBlocked(
                f"Complete integration row count failed: {key}"
            )

    unit_grid = {(dataset, method) for dataset in DATASETS for method in METHODS}
    grids = {
        "seed": {
            (dataset, method, seed) for dataset in DATASETS
            for method in METHODS for seed in SEEDS
        },
        "pairwise": {
            (dataset, method, first, second) for dataset in DATASETS
            for method in METHODS for first, second in itertools.combinations(SEEDS, 2)
        },
        "iso": {
            (dataset, method, threshold) for dataset in DATASETS
            for method in METHODS for threshold in THRESHOLDS
        },
        "unit": unit_grid, "consensus": unit_grid, "marker_unit": unit_grid,
        "marker_tertile": {
            (dataset, method, stratum) for dataset in DATASETS
            for method in METHODS for stratum in STRATA
        },
    }
    for key, expected in grids.items():
        columns = ALL_KEYS[key]
        actual = set(map(tuple, frames[key][columns].itertuples(
            index=False, name=None
        )))
        if actual != expected or frames[key].duplicated(columns).any():
            raise FinalizationBlocked(
                f"Complete integration exact key grid failed: {key}"
            )
    for key, frame in frames.items():
        validate_canonical_display(frame, f"complete integrated {key}")

    pairwise = frames["pairwise"]
    eligible = pairwise[
        pairwise["abs_reference_ari_difference"] <= 0.02 + 1e-12
    ]
    eligible_keys = set(map(tuple, eligible[
        ALL_KEYS["marker_pairs"]
    ].itertuples(index=False, name=None)))
    marker_keys = set(map(tuple, frames["marker_pairs"][
        ALL_KEYS["marker_pairs"]
    ].itertuples(index=False, name=None)))
    if (
        frames["marker_pairs"].duplicated(ALL_KEYS["marker_pairs"]).any()
        or marker_keys != eligible_keys
        or len(frames["marker_pairs"]) != len(eligible)
    ):
        raise FinalizationBlocked(
            "Integrated marker pairs are not the exact primary iso-accuracy set"
        )
    primary = frames["iso"][np.isclose(frames["iso"]["threshold"], 0.02)]
    declared_marker_counts = frames["marker_unit"].set_index(
        ["dataset", "method"]
    )["n_iso_accuracy_pairs"].sort_index()
    iso_counts = primary.set_index(["dataset", "method"])[
        "n_iso_accuracy_pairs"
    ].sort_index()
    if not np.array_equal(
        declared_marker_counts.to_numpy(int), iso_counts.to_numpy(int)
    ):
        raise FinalizationBlocked("Integrated marker/core iso counts differ")

    exact_backfilters: dict[str, Any] = {}
    declared_backfilters = manifest.get("four_method_backfilter_reconciliation")
    if not isinstance(declared_backfilters, dict) or set(declared_backfilters) != set(
        OLD_BY_INTEGRATION_KEY
    ):
        raise FinalizationBlocked("Eight-table back-filter manifest is incomplete")
    for key in OLD_BY_INTEGRATION_KEY:
        declared = declared_backfilters[key]
        if (
            declared.get("status") != "PASS"
            or declared.get("in_memory_source_columns_bit_exact") is not True
            or declared.get("serialized_authoritative_tokens_exact") is not True
            or declared.get("numeric_tolerance_used_for_old_rows") is not False
        ):
            raise FinalizationBlocked(
                f"Declared four-method exact reconciliation failed: {key}"
            )
        independently_verified = verify_exact_old_tokens_in_integrated(
            key, ALL_FILES[key]
        )
        if int(declared.get("rows", -1)) != independently_verified["rows"]:
            raise FinalizationBlocked(
                f"Four-method exact reconciliation row count failed: {key}"
            )
        if normalize_hash(
            declared.get("authoritative_source_sha256", ""),
            f"four-method {key} source hash",
        ) != independently_verified["authoritative_source_sha256"]:
            raise FinalizationBlocked(
                f"Four-method exact reconciliation source hash failed: {key}"
            )
        exact_backfilters[key] = independently_verified

    compare_sedr_integrated_columns(
        frames["seed"], core["seed"], ["dataset", "method", "seed"],
        {"reference_ari": "reference_ari", "reference_nmi": "reference_nmi"},
        "integrated seed", pd, np,
    )
    compare_sedr_integrated_columns(
        frames["pairwise"], core["pair"],
        ["dataset", "method", "seed_r", "seed_s"],
        {
            "ari_r": "ari_r", "ari_s": "ari_s",
            "abs_reference_ari_difference": "abs_reference_ari_difference",
            "pairwise_partition_ari": "pairwise_partition_ari",
            "pairwise_partition_nmi": "pairwise_partition_nmi",
        }, "integrated pairwise", pd, np,
    )
    compare_sedr_integrated_columns(
        frames["iso"], core["iso"],
        ["dataset", "method", "threshold"],
        {
            "n_iso_accuracy_pairs": "n_iso_accuracy_pairs",
            "median_pairwise_partition_ari": "median_pairwise_partition_ari",
            "minimum_pairwise_partition_ari": "minimum_pairwise_partition_ari",
            "n_partition_ari_below_0_50":
                "n_divergent_partition_ari_lt_0_50",
        }, "integrated iso", pd, np,
    )
    compare_sedr_integrated_columns(
        frames["unit"], core["unit"], ["dataset", "method"],
        {
            "median_reference_ari": "median_reference_ari",
            "reference_ari_sd": "reference_ari_sd",
            "median_pairwise_partition_ari": "median_pairwise_partition_ari",
            "partition_instability": "partition_instability",
        }, "integrated unit", pd, np,
    )
    compare_sedr_integrated_columns(
        frames["consensus"], core["consensus"], ["dataset", "method"],
        {
            "median_single_seed_reference_ari":
                "median_single_seed_reference_ari",
            "consensus20_reference_ari": "consensus20_reference_ari",
            "split_half_consensus_ari":
                "split_half_consensus_partition_ari",
            "split_half_gain_over_median_single_seed_pairwise_ari":
                "split_half_reproducibility_gain",
        }, "integrated consensus", pd, np,
    )
    compare_sedr_integrated_columns(
        frames["marker_unit"], marker["correlation"], ["dataset", "method"],
        {
            "n_iso_accuracy_pairs": "n_iso_accuracy_pairs",
            "spearman_partition_ari_vs_marker_jaccard":
                "spearman_partition_ari_vs_top100_marker_jaccard",
            "spearman_partition_ari_vs_top50_jaccard":
                "spearman_partition_ari_vs_top50_marker_jaccard",
            "spearman_partition_ari_vs_marker_rank_spearman":
                "spearman_partition_ari_vs_marker_rank_spearman",
        }, "integrated marker unit", pd, np,
    )
    compare_sedr_integrated_columns(
        frames["marker_tertile"], marker["tertile"],
        ["dataset", "method", "partition_ari_tertile"],
        {
            "n_pairs": "n_pairs",
            "median_pairwise_partition_ari": "median_pairwise_partition_ari",
            "median_top100_marker_jaccard": "median_top100_marker_jaccard",
            "median_top50_marker_jaccard": "median_top50_marker_jaccard",
            "median_marker_rank_spearman": "median_marker_rank_spearman",
        }, "integrated marker tertile", pd, np,
    )
    compare_sedr_integrated_columns(
        frames["marker_pairs"], marker["pair"],
        ["dataset", "method", "seed_r", "seed_s"],
        {
            "abs_reference_ari_difference": "abs_reference_ari_difference",
            "pairwise_partition_ari": "pairwise_partition_ari",
            "top100_marker_jaccard": "top100_marker_jaccard",
            "top50_marker_jaccard": "top50_marker_jaccard",
            "marker_rank_spearman": "marker_rank_spearman",
        }, "integrated marker pairs", pd, np,
    )

    headline = load_json(ALL_FILES["headline"])
    structural = headline.get("structural_totals", {})
    if structural != {
        "dataset_entries": 19, "methods": 5, "method_dataset_units": 95,
        "seed_specific_runs": 1900, "pairwise_seed_comparisons": 18050,
    }:
        raise FinalizationBlocked("Integrated headline structural totals failed")
    headline_iso = headline.get("primary_iso_accuracy", {})
    expected_eligible = int(primary["n_iso_accuracy_pairs"].sum())
    expected_divergent = int(primary["n_partition_ari_below_0_50"].sum())
    if (
        int(headline_iso.get("eligible_pairs", -1)) != expected_eligible
        or int(headline_iso.get("divergent_partition_ari_lt_0_50", -1))
        != expected_divergent
        or int(headline_iso.get("affected_units", -1))
        != int((primary["n_partition_ari_below_0_50"] > 0).sum())
    ):
        raise FinalizationBlocked("Integrated headline iso totals failed")
    close(
        headline_iso.get("percentage_divergent"),
        nullable_percentage(expected_divergent, expected_eligible),
        np, "integrated headline divergent percentage",
    )

    hashes = {key: sha256_file(path) for key, path in ALL_FILES.items()}
    return {"frames": frames, "headline": headline, "manifest": manifest}, {
        "status": "PASS",
        "integrator_sha256": INTEGRATOR_SHA256,
        "row_counts": expected_rows,
        "exact_four_method_backfilters": exact_backfilters,
        "sha256": hashes,
    }


def validate_old_integrated_sources(pd: Any, np: Any) -> dict[str, Any]:
    require_files(OLD_FILES.values(), "immutable four-method integrated source")
    frames = {
        name: normalize_dataset_column(
            pd.read_csv(path, dtype={"section": str, "dataset": str}), name
        )
        for name, path in OLD_FILES.items() if path.suffix == ".csv"
    }
    expected_units = {(dataset, method) for dataset in DATASETS for method in OLD_METHODS}
    unit_grid = set(zip(
        frames["unit"]["dataset"].astype(str),
        frames["unit"]["method"].astype(str),
    ))
    if len(frames["seed"]) != 1520 or len(frames["pair"]) != 14440:
        raise FinalizationBlocked("Four-method structural totals changed")
    if len(frames["unit"]) != 76 or unit_grid != expected_units:
        raise FinalizationBlocked("Four-method unit grid changed")
    if len(frames["iso"]) != 228 or len(frames["consensus"]) != 76:
        raise FinalizationBlocked("Four-method iso/consensus totals changed")
    if len(frames["marker_correlation"]) != 76 or len(frames["marker_tertile"]) != 228:
        raise FinalizationBlocked("Four-method marker summary totals changed")
    primary_iso = frames["iso"][np.isclose(frames["iso"]["threshold"], 0.02)]
    if int(primary_iso["n_iso_accuracy_pairs"].sum()) != len(frames["marker_pair"]):
        raise FinalizationBlocked("Four-method marker-pair count no longer matches iso summary")
    return frames


def component_label(success_count: int, total_count: int) -> str:
    if total_count == 0:
        return "NOT_ESTIMABLE"
    if success_count == total_count:
        return "SUPPORTS_EXISTING_PATTERN"
    if success_count == 0:
        return "DOES_NOT_SUPPORT"
    return "HETEROGENEOUS"


def scientific_assessment(
    core: dict[str, Any], marker: dict[str, Any], five: dict[str, Any],
    np: Any,
) -> dict[str, Any]:
    low_sd = bool_series_sum(
        core["unit"]["low_sd_high_instability"],
        "unit low-SD/high-instability flag",
    )
    primary_iso = core["iso"][np.isclose(core["iso"]["threshold"], 0.02)]
    divergent_entries = bool_series_sum(
        primary_iso["contains_divergent_pair"],
        "iso contains-divergent flag",
    )
    sedr_winner = five["winner"][five["winner"]["method"].eq("SEDR")]
    winner_positive = int((sedr_winner["p_rank1"] > 0).sum())
    rho = marker["correlation"][
        "spearman_partition_ari_vs_top100_marker_jaccard"
    ].to_numpy(float)
    estimable = int(np.isfinite(rho).sum())
    positive = int(np.sum(rho[np.isfinite(rho)] > 0))
    improved = bool_series_sum(
        core["consensus"]["split_half_improved"],
        "consensus split-half-improved flag",
    )
    components = {
        "score_map_decoupling": {
            "label": component_label(low_sd, 19),
            "numerator": low_sd, "denominator": 19,
            "criterion": "reference ARI SD <=0.02 and partition instability >=0.30",
        },
        "iso_accuracy_map_divergence": {
            "label": component_label(divergent_entries, 19),
            "numerator": divergent_entries, "denominator": 19,
            "criterion": "at least one primary iso-accuracy pair with partition ARI <0.50",
        },
        "winner_distribution_contribution": {
            "label": component_label(winner_positive, 19),
            "numerator": winner_positive, "denominator": 19,
            "criterion": "SEDR receives positive exact fractional rank-1 probability",
        },
        "partition_marker_relationship": {
            "label": component_label(positive, estimable),
            "numerator": positive, "denominator": estimable,
            "criterion": "positive within-entry Spearman rho for partition ARI vs top-100 marker Jaccard",
        },
        "consensus_mitigation": {
            "label": component_label(improved, 19),
            "numerator": improved, "denominator": 19,
            "criterion": "split-half consensus ARI exceeds median single-seed pairwise ARI",
        },
    }
    labels = [item["label"] for item in components.values()]
    support_count = labels.count("SUPPORTS_EXISTING_PATTERN")
    core_contrast = (
        components["score_map_decoupling"]["label"] == "DOES_NOT_SUPPORT"
        and components["iso_accuracy_map_divergence"]["label"]
        == "DOES_NOT_SUPPORT"
    )
    if core_contrast:
        overall = "CONTRASTING_STOCHASTIC_PROFILE"
    elif support_count >= 4 and "DOES_NOT_SUPPORT" not in labels:
        overall = "STRONG_METHOD_GENERALIZATION"
    elif support_count >= 2:
        overall = "PARTIAL_METHOD_GENERALIZATION"
    else:
        overall = "LIMITED_METHOD_GENERALIZATION"
    if overall not in OVERALL_LABELS or any(
        item["label"] not in COMPONENT_LABELS for item in components.values()
    ):
        raise FinalizationBlocked("Scientific classification is outside allowed labels")
    return {
        "components": components,
        "overall": overall,
        "classification_rule": (
            "CONTRASTING when both prespecified core stochastic components do not "
            "support; otherwise STRONG for >=4 supporting components with no "
            "non-support, PARTIAL for >=2 supporting components, LIMITED otherwise"
        ),
    }


def build_quantitative_summary(
    audit: dict[str, Any], immutability: dict[str, Any], core: dict[str, Any],
    marker: dict[str, Any], five: dict[str, Any], old: dict[str, Any],
    assessment: dict[str, Any], pd: Any, np: Any,
) -> dict[str, Any]:
    unit = core["unit"]
    primary_iso = core["iso"][np.isclose(core["iso"]["threshold"], 0.02)]
    marker_rho = marker["correlation"][
        "spearman_partition_ari_vs_top100_marker_jaccard"
    ].to_numpy(float)
    consensus = core["consensus"]
    winner = five["winner"]
    uncertainty = five["uncertainty"]
    sedr_winner = winner[winner["method"].eq("SEDR")]
    most_probable = int(sum(
        "SEDR" in str(value).split(";")
        for value in uncertainty["most_probable_winner"]
    ))
    if most_probable >= 10:
        winner_description = "often"
    elif most_probable >= 1:
        winner_description = "occasionally"
    else:
        winner_description = "rarely"

    old_iso_primary = old["iso"][np.isclose(old["iso"]["threshold"], 0.02)]
    old_divergent_column = (
        "n_partition_ari_below_0_50"
        if "n_partition_ari_below_0_50" in old_iso_primary.columns
        else "n_divergent_partition_ari_lt_0_50"
    )
    old_affected = int((old_iso_primary[old_divergent_column] > 0).sum())
    old_iso_pairs = int(old_iso_primary["n_iso_accuracy_pairs"].sum())
    old_divergent = int(old_iso_primary[old_divergent_column].sum())
    sedr_iso_pairs = int(primary_iso["n_iso_accuracy_pairs"].sum())
    sedr_divergent = int(
        primary_iso["n_divergent_partition_ari_lt_0_50"].sum()
    )
    integrated_iso_pairs = old_iso_pairs + sedr_iso_pairs
    integrated_divergent = old_divergent + sedr_divergent

    old_rho_column = (
        "spearman_partition_ari_vs_marker_jaccard"
        if "spearman_partition_ari_vs_marker_jaccard"
        in old["marker_correlation"].columns
        else "spearman_partition_ari_vs_top100_marker_jaccard"
    )
    old_rho = old["marker_correlation"][old_rho_column].to_numpy(float)
    integrated_rho = np.concatenate([old_rho, marker_rho])
    old_gain_column = (
        "split_half_gain_over_median_single_seed_pairwise_ari"
        if "split_half_gain_over_median_single_seed_pairwise_ari"
        in old["consensus"].columns
        else "split_half_reproducibility_gain"
    )
    old_gain = old["consensus"][old_gain_column].to_numpy(float)
    integrated_gain = np.concatenate([
        old_gain, consensus["split_half_reproducibility_gain"].to_numpy(float)
    ])
    sedr_primary_pair_ari = core["pair"].loc[
        core["pair"]["abs_reference_ari_difference"] <= 0.02 + 1e-12,
        "pairwise_partition_ari",
    ].to_numpy(float)

    technical = pd.read_csv(EXPANSION / "technical_metadata.csv")
    if len(technical) != 380:
        raise FinalizationBlocked("Final technical metadata is not 380 rows")
    gate = audit["gate"]
    if sha256_file(EXPANSION / "technical_metadata.csv") != normalize_hash(
        gate.get("technical_metadata_sha256", ""), "gate technical metadata hash"
    ):
        raise FinalizationBlocked("Final technical metadata hash failed")
    identical = pd.read_csv(EXPANSION / "identical_seed_controls.csv")
    if len(identical) != 2 or not np.allclose(
        identical["partition_ari_same_seed"].to_numpy(float), 1.0,
        rtol=0, atol=0,
    ):
        raise FinalizationBlocked("Identical-seed technical controls failed")

    summary = {
        "status": "PASS",
        "decision": "LOCK_ADD_SEDR",
        "technical": {
            "datasets": 19, "runs_valid": 380, "runs_target": 380,
            "runtime_seconds_total": float(technical["runtime_seconds"].sum()),
            "runtime_hours_total": float(technical["runtime_seconds"].sum() / 3600),
            "runtime_seconds_median": float(technical["runtime_seconds"].median()),
            "peak_ram_gib_max": float(technical["peak_ram_gib"].max()),
            "peak_gpu_memory_mib_max": float(
                technical["peak_gpu_memory_mib"].max()
            ),
            "identical_seed_controls_passed": 2,
            "identical_seed_controls_total": 2,
        },
        "sedr_reference_score_stability": {
            "median_reference_ari_sd": float(unit["reference_ari_sd"].median()),
            "minimum_reference_ari_sd": float(unit["reference_ari_sd"].min()),
            "maximum_reference_ari_sd": float(unit["reference_ari_sd"].max()),
        },
        "sedr_partition_reproducibility": {
            "median_of_unit_median_pairwise_ari": float(
                unit["median_pairwise_partition_ari"].median()
            ),
            "minimum_unit_median_pairwise_ari": float(
                unit["median_pairwise_partition_ari"].min()
            ),
            "maximum_unit_median_pairwise_ari": float(
                unit["median_pairwise_partition_ari"].max()
            ),
            "low_sd_high_instability_entries": bool_series_sum(
                unit["low_sd_high_instability"],
                "unit low-SD/high-instability flag",
            ),
        },
        "sedr_iso_accuracy": {
            "threshold": 0.02,
            "eligible_pairs": sedr_iso_pairs,
            "divergent_pairs_partition_ari_lt_0_50": sedr_divergent,
            "divergent_percentage": nullable_percentage(
                sedr_divergent, sedr_iso_pairs
            ),
            "affected_entries": bool_series_sum(
                primary_iso["contains_divergent_pair"],
                "iso contains-divergent flag",
            ),
            "median_iso_partition_ari": nullable_finite_median(
                sedr_primary_pair_ari, np
            ),
            "minimum_iso_partition_ari": (
                float(np.min(sedr_primary_pair_ari))
                if len(sedr_primary_pair_ari) else None
            ),
        },
        "sedr_partition_marker": {
            "iso_accuracy_pairs": len(marker["pair"]),
            "estimable_entries": int(np.isfinite(marker_rho).sum()),
            "positive_entries": int(np.sum(marker_rho[np.isfinite(marker_rho)] > 0)),
            "median_within_entry_rho": nullable_finite_median(marker_rho, np),
            "low_tertile_median": marker["paired_test"]["median_low"],
            "middle_tertile_median": marker["paired_test"]["median_middle"],
            "high_tertile_median": marker["paired_test"]["median_high"],
            "median_paired_high_minus_low": marker["paired_test"][
                "median_paired_high_minus_low"
            ],
            "paired_test_estimable": strict_bool(
                marker["paired_test"]["estimable"],
                "marker paired-test estimable flag",
            ),
            "wilcoxon_statistic": marker["paired_test"]["wilcoxon_statistic"],
            "wilcoxon_p_value_one_sided": marker["paired_test"][
                "wilcoxon_p_value_one_sided"
            ],
        },
        "sedr_consensus": {
            "median_single_seed_pairwise_ari": float(
                consensus["median_single_seed_pairwise_partition_ari"].median()
            ),
            "median_split_half_consensus_ari": float(
                consensus["split_half_consensus_partition_ari"].median()
            ),
            "improved_entries": bool_series_sum(
                consensus["split_half_improved"],
                "consensus split-half-improved flag",
            ),
            "entries_total": 19,
            "median_gain": float(consensus["split_half_reproducibility_gain"].median()),
        },
        "five_method_ranking": {
            "exact_combinations_per_entry": COMBINATIONS_PER_DATASET,
            "exact_combinations_total": TOTAL_COMBINATIONS,
            "combinations_are_independent_experiments": False,
            "minimum_max_p_rank1": float(uncertainty["maximum_p_rank1"].min()),
            "maximum_max_p_rank1": float(uncertainty["maximum_p_rank1"].max()),
            "entries_max_p_rank1_lt_0_50": int(
                (uncertainty["maximum_p_rank1"] < 0.50).sum()
            ),
            "entries_max_p_rank1_lt_0_75": int(
                (uncertainty["maximum_p_rank1"] < 0.75).sum()
            ),
            "sedr_positive_p_rank1_entries": int((sedr_winner["p_rank1"] > 0).sum()),
            "sedr_most_probable_winner_entries": most_probable,
            "sedr_winner_description": winner_description,
        },
        "integrated_totals": {
            "datasets": 19, "methods": 5, "method_dataset_units": 95,
            "seed_specific_runs": 1900, "pairwise_seed_comparisons": 18050,
            "iso_accuracy_pairs": integrated_iso_pairs,
            "divergent_iso_accuracy_pairs": integrated_divergent,
            "divergent_iso_accuracy_percentage": nullable_percentage(
                integrated_divergent, integrated_iso_pairs
            ),
            "affected_method_dataset_units": old_affected + bool_series_sum(
                primary_iso["contains_divergent_pair"],
                "iso contains-divergent flag",
            ),
            "marker_correlation_estimable_units": int(np.isfinite(integrated_rho).sum()),
            "marker_correlation_positive_units": int(
                np.sum(integrated_rho[np.isfinite(integrated_rho)] > 0)
            ),
            "median_within_unit_marker_rho": nullable_finite_median(
                integrated_rho, np
            ),
            "consensus_improved_units": int(np.sum(integrated_gain > 0)),
            "median_consensus_gain": float(np.median(integrated_gain)),
        },
        "hbca1": {
            "reference_provenance": (
                "manual H&E/pathology segmentation from the original SEDR study; "
                "not SEDR clustering output"
            ),
            "interpretive_caveat": "prior developer-dataset exposure",
            "included": True,
        },
        "scientific_assessment": assessment,
        "integrity": immutability,
    }
    return summary


def f(value: object, digits: int = 3) -> str:
    if value is None:
        return "not estimable"
    numeric = float(value)
    if not math.isfinite(numeric):
        return "not estimable"
    return f"{numeric:.{digits}f}"


def render_reports(
    generated: str, summary: dict[str, Any], validation: dict[str, Any],
    audit: dict[str, Any],
) -> dict[Path, bytes]:
    technical = summary["technical"]
    stability = summary["sedr_reference_score_stability"]
    reproducibility = summary["sedr_partition_reproducibility"]
    iso = summary["sedr_iso_accuracy"]
    marker = summary["sedr_partition_marker"]
    consensus = summary["sedr_consensus"]
    ranking = summary["five_method_ranking"]
    integrated = summary["integrated_totals"]
    assessment = summary["scientific_assessment"]

    marker_rho_text = f(marker["median_within_entry_rho"])
    marker_low_text = f(marker["low_tertile_median"])
    marker_middle_text = f(marker["middle_tertile_median"])
    marker_high_text = f(marker["high_tertile_median"])
    marker_difference_text = f(marker["median_paired_high_minus_low"])
    integrated_rho_text = f(integrated["median_within_unit_marker_rho"])
    iso_percentage_text = (
        f(iso["divergent_percentage"], 1) + "%"
        if iso["divergent_percentage"] is not None else "not estimable"
    )
    iso_median_text = f(iso["median_iso_partition_ari"])
    iso_minimum_text = f(iso["minimum_iso_partition_ari"])
    integrated_percentage_text = (
        f(integrated["divergent_iso_accuracy_percentage"], 1) + "%"
        if integrated["divergent_iso_accuracy_percentage"] is not None
        else "not estimable"
    )

    final_report = f"""# Final SEDR report

## SEDR EXPANSION: LOCK_ADD_SEDR — 380/380 COMPLETE

The outcome-blind technical decision was locked before unblinding, and all 19 entries x 20 seeds produced valid checkpoints. Total measured SEDR runtime was {technical['runtime_hours_total']:.2f} hours; the two prespecified identical-seed controls both returned partition ARI 1.0. The Windows compatibility layer preserved all scientific parameters while externalizing R, using the audited rpy2 matrix bridge and modern PyTorch index syntax, enforcing deterministic algorithms, and disabling TF32.

Across the 19 SEDR units, the median reference-ARI SD was {stability['median_reference_ari_sd']:.3f} (range {stability['minimum_reference_ari_sd']:.3f}–{stability['maximum_reference_ari_sd']:.3f}). The median of the unit-level median pairwise partition ARIs was {reproducibility['median_of_unit_median_pairwise_ari']:.3f} (range {reproducibility['minimum_unit_median_pairwise_ari']:.3f}–{reproducibility['maximum_unit_median_pairwise_ari']:.3f}); {reproducibility['low_sd_high_instability_entries']}/19 units met the frozen low-score-SD/high-partition-instability rule.

At the primary absolute reference-ARI difference threshold of 0.02, SEDR contributed {iso['eligible_pairs']:,} iso-accuracy pairs. Of these, {iso['divergent_pairs_partition_ari_lt_0_50']:,} ({iso_percentage_text}) had partition ARI below 0.50, affecting {iso['affected_entries']}/19 entries. Median iso-accuracy partition ARI was {iso_median_text}, with minimum {iso_minimum_text}.

The partition-to-marker analysis was estimable in {marker['estimable_entries']}/19 entries; {marker['positive_entries']} had positive within-entry Spearman correlation, with median rho {marker_rho_text}. Median top-100 marker Jaccard was {marker_low_text}, {marker_middle_text}, and {marker_high_text} across low, middle, and high within-entry partition-ARI tertiles. The median paired high-minus-low difference was {marker_difference_text}; the one-sided paired Wilcoxon result was {('W = ' + f(marker['wilcoxon_statistic'], 1) + ', P = ' + f(marker['wilcoxon_p_value_one_sided'], 4)) if marker['paired_test_estimable'] else 'not estimable'}.

Median single-seed pairwise partition ARI was {consensus['median_single_seed_pairwise_ari']:.3f}, compared with median split-half consensus ARI {consensus['median_split_half_consensus_ari']:.3f}. Consensus improved reproducibility in {consensus['improved_entries']}/19 entries, with median gain {consensus['median_gain']:.3f}.

The five-method analysis exactly enumerated 20^5 = 3,200,000 empirical combinations per entry (60,800,000 total). These combinations were not treated as independent observations. Maximum P(rank 1) ranged from {ranking['minimum_max_p_rank1']:.3f} to {ranking['maximum_max_p_rank1']:.3f}; {ranking['entries_max_p_rank1_lt_0_50']}/19 entries were below 0.50 and {ranking['entries_max_p_rank1_lt_0_75']}/19 were below 0.75. SEDR had positive rank-1 probability in {ranking['sedr_positive_p_rank1_entries']}/19 entries and was a most-probable empirical winner in {ranking['sedr_most_probable_winner_entries']}/19, classified descriptively as **{ranking['sedr_winner_description']}**.

The integrated candidate analysis contains 19 entries, 95 method-entry units, 1,900 seed runs, and 18,050 seed-pair comparisons. It contains {integrated['iso_accuracy_pairs']:,} primary iso-accuracy pairs, including {integrated['divergent_iso_accuracy_pairs']:,} divergent pairs ({integrated_percentage_text}) across {integrated['affected_method_dataset_units']} units. Marker correlations were estimable in {integrated['marker_correlation_estimable_units']} units, positive in {integrated['marker_correlation_positive_units']}, with median rho {integrated_rho_text}. Consensus improved {integrated['consensus_improved_units']}/95 units, with median gain {integrated['median_consensus_gain']:.3f}.

HBCA1 was retained. Its reference segmentation was manually defined from H&E/pathological features in the original SEDR study, not generated by SEDR clustering; prior developer-dataset exposure should nevertheless be considered when interpreting cross-method reference accuracy.

## Scientific verdict

**{assessment['overall']}**

No SEDR result was inspected before `LOCK_ADD_SEDR`; no scientific threshold changed; no dataset or seed was removed because of its result; GraphST, STAGATE, SpaGCN, and BANKSY were never rerun; and the existing manuscript, figures, tables, and publication package were not modified.

Ready for five-method publication integration review.
"""

    component_lines = "\n".join(
        f"| {name.replace('_', ' ').title()} | **{item['label']}** | "
        f"{item['numerator']}/{item['denominator']} | {item['criterion']} |"
        for name, item in assessment["components"].items()
    )
    assessment_report = f"""# SEDR generalization assessment

The SEDR expansion was committed outcome-independently before scientific unblinding. Component labels therefore describe the complete 19-entry evidence and are not keep/drop decisions.

| Component | Classification | Quantitative basis | Frozen interpretation rule |
|---|---|---:|---|
{component_lines}

## Overall characterization

**{assessment['overall']}**

The outcome-independent classification rule was: {assessment['classification_rule']}. `HETEROGENEOUS` denotes a pattern present in some but not all estimable entries; it does not denote technical failure. `NOT_ESTIMABLE` is used only when no unit supports the requested component calculation.

HBCA1 remains included with its manual-pathology-reference and prior developer-dataset-exposure caveat.
"""

    five_report = f"""# Five-method integration summary

The candidate integration combines GraphST, STAGATE, SpaGCN, BANKSY, and SEDR across 19 entries and 20 seeds per method, yielding 1,900 accuracy rows. Across all eight integrated scientific tables, filtering back to the four original methods reproduced every authoritative old CSV field token exactly; no numeric tolerance was used for old rows.

The ranking calculation used the exact Cartesian product of the five 20-seed empirical distributions: 3,200,000 combinations per entry and 60,800,000 total. Average midranks were used for exact ties, and tied maxima divided rank-1 credit equally. Independent final validation re-enumerated every combination and reproduced the saved rank counts, rank probabilities, winner credits, expected and median ranks, top-2/top-3 probabilities, and pairwise superiority values.

Maximum P(rank 1) ranged from {ranking['minimum_max_p_rank1']:.3f} to {ranking['maximum_max_p_rank1']:.3f}. {ranking['entries_max_p_rank1_lt_0_50']}/19 entries had maximum P(rank 1) below 0.50 and {ranking['entries_max_p_rank1_lt_0_75']}/19 were below 0.75. SEDR had positive P(rank 1) in {ranking['sedr_positive_p_rank1_entries']}/19 entries and was among the most probable winner(s) in {ranking['sedr_most_probable_winner_entries']}/19.

The 3.2 million combinations per entry are an exact description of the observed empirical distributions, not independent experiments or an inferential sample size.
"""

    implications = f"""# Manuscript implications only

No manuscript, final figure, final table, supplement, or publication archive was edited during this expansion. The following are candidate integration implications for later editorial review only.

The Methods should add the pinned official SEDR implementation, platform-specific preprocessing and graph rules, 200+200 epoch DEC path, one EEE mclust readout at project K, full RNG propagation, and the 19 x 20 design. The Results should report the complete SEDR stability, iso-accuracy, marker, consensus, and exact five-method ranking results summarized in `FINAL_SEDR_REPORT.md`, including results that contrast with the prior four-method pattern.

The Discussion should frame the overall characterization as **{assessment['overall']}**, preserve the established status of co-association consensus as a mitigation strategy rather than a novel method, and avoid treating the 60.8 million exact rank combinations as independent evidence. HBCA1 should carry the concise caveat that its reference is manual H&E/pathology annotation rather than SEDR output, while noting prior developer-dataset exposure for cross-method accuracy interpretation.

Any later publication integration should remain additive, regenerate candidate five-method displays in a separate review package, and retain the existing four-method publication package unchanged until explicit editorial approval.
"""

    checks = validation["checks"]
    check_lines = "\n".join(
        f"| {name.replace('_', ' ').title()} | **{value}** |"
        for name, value in checks.items()
    )
    artifact_lines = "\n".join(
        f"| `{path}` | `{digest}` |"
        for path, digest in sorted(validation["artifact_sha256"].items())
    )
    validation_report = f"""# Project 9 SEDR final validation report

**Overall status: PASS**  
Generated: {generated}

| Check | Status |
|---|---|
{check_lines}

The final scan validated 380/380 technical checkpoints, 380 seed-level SEDR rows, 3,610 within-SEDR seed-pair rows, 57 iso-threshold summaries, 19 consensus rows, and 19 SEDR unit summaries. Marker outputs reconciled exactly to the primary iso-accuracy pair set. Exact five-method ranking was independently re-enumerated for all 60,800,000 combinations. The complete additive integration contained eight scientific tables with the exact 1,900/18,050/285/95 structural grids; each four-method back-filter was independently token-for-token identical to its authoritative CSV. All 192 protected publication-package files plus all 14 authoritative four-method sources matched the pre-SEDR byte-level baseline.

## Artifact hashes

| Artifact | SHA-256 |
|---|---|
{artifact_lines}

Scientific gate SHA-256: `{audit['gate_sha256']}`  
Protocol SHA-256: `{audit['protocol_hash']}`  
Checkpoint-manifest SHA-256: `{audit['checkpoint_manifest_hash']}`
"""

    final_summary = {
        "schema_version": 1,
        "status": "PASS",
        "generated_utc": generated,
        "decision": "LOCK_ADD_SEDR",
        "completion": "380/380",
        "scientific_verdict": assessment["overall"],
        "summary": summary,
        "validation": validation,
        "gate": {
            "scientific_gate_sha256": audit["gate_sha256"],
            "protocol_hash": audit["protocol_hash"],
            "input_manifest_sha256": audit["input_manifest_hash"],
            "checkpoint_manifest_sha256": audit["checkpoint_manifest_hash"],
        },
        "confirmations": {
            "sedr_outcomes_inspected_before_lock": False,
            "scientific_thresholds_changed": False,
            "sedr_results_excluded_by_outcome": False,
            "existing_four_methods_rerun": False,
            "existing_publication_artifacts_modified": False,
            "ready_for_five_method_publication_integration_review": True,
        },
    }
    payloads = {
        REPORTS["final"]: final_report.encode("utf-8"),
        REPORTS["assessment"]: assessment_report.encode("utf-8"),
        REPORTS["five_method"]: five_report.encode("utf-8"),
        REPORTS["implications"]: implications.encode("utf-8"),
        REPORTS["validation"]: validation_report.encode("utf-8"),
        REPORTS["summary"]: (
            json.dumps(
                final_summary, indent=2, ensure_ascii=False, allow_nan=False
            ) + "\n"
        ).encode("utf-8"),
    }
    return payloads


def transactional_publish(payloads: dict[Path, bytes]) -> None:
    existing = [str(path) for path in payloads if path.exists()]
    if existing:
        raise FinalizationBlocked(
            "Refusing to overwrite final report artifacts: " + ", ".join(existing)
        )
    temporary: dict[Path, Path] = {}
    installed: list[Path] = []
    try:
        for path, value in payloads.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
            if tmp.exists():
                tmp.unlink()
            with tmp.open("wb") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            temporary[path] = tmp
        # JSON completion record is installed last.
        order = [path for path in payloads if path != REPORTS["summary"]]
        order.append(REPORTS["summary"])
        for path in order:
            os.replace(temporary[path], path)
            installed.append(path)
        for path, expected in payloads.items():
            if sha256_file(path) != sha256_bytes(expected):
                raise RuntimeError(f"Post-write report hash failed: {path}")
    except BaseException:
        for tmp in temporary.values():
            if tmp.exists():
                tmp.unlink()
        # Only files proven absent before this transaction are rolled back.
        for path in installed:
            if path.exists():
                path.unlink()
        raise


def run_finalization(execute: bool, rank_chunk_size: int) -> dict[str, Any]:
    if rank_chunk_size < 1:
        raise FinalizationBlocked("rank-chunk-size must be positive")
    # Both operations are outcome-blind and precede scientific-table imports.
    audit = fresh_gate_audit()
    immutability = verify_immutability_baseline()

    import numpy as np
    import pandas as pd
    from scipy import stats

    old = validate_old_integrated_sources(pd, np)
    core, core_validation = validate_core_outputs(audit, pd, np)
    marker, marker_validation = validate_marker_outputs(
        audit, core, pd, np, stats
    )
    five, five_validation = validate_five_method_outputs(
        audit, core, pd, np, rank_chunk_size
    )
    _all_outputs, all_outputs_validation = validate_all_outputs(
        audit, core, marker, pd, np
    )
    assessment = scientific_assessment(core, marker, five, np)
    summary = build_quantitative_summary(
        audit, immutability, core, marker, five, old, assessment, pd, np
    )
    artifact_hashes: dict[str, str] = {}
    for group in (CORE_FILES, MARKER_FILES, FIVE_FILES, ALL_FILES):
        for path in group.values():
            artifact_hashes[path.relative_to(ROOT).as_posix()] = sha256_file(path)
    alias_validation: list[dict[str, str]] = []
    for destination, source in ROOT_SCIENTIFIC_ALIASES.items():
        digest = sha256_file(source)
        artifact_hashes[destination.relative_to(ROOT).as_posix()] = digest
        alias_validation.append({
            "destination": destination.relative_to(ROOT).as_posix(),
            "source": source.relative_to(ROOT).as_posix(),
            "sha256": digest,
            "publication_mode": "transactional byte-identical new file",
        })
    validation = {
        "status": "PASS",
        "checks": {
            "fresh_scientific_gate_and_380_checkpoint_scan": "PASS",
            "core_19x20_and_3610_reconciliation": "PASS",
            "iso_thresholds_0.01_0.02_0.03": "PASS",
            "marker_pair_and_unit_reconciliation": "PASS",
            "exact_five_method_20_pow_5_reenumeration": "PASS",
            "complete_eight_table_integration": "PASS",
            "four_method_eight_table_token_exact_back_filter": "PASS",
            "publication_and_source_immutability": "PASS",
            "no_existing_publication_file_written": "PASS",
        },
        "core": core_validation,
        "marker": marker_validation,
        "five_method": five_validation,
        "complete_integration": all_outputs_validation,
        "root_scientific_delivery_aliases": alias_validation,
        "immutability": immutability,
        "artifact_sha256": artifact_hashes,
    }
    generated = utc_now()
    payloads = render_reports(generated, summary, validation, audit)
    for destination, source in ROOT_SCIENTIFIC_ALIASES.items():
        payloads[destination] = source.read_bytes()
    if execute:
        transactional_publish(payloads)
    return {
        "status": "FINAL_VALIDATION_PASS",
        "reports_written": bool(execute),
        "scientific_verdict": assessment["overall"],
        "validated_checkpoints": len(audit["checkpoints"]),
        "sedr_seed_rows": len(core["seed"]),
        "sedr_pair_rows": len(core["pair"]),
        "exact_rank_combinations": TOTAL_COMBINATIONS,
        "four_method_back_filter": "TOKEN_FOR_TOKEN_EXACT_ACROSS_EIGHT_TABLES",
        "complete_integration_tables": 8,
        "immutability": "PASS",
        "report_paths": [str(path.resolve()) for path in REPORTS.values()],
        "root_scientific_alias_paths": [
            str(path.resolve()) for path in ROOT_SCIENTIFIC_ALIASES
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Final Project 9 SEDR validation and report orchestrator"
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Publish the six final reports after validation; omission writes nothing",
    )
    parser.add_argument(
        "--rank-chunk-size", type=int, default=100_000,
        help="Chunk size for independent exact 20^5 validation",
    )
    args = parser.parse_args()
    try:
        result = run_finalization(args.execute, args.rank_chunk_size)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as error:
        print(
            json.dumps({
                "status": "FINALIZATION_BLOCKED_NO_REPORTS_WRITTEN",
                "error_type": type(error).__name__,
                "error": str(error),
            }, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
