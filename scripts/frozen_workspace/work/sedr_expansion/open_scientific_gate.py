"""Open the Project 9 SEDR scientific gate only after 380/380 technical PASS.

Fail-closed contract:

* validate exactly 19 datasets x seeds 1..20 using validate_technical.py;
* accept only final-mode checkpoints tied to the current protocol and input;
* reject missing, duplicate, extra, smoke, failed, or stale artifacts;
* reject if any prespecified scientific-output artifact already exists;
* write a deterministic 380-row checkpoint manifest hash, a technical metadata
  aggregate, and SCIENTIFIC_GATE_OPEN.json only after all checks pass.

This module contains no reference-label reader and imports no scientific metric.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
TECHNICAL_METADATA = EXPANSION / "technical_metadata.csv"
PREFLIGHT_TECHNICAL_METADATA = EXPANSION / "technical_metadata_preflight.csv"
CHECKPOINT_MANIFEST = EXPANSION / "FINAL_380_CHECKPOINT_MANIFEST.csv"
TECHNICAL_VALIDATION_REPORT = (
    EXPANSION / "FINAL_380_TECHNICAL_VALIDATION.json"
)
GATE_FILE = EXPANSION / "SCIENTIFIC_GATE_OPEN.json"
GATE_TRANSACTION_DIR = EXPANSION / ".gate_publish_transaction"

DATASETS = (
    "151507", "151508", "151509", "151510", "151669", "151670",
    "151671", "151672", "151673", "151674", "151675", "151676",
    "STARmap_20180505_BY3_1k", "HBCA1",
    "MERFISH_Bregma_m0.04", "MERFISH_Bregma_m0.09",
    "MERFISH_Bregma_m0.14", "MERFISH_Bregma_m0.19",
    "MERFISH_Bregma_m0.24",
)
EXPECTED_IDENTITIES = {(dataset, seed) for dataset in DATASETS for seed in range(1, 21)}
EXPECTED_COUNT = 380

# These paths are reserved for post-gate scientific computation. Their prior
# existence means the pre-unblinding firewall cannot be certified.
SCIENTIFIC_OUTPUT_PATHS = (
    EXPANSION / "Scientific",
    EXPANSION / "Five-method integration",
    EXPANSION / "candidate_integration",
    EXPANSION / "seed_level_accuracy.csv",
    EXPANSION / "pairwise_partition_reproducibility.csv",
    EXPANSION / "iso_accuracy_results.csv",
    EXPANSION / "marker_reproducibility_all_pairs.csv",
    EXPANSION / "within_unit_marker_correlations.csv",
    EXPANSION / "marker_tertile_summary.csv",
    EXPANSION / "consensus_results.csv",
    EXPANSION / "sedr_unit_summary.csv",
    EXPANSION / "integrated_seed_level_accuracy.csv",
    EXPANSION / "integrated_pairwise_reproducibility.csv",
    EXPANSION / "integrated_iso_accuracy.csv",
    EXPANSION / "five_method_winner_probabilities.csv",
    EXPANSION / "five_method_rank_distributions.csv",
    EXPANSION / "five_method_pairwise_superiority.csv",
    EXPANSION / "integrated_marker_unit_summary.csv",
    EXPANSION / "integrated_consensus_summary.csv",
    EXPANSION / "FINAL_SEDR_REPORT.md",
    EXPANSION / "SEDR_GENERALIZATION_ASSESSMENT.md",
    EXPANSION / "FIVE_METHOD_INTEGRATION_SUMMARY.md",
    EXPANSION / "MANUSCRIPT_IMPLICATIONS_ONLY.md",
    EXPANSION / "VALIDATION_REPORT.md",
    EXPANSION / "FINAL_SUMMARY.json",
    EXPANSION / ".core_scientific_publish_transaction",
    EXPANSION / ".core_scientific_publish_receipt.json",
)
HEX64 = re.compile(r"^[0-9A-F]{64}$")


class GateClosed(RuntimeError):
    """The scientific gate cannot be opened safely."""


def load_validator() -> Any:
    path = WORK / "validate_technical.py"
    spec = importlib.util.spec_from_file_location("sedr_validate_technical", path)
    if spec is None or spec.loader is None:
        raise GateClosed(f"Cannot load strict technical validator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def csv_bytes(fieldnames: list[str], rows: list[dict[str, Any]]) -> bytes:
    import io

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    temporary.write_bytes(value)
    os.replace(temporary, path)


def write_fsynced(path: Path, value: bytes) -> None:
    """Create/replace one staging file and flush its bytes before promotion."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _load_gate_transaction() -> dict[str, Any]:
    journal_path = GATE_TRANSACTION_DIR / "journal.json"
    if not journal_path.is_file():
        raise GateClosed(
            "Ambiguous gate transaction directory without journal: "
            f"{GATE_TRANSACTION_DIR}"
        )
    journal = load_json(journal_path)
    if not isinstance(journal, dict) or journal.get("schema_version") != 1:
        raise GateClosed("Invalid gate publication transaction journal")
    entries = journal.get("entries")
    if not isinstance(entries, list) or not entries:
        raise GateClosed("Gate publication transaction has no entries")
    allowed = {
        path.resolve()
        for path in (
            CHECKPOINT_MANIFEST,
            TECHNICAL_METADATA,
            PREFLIGHT_TECHNICAL_METADATA,
            TECHNICAL_VALIDATION_REPORT,
            GATE_FILE,
        )
    }
    observed: set[Path] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise GateClosed("Invalid gate transaction entry")
        target = Path(str(entry.get("target", ""))).resolve()
        if target not in allowed or target in observed:
            raise GateClosed(f"Unexpected/duplicate gate transaction target: {target}")
        observed.add(target)
        planned = str(entry.get("planned_sha256", "")).upper()
        if not HEX64.fullmatch(planned):
            raise GateClosed(f"Invalid planned transaction hash: {target}")
        staged = (GATE_TRANSACTION_DIR / str(entry.get("staged", ""))).resolve()
        try:
            staged.relative_to(GATE_TRANSACTION_DIR.resolve())
        except ValueError as error:
            raise GateClosed("Gate transaction staging path escapes its directory") from error
        if bool(entry.get("preexisting")):
            prior = str(entry.get("preexisting_sha256", "")).upper()
            if not HEX64.fullmatch(prior):
                raise GateClosed(f"Invalid preexisting transaction hash: {target}")
            backup = (GATE_TRANSACTION_DIR / str(entry.get("backup", ""))).resolve()
            try:
                backup.relative_to(GATE_TRANSACTION_DIR.resolve())
            except ValueError as error:
                raise GateClosed("Gate transaction backup path escapes its directory") from error
            if not backup.is_file() or sha256_file(backup) != prior:
                raise GateClosed(f"Gate transaction backup is missing/stale: {target}")
    return journal


def recover_gate_transaction() -> bool:
    """Recover a prior interrupted gate publish without deleting ambiguity.

    Returns True only when the prior transaction had already installed the
    complete bundle, including the gate (which is always promoted last).
    """

    if not GATE_TRANSACTION_DIR.exists():
        return False
    if not GATE_TRANSACTION_DIR.is_dir():
        raise GateClosed(f"Gate transaction path is not a directory: {GATE_TRANSACTION_DIR}")
    journal = _load_gate_transaction()
    entries = journal["entries"]
    gate_entry = next(
        (entry for entry in entries if Path(entry["target"]).resolve() == GATE_FILE.resolve()),
        None,
    )
    if gate_entry is None:
        raise GateClosed("Gate transaction does not contain the gate as a target")

    def current_hash(entry: dict[str, Any]) -> str | None:
        target = Path(entry["target"])
        return sha256_file(target) if target.is_file() else None

    all_planned = all(
        current_hash(entry) == str(entry["planned_sha256"]).upper()
        for entry in entries
    )
    if all_planned:
        # The gate is last, so a fully matching bundle is a completed commit.
        shutil.rmtree(GATE_TRANSACTION_DIR)
        return True

    gate_hash = current_hash(gate_entry)
    if gate_hash == str(gate_entry["planned_sha256"]).upper():
        raise GateClosed(
            "Gate exists but its interrupted transaction is not a complete, "
            "hash-matching bundle; refusing destructive recovery"
        )

    # Preflight every state before changing anything.  A target may be absent,
    # still contain its prior bytes, or contain the transaction's planned bytes.
    # Anything else is external/ambiguous and must be preserved for diagnosis.
    for entry in entries:
        observed = current_hash(entry)
        allowed = {None, str(entry["planned_sha256"]).upper()}
        if entry.get("preexisting"):
            allowed.add(str(entry["preexisting_sha256"]).upper())
        if observed not in allowed:
            raise GateClosed(
                "Ambiguous artifact encountered during gate recovery; preserved: "
                f"{entry['target']}"
            )

    if gate_hash is not None:
        # An unknown/foreign preexisting gate is never an artifact owned by
        # this transaction and must not be removed during rollback.
        raise GateClosed(
            "An unrelated gate artifact appeared during publication; preserved: "
            f"{GATE_FILE}"
        )

    for entry in reversed(entries):
        target = Path(entry["target"])
        observed = current_hash(entry)
        if entry.get("preexisting"):
            prior = str(entry["preexisting_sha256"]).upper()
            if observed != prior:
                backup = GATE_TRANSACTION_DIR / str(entry["backup"])
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup, target)
        elif observed is not None:
            target.unlink()
    shutil.rmtree(GATE_TRANSACTION_DIR)
    return False


def publish_gate_bundle(payloads: list[tuple[Path, bytes]]) -> None:
    """Transactionally publish gate artifacts, with ``GATE_FILE`` last."""

    targets = [path.resolve() for path, _ in payloads]
    if len(set(targets)) != len(targets) or targets[-1] != GATE_FILE.resolve():
        raise GateClosed("Invalid gate publication order or duplicate target")
    if GATE_TRANSACTION_DIR.exists():
        raise GateClosed("Unrecovered gate publication transaction exists")
    GATE_TRANSACTION_DIR.mkdir(parents=False, exist_ok=False)
    entries: list[dict[str, Any]] = []
    committed = False
    try:
        for index, (target, value) in enumerate(payloads):
            target = target.resolve()
            preexisting = target.is_file()
            if preexisting and target != TECHNICAL_METADATA.resolve():
                raise GateClosed(f"Refusing to overwrite existing gate artifact: {target}")
            entry: dict[str, Any] = {
                "target": str(target),
                "staged": f"new_{index:02d}.bin",
                "planned_sha256": sha256_bytes(value),
                "preexisting": preexisting,
            }
            write_fsynced(GATE_TRANSACTION_DIR / entry["staged"], value)
            if preexisting:
                prior = target.read_bytes()
                entry["preexisting_sha256"] = sha256_bytes(prior)
                entry["backup"] = f"backup_{index:02d}.bin"
                write_fsynced(GATE_TRANSACTION_DIR / entry["backup"], prior)
            entries.append(entry)
        journal = {
            "schema_version": 1,
            "kind": "PROJECT9_SEDR_GATE_PUBLICATION",
            "gate_last": True,
            "entries": entries,
        }
        write_fsynced(
            GATE_TRANSACTION_DIR / "journal.json",
            (json.dumps(journal, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )

        # Refuse races/collisions immediately before the first promotion.
        for entry in entries:
            target = Path(entry["target"])
            if entry["preexisting"]:
                if not target.is_file() or sha256_file(target) != entry["preexisting_sha256"]:
                    raise GateClosed(f"Gate target changed during staging: {target}")
            elif target.exists():
                raise GateClosed(f"Gate target appeared during staging: {target}")

        for entry in entries:
            staged = GATE_TRANSACTION_DIR / entry["staged"]
            target = Path(entry["target"])
            if entry["preexisting"]:
                os.replace(staged, target)
            else:
                # A late collision must be preserved, not overwritten.
                os.rename(staged, target)
        committed = True
    except Exception:
        if not committed:
            if (GATE_TRANSACTION_DIR / "journal.json").is_file():
                if recover_gate_transaction():
                    # A failure after the gate-last promotion is already a
                    # complete, hash-verified commit after recovery.
                    return
            elif GATE_TRANSACTION_DIR.exists():
                # Promotion cannot start before the journal is durable.
                shutil.rmtree(GATE_TRANSACTION_DIR)
        raise
    finally:
        if committed and GATE_TRANSACTION_DIR.exists():
            shutil.rmtree(GATE_TRANSACTION_DIR)


def reject_existing_scientific_outputs() -> None:
    found: list[str] = []
    for path in SCIENTIFIC_OUTPUT_PATHS:
        if path.is_file():
            found.append(str(path.resolve()))
        elif path.is_dir() and any(path.rglob("*")):
            found.append(str(path.resolve()))
    if found:
        raise GateClosed(
            "Scientific output artifacts existed before gate opening: "
            + ", ".join(found)
        )


def verify_lock(protocol_hash: str, input_manifest_hash: str) -> str:
    if not LOCK_FILE.is_file():
        raise GateClosed(f"LOCK_ADD_SEDR is missing: {LOCK_FILE}")
    lock = load_json(LOCK_FILE)
    allowed_lock_keys = {
        "decision", "protocol_file", "protocol_hash", "protocol_sha256",
        "locked_at", "official_repository", "official_commit",
        "technical_gate", "scientific_unblinding",
        "scientific_outcomes_inspected_before_lock", "committed_target_runs",
        "outcome_independent_commitment",
    }
    if set(lock) - allowed_lock_keys:
        raise GateClosed("LOCK_ADD_SEDR contains unrecognized fields")
    if lock.get("decision") != "LOCK_ADD_SEDR":
        raise GateClosed("The outcome-blind decision is not LOCK_ADD_SEDR")
    locked_hash = str(
        lock.get("protocol_hash", lock.get("protocol_sha256", ""))
    ).upper()
    if locked_hash != protocol_hash:
        raise GateClosed("LOCK_ADD_SEDR protocol hash is stale")
    if lock.get("scientific_unblinding") is not False:
        raise GateClosed("LOCK_ADD_SEDR does not preserve scientific blinding")
    if lock.get("scientific_outcomes_inspected_before_lock") is not False:
        raise GateClosed("LOCK_ADD_SEDR reports pre-lock scientific inspection")
    if lock.get("committed_target_runs") != EXPECTED_COUNT:
        raise GateClosed("LOCK_ADD_SEDR target is not exactly 380")
    if lock.get("outcome_independent_commitment") is not True:
        raise GateClosed("LOCK_ADD_SEDR lacks the outcome-independent commitment")
    technical_gate = lock.get("technical_gate")
    if not isinstance(technical_gate, dict):
        raise GateClosed("LOCK_ADD_SEDR technical gate is missing")
    required_technical_gate = {
        "structural_inputs_passed": 19,
        "structural_inputs_total": 19,
        "label_blind_technical_views_passed": 19,
        "label_blind_technical_views_total": 19,
        "representative_smoke_passed": 4,
        "representative_smoke_total": 4,
        "identical_seed_controls_passed": 2,
        "identical_seed_controls_total": 2,
        "runtime_feasible": True,
        "mclust_operational": True,
        "gpu_operational": True,
    }
    for key, expected in required_technical_gate.items():
        if technical_gate.get(key) != expected:
            raise GateClosed(f"LOCK_ADD_SEDR technical gate failed: {key}")
    # The gate records both current hashes even if the lock predates the
    # technical-view manifest field; protocol identity must always be explicit.
    return sha256_file(LOCK_FILE)


def discover_exact_checkpoint_files() -> list[Path]:
    if not CHECKPOINT_ROOT.is_dir():
        raise GateClosed(f"Final checkpoint root is missing: {CHECKPOINT_ROOT}")
    failure_artifacts = sorted(CHECKPOINT_ROOT.rglob("failure.json"))
    temporary_artifacts = sorted(CHECKPOINT_ROOT.rglob("*.tmp"))
    if failure_artifacts or temporary_artifacts:
        raise GateClosed(
            "Invalid/failure artifacts exist in the final checkpoint tree: "
            + ", ".join(
                str(path.resolve())
                for path in (failure_artifacts + temporary_artifacts)[:10]
            )
        )
    all_checkpoint_json = sorted(CHECKPOINT_ROOT.rglob("checkpoint.json"))
    if len(all_checkpoint_json) != EXPECTED_COUNT:
        raise GateClosed(
            f"Gate requires exactly 380 checkpoint.json files; found "
            f"{len(all_checkpoint_json)}"
        )
    return all_checkpoint_json


def latest_validated_checkpoint_timestamp(
    checkpoint_rows: list[dict[str, Any]],
) -> float:
    """Latest metadata/label mtime in the just-validated 380-run panel."""

    return max(
        max(
            Path(row["checkpoint_path"]).stat().st_mtime,
            Path(row["labels_path"]).stat().st_mtime,
        )
        for row in checkpoint_rows
    )


def validate_all() -> tuple[list[dict[str, Any]], str, str, str]:
    validator = load_validator()
    manifest_entries, input_manifest_hash = validator.load_input_manifest(
        INPUT_MANIFEST
    )
    protocol_hash = validator.load_protocol_hash(PROTOCOL, PROTOCOL_HASH_FILE)
    if not HEX64.fullmatch(protocol_hash):
        raise GateClosed("Current protocol hash is not valid SHA-256")
    lock_hash = verify_lock(protocol_hash, input_manifest_hash)
    checkpoint_files = discover_exact_checkpoint_files()

    identities: dict[tuple[str, int], dict[str, Any]] = {}
    validated: list[dict[str, Any]] = []
    errors: list[str] = []
    for checkpoint_path in checkpoint_files:
        try:
            result = validator.validate_checkpoint(
                checkpoint_path, manifest_entries, protocol_hash
            )
            if result["mode"] != "final":
                raise GateClosed(f"Smoke/non-final checkpoint found: {checkpoint_path}")
            identity = (result["dataset"], int(result["seed"]))
            if identity not in EXPECTED_IDENTITIES:
                raise GateClosed(f"Unexpected checkpoint identity: {identity}")
            if identity in identities:
                raise GateClosed(f"Duplicate checkpoint identity: {identity}")
            expected_path = (
                CHECKPOINT_ROOT / identity[0] / f"seed{identity[1]:02d}"
                / "checkpoint.json"
            ).resolve()
            if checkpoint_path.resolve() != expected_path:
                raise GateClosed(
                    f"Checkpoint is outside its canonical identity path: {identity}"
                )
            payload = load_json(checkpoint_path)
            if payload.get("scientific_unblinding") is not False:
                raise GateClosed(f"Checkpoint is not scientifically blinded: {identity}")
            if payload.get("protocol_hash", "").upper() != protocol_hash:
                raise GateClosed(f"Checkpoint protocol hash is stale: {identity}")
            if payload.get("input", {}).get("manifest_sha256", "").upper() != input_manifest_hash:
                raise GateClosed(f"Checkpoint input-manifest hash is stale: {identity}")
            identities[identity] = {"result": result, "payload": payload}
            validated.append(
                {
                    "dataset": result["dataset"],
                    "seed": int(result["seed"]),
                    "checkpoint_path": str(checkpoint_path.resolve()),
                    "checkpoint_bytes": checkpoint_path.stat().st_size,
                    "checkpoint_sha256": result["checkpoint_sha256"],
                    "labels_path": str(
                        (checkpoint_path.parent / payload["outputs"]["labels_path"]).resolve()
                    ),
                    "labels_bytes": payload["outputs"]["labels_bytes"],
                    "labels_sha256": result["labels_sha256"],
                    "input_sha256": payload["input"]["sha256"],
                    "protocol_sha256": protocol_hash,
                    "input_manifest_sha256": input_manifest_hash,
                    "requested_k": result["requested_k"],
                    "observed_k": result["observed_k"],
                    "status": result["status"],
                }
            )
        except Exception as error:
            errors.append(f"{checkpoint_path}: {error}")
    if errors:
        raise GateClosed(
            f"Strict checkpoint validation failed for {len(errors)} artifact(s): "
            + " | ".join(errors[:10])
        )
    actual_identities = set(identities)
    missing = sorted(EXPECTED_IDENTITIES - actual_identities)
    extra = sorted(actual_identities - EXPECTED_IDENTITIES)
    if missing or extra or len(actual_identities) != EXPECTED_COUNT:
        raise GateClosed(
            f"Checkpoint identity grid failed: count={len(actual_identities)}, "
            f"missing={missing[:10]}, extra={extra[:10]}"
        )
    validated.sort(key=lambda row: (DATASETS.index(row["dataset"]), row["seed"]))
    return validated, protocol_hash, input_manifest_hash, lock_hash


def build_technical_metadata(
    checkpoint_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest_row in checkpoint_rows:
        checkpoint = load_json(Path(manifest_row["checkpoint_path"]))
        rows.append(
            {
                "dataset": checkpoint["dataset"],
                "seed": checkpoint["seed"],
                "status": checkpoint["status"],
                "mode": checkpoint["mode"],
                "requested_k": checkpoint["requested_k"],
                "observed_k": checkpoint["observed_k"],
                "n_obs": checkpoint["input"]["obs_count"],
                "n_vars": checkpoint["input"]["var_count"],
                "retained_gene_count": checkpoint["preprocessing"]["retained_gene_count"],
                "pca_dimension": checkpoint["preprocessing"]["pca_dimension"],
                "graph_k": checkpoint["graph"]["k"],
                "graph_edge_count": checkpoint["graph"]["edge_count"],
                "graph_isolates": checkpoint["graph"]["isolates"],
                "graph_connected_components": checkpoint["graph"]["connected_components"],
                "graph_sha256": checkpoint["graph"]["hash"],
                "pretraining_epochs_completed": checkpoint["training"]["pretraining_epochs_completed"],
                "dec_epochs_completed": checkpoint["training"]["dec_epochs_completed"],
                "embedding_shape": "x".join(
                    str(value) for value in checkpoint["training"]["embedding_shape"]
                ),
                "embedding_finite": checkpoint["training"]["embedding_finite"],
                "labels_count": checkpoint["final_readout"]["labels_count"],
                "labels_finite": checkpoint["final_readout"]["labels_finite"],
                "final_readout_model": checkpoint["final_readout"]["model"],
                "final_readout_calls": checkpoint["final_readout"]["calls"],
                "runtime_seconds": checkpoint["runtime_seconds"],
                "peak_ram_gib": checkpoint["resources"]["peak_ram_gib"],
                "peak_gpu_memory_mib": checkpoint["resources"]["peak_gpu_memory_mib"],
                "protocol_sha256": checkpoint["protocol_hash"],
                "input_sha256": checkpoint["input"]["sha256"],
                "input_manifest_sha256": checkpoint["input"]["manifest_sha256"],
                "labels_sha256": checkpoint["outputs"]["labels_sha256"],
                "checkpoint_sha256": manifest_row["checkpoint_sha256"],
            }
        )
    return rows


def build_validation_report(
    checkpoint_rows: list[dict[str, Any]],
    protocol_hash: str,
    input_manifest_hash: str,
    canonical_manifest_hash: str,
) -> dict[str, Any]:
    """Return a deterministic, outcome-blind aggregate validation report."""
    return {
        "schema_version": 1,
        "validator": "strict outcome-blind SEDR technical gate validator",
        "status": "PASS",
        "checkpoint_count": EXPECTED_COUNT,
        "pass_count": EXPECTED_COUNT,
        "fail_count": 0,
        "invalid_count": 0,
        "duplicate_count": 0,
        "missing_count": 0,
        "smoke_count": 0,
        "dataset_count": len(DATASETS),
        "seeds_per_dataset": 20,
        "protocol_hash": protocol_hash,
        "input_manifest_sha256": input_manifest_hash,
        "checkpoint_manifest_sha256": canonical_manifest_hash,
        "scientific_metrics_computed": False,
        "reference_annotations_read": False,
        "results": [
            {
                "dataset": row["dataset"],
                "seed": int(row["seed"]),
                "status": row["status"],
                "mode": "final",
                "checkpoint_sha256": row["checkpoint_sha256"],
                "labels_sha256": row["labels_sha256"],
            }
            for row in checkpoint_rows
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed opener for the Project 9 SEDR scientific gate"
    )
    parser.add_argument(
        "--readiness-only",
        action="store_true",
        help="Validate readiness but never write gate or aggregate outputs",
    )
    args = parser.parse_args()

    try:
        recovered_commit = recover_gate_transaction()
        if recovered_commit:
            print("SCIENTIFIC_GATE_OPEN_380_OF_380_RECOVERED")
            return 0
        if GATE_FILE.exists():
            raise GateClosed(f"Scientific gate already exists: {GATE_FILE}")
        reject_existing_scientific_outputs()
        checkpoint_rows, protocol_hash, input_manifest_hash, lock_hash = validate_all()
        if args.readiness_only:
            print("SCIENTIFIC_GATE_READY_380_OF_380_NO_WRITE")
            return 0

        manifest_fields = list(checkpoint_rows[0])
        checkpoint_manifest_bytes = csv_bytes(manifest_fields, checkpoint_rows)
        checkpoint_manifest_file_hash = sha256_bytes(checkpoint_manifest_bytes)
        canonical_rows = [
            {
                "dataset": row["dataset"],
                "seed": int(row["seed"]),
                "checkpoint_sha256": row["checkpoint_sha256"],
                "labels_sha256": row["labels_sha256"],
            }
            for row in checkpoint_rows
        ]
        canonical_rows.sort(key=lambda row: (row["dataset"], row["seed"]))
        checkpoint_manifest_hash = sha256_bytes(
            json.dumps(
                canonical_rows, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        )
        metadata_rows = build_technical_metadata(checkpoint_rows)
        metadata_bytes = csv_bytes(list(metadata_rows[0]), metadata_rows)
        metadata_hash = sha256_bytes(metadata_bytes)
        validation_report = build_validation_report(
            checkpoint_rows,
            protocol_hash,
            input_manifest_hash,
            checkpoint_manifest_hash,
        )
        validation_report_bytes = (
            json.dumps(validation_report, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        validation_report_hash = sha256_bytes(validation_report_bytes)

        # Recheck the scientific-output firewall immediately before writes.
        reject_existing_scientific_outputs()
        # ``technical_metadata.csv`` is initially the quarantined smoke-test
        # summary.  Preserve that completed pre-lock artifact before replacing
        # the required public path with the final 380-run aggregate.
        if TECHNICAL_METADATA.exists():
            preflight_bytes = TECHNICAL_METADATA.read_bytes()
            if PREFLIGHT_TECHNICAL_METADATA.exists():
                if PREFLIGHT_TECHNICAL_METADATA.read_bytes() != preflight_bytes:
                    raise GateClosed(
                        "Existing preflight technical-metadata snapshot differs"
                    )
        else:
            preflight_bytes = None
        gate = {
            "schema_version": 1,
            "gate": "SCIENTIFIC_GATE_OPEN",
            # Bind temporal ordering to the exact artifacts validated above.
            # Coarse filesystem timestamp precision is handled by choosing the
            # later of wall-clock time and latest artifact mtime plus 1 usec.
            "opened_utc": datetime.fromtimestamp(
                max(
                    datetime.now(timezone.utc).timestamp(),
                    latest_validated_checkpoint_timestamp(checkpoint_rows) + 1e-6,
                ),
                timezone.utc,
            ).isoformat(),
            "technical_checkpoint_count": EXPECTED_COUNT,
            "checkpoint_count": EXPECTED_COUNT,
            "dataset_count": len(DATASETS),
            "seeds_per_dataset": 20,
            "identity_grid_complete": True,
            "duplicate_identities": 0,
            "invalid_checkpoints": 0,
            "missing_checkpoints": 0,
            "smoke_checkpoints_in_final_set": 0,
            "protocol_sha256": protocol_hash,
            "protocol_hash": protocol_hash,
            "input_manifest_sha256": input_manifest_hash,
            "lock_add_sedr_sha256": lock_hash,
            "checkpoint_manifest_file": CHECKPOINT_MANIFEST.name,
            "checkpoint_manifest_sha256": checkpoint_manifest_hash,
            "checkpoint_manifest_file_sha256": checkpoint_manifest_file_hash,
            "checkpoint_manifest_path": str(CHECKPOINT_MANIFEST.resolve()),
            "technical_metadata_file": TECHNICAL_METADATA.name,
            "technical_metadata_sha256": metadata_hash,
            "technical_validation_report_file": TECHNICAL_VALIDATION_REPORT.name,
            "technical_validation_report_path": str(
                TECHNICAL_VALIDATION_REPORT.resolve()
            ),
            "technical_validation_report_sha256": validation_report_hash,
            "scientific_outputs_present_before_gate": False,
            "reference_annotations_read_by_gate": False,
            "scientific_metrics_computed_by_gate": False,
            "scientific_unblinding": True,
            "status": "OPEN",
        }
        gate_bytes = (json.dumps(gate, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        payloads: list[tuple[Path, bytes]] = [
            (CHECKPOINT_MANIFEST, checkpoint_manifest_bytes),
        ]
        if preflight_bytes is not None and not PREFLIGHT_TECHNICAL_METADATA.exists():
            payloads.append((PREFLIGHT_TECHNICAL_METADATA, preflight_bytes))
        payloads.extend(
            [
                (TECHNICAL_METADATA, metadata_bytes),
                (TECHNICAL_VALIDATION_REPORT, validation_report_bytes),
                # The gate is the transaction commit marker and must be last.
                (GATE_FILE, gate_bytes),
            ]
        )
        publish_gate_bundle(payloads)
        print("SCIENTIFIC_GATE_OPEN_380_OF_380")
        return 0
    except Exception as error:
        print(f"SCIENTIFIC_GATE_CLOSED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
