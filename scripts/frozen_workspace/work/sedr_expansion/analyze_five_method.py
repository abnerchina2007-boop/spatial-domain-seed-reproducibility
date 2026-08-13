"""Post-gate exact five-method empirical ranking integration.

This program is intentionally fail-closed.  Before reading either scientific
accuracy table it independently validates the 380 final SEDR checkpoints,
recomputes the canonical checkpoint-manifest digest, and verifies the atomic
scientific-gate record.  It then combines the immutable four-method seed-level
source with the complete SEDR panel and streams all 20^5 combinations for each
of 19 entries.

Frozen ranking rules:

* average midranks for every exact tie;
* tied maxima divide rank-1 credit equally;
* top-2/top-3 and expected/median rank use the midrank distribution;
* pairwise superiority compares the two complete empirical 20-seed
  distributions and never treats equal numerical seed IDs as matched runs.

The 3,200,000 combinations per entry are an exact empirical enumeration, not
independent experiments.  Nothing in this file performs inferential testing.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
EXPANSION = ROOT / "outputs" / "PROJECT9_SEDR_EXPANSION"
GATE_FILE = EXPANSION / "SCIENTIFIC_GATE_OPEN.json"
LOCK_FILE = EXPANSION / "LOCK_ADD_SEDR.json"
CHECKPOINT_ROOT = EXPANSION / "checkpoints"
INPUT_MANIFEST = (
    EXPANSION / "technical_inputs" / "TECHNICAL_INPUT_MANIFEST.json"
)
PROTOCOL = EXPANSION / "SEDR_FROZEN_PROTOCOL.md"
PROTOCOL_HASH_FILE = EXPANSION / "SEDR_FROZEN_PROTOCOL.sha256"
IMMUTABILITY_BASELINE = (
    EXPANSION / "provenance" / "EXISTING_PROJECT9_IMMUTABILITY_BASELINE.json"
)
IMMUTABILITY_BASELINE_SHA256 = (
    "B8FAB19D27392EF959BC49BAC65F0A0581942D6B855462CD482B21E4D33F0B1E"
)
FOUR_METHOD_SOURCE = (
    ROOT / "outputs" / "PROJECT9_MERFISH_EXPANSION"
    / "combined_seed_level_accuracy.csv"
)
SEDR_SOURCE = EXPANSION / "seed_level_accuracy.csv"
DEFAULT_OUTPUT = EXPANSION / "candidate_integration" / "five_method"

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
EXPECTED_CHECKPOINTS = len(DATASETS) * len(SEEDS)
COMBINATIONS_PER_DATASET = len(SEEDS) ** len(METHODS)
TOTAL_ENUMERATED_COMBINATIONS = len(DATASETS) * COMBINATIONS_PER_DATASET
WINNER_CREDIT_SCALE = math.lcm(*range(1, len(METHODS) + 1))  # 60
HEX64 = re.compile(r"^[0-9A-F]{64}$")


class GateClosed(RuntimeError):
    """The post-gate analysis authorization could not be revalidated."""


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


def normalize_hash(value: object, field: str) -> str:
    text = str(value).strip().upper()
    if not HEX64.fullmatch(text):
        raise GateClosed(f"{field} is not an uppercase-normalizable SHA-256")
    return text


def confined_gate_path(value: object, expected: Path, field: str) -> Path:
    """Require a gate-bound artifact to be the canonical expansion path."""
    if not isinstance(value, str) or not value:
        raise GateClosed(f"Gate {field} is missing")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = EXPANSION / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(EXPANSION.resolve())
    except ValueError as error:
        raise GateClosed(f"Gate {field} escapes the expansion directory") from error
    if candidate != expected.resolve():
        raise GateClosed(f"Gate {field} is not the canonical artifact path")
    return candidate


def load_validator() -> Any:
    path = WORK / "validate_technical.py"
    spec = importlib.util.spec_from_file_location(
        "sedr_validate_technical_for_five_method", path
    )
    if spec is None or spec.loader is None:
        raise GateClosed(f"Cannot load strict technical validator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_checkpoint_digest(rows: Iterable[dict[str, Any]]) -> str:
    stable = [
        {
            "dataset": str(row["dataset"]),
            "seed": int(row["seed"]),
            "checkpoint_sha256": normalize_hash(
                row["checkpoint_sha256"], "checkpoint_sha256"
            ),
            "labels_sha256": normalize_hash(
                row["labels_sha256"], "labels_sha256"
            ),
        }
        for row in rows
    ]
    stable.sort(key=lambda row: (row["dataset"], row["seed"]))
    encoded = json.dumps(
        stable, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(encoded)


def verify_scientific_gate() -> tuple[str, dict[tuple[str, int], dict[str, str]]]:
    """Freshly validate the gate and all 380 technical checkpoints."""
    if not GATE_FILE.is_file():
        raise GateClosed(f"Scientific gate is missing: {GATE_FILE}")
    gate = load_json(GATE_FILE)
    if not isinstance(gate, dict):
        raise GateClosed("Scientific gate is not a JSON object")
    if gate.get("gate") != "SCIENTIFIC_GATE_OPEN" or gate.get("status") != "OPEN":
        raise GateClosed("Scientific gate is not OPEN")
    if gate.get("scientific_unblinding") is not True:
        raise GateClosed("Scientific gate does not explicitly authorize unblinding")
    if gate.get("schema_version") != 1:
        raise GateClosed("Unsupported scientific-gate schema")
    opened = gate.get("opened_utc")
    if not isinstance(opened, str):
        raise GateClosed("Scientific gate opened_utc is missing")
    try:
        opened_at = datetime.fromisoformat(opened.replace("Z", "+00:00"))
    except ValueError as error:
        raise GateClosed("Scientific gate opened_utc is invalid") from error
    if opened_at.tzinfo is None:
        raise GateClosed("Scientific gate opened_utc lacks timezone")
    if gate.get("checkpoint_count") != EXPECTED_CHECKPOINTS:
        raise GateClosed("Scientific gate does not certify exactly 380 checkpoints")
    for field in (
        "identity_grid_complete",
        "scientific_outputs_present_before_gate",
        "reference_annotations_read_by_gate",
        "scientific_metrics_computed_by_gate",
    ):
        expected = field == "identity_grid_complete"
        if gate.get(field) is not expected:
            raise GateClosed(f"Scientific gate safety field failed: {field}")

    validator = load_validator()
    manifest_entries, manifest_hash = validator.load_input_manifest(INPUT_MANIFEST)
    protocol_hash = validator.load_protocol_hash(PROTOCOL, PROTOCOL_HASH_FILE)
    protocol_hash = normalize_hash(protocol_hash, "current protocol hash")
    if normalize_hash(
        gate.get("protocol_hash", gate.get("protocol_sha256")),
        "gate protocol hash",
    ) != protocol_hash:
        raise GateClosed("Scientific gate protocol hash is stale")
    if normalize_hash(
        gate.get("input_manifest_sha256"), "gate input-manifest hash"
    ) != normalize_hash(manifest_hash, "current input-manifest hash"):
        raise GateClosed("Scientific gate input-manifest hash is stale")

    if not LOCK_FILE.is_file():
        raise GateClosed("LOCK_ADD_SEDR.json is missing")
    lock = load_json(LOCK_FILE)
    if (
        not isinstance(lock, dict)
        or lock.get("decision") != "LOCK_ADD_SEDR"
        or lock.get("scientific_unblinding") is not False
        or lock.get("scientific_outcomes_inspected_before_lock") is not False
        or lock.get("committed_target_runs") != EXPECTED_CHECKPOINTS
        or lock.get("outcome_independent_commitment") is not True
    ):
        raise GateClosed("LOCK_ADD_SEDR invariants failed")
    locked_at = lock.get("locked_at")
    if not isinstance(locked_at, str):
        raise GateClosed("LOCK_ADD_SEDR locked_at is missing")
    try:
        locked_datetime = datetime.fromisoformat(
            locked_at.replace("Z", "+00:00")
        )
    except ValueError as error:
        raise GateClosed("LOCK_ADD_SEDR locked_at is invalid") from error
    if locked_datetime.tzinfo is None or locked_datetime >= opened_at:
        raise GateClosed("LOCK_ADD_SEDR timestamp is not before gate opening")
    if normalize_hash(
        lock.get("protocol_hash", lock.get("protocol_sha256")),
        "lock protocol hash",
    ) != protocol_hash:
        raise GateClosed("LOCK_ADD_SEDR protocol hash is stale")
    if normalize_hash(
        gate.get("lock_add_sedr_sha256"), "gate lock hash"
    ) != sha256_file(LOCK_FILE):
        raise GateClosed("Scientific gate LOCK_ADD_SEDR hash is stale")

    checkpoint_files = sorted(CHECKPOINT_ROOT.rglob("checkpoint.json"))
    if len(checkpoint_files) != EXPECTED_CHECKPOINTS:
        raise GateClosed(
            f"Fresh scan found {len(checkpoint_files)}/380 checkpoint files"
        )
    expected = {(dataset, seed) for dataset in DATASETS for seed in SEEDS}
    observed: dict[tuple[str, int], dict[str, str]] = {}
    digest_rows: list[dict[str, Any]] = []
    for checkpoint_path in checkpoint_files:
        result = validator.validate_checkpoint(
            checkpoint_path, manifest_entries, protocol_hash
        )
        identity = (str(result["dataset"]), int(result["seed"]))
        canonical_path = (
            CHECKPOINT_ROOT / identity[0] / f"seed{identity[1]:02d}"
            / "checkpoint.json"
        ).resolve()
        if checkpoint_path.resolve() != canonical_path:
            raise GateClosed(f"Checkpoint is outside its canonical path: {identity}")
        if result.get("mode") != "final" or identity not in expected:
            raise GateClosed(f"Non-final or unexpected checkpoint: {identity}")
        if identity in observed:
            raise GateClosed(f"Duplicate checkpoint identity: {identity}")
        payload = load_json(checkpoint_path)
        if payload.get("scientific_unblinding") is not False:
            raise GateClosed(f"Technical checkpoint is not blinded: {identity}")
        row = {
            "dataset": identity[0],
            "seed": identity[1],
            "checkpoint_sha256": result["checkpoint_sha256"],
            "labels_sha256": result["labels_sha256"],
        }
        digest_rows.append(row)
        observed[identity] = {
            "checkpoint_sha256": normalize_hash(
                result["checkpoint_sha256"], "fresh checkpoint hash"
            ),
            "labels_sha256": normalize_hash(
                result["labels_sha256"], "fresh labels hash"
            ),
        }
    if set(observed) != expected:
        raise GateClosed("Fresh checkpoint identity grid is not 19 x 20")
    digest = canonical_checkpoint_digest(digest_rows)
    gate_digest = normalize_hash(
        gate.get("checkpoint_manifest_sha256"),
        "gate checkpoint-manifest hash",
    )
    if digest != gate_digest:
        raise GateClosed("Fresh canonical checkpoint digest differs from the gate")

    validation_path_value = gate.get(
        "technical_validation_report_path",
        gate.get("technical_validation_report_file"),
    )
    validation_path = confined_gate_path(
        validation_path_value,
        EXPANSION / "FINAL_380_TECHNICAL_VALIDATION.json",
        "technical_validation_report_path",
    )
    if not validation_path.is_file():
        raise GateClosed("Gate technical-validation report is missing")
    validation_hash = normalize_hash(
        gate.get("technical_validation_report_sha256"),
        "gate technical-validation report hash",
    )
    if sha256_file(validation_path) != validation_hash:
        raise GateClosed("Gate technical-validation report hash mismatch")
    validation = load_json(validation_path)
    if (
        validation.get("status") != "PASS"
        or validation.get("checkpoint_count") != EXPECTED_CHECKPOINTS
        or validation.get("pass_count") != EXPECTED_CHECKPOINTS
        or validation.get("fail_count") != 0
        or validation.get("scientific_metrics_computed") is not False
        or validation.get("reference_annotations_read") is not False
        or normalize_hash(
            validation.get("checkpoint_manifest_sha256"),
            "validation checkpoint-manifest hash",
        ) != digest
    ):
        raise GateClosed("Gate technical-validation report is not a 380/380 PASS")

    manifest_file = confined_gate_path(
        gate.get("checkpoint_manifest_path", gate.get("checkpoint_manifest_file")),
        EXPANSION / "FINAL_380_CHECKPOINT_MANIFEST.csv",
        "checkpoint_manifest_path",
    )
    if not manifest_file.is_file():
        raise GateClosed("Gate checkpoint-manifest file is missing")
    manifest_file_hash = normalize_hash(
        gate.get("checkpoint_manifest_file_sha256"),
        "gate checkpoint-manifest file hash",
    )
    if sha256_file(manifest_file) != manifest_file_hash:
        raise GateClosed("Gate checkpoint-manifest file hash mismatch")
    with manifest_file.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required_manifest_columns = {
            "dataset", "seed", "checkpoint_sha256", "labels_sha256"
        }
        if reader.fieldnames is None or not required_manifest_columns.issubset(
            reader.fieldnames
        ):
            raise GateClosed("Gate checkpoint-manifest schema is incomplete")
        manifest_rows = list(reader)
    if len(manifest_rows) != EXPECTED_CHECKPOINTS:
        raise GateClosed("Gate checkpoint-manifest row count is not 380")
    if canonical_checkpoint_digest(manifest_rows) != digest:
        raise GateClosed("Gate checkpoint-manifest contents differ from fresh scan")
    return protocol_hash, observed


def verify_immutable_four_method_sources() -> str:
    """Re-hash every authoritative four-method source in the baseline."""
    if not IMMUTABILITY_BASELINE.is_file():
        raise RuntimeError(f"Immutability baseline is missing: {IMMUTABILITY_BASELINE}")
    if sha256_file(IMMUTABILITY_BASELINE) != IMMUTABILITY_BASELINE_SHA256:
        raise RuntimeError("The pre-SEDR immutability baseline itself changed")
    baseline = load_json(IMMUTABILITY_BASELINE)
    source_block = baseline.get("authoritative_four_method_sources", {})
    records = source_block.get("files")
    if not isinstance(records, list) or len(records) != 14:
        raise RuntimeError("Immutability baseline does not list 14 source files")
    seed_source_hash: str | None = None
    for record in records:
        path = ROOT / str(record["path"])
        expected_hash = normalize_hash(record["sha256"], "baseline source hash")
        if (
            not path.is_file()
            or path.stat().st_size != int(record["bytes"])
            or sha256_file(path) != expected_hash
        ):
            raise RuntimeError(f"Immutable four-method source changed: {path}")
        if path.resolve() == FOUR_METHOD_SOURCE.resolve():
            seed_source_hash = expected_hash
    if seed_source_hash is None:
        raise RuntimeError("Four-method seed-level source is absent from the baseline")
    return seed_source_hash


def require_identity_grid(
    frame: pd.DataFrame,
    methods: tuple[str, ...],
    source_name: str,
) -> None:
    required = {"section", "method", "seed", "reference_ari", "reference_nmi"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"{source_name} lacks required columns: {sorted(missing)}")
    if frame[list(required)].isna().any().any():
        raise RuntimeError(f"{source_name} has missing required values")
    if set(frame["section"].astype(str)) != set(DATASETS):
        raise RuntimeError(f"{source_name} does not contain the frozen 19 entries")
    if set(frame["method"].astype(str)) != set(methods):
        raise RuntimeError(f"{source_name} method set is not frozen")
    expected = {
        (dataset, method, seed)
        for dataset in DATASETS for method in methods for seed in SEEDS
    }
    actual = set(
        zip(
            frame["section"].astype(str),
            frame["method"].astype(str),
            frame["seed"].astype(int),
        )
    )
    if actual != expected or len(frame) != len(expected):
        raise RuntimeError(f"{source_name} identity grid is incomplete or duplicated")
    values = frame[["reference_ari", "reference_nmi"]].to_numpy(float)
    if not np.isfinite(values).all():
        raise RuntimeError(f"{source_name} contains non-finite accuracy values")


def load_inputs(
    protocol_hash: str,
    checkpoint_hashes: dict[tuple[str, int], dict[str, str]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    source_hash = verify_immutable_four_method_sources()
    old = pd.read_csv(FOUR_METHOD_SOURCE, dtype={"section": str})
    require_identity_grid(old, OLD_METHODS, "immutable four-method source")
    if len(old) != 19 * 4 * 20:
        raise RuntimeError("Immutable four-method source is not exactly 1,520 rows")

    if not SEDR_SOURCE.is_file():
        raise RuntimeError(f"Post-gate SEDR accuracy source is missing: {SEDR_SOURCE}")
    sedr = pd.read_csv(SEDR_SOURCE, dtype={"dataset": str})
    required_sedr = {
        "dataset", "dataset_display", "method", "seed", "reference_ari",
        "reference_nmi", "checkpoint_sha256", "labels_sha256", "protocol_hash",
    }
    missing = required_sedr - set(sedr.columns)
    if missing:
        raise RuntimeError(f"SEDR accuracy source lacks columns: {sorted(missing)}")
    sedr = sedr.rename(
        columns={"dataset": "section", "dataset_display": "section_display"}
    )
    require_identity_grid(sedr, ("SEDR",), "SEDR accuracy source")
    if len(sedr) != EXPECTED_CHECKPOINTS:
        raise RuntimeError("SEDR accuracy source is not exactly 380 rows")
    if not sedr["protocol_hash"].astype(str).str.upper().eq(protocol_hash).all():
        raise RuntimeError("SEDR accuracy rows do not all use the gated protocol")
    for row in sedr.itertuples(index=False):
        identity = (str(row.section), int(row.seed))
        technical = checkpoint_hashes[identity]
        if (
            normalize_hash(row.checkpoint_sha256, "SEDR checkpoint hash")
            != technical["checkpoint_sha256"]
            or normalize_hash(row.labels_sha256, "SEDR labels hash")
            != technical["labels_sha256"]
        ):
            raise RuntimeError(
                f"SEDR accuracy provenance differs from checkpoint: {identity}"
            )

    validate_source_display_names(old, sedr)

    old_copy = old.copy()
    old_copy["integration_source"] = "immutable_four_method"
    sedr_copy = sedr.copy()
    # SEDR's frozen core table uses presentation aliases ending in `` mm`` for
    # the five MERFISH sections.  The immutable four-method dataset manifest
    # and publication package use the shorter labels in DISPLAY.  Normalize
    # only this presentation field in the new additive candidate package;
    # stable identities, metrics, provenance, and the SEDR source remain
    # untouched.
    sedr_copy["section_display"] = sedr_copy["section"].map(DISPLAY)
    sedr_copy["integration_source"] = "post_gate_sedr"
    integrated = pd.concat([old_copy, sedr_copy], ignore_index=True, sort=False)
    method_order = {method: index for index, method in enumerate(METHODS)}
    dataset_order = {dataset: index for index, dataset in enumerate(DATASETS)}
    integrated["_dataset_order"] = integrated["section"].map(dataset_order)
    integrated["_method_order"] = integrated["method"].map(method_order)
    integrated.sort_values(
        ["_dataset_order", "_method_order", "seed"], inplace=True
    )
    integrated.drop(columns=["_dataset_order", "_method_order"], inplace=True)
    integrated.reset_index(drop=True, inplace=True)
    require_identity_grid(integrated, METHODS, "integrated five-method source")
    if len(integrated) != 19 * 5 * 20:
        raise RuntimeError("Integrated source is not exactly 1,900 rows")
    reconcile_four_method_values(old, integrated)
    return old, sedr, integrated, source_hash


def reconcile_four_method_values(old: pd.DataFrame, integrated: pd.DataFrame) -> None:
    keys = ["section", "method", "seed"]
    expected = old.sort_values(keys).reset_index(drop=True)
    observed = (
        integrated[integrated["method"].isin(OLD_METHODS)][list(old.columns)]
        .sort_values(keys)
        .reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(
        observed,
        expected,
        check_dtype=False,
        check_exact=True,
        check_like=False,
    )


def validate_source_display_names(
    old: pd.DataFrame, sedr: pd.DataFrame
) -> None:
    """Validate the two frozen display vocabularies without changing sources."""

    for dataset in DATASETS:
        canonical = DISPLAY[dataset]
        old_values = old.loc[
            old["section"].eq(dataset), "section_display"
        ].dropna().astype(str).unique()
        if len(old_values) != 1 or str(old_values[0]) != canonical:
            raise RuntimeError(
                f"Authoritative four-method display name drifted for {dataset}: "
                f"{old_values}"
            )
        sedr_values = sedr.loc[
            sedr["section"].eq(dataset), "section_display"
        ].dropna().astype(str).unique()
        allowed = {canonical}
        if dataset.startswith("MERFISH_Bregma_"):
            allowed.add(f"{canonical} mm")
        if len(sedr_values) != 1 or str(sedr_values[0]) not in allowed:
            raise RuntimeError(
                f"Unexpected SEDR display alias for {dataset}: {sedr_values}"
            )


def display_names(frame: pd.DataFrame) -> dict[str, str]:
    """Return the frozen publication labels after exact canonical validation."""

    for dataset in DATASETS:
        values = frame.loc[
            frame["section"].eq(dataset), "section_display"
        ].dropna().astype(str).unique()
        if len(values) != 1 or str(values[0]) != DISPLAY[dataset]:
            raise RuntimeError(
                f"Noncanonical integrated display name for {dataset}: {values}"
            )
    return dict(DISPLAY)


def score_arrays(frame: pd.DataFrame, dataset: str) -> list[np.ndarray]:
    arrays: list[np.ndarray] = []
    for method in METHODS:
        subset = frame[
            frame["section"].eq(dataset) & frame["method"].eq(method)
        ].sort_values("seed")
        if tuple(subset["seed"].astype(int)) != SEEDS:
            raise RuntimeError(f"Seed order is incomplete: {dataset}/{method}")
        values = subset["reference_ari"].to_numpy(np.float64)
        if values.shape != (20,) or not np.isfinite(values).all():
            raise RuntimeError(f"Invalid reference ARI vector: {dataset}/{method}")
        arrays.append(values)
    return arrays


def stream_rank_one_dataset(
    dataset: str,
    display: str,
    arrays: list[np.ndarray],
    chunk_size: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    """Stream exactly 20^5 Cartesian combinations for one entry."""
    if len(arrays) != 5 or any(values.shape != (20,) for values in arrays):
        raise RuntimeError("Exact enumeration requires five 20-value vectors")
    total = COMBINATIONS_PER_DATASET
    rank_counts = np.zeros((5, 11), dtype=np.int64)  # index is rank x 2
    winner_credit_scaled = np.zeros(5, dtype=np.int64)
    processed = 0
    strides = np.asarray([20 ** (4 - index) for index in range(5)], dtype=np.int64)

    for start in range(0, total, chunk_size):
        stop = min(total, start + chunk_size)
        flat = np.arange(start, stop, dtype=np.int64)
        scores = np.empty((stop - start, 5), dtype=np.float64)
        for method_index in range(5):
            seed_index = (flat // strides[method_index]) % 20
            scores[:, method_index] = arrays[method_index][seed_index]

        # Average midrank: 1 + number greater + 0.5 * tied others.
        rank_x2 = np.empty((len(flat), 5), dtype=np.uint8)
        for method_index in range(5):
            focal = scores[:, method_index, None]
            greater = np.sum(scores > focal, axis=1, dtype=np.uint8)
            equal_other = np.sum(scores == focal, axis=1, dtype=np.uint8) - 1
            rank_x2[:, method_index] = 2 + 2 * greater + equal_other
            rank_counts[method_index] += np.bincount(
                rank_x2[:, method_index], minlength=11
            )[:11]

        maxima = scores.max(axis=1)
        tied_maxima = scores == maxima[:, None]
        tie_sizes = tied_maxima.sum(axis=1).astype(np.int64)
        for method_index in range(5):
            selected_tie_sizes = tie_sizes[tied_maxima[:, method_index]]
            # LCM scaling keeps all 1/tie_size credits exactly integral.
            winner_credit_scaled[method_index] += int(
                np.sum(WINNER_CREDIT_SCALE // selected_tie_sizes, dtype=np.int64)
            )
        processed += len(flat)

    if processed != total:
        raise RuntimeError(f"Enumeration incomplete for {dataset}: {processed}")
    if not np.all(rank_counts.sum(axis=1) == total):
        raise RuntimeError(f"Rank-count totals failed for {dataset}")
    if winner_credit_scaled.sum() != WINNER_CREDIT_SCALE * total:
        raise RuntimeError(f"Fractional rank-1 credits failed for {dataset}")

    distribution_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    winner_rows: list[dict[str, Any]] = []
    denominator = WINNER_CREDIT_SCALE * total
    winner_probabilities = winner_credit_scaled.astype(np.float64) / denominator
    positive = winner_probabilities[winner_probabilities > 0]
    entropy = float(-np.sum(positive * np.log2(positive)))
    maximum_winner = float(winner_probabilities.max())

    for method_index, method in enumerate(METHODS):
        counts = rank_counts[method_index]
        for rank_twice in range(2, 11):
            count = int(counts[rank_twice])
            distribution_rows.append({
                "section": dataset,
                "section_display": display,
                "method": method,
                "rank": rank_twice / 2.0,
                "rank_x2": rank_twice,
                "count": count,
                "probability": count / total,
                "enumerated_combinations": total,
                "rank_rule": "average midrank for exact ties",
                "interpretation_unit": (
                    "exact empirical combinations; not independent experiments"
                ),
            })
        cumulative = np.cumsum(counts)
        median_rank_x2 = int(np.flatnonzero(cumulative >= math.ceil(total / 2))[0])
        expected_rank = float(
            sum(rank_twice * int(counts[rank_twice]) for rank_twice in range(2, 11))
            / (2 * total)
        )
        p_top2 = float(counts[:5].sum() / total)  # rank_x2 <= 4
        p_top3 = float(counts[:7].sum() / total)  # rank_x2 <= 6
        p_rank1 = float(winner_probabilities[method_index])
        summary_rows.append({
            "section": dataset,
            "section_display": display,
            "method": method,
            "empirical_p_rank1": p_rank1,
            "empirical_expected_rank": expected_rank,
            "empirical_median_rank": median_rank_x2 / 2.0,
            "empirical_p_top2": p_top2,
            "empirical_p_top3": p_top3,
            "enumerated_combinations": total,
            "rank_rule": "average midrank for exact ties",
            "rank1_rule": "tied maxima split rank-1 credit equally",
        })
        winner_rows.append({
            "section": dataset,
            "section_display": display,
            "method": method,
            "p_rank1": p_rank1,
            "winner_credit_scaled_60": int(winner_credit_scaled[method_index]),
            "winner_credit_denominator_scaled_60": denominator,
            "max_winner_probability": maximum_winner,
            "winner_entropy_bits": entropy,
            "winner_entropy_normalized": entropy / math.log2(5),
            "enumerated_combinations": total,
            "tie_rule": "tied maxima split rank-1 credit equally",
        })

    pair_rows: list[dict[str, Any]] = []
    expansion_factor = 20 ** 3
    for method_a_index, method_a in enumerate(METHODS):
        a = arrays[method_a_index]
        for method_b_index in range(method_a_index + 1, len(METHODS)):
            method_b = METHODS[method_b_index]
            b = arrays[method_b_index]
            greater = int(np.count_nonzero(a[:, None] > b[None, :]))
            less = int(np.count_nonzero(a[:, None] < b[None, :]))
            ties = 400 - greater - less
            pair_rows.append({
                "section": dataset,
                "section_display": display,
                "method_A": method_a,
                "method_B": method_b,
                "count_A_gt_B_20x20": greater,
                "count_B_gt_A_20x20": less,
                "tie_count_20x20": ties,
                "count_A_gt_B": greater * expansion_factor,
                "count_B_gt_A": less * expansion_factor,
                "tie_count": ties * expansion_factor,
                "p_A_gt_B": greater / 400,
                "p_B_gt_A": less / 400,
                "tie_probability": ties / 400,
                "enumerated_pairwise_comparisons": 400,
                "enumerated_five_method_combinations": total,
                "seed_pairing": "unmatched empirical Cartesian product",
            })

    dataset_summary = {
        "section": dataset,
        "section_display": display,
        "enumerated_combinations": total,
        "winner_credit_scaled_60_sum": int(winner_credit_scaled.sum()),
        "winner_credit_denominator_scaled_60": denominator,
        "maximum_p_rank1": maximum_winner,
        "most_probable_winner": ";".join(
            METHODS[index]
            for index in np.flatnonzero(
                np.isclose(winner_probabilities, maximum_winner, rtol=0, atol=0)
            )
        ),
        "n_methods_positive_p_rank1": int(np.sum(winner_probabilities > 0)),
        "n_methods_p_rank1_ge_0_05": int(np.sum(winner_probabilities >= 0.05)),
        "winner_entropy_bits": entropy,
        "winner_entropy_normalized": entropy / math.log2(5),
    }
    return distribution_rows, summary_rows, winner_rows, pair_rows, dataset_summary


def validate_rank_outputs(
    distribution: pd.DataFrame,
    summary: pd.DataFrame,
    winners: pd.DataFrame,
    superiority: pd.DataFrame,
    datasets: pd.DataFrame,
) -> None:
    if len(distribution) != 19 * 5 * 9:
        raise RuntimeError("Rank-distribution output does not have 855 rows")
    if len(summary) != 19 * 5 or len(winners) != 19 * 5:
        raise RuntimeError("Rank/winner summaries do not have 95 rows each")
    if len(superiority) != 19 * math.comb(5, 2):
        raise RuntimeError("Pairwise-superiority output does not have 190 rows")
    if len(datasets) != 19:
        raise RuntimeError("Dataset uncertainty summary does not have 19 rows")

    count_sums = distribution.groupby(["section", "method"])["count"].sum()
    probability_sums = distribution.groupby(
        ["section", "method"]
    )["probability"].sum()
    if not count_sums.eq(COMBINATIONS_PER_DATASET).all():
        raise RuntimeError("Rank counts do not sum to 20^5")
    if not np.allclose(probability_sums.to_numpy(), 1.0, rtol=0, atol=1e-12):
        raise RuntimeError("Rank probabilities do not sum to one")
    winner_sums = winners.groupby("section")["p_rank1"].sum()
    if not np.allclose(winner_sums.to_numpy(), 1.0, rtol=0, atol=1e-12):
        raise RuntimeError("Fractional winner probabilities do not sum to one")
    pair_sums = (
        superiority["p_A_gt_B"]
        + superiority["p_B_gt_A"]
        + superiority["tie_probability"]
    )
    if not np.allclose(pair_sums.to_numpy(), 1.0, rtol=0, atol=1e-12):
        raise RuntimeError("Pairwise superiority probabilities do not sum to one")
    if not summary["enumerated_combinations"].eq(COMBINATIONS_PER_DATASET).all():
        raise RuntimeError("Rank summary has an incorrect enumeration count")
    for column in ("empirical_p_rank1", "empirical_p_top2", "empirical_p_top3"):
        if not summary[column].between(0, 1).all():
            raise RuntimeError(f"Invalid probability in {column}")
    # P(rank 1) uses fractional winner credit for tied maxima, whereas top-k
    # probabilities use the average-midrank distribution.  With a four- or
    # five-way tied maximum the average rank is >2 even though every tied
    # method receives positive rank-1 credit, so P(top 2) need not dominate
    # P(rank 1).  Top 3 and top 2 share the same midrank semantics and must
    # remain monotone.
    if not summary["empirical_p_top3"].ge(
        summary["empirical_p_top2"]
    ).all():
        raise RuntimeError("Top-k probability ordering failed")


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(
        index=False,
        lineterminator="\n",
        float_format="%.17g",
    ).encode("utf-8")


def authoritative_four_method_tokens() -> tuple[list[str], dict[tuple[str, str, str], dict[str, str]]]:
    """Read immutable four-method CSV fields as exact text tokens."""
    with FOUR_METHOD_SOURCE.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise RuntimeError("Immutable four-method source has no CSV header")
        fieldnames = list(reader.fieldnames)
        rows: dict[tuple[str, str, str], dict[str, str]] = {}
        for row in reader:
            identity = (row["section"], row["method"], row["seed"])
            if identity in rows:
                raise RuntimeError(f"Duplicate immutable source token row: {identity}")
            rows[identity] = dict(row)
    expected = {
        (dataset, method, str(seed))
        for dataset in DATASETS for method in OLD_METHODS for seed in SEEDS
    }
    if set(rows) != expected:
        raise RuntimeError("Immutable four-method token grid is not 19 x 4 x 20")
    return fieldnames, rows


def integrated_csv_with_authoritative_tokens(frame: pd.DataFrame) -> bytes:
    """Serialize integration while preserving every old-source token exactly."""
    source_fields, source_rows = authoritative_four_method_tokens()
    output_fields = list(frame.columns)
    if not set(source_fields).issubset(output_fields):
        raise RuntimeError("Integrated schema omits immutable source fields")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream, fieldnames=output_fields, lineterminator="\n", extrasaction="raise"
    )
    writer.writeheader()
    seen_old: set[tuple[str, str, str]] = set()
    for parsed in frame.to_dict(orient="records"):
        identity = (
            str(parsed["section"]), str(parsed["method"]), str(int(parsed["seed"]))
        )
        row = {
            field: "" if pd.isna(value) else format(value, ".17g")
            if isinstance(value, (float, np.floating)) else str(value)
            for field, value in parsed.items()
        }
        if identity in source_rows:
            for field in source_fields:
                row[field] = source_rows[identity][field]
            seen_old.add(identity)
        writer.writerow({field: row.get(field, "") for field in output_fields})
    if seen_old != set(source_rows):
        raise RuntimeError("Not every immutable four-method row was serialized")
    return stream.getvalue().encode("utf-8")


def verify_serialized_four_method_reconciliation(
    integrated_bytes: bytes, old: pd.DataFrame
) -> dict[str, Any]:
    """Require exact token equality for every original four-method field."""
    source_fields, source_rows = authoritative_four_method_tokens()
    with io.StringIO(integrated_bytes.decode("utf-8"), newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not set(source_fields).issubset(reader.fieldnames):
            raise RuntimeError("Serialized integrated header omits source fields")
        observed: dict[tuple[str, str, str], dict[str, str]] = {}
        for row in reader:
            if row["method"] not in OLD_METHODS:
                continue
            identity = (row["section"], row["method"], row["seed"])
            if identity in observed:
                raise RuntimeError(f"Duplicate serialized source row: {identity}")
            observed[identity] = {field: row[field] for field in source_fields}
    if observed != source_rows:
        raise RuntimeError("Serialized four-method tokens differ from authoritative CSV")
    # Check the serialized identity grid in addition to exact source tokens.
    reread = pd.read_csv(io.BytesIO(integrated_bytes), dtype={"section": str})
    require_identity_grid(reread, METHODS, "serialized integrated five-method source")
    if len(reread) != len(DATASETS) * len(METHODS) * len(SEEDS):
        raise RuntimeError("Serialized integrated source is not exactly 1,900 rows")
    return {
        "serialized_authoritative_tokens_exact": True,
        "serialized_source_fields_exact": source_fields,
        "serialized_source_rows_exact": len(source_rows),
        "serialized_float_tolerance_used": False,
    }


def write_package(
    output_dir: Path,
    files: dict[str, bytes],
    manifest: dict[str, Any],
) -> None:
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise RuntimeError(f"Refusing to overwrite output directory: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = output_dir.with_name(
        output_dir.name + f".tmp-{os.getpid()}-{uuid.uuid4().hex}"
    )
    staging.mkdir()
    try:
        output_records: list[dict[str, Any]] = []
        for name, value in files.items():
            path = staging / name
            path.write_bytes(value)
            output_records.append({
                "path": name,
                "bytes": len(value),
                "sha256": sha256_bytes(value),
            })
        manifest["outputs"] = output_records
        manifest_bytes = (
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        (staging / "analysis_manifest.json").write_bytes(manifest_bytes)
        os.replace(staging, output_dir)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def analyze(args: argparse.Namespace) -> None:
    if args.chunk_size < 1:
        raise RuntimeError("chunk-size must be positive")
    # This must remain the first data-dependent operation.
    protocol_hash, checkpoint_hashes = verify_scientific_gate()
    old, sedr, integrated, old_source_hash = load_inputs(
        protocol_hash, checkpoint_hashes
    )
    displays = display_names(integrated)

    distribution_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    winner_rows: list[dict[str, Any]] = []
    superiority_rows: list[dict[str, Any]] = []
    dataset_rows: list[dict[str, Any]] = []
    for dataset in DATASETS:
        result = stream_rank_one_dataset(
            dataset,
            displays[dataset],
            score_arrays(integrated, dataset),
            args.chunk_size,
        )
        distributions, summaries, winners, pairs, dataset_summary = result
        distribution_rows.extend(distributions)
        summary_rows.extend(summaries)
        winner_rows.extend(winners)
        superiority_rows.extend(pairs)
        dataset_rows.append(dataset_summary)

    distribution = pd.DataFrame(distribution_rows)
    rank_summary = pd.DataFrame(summary_rows)
    winners = pd.DataFrame(winner_rows)
    superiority = pd.DataFrame(superiority_rows)
    dataset_summary = pd.DataFrame(dataset_rows)
    validate_rank_outputs(
        distribution, rank_summary, winners, superiority, dataset_summary
    )
    # Reconcile once more immediately before serialization.
    reconcile_four_method_values(old, integrated)

    integrated_bytes = integrated_csv_with_authoritative_tokens(integrated)
    serialized_audit = verify_serialized_four_method_reconciliation(
        integrated_bytes, old
    )
    reconciliation = {
        "status": "PASS",
        "immutable_source": FOUR_METHOD_SOURCE.relative_to(ROOT).as_posix(),
        "immutable_source_sha256": old_source_hash,
        "authoritative_sources_rehashed": 14,
        "original_method_rows_expected": 1520,
        "original_method_rows_observed_after_filter": int(
            integrated["method"].isin(OLD_METHODS).sum()
        ),
        "key_grid_exact": True,
        "source_columns_exact_after_filter": True,
        "in_memory_source_columns_bit_exact": True,
        **serialized_audit,
        "existing_source_modified": False,
    }
    files = {
        "integrated_seed_level_accuracy.csv": integrated_bytes,
        "five_method_rank_distributions.csv": csv_bytes(distribution),
        "five_method_rank_summary.csv": csv_bytes(rank_summary),
        "five_method_winner_probabilities.csv": csv_bytes(winners),
        "five_method_pairwise_superiority.csv": csv_bytes(superiority),
        "five_method_dataset_uncertainty.csv": csv_bytes(dataset_summary),
        "four_method_reconciliation.json": (
            json.dumps(reconciliation, indent=2) + "\n"
        ).encode("utf-8"),
    }
    manifest = {
        "schema_version": 1,
        "analysis": "exact five-method empirical ranking integration",
        "scientific_gate_sha256": sha256_file(GATE_FILE),
        "protocol_hash": protocol_hash,
        "checkpoint_manifest_sha256": canonical_checkpoint_digest([
            {
                "dataset": dataset,
                "seed": seed,
                **checkpoint_hashes[(dataset, seed)],
            }
            for dataset in DATASETS for seed in SEEDS
        ]),
        "methods": list(METHODS),
        "dataset_count": len(DATASETS),
        "seeds_per_method_dataset": 20,
        "integrated_seed_rows": len(integrated),
        "combinations_per_dataset": COMBINATIONS_PER_DATASET,
        "total_enumerated_combinations": TOTAL_ENUMERATED_COMBINATIONS,
        "enumeration": "exact streamed Cartesian product",
        "chunk_size": args.chunk_size,
        "rank_rule": "average midrank for exact ties",
        "rank1_rule": "tied maxima split rank-1 credit equally",
        "top_k_rule": "probability from average-midrank distribution",
        "pairwise_rule": "unmatched exact 20 x 20 empirical Cartesian product",
        "combinations_are_independent_experiments": False,
        "four_method_reconciliation": reconciliation,
        "sedr_seed_level_source_sha256": sha256_file(SEDR_SOURCE),
        "status": "PASS",
    }
    write_package(args.output_dir, files, manifest)
    print(json.dumps({
        "status": "FIVE_METHOD_EXACT_INTEGRATION_PASS",
        "output_dir": str(args.output_dir.resolve()),
        "integrated_rows": len(integrated),
        "total_exact_combinations": TOTAL_ENUMERATED_COMBINATIONS,
        "four_method_reconciliation": "PASS",
    }, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Post-gate exact five-method empirical ranking integration"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT,
        help="New candidate output directory; existing directories are refused",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=100_000,
        help="Streaming chunk size; does not change exact enumeration",
    )
    args = parser.parse_args()
    try:
        analyze(args)
        return 0
    except Exception as error:
        print(
            f"FIVE_METHOD_ANALYSIS_BLOCKED: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
