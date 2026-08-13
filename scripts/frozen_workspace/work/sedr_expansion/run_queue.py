"""Run the locked 380-checkpoint SEDR technical queue.

The queue is deliberately serial: exactly one child process may use the GPU.
It launches only the outcome-blind checkpoint worker, validates every artifact
with the strict technical validator, and promotes only a validator-PASS attempt
into the final checkpoint tree.  No downstream analysis is imported here.

Nothing executes unless ``--execute`` is supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EXPANSION = ROOT / "outputs" / "PROJECT9_SEDR_EXPANSION"
WORKER = ROOT / "work" / "sedr_expansion" / "run_sedr_checkpoint.py"
VALIDATOR = ROOT / "work" / "sedr_expansion" / "validate_technical.py"
INPUT_MANIFEST = (
    EXPANSION / "technical_inputs" / "TECHNICAL_INPUT_MANIFEST.json"
)
PROTOCOL = EXPANSION / "SEDR_FROZEN_PROTOCOL.md"
PROTOCOL_HASH_FILE = EXPANSION / "SEDR_FROZEN_PROTOCOL.sha256"
LOCK_FILE = EXPANSION / "LOCK_ADD_SEDR.json"
CHECKPOINT_ROOT = EXPANSION / "checkpoints"
LOG_ROOT = EXPANSION / "logs" / "queue"
ATTEMPT_ROOT = EXPANSION / "queue_work" / "attempts"
STATE_FILE = EXPANSION / "queue_state.json"
QUEUE_LOCK = EXPANSION / "queue.lock"

TARGET_COUNT = 19 * 20
MAX_ATTEMPTS = 2  # first launch plus one crash retry
HEX64 = re.compile(r"^[0-9A-Fa-f]{64}$")
THREAD_ENV_KEYS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def parse_hash_file(path: Path) -> str:
    matches = re.findall(
        r"(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])",
        path.read_text(encoding="utf-8-sig"),
    )
    distinct = {value.upper() for value in matches}
    if len(distinct) != 1:
        raise RuntimeError(
            f"Protocol hash file must contain one distinct SHA-256: {path}"
        )
    return next(iter(distinct))


def verify_frozen_control() -> tuple[str, dict[str, Any]]:
    for path in (PROTOCOL, PROTOCOL_HASH_FILE, LOCK_FILE, INPUT_MANIFEST):
        if not path.is_file():
            raise RuntimeError(f"Required locked artifact is missing: {path}")

    recorded_hash = parse_hash_file(PROTOCOL_HASH_FILE)
    actual_hash = sha256_file(PROTOCOL)
    if recorded_hash != actual_hash:
        raise RuntimeError(
            f"Frozen protocol hash mismatch: {recorded_hash} != {actual_hash}"
        )

    lock = load_json(LOCK_FILE)
    if not isinstance(lock, dict) or lock.get("decision") != "LOCK_ADD_SEDR":
        raise RuntimeError("LOCK_ADD_SEDR.json does not contain LOCK_ADD_SEDR")
    lock_hash = str(lock.get("protocol_hash", "")).upper()
    if not HEX64.fullmatch(lock_hash) or lock_hash != actual_hash:
        raise RuntimeError("LOCK_ADD_SEDR protocol hash does not match the protocol")
    if lock.get("scientific_unblinding") is not False:
        raise RuntimeError("The lock must record scientific_unblinding=false")

    manifest = load_json(INPUT_MANIFEST)
    if not isinstance(manifest, dict):
        raise RuntimeError("Technical-input manifest is not a JSON object")
    required_flags = {
        "entry_count": 19,
        "pass_count": 19,
        "label_blind": True,
        "reference_annotation_values_read": False,
        "scientific_preprocessing_performed": False,
        "scientific_outcomes_computed_or_inspected": False,
    }
    for key, expected in required_flags.items():
        if manifest.get(key) != expected:
            raise RuntimeError(f"Technical-input manifest firewall failed: {key}")
    rows = manifest.get("entries")
    if not isinstance(rows, list) or len(rows) != 19:
        raise RuntimeError("Technical-input manifest must contain 19 entries")
    datasets: set[str] = set()
    for row in rows:
        dataset = row.get("dataset") if isinstance(row, dict) else None
        if (
            not isinstance(dataset, str)
            or dataset in datasets
            or row.get("status") != "PASS"
        ):
            raise RuntimeError("Technical-input manifest has an invalid entry")
        datasets.add(dataset)
    return actual_hash, manifest


def queue_items(manifest: dict[str, Any]) -> list[tuple[str, int]]:
    return [
        (str(row["dataset"]), seed)
        for row in manifest["entries"]
        for seed in range(1, 21)
    ]


def checkpoint_dir(dataset: str, seed: int) -> Path:
    return CHECKPOINT_ROOT / dataset / f"seed{seed:02d}"


def attempt_dir(dataset: str, seed: int, attempt: int) -> Path:
    return ATTEMPT_ROOT / dataset / f"seed{seed:02d}" / f"attempt{attempt:02d}"


def validator_command(
    python: Path, target: Path, report: Path
) -> list[str]:
    return [
        str(python),
        str(VALIDATOR),
        str(target),
        "--input-manifest",
        str(INPUT_MANIFEST),
        "--protocol",
        str(PROTOCOL),
        "--protocol-hash-file",
        str(PROTOCOL_HASH_FILE),
        "--report-json",
        str(report),
        "--require-count",
        "1",
    ]


def strict_validator_pass(
    python: Path, target: Path, log_stem: Path
) -> bool:
    log_stem.parent.mkdir(parents=True, exist_ok=True)
    report = log_stem.with_suffix(".validation.json")
    stdout_path = log_stem.with_suffix(".validator.stdout.log")
    stderr_path = log_stem.with_suffix(".validator.stderr.log")
    with stdout_path.open("w", encoding="utf-8", newline="\n") as stdout, \
            stderr_path.open("w", encoding="utf-8", newline="\n") as stderr:
        result = subprocess.run(
            validator_command(python, target, report),
            cwd=ROOT,
            stdout=stdout,
            stderr=stderr,
            check=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            ),
        )
    if result.returncode != 0 or not report.is_file():
        return False
    try:
        payload = load_json(report)
    except (OSError, json.JSONDecodeError):
        return False
    return (
        payload.get("status") == "PASS"
        and payload.get("pass_count") == 1
        and payload.get("fail_count") == 0
    )


def child_environment(seed: int, gpu: str) -> dict[str, str]:
    environment = os.environ.copy()
    for key in THREAD_ENV_KEYS:
        environment[key] = "4"
    environment["CUDA_VISIBLE_DEVICES"] = gpu
    environment["PYTHONHASHSEED"] = str(seed)
    environment["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    return environment


def worker_command(
    python: Path,
    dataset: str,
    seed: int,
    output_dir: Path,
    protocol_hash: str,
    save_embeddings: bool,
) -> list[str]:
    command = [
        str(python),
        str(WORKER),
        "--dataset",
        dataset,
        "--seed",
        str(seed),
        "--output-dir",
        str(output_dir),
        "--mode",
        "final",
        "--protocol-hash",
        protocol_hash,
        "--input-manifest",
        str(INPUT_MANIFEST),
    ]
    if save_embeddings:
        command.append("--embedding")
    return command


def acquire_queue_lock() -> str:
    QUEUE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    payload = {
        "pid": os.getpid(),
        "token": token,
        "created_utc": utc_now(),
    }
    try:
        descriptor = os.open(
            QUEUE_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY
        )
    except FileExistsError as error:
        raise RuntimeError(
            f"Queue lock already exists; inspect before resuming: {QUEUE_LOCK}"
        ) from error
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return token


def release_queue_lock(token: str) -> None:
    try:
        payload = load_json(QUEUE_LOCK)
        if payload.get("pid") == os.getpid() and payload.get("token") == token:
            QUEUE_LOCK.unlink()
    except (OSError, json.JSONDecodeError):
        pass


def count_prior_attempts(dataset: str, seed: int) -> int:
    parent = ATTEMPT_ROOT / dataset / f"seed{seed:02d}"
    if not parent.is_dir():
        return 0
    return sum(
        child.is_dir() and re.fullmatch(r"attempt\d{2}", child.name) is not None
        for child in parent.iterdir()
    )


def write_state(
    state: dict[str, Any], status: str, active: dict[str, Any] | None = None
) -> None:
    state["status"] = status
    state["updated_utc"] = utc_now()
    state["active_job"] = active
    atomic_json(STATE_FILE, state)


def run_queue(args: argparse.Namespace) -> int:
    if not WORKER.is_file() or not VALIDATOR.is_file():
        raise RuntimeError("Worker or strict validator is missing")
    python = args.python.resolve()
    if not python.is_file():
        raise RuntimeError(f"Python executable is missing: {python}")

    protocol_hash, manifest = verify_frozen_control()
    items = queue_items(manifest)
    if len(items) != TARGET_COUNT or len(set(items)) != TARGET_COUNT:
        raise RuntimeError("Frozen queue does not contain exactly 380 unique jobs")

    state: dict[str, Any] = {
        "schema_version": 1,
        "queue": "PROJECT9_SEDR_LOCKED_TECHNICAL_EXECUTION",
        "created_utc": utc_now(),
        "updated_utc": utc_now(),
        "status": "AUDITING",
        "protocol_hash": protocol_hash,
        "input_manifest_sha256": sha256_file(INPUT_MANIFEST),
        "target_count": TARGET_COUNT,
        "worker_processes": 1,
        "gpu": args.gpu,
        "cpu_threads_per_process": 4,
        "max_attempts_per_job": MAX_ATTEMPTS,
        "completed_valid": [],
        "pending": [],
        "failed_terminal": [],
        "active_job": None,
        "scientific_unblinding": False,
    }

    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_ROOT.mkdir(parents=True, exist_ok=True)
    ATTEMPT_ROOT.mkdir(parents=True, exist_ok=True)

    pending: list[tuple[str, int]] = []
    for dataset, seed in items:
        final_dir = checkpoint_dir(dataset, seed)
        identity = f"{dataset}/seed{seed:02d}"
        if final_dir.exists():
            audit_stem = LOG_ROOT / "resume_validation" / dataset / f"seed{seed:02d}"
            if strict_validator_pass(python, final_dir, audit_stem):
                state["completed_valid"].append(identity)
                continue
            raise RuntimeError(
                "Existing final checkpoint is not strict-validator PASS; "
                f"preserved without overwrite: {final_dir}"
            )
        pending.append((dataset, seed))
    state["pending"] = [f"{d}/seed{s:02d}" for d, s in pending]
    write_state(state, "READY")

    if not args.execute:
        print(json.dumps({
            "status": "READY_NOT_EXECUTED",
            "protocol_hash": protocol_hash,
            "completed_valid": len(state["completed_valid"]),
            "pending": len(pending),
            "target": TARGET_COUNT,
            "worker_processes": 1,
            "cpu_threads_per_process": 4,
        }, indent=2))
        return 0

    token = acquire_queue_lock()
    try:
        write_state(state, "RUNNING")
        for dataset, seed in pending:
            # Reverify the immutable controls immediately before every launch.
            current_hash, _ = verify_frozen_control()
            if current_hash != protocol_hash:
                raise RuntimeError("Protocol changed while the queue was running")

            identity = f"{dataset}/seed{seed:02d}"
            prior_attempts = count_prior_attempts(dataset, seed)
            if prior_attempts >= MAX_ATTEMPTS:
                state["failed_terminal"].append({
                    "job": identity,
                    "reason": "maximum crash attempts already exhausted",
                    "attempts": prior_attempts,
                })
                write_state(state, "STOPPED_TECHNICAL_FAILURE")
                return 1

            completed = False
            for attempt in range(prior_attempts + 1, MAX_ATTEMPTS + 1):
                staging = attempt_dir(dataset, seed, attempt)
                if staging.exists():
                    raise RuntimeError(
                        f"Attempt directory already exists and is preserved: {staging}"
                    )
                log_dir = LOG_ROOT / "runs" / dataset
                log_dir.mkdir(parents=True, exist_ok=True)
                stem = log_dir / f"seed{seed:02d}.attempt{attempt:02d}"
                stdout_path = stem.with_suffix(".stdout.log")
                stderr_path = stem.with_suffix(".stderr.log")
                command = worker_command(
                    python, dataset, seed, staging, protocol_hash,
                    args.save_embeddings,
                )
                active = {
                    "job": identity,
                    "dataset": dataset,
                    "seed": seed,
                    "attempt": attempt,
                    "started_utc": utc_now(),
                    "output_dir": str(staging),
                    "stdout_log": str(stdout_path),
                    "stderr_log": str(stderr_path),
                }
                write_state(state, "RUNNING", active)
                with stdout_path.open(
                    "w", encoding="utf-8", newline="\n"
                ) as stdout, stderr_path.open(
                    "w", encoding="utf-8", newline="\n"
                ) as stderr:
                    process = subprocess.Popen(
                        command,
                        cwd=ROOT,
                        env=child_environment(seed, args.gpu),
                        stdout=stdout,
                        stderr=stderr,
                        creationflags=(
                            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                        ),
                    )
                    active["pid"] = process.pid
                    write_state(state, "RUNNING", active)
                    return_code = process.wait()

                active["return_code"] = return_code
                active["finished_utc"] = utc_now()
                write_state(state, "VALIDATING", active)
                if return_code != 0:
                    # Only a crashed/failed child is eligible for the one retry.
                    if attempt < MAX_ATTEMPTS:
                        write_state(state, "RETRYING_AFTER_PROCESS_FAILURE")
                        continue
                    state["failed_terminal"].append({
                        "job": identity,
                        "reason": "worker process failed twice",
                        "attempts": attempt,
                        "last_return_code": return_code,
                    })
                    write_state(state, "STOPPED_TECHNICAL_FAILURE")
                    return 1

                validation_stem = (
                    LOG_ROOT / "post_run_validation" / dataset
                    / f"seed{seed:02d}.attempt{attempt:02d}"
                )
                if not strict_validator_pass(python, staging, validation_stem):
                    # A normally returning but invalid artifact is not rerun.
                    state["failed_terminal"].append({
                        "job": identity,
                        "reason": "strict technical validation failed",
                        "attempts": attempt,
                    })
                    write_state(state, "STOPPED_TECHNICAL_FAILURE")
                    return 1

                final_dir = checkpoint_dir(dataset, seed)
                final_dir.parent.mkdir(parents=True, exist_ok=True)
                if final_dir.exists():
                    raise RuntimeError(
                        f"Final path appeared during execution: {final_dir}"
                    )
                os.replace(staging, final_dir)
                final_validation_stem = (
                    LOG_ROOT / "final_validation" / dataset / f"seed{seed:02d}"
                )
                if not strict_validator_pass(
                    python, final_dir, final_validation_stem
                ):
                    raise RuntimeError(
                        f"Promoted artifact failed final validation: {final_dir}"
                    )
                completed = True
                state["completed_valid"].append(identity)
                state["pending"] = [
                    value for value in state["pending"] if value != identity
                ]
                write_state(state, "RUNNING")
                break

            if not completed:
                raise RuntimeError(f"Job did not complete: {identity}")

        if len(state["completed_valid"]) != TARGET_COUNT:
            raise RuntimeError(
                f"Queue ended with {len(state['completed_valid'])}/{TARGET_COUNT}"
            )
        write_state(state, "TECHNICAL_CHECKPOINTS_380_OF_380")
        print("TECHNICAL_CHECKPOINTS_380_OF_380")
        return 0
    except KeyboardInterrupt:
        write_state(state, "INTERRUPTED")
        raise
    except Exception as error:
        state["scheduler_error"] = {
            "type": type(error).__name__,
            "message": str(error),
            "timestamp_utc": utc_now(),
        }
        write_state(state, "STOPPED_TECHNICAL_FAILURE")
        raise
    finally:
        release_queue_lock(token)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Serial outcome-blind SEDR technical checkpoint queue"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Launch the locked queue; omission performs a read-only readiness audit",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python executable from the frozen SEDR environment",
    )
    parser.add_argument(
        "--gpu",
        default="0",
        help="Single CUDA_VISIBLE_DEVICES entry (default: 0)",
    )
    parser.add_argument(
        "--save-embeddings",
        action="store_true",
        help="Persist optional compressed embeddings for final checkpoints",
    )
    args = parser.parse_args()
    try:
        return run_queue(args)
    except Exception as error:
        print(
            json.dumps({
                "status": "QUEUE_NOT_COMPLETED",
                "error_type": type(error).__name__,
                "error": str(error),
            }, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
