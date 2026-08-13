"""Run the prespecified core SEDR analysis after the 380/380 gate opens.

This module is deliberately fail-closed.  Its module-level imports are Python
standard-library only.  Before AnnData, pandas, NumPy, sklearn clustering, or
sklearn metrics are imported, ``verify_gate_and_fresh_scan`` independently:

* verifies the hash-bound SCIENTIFIC_GATE_OPEN record;
* re-hashes the frozen protocol, input manifest, lock, and checkpoint manifest;
* strict-validates exactly 19 datasets x 20 seeds from the live checkpoint tree;
* recomputes the canonical 380-row checkpoint-manifest SHA-256.

Reference H5AD files are not opened, and scientific metric code is not imported,
unless every check passes.  Outputs are written atomically and never overwrite
an existing scientific result.  Omitting ``--execute`` performs the gate and
fresh-checkpoint audit only and cannot import scientific metric code.
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
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
EXPANSION = ROOT / "outputs" / "PROJECT9_SEDR_EXPANSION"
CHECKPOINT_ROOT = EXPANSION / "checkpoints"
INPUT_MANIFEST = (
    EXPANSION / "technical_inputs" / "TECHNICAL_INPUT_MANIFEST.json"
)
PROTOCOL = EXPANSION / "SEDR_FROZEN_PROTOCOL.md"
PROTOCOL_HASH_FILE = EXPANSION / "SEDR_FROZEN_PROTOCOL.sha256"
LOCK_FILE = EXPANSION / "LOCK_ADD_SEDR.json"
GATE_FILE = EXPANSION / "SCIENTIFIC_GATE_OPEN.json"
CHECKPOINT_MANIFEST = EXPANSION / "FINAL_380_CHECKPOINT_MANIFEST.csv"
VALIDATOR = WORK / "validate_technical.py"

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
    "MERFISH_Bregma_m0.04": "Bregma -0.04 mm",
    "MERFISH_Bregma_m0.09": "Bregma -0.09 mm",
    "MERFISH_Bregma_m0.14": "Bregma -0.14 mm",
    "MERFISH_Bregma_m0.19": "Bregma -0.19 mm",
    "MERFISH_Bregma_m0.24": "Bregma -0.24 mm",
}
SEEDS = tuple(range(1, 21))
EXPECTED_IDENTITIES = {
    (dataset, seed) for dataset in DATASETS for seed in SEEDS
}
EXPECTED_COUNT = 380
EXPECTED_PAIR_COUNT = 19 * math.comb(20, 2)
ISO_THRESHOLDS = (0.01, 0.02, 0.03)
PRIMARY_ISO_THRESHOLD = 0.02
METHOD = "SEDR"
HEX64 = re.compile(r"^[0-9A-F]{64}$")

OUTPUTS = {
    "seed": EXPANSION / "seed_level_accuracy.csv",
    "pairwise": EXPANSION / "pairwise_partition_reproducibility.csv",
    "iso": EXPANSION / "iso_accuracy_results.csv",
    "consensus": EXPANSION / "consensus_results.csv",
    "unit": EXPANSION / "sedr_unit_summary.csv",
}
CORE_TRANSACTION_DIR = EXPANSION / ".core_scientific_publish_transaction"
CORE_RECEIPT = EXPANSION / ".core_scientific_publish_receipt.json"


class ScientificGateClosed(RuntimeError):
    """The scientific analysis is not authorized to load references."""


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
        raise ScientificGateClosed(f"{field} is not a valid SHA-256")
    return text


def path_within(path: Path, parent: Path, field: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(parent.resolve())
    except ValueError as error:
        raise ScientificGateClosed(
            f"{field} escapes the expansion directory: {resolved}"
        ) from error
    return resolved


def canonical_manifest_hash(rows: Iterable[dict[str, Any]]) -> str:
    canonical = [
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
    canonical.sort(key=lambda row: (row["dataset"], row["seed"]))
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(encoded)


def load_strict_validator() -> Any:
    if not VALIDATOR.is_file():
        raise ScientificGateClosed(f"Strict validator is missing: {VALIDATOR}")
    # The gate audit may import only the outcome-blind technical validator.
    source = VALIDATOR.read_text(encoding="utf-8-sig").lower()
    forbidden = (
        "sklearn.metrics", "adjusted_rand_score",
        "normalized_mutual_info_score", "manual_layer",
    )
    found = [token for token in forbidden if token in source]
    if found:
        raise ScientificGateClosed(
            "Technical validator contains scientific/reference code: "
            + ", ".join(found)
        )
    spec = importlib.util.spec_from_file_location(
        "sedr_strict_technical_validator_for_scientific_gate", VALIDATOR
    )
    if spec is None or spec.loader is None:
        raise ScientificGateClosed("Could not load strict technical validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_gate_schema(gate: dict[str, Any]) -> None:
    if gate.get("schema_version") != 1:
        raise ScientificGateClosed("Unsupported scientific-gate schema")
    if gate.get("status") not in {"OPEN", "SCIENTIFIC_GATE_OPEN"}:
        raise ScientificGateClosed("Scientific gate status is not OPEN")
    if gate.get("gate", "SCIENTIFIC_GATE_OPEN") != "SCIENTIFIC_GATE_OPEN":
        raise ScientificGateClosed("Gate identity is not SCIENTIFIC_GATE_OPEN")
    if gate.get("scientific_unblinding") is not True:
        raise ScientificGateClosed("scientific_unblinding is not true")
    if gate.get("checkpoint_count") != EXPECTED_COUNT:
        raise ScientificGateClosed("Gate checkpoint_count is not exactly 380")
    if gate.get("technical_checkpoint_count", EXPECTED_COUNT) != EXPECTED_COUNT:
        raise ScientificGateClosed("Gate technical count is not exactly 380")
    fixed_values = {
        "identity_grid_complete": True,
        "duplicate_identities": 0,
        "invalid_checkpoints": 0,
        "missing_checkpoints": 0,
        "smoke_checkpoints_in_final_set": 0,
        "scientific_outputs_present_before_gate": False,
        "reference_annotations_read_by_gate": False,
        "scientific_metrics_computed_by_gate": False,
    }
    for key, expected in fixed_values.items():
        # Every firewall invariant must be explicit in the signed gate; an
        # omitted field is not equivalent to a PASS assertion.
        if key not in gate or gate.get(key) != expected:
            raise ScientificGateClosed(f"Gate invariant failed: {key}")
    opened = gate.get("opened_utc")
    if not isinstance(opened, str):
        raise ScientificGateClosed("Gate opened_utc is missing")
    try:
        timestamp = datetime.fromisoformat(opened.replace("Z", "+00:00"))
    except ValueError as error:
        raise ScientificGateClosed("Gate opened_utc is invalid") from error
    if timestamp.tzinfo is None:
        raise ScientificGateClosed("Gate opened_utc must include a timezone")
    # The caller independently re-parses this signed value when checking that
    # every checkpoint artifact predates gate opening.


def verify_lock_and_gate_hashes(
    gate: dict[str, Any], protocol_hash: str, input_manifest_hash: str
) -> None:
    gate_protocol = normalize_hash(
        gate.get("protocol_hash", gate.get("protocol_sha256", "")),
        "gate.protocol_hash",
    )
    if gate_protocol != protocol_hash:
        raise ScientificGateClosed("Gate protocol hash is stale")
    if normalize_hash(
        gate.get("input_manifest_sha256", ""),
        "gate.input_manifest_sha256",
    ) != input_manifest_hash:
        raise ScientificGateClosed("Gate input-manifest hash is stale")

    if not LOCK_FILE.is_file():
        raise ScientificGateClosed(f"LOCK_ADD_SEDR is missing: {LOCK_FILE}")
    lock = load_json(LOCK_FILE)
    if not isinstance(lock, dict) or lock.get("decision") != "LOCK_ADD_SEDR":
        raise ScientificGateClosed("Outcome-blind lock is not LOCK_ADD_SEDR")
    lock_protocol = normalize_hash(
        lock.get("protocol_hash", lock.get("protocol_sha256", "")),
        "lock.protocol_hash",
    )
    if lock_protocol != protocol_hash:
        raise ScientificGateClosed("LOCK_ADD_SEDR protocol hash is stale")
    if lock.get("scientific_unblinding") is not False:
        raise ScientificGateClosed("LOCK_ADD_SEDR did not preserve blinding")
    if lock.get("scientific_outcomes_inspected_before_lock") is not False:
        raise ScientificGateClosed("Lock does not certify outcome blinding")
    if lock.get("committed_target_runs") != EXPECTED_COUNT:
        raise ScientificGateClosed("Lock target is not exactly 380 runs")
    gate_lock_hash = normalize_hash(
        gate.get("lock_add_sedr_sha256", ""),
        "gate.lock_add_sedr_sha256",
    )
    if gate_lock_hash != sha256_file(LOCK_FILE):
        raise ScientificGateClosed("Gate LOCK_ADD_SEDR hash is stale")


def verify_checkpoint_manifest_file(
    gate: dict[str, Any], fresh_rows: list[dict[str, Any]], fresh_hash: str
) -> None:
    raw_path = gate.get("checkpoint_manifest_path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ScientificGateClosed("Gate checkpoint_manifest_path is missing")
    manifest_path = path_within(
        Path(raw_path), EXPANSION, "checkpoint_manifest_path"
    )
    if manifest_path != CHECKPOINT_MANIFEST.resolve() or not manifest_path.is_file():
        raise ScientificGateClosed("Gate checkpoint manifest path is unexpected")
    declared_file_hash = normalize_hash(
        gate.get("checkpoint_manifest_file_sha256", ""),
        "gate.checkpoint_manifest_file_sha256",
    )
    if sha256_file(manifest_path) != declared_file_hash:
        raise ScientificGateClosed("Checkpoint-manifest file hash is stale")

    with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
        disk_rows = list(csv.DictReader(handle))
    if len(disk_rows) != EXPECTED_COUNT:
        raise ScientificGateClosed("Checkpoint-manifest file is not 380 rows")
    if canonical_manifest_hash(disk_rows) != fresh_hash:
        raise ScientificGateClosed(
            "Checkpoint-manifest file differs from the fresh checkpoint scan"
        )

    expected = {
        (row["dataset"], int(row["seed"])): (
            row["checkpoint_sha256"], row["labels_sha256"]
        )
        for row in fresh_rows
    }
    observed: dict[tuple[str, int], tuple[str, str]] = {}
    for row in disk_rows:
        identity = (str(row["dataset"]), int(row["seed"]))
        if identity in observed:
            raise ScientificGateClosed(
                f"Duplicate identity in checkpoint manifest: {identity}"
            )
        observed[identity] = (
            normalize_hash(row["checkpoint_sha256"], "manifest checkpoint hash"),
            normalize_hash(row["labels_sha256"], "manifest labels hash"),
        )
    if observed != expected:
        raise ScientificGateClosed(
            "Checkpoint-manifest rows do not match the fresh strict scan"
        )


def verify_optional_technical_report(
    gate: dict[str, Any], canonical_hash: str
) -> None:
    declared = normalize_hash(
        gate.get("technical_validation_report_sha256", ""),
        "gate.technical_validation_report_sha256",
    )
    raw_path = gate.get(
        "technical_validation_report_path",
        gate.get("technical_validation_report_file"),
    )
    if raw_path in (None, ""):
        # The gate opener uses the freshly validated canonical manifest digest
        # as its compact technical-validation signature when no separate report
        # file is emitted.
        if declared != canonical_hash:
            raise ScientificGateClosed(
                "Unbound technical-validation signature in gate"
            )
        return
    report_path = path_within(
        Path(str(raw_path)), EXPANSION, "technical_validation_report_path"
    )
    if not report_path.is_file() or sha256_file(report_path) != declared:
        raise ScientificGateClosed("Technical-validation report hash is stale")


def verify_gate_and_fresh_scan() -> dict[str, Any]:
    """Return validated checkpoint/input records without touching references."""

    if not GATE_FILE.is_file():
        raise ScientificGateClosed(f"Scientific gate is missing: {GATE_FILE}")
    gate = load_json(GATE_FILE)
    if not isinstance(gate, dict):
        raise ScientificGateClosed("Scientific gate is not a JSON object")
    verify_gate_schema(gate)

    validator = load_strict_validator()
    manifest_entries, input_manifest_hash = validator.load_input_manifest(
        INPUT_MANIFEST
    )
    protocol_hash = validator.load_protocol_hash(
        PROTOCOL, PROTOCOL_HASH_FILE
    )
    protocol_hash = normalize_hash(protocol_hash, "current protocol hash")
    input_manifest_hash = normalize_hash(
        input_manifest_hash, "current input-manifest hash"
    )
    verify_lock_and_gate_hashes(gate, protocol_hash, input_manifest_hash)

    checkpoint_files = sorted(CHECKPOINT_ROOT.rglob("checkpoint.json"))
    if len(checkpoint_files) != EXPECTED_COUNT:
        raise ScientificGateClosed(
            f"Fresh scan found {len(checkpoint_files)} checkpoint files, not 380"
        )
    rows: list[dict[str, Any]] = []
    identities: set[tuple[str, int]] = set()
    for checkpoint_path in checkpoint_files:
        result = validator.validate_checkpoint(
            checkpoint_path, manifest_entries, protocol_hash
        )
        dataset = str(result["dataset"])
        seed = int(result["seed"])
        identity = (dataset, seed)
        if result["mode"] != "final":
            raise ScientificGateClosed(
                f"Non-final checkpoint in final tree: {checkpoint_path}"
            )
        if identity not in EXPECTED_IDENTITIES or identity in identities:
            raise ScientificGateClosed(
                f"Unexpected or duplicate checkpoint identity: {identity}"
            )
        expected_path = (
            CHECKPOINT_ROOT / dataset / f"seed{seed:02d}" / "checkpoint.json"
        ).resolve()
        if checkpoint_path.resolve() != expected_path:
            raise ScientificGateClosed(
                f"Checkpoint is outside its canonical identity path: {identity}"
            )
        payload = load_json(checkpoint_path)
        if payload.get("scientific_unblinding") is not False:
            raise ScientificGateClosed(
                f"Checkpoint was not written under the blinded runner: {identity}"
            )
        if normalize_hash(payload.get("protocol_hash", ""), "checkpoint protocol") != protocol_hash:
            raise ScientificGateClosed(f"Stale checkpoint protocol: {identity}")
        if normalize_hash(
            payload.get("input", {}).get("manifest_sha256", ""),
            "checkpoint input-manifest hash",
        ) != input_manifest_hash:
            raise ScientificGateClosed(
                f"Stale checkpoint input manifest: {identity}"
            )
        opened_timestamp = datetime.fromisoformat(
            str(gate["opened_utc"]).replace("Z", "+00:00")
        )
        latest_artifact_mtime = max(
            checkpoint_path.stat().st_mtime,
            (checkpoint_path.parent / "labels.csv").stat().st_mtime,
        )
        if opened_timestamp.timestamp() + 1e-6 < latest_artifact_mtime:
            raise ScientificGateClosed(
                "Gate timestamp predates a validated checkpoint artifact: "
                f"{identity}"
            )
        labels_path = (checkpoint_path.parent / "labels.csv").resolve()
        identities.add(identity)
        rows.append(
            {
                "dataset": dataset,
                "seed": seed,
                "checkpoint_path": checkpoint_path.resolve(),
                "labels_path": labels_path,
                "checkpoint_sha256": normalize_hash(
                    result["checkpoint_sha256"], "fresh checkpoint hash"
                ),
                "labels_sha256": normalize_hash(
                    result["labels_sha256"], "fresh labels hash"
                ),
                "requested_k": int(result["requested_k"]),
                "observed_k": int(result["observed_k"]),
                "n_observations": int(result["labels_count"]),
                "payload": payload,
            }
        )
    if identities != EXPECTED_IDENTITIES or len(rows) != EXPECTED_COUNT:
        missing = sorted(EXPECTED_IDENTITIES - identities)
        raise ScientificGateClosed(
            f"Fresh 380-run identity grid is incomplete: {missing[:10]}"
        )
    rows.sort(key=lambda row: (DATASETS.index(row["dataset"]), row["seed"]))
    fresh_hash = canonical_manifest_hash(rows)
    gate_manifest_hash = normalize_hash(
        gate.get("checkpoint_manifest_sha256", ""),
        "gate.checkpoint_manifest_sha256",
    )
    if fresh_hash != gate_manifest_hash:
        raise ScientificGateClosed(
            "Fresh 380-checkpoint digest differs from the gate signature"
        )
    verify_checkpoint_manifest_file(gate, rows, fresh_hash)
    verify_optional_technical_report(gate, fresh_hash)

    source_entries: dict[str, dict[str, Any]] = {}
    for dataset, record in manifest_entries.items():
        if dataset not in EXPECTED_IDENTITIES_BY_DATASET:
            raise ScientificGateClosed(f"Unexpected input dataset: {dataset}")
        source_entries[dataset] = record
    if set(source_entries) != set(DATASETS):
        raise ScientificGateClosed("Input manifest does not contain 19 datasets")
    return {
        "gate": gate,
        "gate_sha256": sha256_file(GATE_FILE),
        "protocol_hash": protocol_hash,
        "input_manifest_hash": input_manifest_hash,
        "checkpoint_manifest_hash": fresh_hash,
        "checkpoints": rows,
        "input_entries": source_entries,
    }


# A named set avoids constructing 380 tuples during the source-manifest check.
EXPECTED_IDENTITIES_BY_DATASET = frozenset(DATASETS)


def ordered_string_hash(values: Iterable[str]) -> str:
    return sha256_bytes("\n".join(values).encode("utf-8"))


def atomic_dataframes(frames: dict[Path, Any]) -> None:
    if recover_core_transaction(frames):
        return
    existing = [str(path) for path in frames if path.exists()]
    if existing:
        raise RuntimeError(
            "Refusing to overwrite existing scientific outputs: "
            + ", ".join(existing)
        )
    if CORE_RECEIPT.exists():
        raise RuntimeError(
            "Core publication receipt exists without its complete outputs; "
            f"refusing ambiguous retry: {CORE_RECEIPT}"
        )
    if CORE_TRANSACTION_DIR.exists():
        raise RuntimeError(
            f"Unrecovered core publication transaction: {CORE_TRANSACTION_DIR}"
        )
    CORE_TRANSACTION_DIR.mkdir(parents=False, exist_ok=False)
    entries: list[dict[str, Any]] = []
    committed = False
    try:
        for index, (path, frame) in enumerate(frames.items()):
            path.parent.mkdir(parents=True, exist_ok=True)
            staged = CORE_TRANSACTION_DIR / f"new_{index:02d}.csv"
            frame.to_csv(
                staged, index=False, float_format="%.12g", lineterminator="\n"
            )
            with staged.open("r+b") as handle:
                os.fsync(handle.fileno())
            entries.append(
                {
                    "target": str(path.resolve()),
                    "staged": staged.name,
                    "planned_sha256": sha256_file(staged),
                }
            )
        journal = {
            "schema_version": 1,
            "kind": "PROJECT9_SEDR_CORE_SCIENTIFIC_PUBLICATION",
            "entries": entries,
        }
        journal_path = CORE_TRANSACTION_DIR / "journal.json"
        with journal_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(journal, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        # Refuse a concurrent creator before installing any transaction bytes.
        appeared = [entry["target"] for entry in entries if Path(entry["target"]).exists()]
        if appeared:
            raise RuntimeError(
                "Core scientific output appeared during staging: " + ", ".join(appeared)
            )
        for entry in entries:
            # All five targets are required to be absent.  On Windows,
            # ``rename`` refuses a late collision instead of overwriting it.
            os.rename(
                CORE_TRANSACTION_DIR / entry["staged"], Path(entry["target"])
            )
        receipt_bytes = (
            json.dumps(journal, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        receipt_tmp = CORE_TRANSACTION_DIR / "receipt.tmp"
        with receipt_tmp.open("wb") as handle:
            handle.write(receipt_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        if CORE_RECEIPT.exists():
            raise RuntimeError(f"Core receipt collision: {CORE_RECEIPT}")
        os.rename(receipt_tmp, CORE_RECEIPT)
        committed = True
    except Exception:
        if not committed:
            if (CORE_TRANSACTION_DIR / "journal.json").is_file():
                if recover_core_transaction(frames):
                    # A transient failure after all five CSV promotions (for
                    # example, immediately before receipt promotion) is a
                    # complete, hash-verified commit after recovery.
                    committed = True
                    return
            elif CORE_TRANSACTION_DIR.exists():
                # No promotion begins before the durable journal exists.
                shutil.rmtree(CORE_TRANSACTION_DIR)
        raise
    finally:
        if committed and CORE_TRANSACTION_DIR.exists():
            shutil.rmtree(CORE_TRANSACTION_DIR)


def _core_transaction_entries(frames: dict[Path, Any]) -> list[dict[str, Any]]:
    journal_path = CORE_TRANSACTION_DIR / "journal.json"
    if not journal_path.is_file():
        raise RuntimeError(
            "Ambiguous core transaction directory without journal: "
            f"{CORE_TRANSACTION_DIR}"
        )
    journal = load_json(journal_path)
    entries = journal.get("entries") if isinstance(journal, dict) else None
    if (
        not isinstance(journal, dict)
        or journal.get("schema_version") != 1
        or not isinstance(entries, list)
        or len(entries) != len(frames)
    ):
        raise RuntimeError("Invalid core publication transaction journal")
    allowed = {path.resolve() for path in frames}
    observed: set[Path] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError("Invalid core transaction entry")
        target = Path(str(entry.get("target", ""))).resolve()
        if target not in allowed or target in observed:
            raise RuntimeError(f"Unexpected/duplicate core transaction target: {target}")
        observed.add(target)
        planned = str(entry.get("planned_sha256", "")).upper()
        if not HEX64.fullmatch(planned):
            raise RuntimeError(f"Invalid core transaction hash: {target}")
        staged = (CORE_TRANSACTION_DIR / str(entry.get("staged", ""))).resolve()
        try:
            staged.relative_to(CORE_TRANSACTION_DIR.resolve())
        except ValueError as error:
            raise RuntimeError("Core staging path escapes its transaction") from error
    return entries


def recover_core_transaction(frames: dict[Path, Any]) -> bool:
    """Recover a prior interrupted all-new five-CSV publication.

    A complete set is accepted only when every target matches the signed
    transaction hashes. Otherwise only matching transaction-created targets are
    removed. Unknown bytes are never deleted.
    """

    if not CORE_TRANSACTION_DIR.exists():
        return False
    if not CORE_TRANSACTION_DIR.is_dir():
        raise RuntimeError(f"Core transaction path is not a directory: {CORE_TRANSACTION_DIR}")
    entries = _core_transaction_entries(frames)

    hashes: dict[Path, str | None] = {}
    for entry in entries:
        target = Path(entry["target"])
        hashes[target] = sha256_file(target) if target.is_file() else None
        if hashes[target] not in {None, str(entry["planned_sha256"]).upper()}:
            raise RuntimeError(
                "Ambiguous scientific artifact encountered during recovery; preserved: "
                f"{target}"
            )
    if all(hashes[Path(entry["target"])] == entry["planned_sha256"] for entry in entries):
        receipt = {
            "schema_version": 1,
            "kind": "PROJECT9_SEDR_CORE_SCIENTIFIC_PUBLICATION",
            "entries": entries,
        }
        receipt_bytes = (json.dumps(receipt, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        receipt_tmp = CORE_TRANSACTION_DIR / "receipt.recovery.tmp"
        with receipt_tmp.open("wb") as handle:
            handle.write(receipt_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        if CORE_RECEIPT.is_file():
            existing = load_json(CORE_RECEIPT)
            existing_entries = existing.get("entries") if isinstance(existing, dict) else None
            expected_signature = [
                (entry["target"], entry["planned_sha256"]) for entry in entries
            ]
            existing_signature = [
                (entry.get("target"), entry.get("planned_sha256"))
                for entry in (existing_entries or [])
                if isinstance(entry, dict)
            ]
            if (
                not isinstance(existing, dict)
                or existing.get("schema_version") != 1
                or existing.get("kind")
                != "PROJECT9_SEDR_CORE_SCIENTIFIC_PUBLICATION"
                or existing_signature != expected_signature
            ):
                raise RuntimeError("Existing core receipt conflicts with recovered transaction")
            receipt_tmp.unlink()
        elif CORE_RECEIPT.exists():
            raise RuntimeError(f"Core receipt path collision: {CORE_RECEIPT}")
        else:
            os.replace(receipt_tmp, CORE_RECEIPT)
        shutil.rmtree(CORE_TRANSACTION_DIR)
        return True

    for entry in entries:
        target = Path(entry["target"])
        if hashes[target] == entry["planned_sha256"]:
            target.unlink()
    shutil.rmtree(CORE_TRANSACTION_DIR)
    return False


def run_scientific_analysis(audit: dict[str, Any]) -> dict[str, Any]:
    """Import scientific libraries only after the fail-closed audit returns."""

    recovery_frame_keys = {path: None for path in OUTPUTS.values()}
    if recover_core_transaction(recovery_frame_keys):
        return {
            "status": "COMPLETE_RECOVERED_TRANSACTION",
            "gate_sha256": audit["gate_sha256"],
            "protocol_hash": audit["protocol_hash"],
            "checkpoint_manifest_sha256": audit["checkpoint_manifest_hash"],
            "seed_level_rows": EXPECTED_COUNT,
            "pairwise_rows": EXPECTED_PAIR_COUNT,
            "iso_summary_rows": len(DATASETS) * len(ISO_THRESHOLDS),
            "consensus_rows": len(DATASETS),
            "unit_summary_rows": len(DATASETS),
            "outputs": {key: str(path.resolve()) for key, path in OUTPUTS.items()},
        }

    import anndata as ad
    import numpy as np
    import pandas as pd
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import (
        adjusted_rand_score,
        normalized_mutual_info_score,
    )
    from anndata_null_compat import register_h5ad_null_reader

    register_h5ad_null_reader()

    for target in OUTPUTS.values():
        if target.exists():
            raise RuntimeError(
                f"Scientific output already exists; refusing overwrite: {target}"
            )

    def consensus_partition(labels: Any, k: int) -> Any:
        n_observations = int(labels.shape[1])
        association = np.zeros(
            (n_observations, n_observations), dtype=np.float32
        )
        for partition in labels:
            association += partition[:, None] == partition[None, :]
        association /= float(labels.shape[0])
        model = AgglomerativeClustering(
            n_clusters=k, metric="precomputed", linkage="average"
        )
        result = model.fit_predict(1.0 - association).astype(np.int16)
        if result.shape != (n_observations,) or np.unique(result).size != k:
            raise RuntimeError("Consensus partition did not return requested K")
        return result

    checkpoint_map = {
        (row["dataset"], row["seed"]): row
        for row in audit["checkpoints"]
    }
    seed_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    iso_rows: list[dict[str, Any]] = []
    consensus_rows: list[dict[str, Any]] = []
    unit_rows: list[dict[str, Any]] = []

    for dataset in DATASETS:
        input_record = audit["input_entries"][dataset]
        source_path = Path(str(input_record.get("source_path", ""))).resolve()
        if not source_path.is_file():
            raise RuntimeError(f"Frozen reference source is missing: {source_path}")
        source_hash = sha256_file(source_path)
        declared_source_hash = normalize_hash(
            input_record.get("source_sha256", ""), "input source hash"
        )
        locked_source_hash = normalize_hash(
            input_record.get("locked_source_sha256", declared_source_hash),
            "locked input source hash",
        )
        if source_hash != declared_source_hash or source_hash != locked_source_hash:
            raise RuntimeError(f"Frozen reference-source hash changed: {dataset}")
        if int(input_record.get("source_bytes", source_path.stat().st_size)) != source_path.stat().st_size:
            raise RuntimeError(f"Frozen reference-source byte count changed: {dataset}")

        base = ad.read_h5ad(source_path, backed="r")
        try:
            observation_ids = base.obs_names.astype(str).to_numpy()
            if "manual_layer" not in base.obs.columns:
                raise RuntimeError(
                    f"Frozen reference column manual_layer is missing: {dataset}"
                )
            reference_series = base.obs["manual_layer"].copy()
            n_variables = int(base.n_vars)
        finally:
            base.file.close()
        if observation_ids.size != int(input_record["obs_count"]):
            raise RuntimeError(f"Reference observation count changed: {dataset}")
        if ordered_string_hash(observation_ids.tolist()) != normalize_hash(
            input_record["obs_order_sha256_newline_utf8"],
            "input observation-order hash",
        ):
            raise RuntimeError(f"Reference observation order changed: {dataset}")
        valid_reference = reference_series.notna().to_numpy(dtype=bool)
        reference = reference_series.astype(str).to_numpy()
        if int(valid_reference.sum()) < 2 or np.unique(reference[valid_reference]).size < 2:
            raise RuntimeError(f"Reference annotation is not estimable: {dataset}")

        labels_by_seed: list[Any] = []
        observed_k_by_seed: list[int] = []
        dataset_seed_rows: list[dict[str, Any]] = []
        for seed in SEEDS:
            checkpoint = checkpoint_map[(dataset, seed)]
            labels_frame = pd.read_csv(
                checkpoint["labels_path"], dtype={"observation_id": str}
            )
            if list(labels_frame.columns) != ["observation_id", "cluster_label"]:
                raise RuntimeError(
                    f"Unexpected labels.csv columns: {dataset}/seed{seed:02d}"
                )
            if not np.array_equal(
                labels_frame["observation_id"].to_numpy(str), observation_ids
            ):
                raise RuntimeError(
                    f"Prediction/reference order mismatch: {dataset}/seed{seed:02d}"
                )
            labels = labels_frame["cluster_label"].to_numpy(np.int32)
            if labels.shape != observation_ids.shape or not np.isfinite(labels).all():
                raise RuntimeError(
                    f"Invalid labels after gate: {dataset}/seed{seed:02d}"
                )
            if np.unique(labels).size != checkpoint["observed_k"]:
                raise RuntimeError(
                    f"Observed K changed after validation: {dataset}/seed{seed:02d}"
                )
            reference_ari = float(
                adjusted_rand_score(reference[valid_reference], labels[valid_reference])
            )
            reference_nmi = float(
                normalized_mutual_info_score(
                    reference[valid_reference], labels[valid_reference]
                )
            )
            if not math.isfinite(reference_ari) or not math.isfinite(reference_nmi):
                raise RuntimeError(
                    f"Non-finite reference metric: {dataset}/seed{seed:02d}"
                )
            row = {
                "dataset": dataset,
                "dataset_display": DISPLAY[dataset],
                "method": METHOD,
                "seed": seed,
                "reference_ari": reference_ari,
                "reference_nmi": reference_nmi,
                "n_observations": int(observation_ids.size),
                "n_reference_observations": int(valid_reference.sum()),
                "n_genes_frozen_source": n_variables,
                "requested_k": checkpoint["requested_k"],
                "observed_k": checkpoint["observed_k"],
                "checkpoint_sha256": checkpoint["checkpoint_sha256"],
                "labels_sha256": checkpoint["labels_sha256"],
                "protocol_hash": audit["protocol_hash"],
            }
            seed_rows.append(row)
            dataset_seed_rows.append(row)
            labels_by_seed.append(labels)
            observed_k_by_seed.append(checkpoint["observed_k"])

        labels_matrix = np.vstack(labels_by_seed)
        ari_values = np.asarray(
            [row["reference_ari"] for row in dataset_seed_rows], dtype=float
        )
        nmi_values = np.asarray(
            [row["reference_nmi"] for row in dataset_seed_rows], dtype=float
        )
        requested_k_values = {
            checkpoint_map[(dataset, seed)]["requested_k"] for seed in SEEDS
        }
        if len(requested_k_values) != 1:
            raise RuntimeError(f"Requested K varies across seeds: {dataset}")
        requested_k = next(iter(requested_k_values))

        dataset_pairs: list[dict[str, Any]] = []
        for first, second in itertools.combinations(range(20), 2):
            partition_ari = float(
                adjusted_rand_score(
                    labels_matrix[first], labels_matrix[second]
                )
            )
            partition_nmi = float(
                normalized_mutual_info_score(
                    labels_matrix[first], labels_matrix[second]
                )
            )
            difference = float(abs(ari_values[first] - ari_values[second]))
            row = {
                "dataset": dataset,
                "dataset_display": DISPLAY[dataset],
                "method": METHOD,
                "seed_r": first + 1,
                "seed_s": second + 1,
                "ari_r": float(ari_values[first]),
                "ari_s": float(ari_values[second]),
                "nmi_r": float(nmi_values[first]),
                "nmi_s": float(nmi_values[second]),
                "abs_reference_ari_difference": difference,
                "pairwise_partition_ari": partition_ari,
                "pairwise_partition_nmi": partition_nmi,
                "iso_accuracy_0_01": difference <= 0.01 + 1e-12,
                "iso_accuracy_0_02": difference <= 0.02 + 1e-12,
                "iso_accuracy_0_03": difference <= 0.03 + 1e-12,
            }
            pair_rows.append(row)
            dataset_pairs.append(row)
        if len(dataset_pairs) != 190:
            raise RuntimeError(f"Pair grid is not 190 rows: {dataset}")

        pair_frame = pd.DataFrame(dataset_pairs)
        pairwise_ari = pair_frame["pairwise_partition_ari"].to_numpy(float)
        pairwise_nmi = pair_frame["pairwise_partition_nmi"].to_numpy(float)
        median_pairwise_ari = float(np.median(pairwise_ari))
        iso_by_threshold: dict[float, dict[str, Any]] = {}
        for threshold in ISO_THRESHOLDS:
            eligible = pair_frame[
                pair_frame["abs_reference_ari_difference"]
                <= threshold + 1e-12
            ]
            count = int(len(eligible))
            divergent = int(
                (eligible["pairwise_partition_ari"] < 0.50).sum()
            )
            summary = {
                "dataset": dataset,
                "dataset_display": DISPLAY[dataset],
                "method": METHOD,
                "threshold": threshold,
                "n_total_seed_pairs": 190,
                "n_iso_accuracy_pairs": count,
                "n_divergent_partition_ari_lt_0_50": divergent,
                "percentage_divergent_partition_ari_lt_0_50": (
                    100.0 * divergent / count if count else None
                ),
                "contains_divergent_pair": bool(divergent),
                "median_pairwise_partition_ari": (
                    float(eligible["pairwise_partition_ari"].median())
                    if count else None
                ),
                "minimum_pairwise_partition_ari": (
                    float(eligible["pairwise_partition_ari"].min())
                    if count else None
                ),
            }
            iso_rows.append(summary)
            iso_by_threshold[threshold] = summary

        full_consensus = consensus_partition(labels_matrix, requested_k)
        first_consensus = consensus_partition(labels_matrix[:10], requested_k)
        second_consensus = consensus_partition(labels_matrix[10:], requested_k)
        split_half_ari = float(
            adjusted_rand_score(first_consensus, second_consensus)
        )
        consensus_reference_ari = float(
            adjusted_rand_score(
                reference[valid_reference], full_consensus[valid_reference]
            )
        )
        consensus_reference_nmi = float(
            normalized_mutual_info_score(
                reference[valid_reference], full_consensus[valid_reference]
            )
        )
        split_gain = split_half_ari - median_pairwise_ari
        consensus_row = {
            "dataset": dataset,
            "dataset_display": DISPLAY[dataset],
            "method": METHOD,
            "n_seeds": 20,
            "requested_k": requested_k,
            "median_single_seed_reference_ari": float(np.median(ari_values)),
            "best_single_seed_reference_ari": float(np.max(ari_values)),
            "consensus20_reference_ari": consensus_reference_ari,
            "consensus20_reference_nmi": consensus_reference_nmi,
            "consensus20_accuracy_delta_vs_median_seed": (
                consensus_reference_ari - float(np.median(ari_values))
            ),
            "median_single_seed_pairwise_partition_ari": median_pairwise_ari,
            "split_half_consensus_partition_ari": split_half_ari,
            "split_half_reproducibility_gain": split_gain,
            "split_half_improved": split_gain > 0.0,
            "split_half_a": "seeds 1-10",
            "split_half_b": "seeds 11-20",
            "algorithm": (
                "unweighted 20-seed co-association; D=1-C; "
                "average-linkage agglomeration at project K"
            ),
        }
        consensus_rows.append(consensus_row)

        primary_iso = iso_by_threshold[PRIMARY_ISO_THRESHOLD]
        unit_rows.append(
            {
                "dataset": dataset,
                "dataset_display": DISPLAY[dataset],
                "method": METHOD,
                "n_seeds": 20,
                "n_seed_pairs": 190,
                "requested_k": requested_k,
                "observed_k_min": int(min(observed_k_by_seed)),
                "observed_k_max": int(max(observed_k_by_seed)),
                "median_reference_ari": float(np.median(ari_values)),
                "reference_ari_sd": float(np.std(ari_values, ddof=1)),
                "reference_ari_min": float(np.min(ari_values)),
                "reference_ari_max": float(np.max(ari_values)),
                "reference_ari_range": float(np.ptp(ari_values)),
                "median_reference_nmi": float(np.median(nmi_values)),
                "reference_nmi_sd": float(np.std(nmi_values, ddof=1)),
                "median_pairwise_partition_ari": median_pairwise_ari,
                "p05_pairwise_partition_ari": float(
                    np.quantile(pairwise_ari, 0.05)
                ),
                "minimum_pairwise_partition_ari": float(np.min(pairwise_ari)),
                "median_pairwise_partition_nmi": float(np.median(pairwise_nmi)),
                "partition_instability": 1.0 - median_pairwise_ari,
                "low_sd_high_instability": bool(
                    np.std(ari_values, ddof=1) <= 0.02
                    and 1.0 - median_pairwise_ari >= 0.30
                ),
                "primary_iso_accuracy_threshold": PRIMARY_ISO_THRESHOLD,
                "n_primary_iso_accuracy_pairs": primary_iso["n_iso_accuracy_pairs"],
                "n_primary_iso_divergent_lt_0_50": primary_iso[
                    "n_divergent_partition_ari_lt_0_50"
                ],
                "percentage_primary_iso_divergent_lt_0_50": primary_iso[
                    "percentage_divergent_partition_ari_lt_0_50"
                ],
                "median_primary_iso_partition_ari": primary_iso[
                    "median_pairwise_partition_ari"
                ],
                "minimum_primary_iso_partition_ari": primary_iso[
                    "minimum_pairwise_partition_ari"
                ],
                "consensus20_reference_ari": consensus_reference_ari,
                "consensus20_reference_nmi": consensus_reference_nmi,
                "split_half_consensus_partition_ari": split_half_ari,
                "split_half_reproducibility_gain": split_gain,
                "split_half_improved": split_gain > 0.0,
                "hbca1_provenance": (
                    "manual pathology/H&E reference; prior developer-dataset exposure"
                    if dataset == "HBCA1" else ""
                ),
            }
        )

    frames = {
        OUTPUTS["seed"]: pd.DataFrame(seed_rows),
        OUTPUTS["pairwise"]: pd.DataFrame(pair_rows),
        OUTPUTS["iso"]: pd.DataFrame(iso_rows),
        OUTPUTS["consensus"]: pd.DataFrame(consensus_rows),
        OUTPUTS["unit"]: pd.DataFrame(unit_rows),
    }
    expected_rows = {
        OUTPUTS["seed"]: EXPECTED_COUNT,
        OUTPUTS["pairwise"]: EXPECTED_PAIR_COUNT,
        OUTPUTS["iso"]: len(DATASETS) * len(ISO_THRESHOLDS),
        OUTPUTS["consensus"]: len(DATASETS),
        OUTPUTS["unit"]: len(DATASETS),
    }
    for path, expected in expected_rows.items():
        if len(frames[path]) != expected:
            raise RuntimeError(
                f"Output row-count validation failed for {path.name}: "
                f"{len(frames[path])} != {expected}"
            )
    seed_frame = frames[OUTPUTS["seed"]]
    if seed_frame.groupby("dataset")["seed"].nunique().to_dict() != {
        dataset: 20 for dataset in DATASETS
    }:
        raise RuntimeError("Seed-level output is not a complete 19 x 20 grid")
    if seed_frame.duplicated(["dataset", "method", "seed"]).any():
        raise RuntimeError("Duplicate seed-level scientific row")
    pair_frame = frames[OUTPUTS["pairwise"]]
    if pair_frame.groupby("dataset").size().to_dict() != {
        dataset: 190 for dataset in DATASETS
    }:
        raise RuntimeError("Pairwise output is not 19 x 190")
    finite_columns = {
        OUTPUTS["seed"]: ["reference_ari", "reference_nmi"],
        OUTPUTS["pairwise"]: [
            "ari_r", "ari_s", "nmi_r", "nmi_s",
            "abs_reference_ari_difference", "pairwise_partition_ari",
            "pairwise_partition_nmi",
        ],
        OUTPUTS["consensus"]: [
            "consensus20_reference_ari", "consensus20_reference_nmi",
            "split_half_consensus_partition_ari",
        ],
    }
    for path, columns in finite_columns.items():
        values = frames[path][columns].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise RuntimeError(f"Non-finite core metric in {path.name}")

    # Recheck the gate and live checkpoint signature immediately before write.
    # This second pass remains outcome-blind and fails if the technical panel
    # changed while the scientific calculations were in memory.
    closing_audit = verify_gate_and_fresh_scan()
    if (
        closing_audit["gate_sha256"] != audit["gate_sha256"]
        or closing_audit["checkpoint_manifest_hash"]
        != audit["checkpoint_manifest_hash"]
        or closing_audit["protocol_hash"] != audit["protocol_hash"]
    ):
        raise RuntimeError("Scientific gate/checkpoint signature changed during analysis")
    atomic_dataframes(frames)
    return {
        "status": "COMPLETE",
        "gate_sha256": audit["gate_sha256"],
        "protocol_hash": audit["protocol_hash"],
        "checkpoint_manifest_sha256": audit["checkpoint_manifest_hash"],
        "seed_level_rows": len(seed_rows),
        "pairwise_rows": len(pair_rows),
        "iso_summary_rows": len(iso_rows),
        "consensus_rows": len(consensus_rows),
        "unit_summary_rows": len(unit_rows),
        "outputs": {key: str(path.resolve()) for key, path in OUTPUTS.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed post-380 core SEDR scientific analysis"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="After gate verification, load references and write scientific outputs",
    )
    args = parser.parse_args()
    try:
        audit = verify_gate_and_fresh_scan()
        if not args.execute:
            print(
                json.dumps(
                    {
                        "status": "SCIENTIFIC_ANALYSIS_READY_NOT_EXECUTED",
                        "fresh_valid_checkpoints": len(audit["checkpoints"]),
                        "protocol_hash": audit["protocol_hash"],
                        "checkpoint_manifest_sha256": audit[
                            "checkpoint_manifest_hash"
                        ],
                        "reference_annotations_loaded": False,
                        "sklearn_metrics_imported": False,
                    },
                    indent=2,
                )
            )
            return 0
        result = run_scientific_analysis(audit)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "SCIENTIFIC_ANALYSIS_NOT_RUN_OR_NOT_WRITTEN",
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
