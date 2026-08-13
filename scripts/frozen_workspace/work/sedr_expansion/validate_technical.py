"""Strict, outcome-blind validation of SEDR technical checkpoints.

This validator intentionally does not import or calculate any scientific
accuracy, partition-comparison, ranking, marker, or consensus metric. It reads
only the label-blind technical-input manifest, the frozen protocol/hash, and
technical checkpoint artifacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
EXPANSION = ROOT / "outputs" / "PROJECT9_SEDR_EXPANSION"
DEFAULT_INPUT_MANIFEST = (
    EXPANSION / "technical_inputs" / "TECHNICAL_INPUT_MANIFEST.json"
)
DEFAULT_PROTOCOL = EXPANSION / "SEDR_FROZEN_PROTOCOL.md"
DEFAULT_PROTOCOL_HASH_FILE = EXPANSION / "SEDR_FROZEN_PROTOCOL.sha256"
DEFAULT_CHECKPOINT_ROOT = EXPANSION / "Technical" / "checkpoints"

SCHEMA_VERSION = 1
VALID_STATUS = "VALID_TECHNICAL_CHECKPOINT"
REQUIRED_TOP_KEYS = {
    "schema_version",
    "status",
    "mode",
    "dataset",
    "seed",
    "requested_k",
    "observed_k",
    "protocol_hash",
    "input",
    "implementation",
    "parameters",
    "preprocessing",
    "graph",
    "training",
    "final_readout",
    "outputs",
    "runtime_seconds",
    "resources",
    "environment",
    "compatibility",
}
REQUIRED_INPUT_KEYS = {
    "technical_path",
    "bytes",
    "sha256",
    "obs_count",
    "var_count",
    "obs_order_sha256_newline_utf8",
}
REQUIRED_FINAL_READOUT_KEYS = {
    "labels_count",
    "labels_finite",
    "model",
    "calls",
    "requested_k",
    "observed_k",
}
REQUIRED_LABEL_OUTPUT_KEYS = {
    "labels_path",
    "labels_bytes",
    "labels_sha256",
}
REQUIRED_OUTPUT_KEYS = REQUIRED_LABEL_OUTPUT_KEYS | {
    "embedding_path",
    "embedding_bytes",
    "embedding_sha256",
    "embedding_shape",
    "embedding_finite",
}
REQUIRED_PARAMETER_KEYS = {
    "platform_regime",
    "graph_k",
    "requested_k",
    "target_sum",
    "pca_random_state",
    "pretraining_epochs",
    "dec_epochs",
    "internal_dec_k",
    "model_mode",
}
REQUIRED_PREPROCESSING_KEYS = {
    "retained_gene_count",
    "pca_dimension",
    "finite",
}
REQUIRED_GRAPH_KEYS = {"k", "edge_count", "isolates", "connected_components"}
REQUIRED_TRAINING_KEYS = {
    "completed",
    "pretraining_epochs_completed",
    "dec_epochs_completed",
    "embedding_shape",
    "embedding_finite",
}
HEX64 = re.compile(r"^[0-9A-Fa-f]{64}$")


class ValidationError(ValueError):
    """A technical checkpoint violates the frozen artifact contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def normalize_sha256(value: object, field: str) -> str:
    text = str(value).strip()
    if not HEX64.fullmatch(text):
        raise ValidationError(f"{field} is not a 64-character SHA-256")
    return text.upper()


def parse_protocol_hash(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig").strip()
    matches = re.findall(r"(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", text)
    if len(set(value.upper() for value in matches)) != 1:
        raise ValidationError(
            f"Protocol hash file must contain exactly one distinct SHA-256: {path}"
        )
    return matches[0].upper()


def load_protocol_hash(protocol: Path, hash_file: Path) -> str:
    if not protocol.is_file():
        raise ValidationError(f"Frozen protocol is missing: {protocol}")
    if not hash_file.is_file():
        raise ValidationError(f"Frozen protocol hash file is missing: {hash_file}")
    recorded = parse_protocol_hash(hash_file)
    actual = sha256_file(protocol)
    if actual != recorded:
        raise ValidationError(
            f"Frozen protocol hash mismatch: recorded={recorded}, actual={actual}"
        )
    return actual


def load_input_manifest(path: Path) -> tuple[dict[str, Any], str]:
    manifest = load_json(path)
    if not isinstance(manifest, dict):
        raise ValidationError("Technical input manifest is not a JSON object")
    if manifest.get("entry_count") != 19 or manifest.get("pass_count") != 19:
        raise ValidationError("Technical input manifest is not a 19/19 PASS manifest")
    firewall_flags = {
        "label_blind": True,
        "reference_annotation_values_read": False,
        "scientific_preprocessing_performed": False,
        "scientific_outcomes_computed_or_inspected": False,
    }
    for key, expected in firewall_flags.items():
        if manifest.get(key) is not expected:
            raise ValidationError(f"Technical input firewall flag failed: {key}")
    records = manifest.get("entries")
    if not isinstance(records, list) or len(records) != 19:
        raise ValidationError("Technical input manifest entries must contain 19 rows")
    by_dataset: dict[str, Any] = {}
    for record in records:
        dataset = record.get("dataset")
        if not isinstance(dataset, str) or not dataset or dataset in by_dataset:
            raise ValidationError("Invalid or duplicate dataset in input manifest")
        if record.get("status") != "PASS" or record.get("validation", {}).get("valid") is not True:
            raise ValidationError(f"Input manifest entry is not valid: {dataset}")
        by_dataset[dataset] = record
    return by_dataset, sha256_file(path)


def require_keys(value: Any, keys: set[str], location: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{location} must be a JSON object")
    missing = sorted(keys - set(value))
    if missing:
        raise ValidationError(f"{location} missing keys: {', '.join(missing)}")


def require_int(value: object, field: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise ValidationError(f"{field} must be >= {minimum}")
    return value


def require_finite_number(
    value: object, field: str, minimum: float | None = None
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValidationError(f"{field} must be finite")
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field} must be >= {minimum}")
    return number


def resolve_artifact_path(raw_path: object, checkpoint_dir: Path, field: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValidationError(f"{field} must be a non-empty path string")
    path = Path(raw_path)
    if not path.is_absolute():
        path = checkpoint_dir / path
    resolved = path.resolve()
    # Checkpoint artifacts must be colocated beneath their checkpoint directory.
    try:
        resolved.relative_to(checkpoint_dir.resolve())
    except ValueError as error:
        raise ValidationError(f"{field} escapes checkpoint directory: {resolved}") from error
    return resolved


def read_labels_csv(path: Path) -> tuple[list[str], list[int]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["observation_id", "cluster_label"]:
            raise ValidationError(
                f"labels.csv must have exactly observation_id,cluster_label: {path}"
            )
        observation_ids: list[str] = []
        labels: list[int] = []
        for line_number, row in enumerate(reader, start=2):
            observation_id = row.get("observation_id")
            raw_label = row.get("cluster_label")
            if observation_id is None or observation_id == "":
                raise ValidationError(f"Empty observation ID at {path}:{line_number}")
            if raw_label is None or raw_label.strip() == "":
                raise ValidationError(f"Empty cluster label at {path}:{line_number}")
            try:
                as_float = float(raw_label)
            except ValueError as error:
                raise ValidationError(
                    f"Unreadable cluster label at {path}:{line_number}"
                ) from error
            if not math.isfinite(as_float) or not as_float.is_integer():
                raise ValidationError(
                    f"Cluster label must be a finite integer at {path}:{line_number}"
                )
            observation_ids.append(observation_id)
            labels.append(int(as_float))
    if len(set(observation_ids)) != len(observation_ids):
        raise ValidationError(f"Duplicate observation IDs in {path}")
    return observation_ids, labels


def ordered_string_hash(values: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest().upper()


def validate_embedding(
    outputs: dict[str, Any], checkpoint_dir: Path, n_obs: int, mode: str
) -> dict[str, Any]:
    embedding_path_value = outputs.get("embedding_path")
    has_embedding = embedding_path_value not in (None, "")
    if not has_embedding:
        if mode.lower() == "smoke":
            raise ValidationError("Smoke checkpoint must contain embedding.npz")
        # Final-run embeddings are optional; absent metadata must be absent/null.
        for key in ("embedding_bytes", "embedding_sha256", "embedding_shape", "embedding_finite"):
            if outputs.get(key) is not None:
                raise ValidationError(f"{key} present while embedding_path is absent")
        return {"present": False}

    required = {
        "embedding_path",
        "embedding_bytes",
        "embedding_sha256",
        "embedding_shape",
        "embedding_finite",
    }
    require_keys(outputs, required, "checkpoint.outputs embedding metadata")
    path = resolve_artifact_path(embedding_path_value, checkpoint_dir, "outputs.embedding_path")
    if not path.is_file() or path.name != "embedding.npz":
        raise ValidationError(f"Embedding artifact missing or misnamed: {path}")
    expected_bytes = require_int(outputs["embedding_bytes"], "outputs.embedding_bytes", 1)
    if path.stat().st_size != expected_bytes:
        raise ValidationError("Embedding byte count mismatch")
    expected_hash = normalize_sha256(outputs["embedding_sha256"], "outputs.embedding_sha256")
    if sha256_file(path) != expected_hash:
        raise ValidationError("Embedding SHA-256 mismatch")
    with np.load(path, allow_pickle=False) as archive:
        if archive.files != ["embedding"]:
            raise ValidationError("embedding.npz must contain only the embedding key")
        embedding = np.asarray(archive["embedding"])
    if embedding.ndim != 2 or embedding.shape[0] != n_obs or embedding.shape[1] < 1:
        raise ValidationError(f"Invalid embedding shape: {embedding.shape}")
    if not np.issubdtype(embedding.dtype, np.number) or not np.isfinite(embedding).all():
        raise ValidationError("Embedding must be numeric and fully finite")
    declared_shape = outputs["embedding_shape"]
    if declared_shape != list(embedding.shape):
        raise ValidationError("Declared embedding shape does not match artifact")
    if outputs["embedding_finite"] is not True:
        raise ValidationError("outputs.embedding_finite must be true")
    return {
        "present": True,
        "path": str(path),
        "shape": list(embedding.shape),
        "sha256": expected_hash,
    }


def validate_checkpoint(
    checkpoint_json: Path,
    manifest_entries: dict[str, Any],
    protocol_hash: str,
) -> dict[str, Any]:
    checkpoint_json = checkpoint_json.resolve()
    checkpoint_dir = checkpoint_json.parent
    if checkpoint_json.name != "checkpoint.json":
        raise ValidationError(f"Checkpoint metadata must be named checkpoint.json: {checkpoint_json}")
    checkpoint = load_json(checkpoint_json)
    require_keys(checkpoint, REQUIRED_TOP_KEYS, "checkpoint")
    if checkpoint["schema_version"] != SCHEMA_VERSION:
        raise ValidationError("Unsupported checkpoint schema_version")
    if checkpoint["status"] != VALID_STATUS:
        raise ValidationError("Checkpoint status is not VALID_TECHNICAL_CHECKPOINT")

    dataset = checkpoint["dataset"]
    if not isinstance(dataset, str) or dataset not in manifest_entries:
        raise ValidationError(f"Unknown dataset: {dataset!r}")
    seed = require_int(checkpoint["seed"], "seed", 1)
    if seed > 20:
        raise ValidationError("Seed must be in the frozen set 1..20")
    requested_k = require_int(checkpoint["requested_k"], "requested_k", 1)
    observed_k = require_int(checkpoint["observed_k"], "observed_k", 1)
    mode = checkpoint["mode"]
    if mode not in {"smoke", "final"}:
        raise ValidationError("mode must be exactly smoke or final")
    if mode == "smoke":
        if checkpoint["protocol_hash"] != "PRELOCK_TECHNICAL_PREFLIGHT":
            raise ValidationError("Smoke checkpoint must use the pre-lock protocol sentinel")
        recorded_protocol = "PRELOCK_TECHNICAL_PREFLIGHT"
    else:
        recorded_protocol = normalize_sha256(checkpoint["protocol_hash"], "protocol_hash")
        if recorded_protocol != protocol_hash:
            raise ValidationError("Final checkpoint protocol hash does not match frozen protocol")

    manifest_record = manifest_entries[dataset]
    n_obs = require_int(manifest_record["obs_count"], "manifest.obs_count", 1)
    n_vars = require_int(manifest_record["var_count"], "manifest.var_count", 1)

    input_meta = checkpoint["input"]
    require_keys(input_meta, REQUIRED_INPUT_KEYS, "checkpoint.input")
    technical_path = Path(input_meta["technical_path"]).resolve()
    expected_technical_path = Path(manifest_record["technical_path"]).resolve()
    if technical_path != expected_technical_path:
        raise ValidationError("Checkpoint technical input path differs from manifest")
    if not technical_path.is_file():
        raise ValidationError(f"Technical input is missing: {technical_path}")
    if input_meta["bytes"] != manifest_record["technical_bytes"] or technical_path.stat().st_size != input_meta["bytes"]:
        raise ValidationError("Technical input byte count mismatch")
    input_hash = normalize_sha256(input_meta["sha256"], "input.sha256")
    if input_hash != manifest_record["technical_sha256"] or sha256_file(technical_path) != input_hash:
        raise ValidationError("Technical input SHA-256 mismatch")
    if input_meta["obs_count"] != n_obs or input_meta["var_count"] != n_vars:
        raise ValidationError("Technical input dimensions differ from manifest")
    obs_hash = normalize_sha256(
        input_meta["obs_order_sha256_newline_utf8"],
        "input.obs_order_sha256_newline_utf8",
    )
    if obs_hash != manifest_record["obs_order_sha256_newline_utf8"]:
        raise ValidationError("Technical input observation-order hash mismatch")

    outputs = checkpoint["outputs"]
    require_keys(outputs, REQUIRED_OUTPUT_KEYS, "checkpoint.outputs")
    labels_path = resolve_artifact_path(outputs["labels_path"], checkpoint_dir, "outputs.labels_path")
    if not labels_path.is_file() or labels_path.name != "labels.csv":
        raise ValidationError(f"Label artifact missing or misnamed: {labels_path}")
    label_bytes = require_int(outputs["labels_bytes"], "outputs.labels_bytes", 1)
    if labels_path.stat().st_size != label_bytes:
        raise ValidationError("labels.csv byte count mismatch")
    label_hash = normalize_sha256(outputs["labels_sha256"], "outputs.labels_sha256")
    if sha256_file(labels_path) != label_hash:
        raise ValidationError("labels.csv SHA-256 mismatch")
    observation_ids, labels = read_labels_csv(labels_path)
    if len(labels) != n_obs or ordered_string_hash(observation_ids) != obs_hash:
        raise ValidationError("labels.csv does not contain one label in exact frozen observation order")
    artifact_observed_k = len(set(labels))
    if artifact_observed_k != observed_k:
        raise ValidationError("observed_k does not equal the distinct label count")

    final_readout = checkpoint["final_readout"]
    require_keys(final_readout, REQUIRED_FINAL_READOUT_KEYS, "checkpoint.final_readout")
    if final_readout["labels_count"] != n_obs:
        raise ValidationError("final_readout.labels_count mismatch")
    if final_readout["labels_finite"] is not True:
        raise ValidationError("Final label technical checks must be true")
    if not isinstance(final_readout["model"], str) or not final_readout["model"].strip():
        raise ValidationError("final_readout.model is missing")
    if final_readout["calls"] != 1:
        raise ValidationError("Exactly one final clustering call is permitted")

    training = checkpoint["training"]
    require_keys(training, REQUIRED_TRAINING_KEYS, "checkpoint.training")
    if training.get("completed") is not True:
        raise ValidationError("Training was not recorded as completed")
    if training.get("embedding_finite") is not True:
        raise ValidationError("Training embedding_finite must be true")
    pretraining_completed = require_int(
        training["pretraining_epochs_completed"],
        "training.pretraining_epochs_completed",
        1,
    )
    dec_completed = require_int(
        training["dec_epochs_completed"], "training.dec_epochs_completed", 1
    )
    require_finite_number(checkpoint["runtime_seconds"], "runtime_seconds", 0)

    embedding_result = validate_embedding(outputs, checkpoint_dir, n_obs, mode)

    # Scientific-parameter fidelity is primarily cryptographically enforced by
    # protocol_hash. These core technical invariants prevent silent substitution.
    parameters = checkpoint["parameters"]
    preprocessing = checkpoint["preprocessing"]
    graph = checkpoint["graph"]
    for name, value in (
        ("parameters", parameters),
        ("preprocessing", preprocessing),
        ("graph", graph),
        ("implementation", checkpoint["implementation"]),
        ("resources", checkpoint["resources"]),
        ("environment", checkpoint["environment"]),
        ("compatibility", checkpoint["compatibility"]),
    ):
        if not isinstance(value, dict):
            raise ValidationError(f"{name} must be a JSON object")
    require_keys(parameters, REQUIRED_PARAMETER_KEYS, "checkpoint.parameters")
    require_keys(preprocessing, REQUIRED_PREPROCESSING_KEYS, "checkpoint.preprocessing")
    require_keys(graph, REQUIRED_GRAPH_KEYS, "checkpoint.graph")
    recorded_k = parameters["requested_k"]
    if recorded_k != requested_k:
        raise ValidationError("parameters requested K differs from checkpoint")
    if final_readout.get("requested_k") != requested_k:
        raise ValidationError("final_readout requested K differs from checkpoint")
    if final_readout.get("observed_k") != observed_k:
        raise ValidationError("final_readout observed K differs from checkpoint")
    graph_k = require_int(graph["k"], "graph.k", 1)
    if parameters["graph_k"] != graph_k:
        raise ValidationError("parameters.graph_k differs from graph.k")
    if parameters["platform_regime"] not in {"spot", "cell"}:
        raise ValidationError("parameters.platform_regime must be spot or cell")
    expected_graph_k = 12 if parameters["platform_regime"] == "spot" else 6
    if graph_k != expected_graph_k:
        raise ValidationError("Graph K violates the frozen platform rule")
    if require_int(graph["edge_count"], "graph.edge_count", 1) < n_obs:
        raise ValidationError("graph.edge_count is implausibly smaller than n_obs")
    require_int(graph["isolates"], "graph.isolates", 0)
    require_int(graph["connected_components"], "graph.connected_components", 1)
    if preprocessing["finite"] is not True:
        raise ValidationError("preprocessing.finite must be true")
    retained_genes = require_int(
        preprocessing["retained_gene_count"], "preprocessing.retained_gene_count", 2
    )
    pca_dimension = require_int(
        preprocessing["pca_dimension"], "preprocessing.pca_dimension", 1
    )
    if retained_genes > n_vars or pca_dimension > min(200, retained_genes - 1, n_obs - 1):
        raise ValidationError("Preprocessing dimensions violate mathematical bounds")
    if parameters["pca_random_state"] != 42:
        raise ValidationError("PCA random_state must remain fixed at 42")
    pretraining_expected = require_int(
        parameters["pretraining_epochs"], "parameters.pretraining_epochs", 1
    )
    dec_expected = require_int(parameters["dec_epochs"], "parameters.dec_epochs", 1)
    if pretraining_completed != pretraining_expected or dec_completed != dec_expected:
        raise ValidationError("Completed epochs differ from frozen parameter record")
    if parameters["requested_k"] != requested_k:
        raise ValidationError("parameters.requested_k mismatch")
    if not isinstance(parameters["model_mode"], str) or not parameters["model_mode"].strip():
        raise ValidationError("parameters.model_mode is missing")
    if final_readout["model"] != "mclust EEE":
        raise ValidationError("Final readout must be mclust EEE")

    return {
        "checkpoint": str(checkpoint_json),
        "checkpoint_sha256": sha256_file(checkpoint_json),
        "dataset": dataset,
        "seed": seed,
        "mode": mode,
        "requested_k": requested_k,
        "observed_k": observed_k,
        "labels_count": len(labels),
        "labels_sha256": label_hash,
        "embedding": embedding_result,
        "protocol_hash": recorded_protocol,
        "status": "PASS",
    }


def discover_checkpoints(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.exists():
        return []
    return sorted(root.rglob("checkpoint.json"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Outcome-blind validation of one or all SEDR technical checkpoints"
    )
    parser.add_argument("target", nargs="?", type=Path, default=DEFAULT_CHECKPOINT_ROOT)
    parser.add_argument("--input-manifest", type=Path, default=DEFAULT_INPUT_MANIFEST)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--protocol-hash-file", type=Path, default=DEFAULT_PROTOCOL_HASH_FILE)
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--require-count", type=int)
    args = parser.parse_args()

    report: dict[str, Any] = {
        "validator": "strict outcome-blind SEDR technical checkpoint validator",
        "scientific_metrics_computed": False,
        "reference_annotations_read": False,
        "target": str(args.target.resolve()),
        "results": [],
        "errors": [],
    }
    try:
        manifest_entries, manifest_hash = load_input_manifest(args.input_manifest)
        protocol_hash = load_protocol_hash(args.protocol, args.protocol_hash_file)
        report["input_manifest_sha256"] = manifest_hash
        report["protocol_sha256"] = protocol_hash
        checkpoints = discover_checkpoints(args.target)
        report["discovered_count"] = len(checkpoints)
        if not checkpoints:
            raise ValidationError(f"No checkpoint.json files found under {args.target}")
        if args.require_count is not None and len(checkpoints) != args.require_count:
            raise ValidationError(
                f"Expected {args.require_count} checkpoints, found {len(checkpoints)}"
            )
        seen: set[tuple[str, int, str]] = set()
        for path in checkpoints:
            try:
                result = validate_checkpoint(path, manifest_entries, protocol_hash)
                identity = (result["dataset"], result["seed"], result["mode"])
                if result["mode"] == "smoke":
                    # Quarantined preflight deliberately contains two
                    # independent same-seed executions.  Their containing
                    # run directory distinguishes the technical controls.
                    identity = (*identity, path.parent.name)
                if identity in seen:
                    raise ValidationError(f"Duplicate checkpoint identity: {identity}")
                seen.add(identity)
                report["results"].append(result)
            except Exception as error:  # aggregate all technical failures
                report["errors"].append(
                    {"checkpoint": str(path.resolve()), "error": str(error)}
                )
    except Exception as error:
        report["errors"].append({"checkpoint": None, "error": str(error)})

    report["pass_count"] = len(report["results"])
    report["fail_count"] = len(report["errors"])
    report["status"] = "PASS" if not report["errors"] else "FAIL"
    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.report_json.with_suffix(args.report_json.suffix + ".tmp")
        temporary.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.report_json)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
