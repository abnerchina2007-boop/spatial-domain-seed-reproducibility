"""Unattended scheduler for the already locked Project 9 SEDR expansion.

This file performs no scientific calculation itself.  It polls only the
outcome-blind queue state and checkpoint count.  After (and only after) the
locked queue reports a clean 380/380 completion, it invokes the independently
fail-closed stages in the prespecified order.  On a later process restart it
validates and skips a completed prefix.  Partial, stale, or inconsistent output
is preserved and causes an immediate stop rather than an overwrite or repair.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
EXPANSION = ROOT / "outputs" / "PROJECT9_SEDR_EXPANSION"
QUEUE_STATE = EXPANSION / "queue_state.json"
CHECKPOINTS = EXPANSION / "checkpoints"
STATE = EXPANSION / "full_pipeline_state.json"
PROCESS_LOCK = EXPANSION / ".full_pipeline.process.lock"
LOG_ROOT = EXPANSION / "logs" / "full_pipeline"
PYTHON = WORK / ".venv" / "Scripts" / "python.exe"
EXPECTED = 380
POLL_SECONDS = 20
RANK_VALIDATION_CHUNK_SIZE = 100_000

GATE_TRANSACTION_DIR = EXPANSION / ".gate_publish_transaction"
GATE_FILES = (
    EXPANSION / "FINAL_380_CHECKPOINT_MANIFEST.csv",
    EXPANSION / "FINAL_380_TECHNICAL_VALIDATION.json",
    EXPANSION / "technical_metadata_preflight.csv",
    EXPANSION / "SCIENTIFIC_GATE_OPEN.json",
)
TECHNICAL_METADATA = EXPANSION / "technical_metadata.csv"
CORE_TRANSACTION_DIR = EXPANSION / ".core_scientific_publish_transaction"
CORE_RECEIPT = EXPANSION / ".core_scientific_publish_receipt.json"
CORE_RESULT_FILES = (
    EXPANSION / "seed_level_accuracy.csv",
    EXPANSION / "pairwise_partition_reproducibility.csv",
    EXPANSION / "iso_accuracy_results.csv",
    EXPANSION / "consensus_results.csv",
    EXPANSION / "sedr_unit_summary.csv",
)
CORE_FILES = CORE_RESULT_FILES + (CORE_RECEIPT,)
MARKER_DIR = EXPANSION / "candidate_integration" / "sedr_markers"
MARKER_FILES = (
    MARKER_DIR / "marker_reproducibility_all_pairs.csv",
    MARKER_DIR / "within_unit_marker_correlations.csv",
    MARKER_DIR / "marker_tertile_summary.csv",
    MARKER_DIR / "paired_high_vs_low_test.json",
    MARKER_DIR / "SEDR_MARKER_ANALYSIS_VALIDATION.json",
)
FIVE_DIR = EXPANSION / "candidate_integration" / "five_method"
FIVE_FILES = (
    FIVE_DIR / "integrated_seed_level_accuracy.csv",
    FIVE_DIR / "five_method_rank_distributions.csv",
    FIVE_DIR / "five_method_rank_summary.csv",
    FIVE_DIR / "five_method_winner_probabilities.csv",
    FIVE_DIR / "five_method_pairwise_superiority.csv",
    FIVE_DIR / "five_method_dataset_uncertainty.csv",
    FIVE_DIR / "four_method_reconciliation.json",
    FIVE_DIR / "analysis_manifest.json",
)
ALL_DIR = EXPANSION / "candidate_integration" / "all_outputs"
ALL_FILES = (
    ALL_DIR / "integrated_seed_level_accuracy.csv",
    ALL_DIR / "integrated_pairwise_reproducibility.csv",
    ALL_DIR / "integrated_iso_accuracy.csv",
    ALL_DIR / "integrated_method_dataset_summary.csv",
    ALL_DIR / "integrated_consensus_summary.csv",
    ALL_DIR / "integrated_marker_unit_summary.csv",
    ALL_DIR / "integrated_marker_tertile_summary.csv",
    ALL_DIR / "integrated_marker_reproducibility_all_pairs.csv",
    ALL_DIR / "integrated_headline_summary.json",
    ALL_DIR / "INTEGRATION_MANIFEST.json",
)
REPORT_FILES = (
    EXPANSION / "FINAL_SEDR_REPORT.md",
    EXPANSION / "SEDR_GENERALIZATION_ASSESSMENT.md",
    EXPANSION / "FIVE_METHOD_INTEGRATION_SUMMARY.md",
    EXPANSION / "MANUSCRIPT_IMPLICATIONS_ONLY.md",
    EXPANSION / "VALIDATION_REPORT.md",
    EXPANSION / "FINAL_SUMMARY.json",
)
FINAL_ALIASES = {
    EXPANSION / "marker_reproducibility_all_pairs.csv": MARKER_FILES[0],
    EXPANSION / "within_unit_marker_correlations.csv": MARKER_FILES[1],
    EXPANSION / "marker_tertile_summary.csv": MARKER_FILES[2],
    EXPANSION / "integrated_seed_level_accuracy.csv": ALL_FILES[0],
    EXPANSION / "integrated_pairwise_reproducibility.csv": ALL_FILES[1],
    EXPANSION / "integrated_iso_accuracy.csv": ALL_FILES[2],
    EXPANSION / "integrated_marker_unit_summary.csv": ALL_FILES[5],
    EXPANSION / "integrated_consensus_summary.csv": ALL_FILES[4],
    EXPANSION / "five_method_winner_probabilities.csv": FIVE_FILES[3],
    EXPANSION / "five_method_rank_distributions.csv": FIVE_FILES[1],
    EXPANSION / "five_method_pairwise_superiority.csv": FIVE_FILES[4],
}

STAGES = (
    ("open_scientific_gate", (WORK / "open_scientific_gate.py",)),
    ("core_scientific_analysis", (WORK / "analyze_scientific.py", "--execute")),
    ("sedr_marker_analysis", (WORK / "analyze_sedr_markers.py",)),
    ("exact_five_method_ranking", (WORK / "analyze_five_method.py",)),
    ("complete_eight_table_integration", (WORK / "integrate_all_outputs.py",)),
    (
        "final_validation_and_reports",
        (WORK / "finalize_validation_reports.py", "--execute"),
    ),
)

STAGE_ARTIFACTS = {
    "open_scientific_gate": GATE_FILES,
    "core_scientific_analysis": CORE_FILES,
    "sedr_marker_analysis": MARKER_FILES,
    "exact_five_method_ranking": FIVE_FILES,
    "complete_eight_table_integration": ALL_FILES,
    "final_validation_and_reports": REPORT_FILES + tuple(FINAL_ALIASES),
}
STAGE_CONTAINERS = {
    "sedr_marker_analysis": (MARKER_DIR,),
    "exact_five_method_ranking": (FIVE_DIR,),
    "complete_eight_table_integration": (ALL_DIR,),
}
STAGE_RECOVERY_TRANSACTIONS = {
    "open_scientific_gate": GATE_TRANSACTION_DIR,
    "core_scientific_analysis": CORE_TRANSACTION_DIR,
}


class PipelineAlreadyRunning(RuntimeError):
    """Another process owns the post-gate orchestration lock."""


class PipelineProcessLock:
    """Cross-platform nonblocking OS lock held for the process lifetime.

    The one-byte control file is intentionally persistent.  Lock ownership is
    maintained by the operating system and is released automatically after an
    abnormal process exit, avoiding stale-PID heuristics and unlink races.
    """

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.handle: Any | None = None

    def acquire(self) -> "PipelineProcessLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            raise PipelineAlreadyRunning(
                "Another locked post-gate pipeline instance is active; "
                f"control lock: {self.path}"
            ) from error
        self.handle = handle
        return self

    def release(self) -> None:
        handle, self.handle = self.handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> "PipelineProcessLock":
        return self.acquire()

    def __exit__(self, *_exc: object) -> None:
        self.release()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load read-only validator module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def temporary_residue(name: str) -> list[Path]:
    """Return interrupted atomic/staging artifacts for one stage."""

    paths = STAGE_ARTIFACTS[name]
    residue: list[Path] = []
    for path in paths:
        residue.extend(path.parent.glob(path.name + ".*.tmp"))
        candidate = path.with_suffix(path.suffix + ".tmp")
        if candidate.exists():
            residue.append(candidate)
    if name == "exact_five_method_ranking":
        residue.extend(FIVE_DIR.parent.glob(FIVE_DIR.name + ".tmp-*"))
    elif name == "complete_eight_table_integration":
        residue.extend(ALL_DIR.parent.glob(ALL_DIR.name + ".tmp-*"))
    return sorted(set(path.resolve() for path in residue))


def recovery_transaction(name: str) -> Path | None:
    path = STAGE_RECOVERY_TRANSACTIONS.get(name)
    return path.resolve() if path is not None and path.exists() else None


def classify_artifact_set(
    name: str,
    required: tuple[Path, ...],
    containers: tuple[Path, ...] = (),
    residue: tuple[Path, ...] = (),
    recoverable_transaction: Path | None = None,
) -> str:
    """Classify an output set without opening scientific result content.

    A partially present set is intentionally not repairable here: its producer
    may have stopped between atomic file installs.  Retaining it and stopping
    is safer than guessing which files are authoritative.
    """

    leftovers = [path for path in residue if path.exists()]
    if leftovers:
        raise RuntimeError(
            f"Interrupted temporary/staging artifact for {name}: "
            + ", ".join(str(path) for path in leftovers)
        )
    present = [path for path in required if path.is_file()]
    malformed = [path for path in required if path.exists() and not path.is_file()]
    if malformed:
        raise RuntimeError(
            f"Non-file artifact at required path for {name}: "
            + ", ".join(str(path) for path in malformed)
        )
    if recoverable_transaction is not None:
        # The producer owns this durable journal and is the only component
        # authorized to roll it back or finish its hash-bound promotion.  Any
        # unrelated residue/path-type conflict above still fails closed.
        return "RECOVERABLE"
    if not present:
        nonempty = [
            path for path in containers
            if path.exists() and (not path.is_dir() or any(path.iterdir()))
        ]
        if nonempty:
            raise RuntimeError(
                f"Output container exists without a complete set for {name}: "
                + ", ".join(str(path) for path in nonempty)
            )
        return "ABSENT"
    if len(present) != len(required):
        missing = [path for path in required if not path.is_file()]
        raise RuntimeError(
            f"Partial output set for {name}; preserving it and stopping. "
            "Missing: " + ", ".join(str(path) for path in missing)
        )
    required_resolved = {path.resolve() for path in required}
    unexpected: list[Path] = []
    for container in containers:
        if container.is_dir():
            unexpected.extend(
                child.resolve() for child in container.iterdir()
                if child.resolve() not in required_resolved
            )
    if unexpected:
        raise RuntimeError(
            f"Unexpected artifact in completed output set for {name}: "
            + ", ".join(str(path) for path in sorted(unexpected))
        )
    return "COMPLETE"


def inspect_pipeline_artifacts(
    stages: tuple[tuple[str, tuple[Any, ...]], ...] | None = None,
) -> dict[str, str]:
    """Require completed stages to form one uninterrupted prefix."""

    states: dict[str, str] = {}
    first_absent: str | None = None
    for name, _arguments in STAGES if stages is None else stages:
        state = classify_artifact_set(
            name,
            STAGE_ARTIFACTS[name],
            STAGE_CONTAINERS.get(name, ()),
            tuple(temporary_residue(name)),
            recovery_transaction(name),
        )
        states[name] = state
        if state in {"ABSENT", "RECOVERABLE"}:
            first_absent = first_absent or name
        elif first_absent is not None:
            # A recoverable producer transaction may already have installed
            # its complete stage.  Downstream artifacts still cannot be
            # trusted/skipped until that transaction is recovered and the
            # pipeline is inspected again.
            predecessor_state = states[first_absent]
            raise RuntimeError(
                f"Completed {name} exists after absent predecessor "
                f"{first_absent} ({predecessor_state}); refusing out-of-order resume"
            )
    return states


def validate_gate_read_only() -> None:
    """Use the core analyzer's strict outcome-blind 380/gate audit."""

    core = load_module(
        "sedr_resume_core_gate_validator", WORK / "analyze_scientific.py"
    )
    audit = core.verify_gate_and_fresh_scan()
    if len(audit.get("checkpoints", ())) != EXPECTED:
        raise RuntimeError("Read-only gate validation did not return exactly 380 runs")
    gate = audit["gate"]
    if gate.get("technical_metadata_file") != TECHNICAL_METADATA.name:
        raise RuntimeError("Gate technical-metadata path is not canonical")
    if (
        not TECHNICAL_METADATA.is_file()
        or sha256_file(TECHNICAL_METADATA)
        != str(gate.get("technical_metadata_sha256", "")).upper()
    ):
        raise RuntimeError("Gate technical-metadata hash failed")
    report = load_json(GATE_FILES[1])
    if (
        report.get("status") != "PASS"
        or report.get("checkpoint_count") != EXPECTED
        or report.get("pass_count") != EXPECTED
        or report.get("fail_count") != 0
        or report.get("scientific_metrics_computed") is not False
        or report.get("reference_annotations_read") is not False
        or str(report.get("protocol_hash", "")).upper() != audit["protocol_hash"]
        or str(report.get("input_manifest_sha256", "")).upper()
        != audit["input_manifest_hash"]
        or str(report.get("checkpoint_manifest_sha256", "")).upper()
        != audit["checkpoint_manifest_hash"]
    ):
        raise RuntimeError("Gate technical-validation report contract failed")
    if GATE_FILES[2].stat().st_size == 0:
        raise RuntimeError("Preserved preflight technical metadata is empty")


def validate_core_read_only() -> None:
    """Validate the complete core set using the finalizer's strongest checks."""

    finalizer = load_module(
        "sedr_resume_core_output_validator", WORK / "finalize_validation_reports.py"
    )
    audit = finalizer.fresh_gate_audit()
    import numpy as np
    import pandas as pd

    _core, validation = finalizer.validate_core_outputs(audit, pd, np)
    if validation.get("status") != "PASS":
        raise RuntimeError("Read-only core-output validation did not PASS")
    receipt = load_json(CORE_RECEIPT)
    entries = receipt.get("entries") if isinstance(receipt, dict) else None
    if (
        receipt.get("schema_version") != 1
        or receipt.get("kind")
        != "PROJECT9_SEDR_CORE_SCIENTIFIC_PUBLICATION"
        or not isinstance(entries, list)
        or len(entries) != len(CORE_RESULT_FILES)
    ):
        raise RuntimeError("Core publication receipt contract failed")
    expected = {path.resolve() for path in CORE_RESULT_FILES}
    observed: set[Path] = set()
    for entry in entries:
        target = Path(str(entry.get("target", ""))).resolve()
        planned = str(entry.get("planned_sha256", "")).upper()
        if target not in expected or target in observed or sha256_file(target) != planned:
            raise RuntimeError(f"Core publication receipt hash failed: {target}")
        observed.add(target)
    if observed != expected:
        raise RuntimeError("Core publication receipt target set failed")


def validate_marker_read_only() -> None:
    """Validate markers plus their exact dependency on the core results."""

    finalizer = load_module(
        "sedr_resume_marker_validator", WORK / "finalize_validation_reports.py"
    )
    audit = finalizer.fresh_gate_audit()
    import numpy as np
    import pandas as pd
    from scipy import stats

    core, _ = finalizer.validate_core_outputs(audit, pd, np)
    _marker, validation = finalizer.validate_marker_outputs(
        audit, core, pd, np, stats
    )
    if validation.get("status") != "PASS":
        raise RuntimeError("Read-only marker-output validation did not PASS")


def validate_five_method_read_only() -> None:
    """Run the exact independent 20^5 validation before skipping ranking."""

    finalizer = load_module(
        "sedr_resume_five_method_validator", WORK / "finalize_validation_reports.py"
    )
    audit = finalizer.fresh_gate_audit()
    import numpy as np
    import pandas as pd

    core, _ = finalizer.validate_core_outputs(audit, pd, np)
    _five, validation = finalizer.validate_five_method_outputs(
        audit, core, pd, np, RANK_VALIDATION_CHUNK_SIZE
    )
    if validation.get("status") != "PASS":
        raise RuntimeError("Read-only five-method validation did not PASS")


def validate_all_outputs_read_only() -> None:
    """Validate all eight integrations and their immutable back-filters."""

    finalizer = load_module(
        "sedr_resume_all_output_validator", WORK / "finalize_validation_reports.py"
    )
    audit = finalizer.fresh_gate_audit()
    import numpy as np
    import pandas as pd
    from scipy import stats

    core, _ = finalizer.validate_core_outputs(audit, pd, np)
    marker, _ = finalizer.validate_marker_outputs(audit, core, pd, np, stats)
    _integrated, validation = finalizer.validate_all_outputs(
        audit, core, marker, pd, np
    )
    if validation.get("status") != "PASS":
        raise RuntimeError("Read-only complete-integration validation did not PASS")


def validate_final_read_only() -> None:
    """Bind final reports to fully revalidated sources without publishing."""

    summary = load_json(EXPANSION / "FINAL_SUMMARY.json")
    if (
        not isinstance(summary, dict)
        or summary.get("status") != "PASS"
        or summary.get("completion") != "380/380"
        or summary.get("decision") != "LOCK_ADD_SEDR"
    ):
        raise RuntimeError("Final completion record is not a locked 380/380 PASS")
    declared_hashes = summary.get("validation", {}).get("artifact_sha256")
    if not isinstance(declared_hashes, dict):
        raise RuntimeError("Final completion record lacks artifact hashes")
    # The finalizer hashes scientific/report inputs; the hidden core
    # publication receipt is validated separately above and is not one of its
    # declared scientific artifacts.
    source_paths = CORE_RESULT_FILES + MARKER_FILES + FIVE_FILES + ALL_FILES
    expected_relatives = {
        path.relative_to(ROOT).as_posix() for path in source_paths
    } | {
        path.relative_to(ROOT).as_posix() for path in FINAL_ALIASES
    }
    if set(declared_hashes) != expected_relatives:
        raise RuntimeError("Final completion artifact-hash set is incomplete or extra")
    for relative, declared in declared_hashes.items():
        artifact = (ROOT / relative).resolve()
        try:
            artifact.relative_to(ROOT.resolve())
        except ValueError as error:
            raise RuntimeError(
                f"Final completion artifact escapes the workspace: {relative}"
            ) from error
        if not artifact.is_file() or sha256_file(artifact) != str(declared).upper():
            raise RuntimeError(f"Final completion artifact hash failed: {relative}")
    for destination, source in FINAL_ALIASES.items():
        if sha256_file(destination) != sha256_file(source):
            raise RuntimeError(f"Final delivery alias differs from source: {destination}")
    finalizer = load_module(
        "sedr_resume_final_validator", WORK / "finalize_validation_reports.py"
    )
    generated = summary.get("generated_utc")
    if not isinstance(generated, str) or not generated:
        raise RuntimeError("Final completion record lacks its generation timestamp")
    captured_reports: dict[Path, bytes] = {}
    original_render = finalizer.render_reports

    def capture_render(*args: Any, **kwargs: Any) -> dict[Path, bytes]:
        payloads = original_render(*args, **kwargs)
        captured_reports.update(payloads)
        return payloads

    # Recompute the complete final validation without writes, but use the
    # original transaction timestamp so every saved report can be compared
    # byte-for-byte with the independently reconstructed payload.
    finalizer.utc_now = lambda: generated
    finalizer.render_reports = capture_render
    result = finalizer.run_finalization(False, RANK_VALIDATION_CHUNK_SIZE)
    if (
        result.get("status") != "FINAL_VALIDATION_PASS"
        or result.get("reports_written") is not False
    ):
        raise RuntimeError("Read-only final validation did not PASS without writes")
    if set(captured_reports) != set(REPORT_FILES):
        raise RuntimeError("Read-only final validation reconstructed a wrong report set")
    for path, expected in captured_reports.items():
        if path.read_bytes() != expected:
            raise RuntimeError(f"Saved final report differs from reconstruction: {path}")


STAGE_VALIDATORS = {
    "open_scientific_gate": validate_gate_read_only,
    "core_scientific_analysis": validate_core_read_only,
    "sedr_marker_analysis": validate_marker_read_only,
    "exact_five_method_ranking": validate_five_method_read_only,
    "complete_eight_table_integration": validate_all_outputs_read_only,
    "final_validation_and_reports": validate_final_read_only,
}


def validate_completed_stage(name: str) -> None:
    """Validate an already complete stage; this function never writes."""

    STAGE_VALIDATORS[name]()


def require_stage_complete(name: str) -> None:
    """Confirm a just-run producer installed its entire atomic output set.

    The producer's own exit status already certifies its calculations.  The
    deeper independent validators are reserved for artifacts inherited by a
    restarted process, where provenance must be re-established before skip.
    """

    state = classify_artifact_set(
        name,
        STAGE_ARTIFACTS[name],
        STAGE_CONTAINERS.get(name, ()),
        tuple(temporary_residue(name)),
        recovery_transaction(name),
    )
    if state != "COMPLETE":
        raise RuntimeError(
            f"Stage {name} exited successfully but its complete output set is absent"
        )


def atomic_state(payload: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, STATE)


def checkpoint_count() -> int:
    return sum(1 for _ in CHECKPOINTS.rglob("checkpoint.json"))


def wait_for_queue() -> dict[str, Any]:
    while True:
        if not QUEUE_STATE.is_file():
            atomic_state({
                "status": "WAITING_FOR_LOCKED_QUEUE_STATE",
                "updated_utc": utc_now(),
            })
            time.sleep(POLL_SECONDS)
            continue
        queue = load_json(QUEUE_STATE)
        completed = len(queue.get("completed_valid", []))
        pending = len(queue.get("pending", []))
        failures = len(queue.get("failed_terminal", []))
        state = str(queue.get("status", ""))
        atomic_state({
            "status": "WAITING_FOR_380_TECHNICAL_CHECKPOINTS",
            "queue_status": state,
            "completed_valid": completed,
            "pending": pending,
            "failed_terminal": failures,
            "active_job": queue.get("active_job"),
            "updated_utc": utc_now(),
        })
        if failures:
            raise RuntimeError(
                f"Locked queue has {failures} terminal failure(s); refusing gate"
            )
        if state in {"FAILED", "STOPPED", "BLOCKED"}:
            raise RuntimeError(f"Locked queue stopped with status {state}")
        if state in {
            "COMPLETE", "COMPLETED", "PASS",
            "TECHNICAL_CHECKPOINTS_380_OF_380",
        }:
            live_count = checkpoint_count()
            if completed != EXPECTED or pending != 0 or live_count != EXPECTED:
                raise RuntimeError(
                    "Queue completion state is not an exact clean 380/380: "
                    f"completed={completed}, pending={pending}, files={live_count}"
                )
            return queue
        time.sleep(POLL_SECONDS)


def run_stage(name: str, arguments: tuple[Any, ...], completed: list[str]) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    stdout_path = LOG_ROOT / f"{name}.stdout.log"
    stderr_path = LOG_ROOT / f"{name}.stderr.log"
    command = [str(PYTHON), *(str(value) for value in arguments)]
    atomic_state({
        "status": "RUNNING_POST_GATE_STAGE",
        "stage": name,
        "completed_stages": completed,
        "command": command,
        "started_utc": utc_now(),
        "scientific_gate_required": name != "open_scientific_gate",
    })
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        result = subprocess.run(
            command,
            cwd=ROOT,
            stdout=stdout,
            stderr=stderr,
            check=False,
            env={
                **os.environ,
                "OMP_NUM_THREADS": "4",
                "MKL_NUM_THREADS": "4",
                "OPENBLAS_NUM_THREADS": "4",
                "NUMEXPR_NUM_THREADS": "4",
            },
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"Post-gate stage {name} failed with exit code {result.returncode}; "
            f"see {stderr_path}"
        )
    require_stage_complete(name)
    completed.append(name)


def run_pipeline() -> int:
    completed: list[str] = []
    try:
        if not PYTHON.is_file():
            raise FileNotFoundError(f"Locked SEDR environment is missing: {PYTHON}")
        wait_for_queue()
        artifact_states = inspect_pipeline_artifacts()
        for name, arguments in STAGES:
            if artifact_states[name] == "COMPLETE":
                atomic_state({
                    "status": "VALIDATING_COMPLETED_STAGE_FOR_RESUME",
                    "stage": name,
                    "completed_stages": completed,
                    "validation_mode": "read_only",
                    "updated_utc": utc_now(),
                })
                validate_completed_stage(name)
                completed.append(name)
                continue
            if artifact_states[name] == "RECOVERABLE":
                atomic_state({
                    "status": "RECOVERING_INTERRUPTED_STAGE_TRANSACTION",
                    "stage": name,
                    "completed_stages": completed,
                    "transaction": str(STAGE_RECOVERY_TRANSACTIONS[name]),
                    "recovery_owner": "stage_producer",
                    "updated_utc": utc_now(),
                })
            run_stage(name, arguments, completed)
        atomic_state({
            "status": "PIPELINE_COMPLETE",
            "completed_stages": completed,
            "completed_utc": utc_now(),
            "technical_checkpoints": EXPECTED,
        })
        print("PROJECT9_SEDR_LOCKED_PIPELINE_COMPLETE", flush=True)
        return 0
    except Exception as error:
        atomic_state({
            "status": "PIPELINE_STOPPED",
            "completed_stages": completed,
            "error_type": type(error).__name__,
            "error": str(error),
            "stopped_utc": utc_now(),
        })
        print(f"PROJECT9_SEDR_PIPELINE_STOPPED: {error}", file=sys.stderr, flush=True)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resume the locked Project 9 SEDR post-gate pipeline. The command "
            "takes no execution flags; invoking it starts/resumes the pipeline."
        )
    )
    parser.parse_args(argv)
    try:
        with PipelineProcessLock(PROCESS_LOCK):
            return run_pipeline()
    except PipelineAlreadyRunning as error:
        print(f"PROJECT9_SEDR_PIPELINE_ALREADY_RUNNING: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
