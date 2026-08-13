"""Gate-protected Project 9 SEDR marker-reproducibility analysis.

This module is intentionally safe to invoke before the scientific gate opens:
``main`` verifies the frozen protocol, label-blind input manifest, gate hashes,
and all 380 final technical checkpoints before importing any scientific-analysis
package or opening a source H5AD.  It then performs only the marker workflow
prespecified in the locked SEDR protocol.

The implementation verifies the separately produced core SEDR tables against
the same live 380-checkpoint panel, reconstructs the full 20-seed consensus
solely for domain alignment, and runs the inherited Project 9 marker analysis.
It never rewrites or overwrites a core scientific output.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
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
GATE_FILE = EXPANSION / "SCIENTIFIC_GATE_OPEN.json"
CHECKPOINT_MANIFEST = EXPANSION / "FINAL_380_CHECKPOINT_MANIFEST.csv"
VALIDATION_REPORT = EXPANSION / "FINAL_380_TECHNICAL_VALIDATION.json"
OUTPUT_DIR = EXPANSION / "candidate_integration" / "sedr_markers"
CORE_SEED = EXPANSION / "seed_level_accuracy.csv"
CORE_PAIRWISE = EXPANSION / "pairwise_partition_reproducibility.csv"
CORE_ISO = EXPANSION / "iso_accuracy_results.csv"
CORE_CONSENSUS = EXPANSION / "consensus_results.csv"
CORE_UNIT = EXPANSION / "sedr_unit_summary.csv"
CORE_OUTPUTS = (CORE_SEED, CORE_PAIRWISE, CORE_ISO, CORE_CONSENSUS, CORE_UNIT)

DATASETS = (
    "151507", "151508", "151509", "151510", "151669", "151670",
    "151671", "151672", "151673", "151674", "151675", "151676",
    "STARmap_20180505_BY3_1k", "HBCA1",
    "MERFISH_Bregma_m0.04", "MERFISH_Bregma_m0.09",
    "MERFISH_Bregma_m0.14", "MERFISH_Bregma_m0.19",
    "MERFISH_Bregma_m0.24",
)
SEEDS = tuple(range(1, 21))
EXPECTED_IDENTITIES = {(dataset, seed) for dataset in DATASETS for seed in SEEDS}
EXPECTED_COUNT = 380
STRATA = ("Low", "Middle", "High")
ISO_THRESHOLD = 0.02
# Core scientific CSVs were deliberately serialized with ``%.12g``.  A value
# and a difference computed from two independently rounded values can differ by
# at most 1.5e-12 on the bounded ARI scale; use the next simple decimal bound.
CORE_CSV_DERIVED_ATOL = 2e-12
TARGET_SUM = 10_000.0
PRIMARY_TOP_K = 100
SENSITIVITY_TOP_K = 50
HEX64 = re.compile(r"^[0-9A-F]{64}$")

OUTPUTS = {
    "pairwise": OUTPUT_DIR / "marker_reproducibility_all_pairs.csv",
    "correlations": OUTPUT_DIR / "within_unit_marker_correlations.csv",
    "tertiles": OUTPUT_DIR / "marker_tertile_summary.csv",
    "test": OUTPUT_DIR / "paired_high_vs_low_test.json",
    "validation": OUTPUT_DIR / "SEDR_MARKER_ANALYSIS_VALIDATION.json",
}

PAIR_COLUMNS = (
    "dataset", "method", "seed_r", "seed_s",
    "abs_reference_ari_difference", "pairwise_partition_ari",
    "marker_set_size", "top100_marker_jaccard", "top50_marker_jaccard",
    "marker_rank_spearman", "aligned_domains_compared_n",
    "aligned_domains_compared",
)
CORRELATION_COLUMNS = (
    "dataset", "method", "n_iso_accuracy_pairs",
    "spearman_partition_ari_vs_top100_marker_jaccard",
    "spearman_partition_ari_vs_top50_marker_jaccard",
    "spearman_partition_ari_vs_marker_rank_spearman",
)
TERTILE_COLUMNS = (
    "dataset", "method", "partition_ari_tertile", "n_pairs",
    "median_pairwise_partition_ari", "median_top100_marker_jaccard",
    "median_top50_marker_jaccard", "median_marker_rank_spearman",
)


class GateError(RuntimeError):
    """Scientific analysis is not authorized or its frozen inputs drifted."""


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


def load_validator() -> Any:
    path = WORK / "validate_technical.py"
    spec = importlib.util.spec_from_file_location("sedr_validate_technical", path)
    if spec is None or spec.loader is None:
        raise GateError(f"Cannot load strict technical validator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_checkpoint_digest(rows: list[dict[str, Any]]) -> str:
    canonical = [
        {
            "dataset": str(row["dataset"]),
            "seed": int(row["seed"]),
            "checkpoint_sha256": str(row["checkpoint_sha256"]).upper(),
            "labels_sha256": str(row["labels_sha256"]).upper(),
        }
        for row in rows
    ]
    canonical.sort(key=lambda row: (row["dataset"], row["seed"]))
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(payload.encode("utf-8"))


def read_gate_manifest(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"dataset", "seed", "checkpoint_sha256", "labels_sha256"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise GateError("Gate checkpoint manifest schema is incomplete")
        return list(reader)


def verify_gate_and_fresh_380() -> tuple[dict[str, Any], dict[str, Any]]:
    """Fail closed before any reference-capable H5AD or label is opened."""
    if not GATE_FILE.is_file():
        raise GateError(f"Scientific gate is absent: {GATE_FILE}")
    gate = load_json(GATE_FILE)
    if (
        gate.get("schema_version") != 1
        or gate.get("gate") != "SCIENTIFIC_GATE_OPEN"
        or gate.get("status") != "OPEN"
        or gate.get("scientific_unblinding") is not True
    ):
        raise GateError("Scientific gate is not explicitly OPEN for unblinding")
    if gate.get("checkpoint_count") != EXPECTED_COUNT:
        raise GateError("Scientific gate does not certify exactly 380 checkpoints")

    validator = load_validator()
    entries, input_manifest_hash = validator.load_input_manifest(INPUT_MANIFEST)
    protocol_hash = validator.load_protocol_hash(PROTOCOL, PROTOCOL_HASH_FILE)
    if not HEX64.fullmatch(protocol_hash):
        raise GateError("Frozen protocol hash is malformed")
    if str(gate.get("protocol_hash", "")).upper() != protocol_hash:
        raise GateError("Scientific gate protocol hash is stale")
    if str(gate.get("input_manifest_sha256", "")).upper() != input_manifest_hash:
        raise GateError("Scientific gate input-manifest hash is stale")
    if not LOCK_FILE.is_file():
        raise GateError("LOCK_ADD_SEDR.json is missing")
    lock = load_json(LOCK_FILE)
    if (
        lock.get("decision") != "LOCK_ADD_SEDR"
        or lock.get("scientific_unblinding") is not False
        or lock.get("scientific_outcomes_inspected_before_lock") is not False
        or lock.get("committed_target_runs") != EXPECTED_COUNT
        or str(lock.get("protocol_hash", lock.get("protocol_sha256", ""))).upper()
        != protocol_hash
        or str(gate.get("lock_add_sedr_sha256", "")).upper()
        != sha256_file(LOCK_FILE)
    ):
        raise GateError("LOCK_ADD_SEDR/gate binding failed")

    if not CHECKPOINT_MANIFEST.is_file():
        raise GateError("Gate checkpoint manifest is missing")
    manifest_path = gate.get("checkpoint_manifest_path")
    if not manifest_path or Path(manifest_path).resolve() != CHECKPOINT_MANIFEST.resolve():
        raise GateError("Gate checkpoint-manifest path is not canonical")
    recorded_file_hash = str(gate.get("checkpoint_manifest_file_sha256", "")).upper()
    if not HEX64.fullmatch(recorded_file_hash) or sha256_file(CHECKPOINT_MANIFEST) != recorded_file_hash:
        raise GateError("Gate checkpoint-manifest file hash mismatch")
    gate_rows = read_gate_manifest(CHECKPOINT_MANIFEST)
    if len(gate_rows) != EXPECTED_COUNT:
        raise GateError("Gate checkpoint manifest is not 380 rows")
    manifest_digest = canonical_checkpoint_digest(gate_rows)
    if manifest_digest != str(gate.get("checkpoint_manifest_sha256", "")).upper():
        raise GateError("Gate canonical checkpoint-manifest digest mismatch")

    report_path_raw = gate.get("technical_validation_report_path")
    if not report_path_raw:
        raise GateError("Gate technical-validation report path is missing")
    report_path = Path(report_path_raw).resolve()
    if report_path != VALIDATION_REPORT.resolve():
        raise GateError("Gate technical-validation report path is not canonical")
    if not report_path.is_file():
        raise GateError("Gate technical-validation report is missing")
    if sha256_file(report_path) != str(
        gate.get("technical_validation_report_sha256", "")
    ).upper():
        raise GateError("Gate technical-validation report hash mismatch")
    report = load_json(report_path)
    if (
        report.get("status") != "PASS"
        or report.get("pass_count") != EXPECTED_COUNT
        or report.get("fail_count") != 0
        or report.get("scientific_metrics_computed") is not False
        or report.get("reference_annotations_read") is not False
    ):
        raise GateError("Gate technical-validation report is not strict 380/380 PASS")

    checkpoint_paths = sorted(CHECKPOINT_ROOT.rglob("checkpoint.json"))
    if len(checkpoint_paths) != EXPECTED_COUNT:
        raise GateError(
            f"Fresh technical scan requires 380 checkpoints; found {len(checkpoint_paths)}"
        )
    if list(CHECKPOINT_ROOT.rglob("failure.json")) or list(
        CHECKPOINT_ROOT.rglob("*.tmp")
    ):
        raise GateError("Failure/temporary artifact exists in final checkpoint tree")

    fresh_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for checkpoint_path in checkpoint_paths:
        result = validator.validate_checkpoint(checkpoint_path, entries, protocol_hash)
        identity = (str(result["dataset"]), int(result["seed"]))
        if result["mode"] != "final" or identity not in EXPECTED_IDENTITIES:
            raise GateError(f"Smoke or unexpected final identity: {identity}")
        if identity in seen:
            raise GateError(f"Duplicate final identity: {identity}")
        expected_path = (
            CHECKPOINT_ROOT / identity[0] / f"seed{identity[1]:02d}"
            / "checkpoint.json"
        ).resolve()
        if checkpoint_path.resolve() != expected_path:
            raise GateError(f"Noncanonical checkpoint path: {checkpoint_path}")
        payload = load_json(checkpoint_path)
        if payload.get("scientific_unblinding") is not False:
            raise GateError(f"Pre-gate checkpoint blinding flag drift: {identity}")
        if str(payload.get("input", {}).get("manifest_sha256", "")).upper() != input_manifest_hash:
            raise GateError(f"Checkpoint input-manifest drift: {identity}")
        fresh_rows.append(
            {
                "dataset": identity[0],
                "seed": identity[1],
                "checkpoint_sha256": result["checkpoint_sha256"],
                "labels_sha256": result["labels_sha256"],
            }
        )
        seen.add(identity)
    if seen != EXPECTED_IDENTITIES:
        raise GateError("Fresh 19 x 20 checkpoint identity grid is incomplete")
    if canonical_checkpoint_digest(fresh_rows) != manifest_digest:
        raise GateError("Fresh 380-checkpoint digest differs from the opened gate")
    return entries, {
        "protocol_hash": protocol_hash,
        "input_manifest_sha256": input_manifest_hash,
        "checkpoint_manifest_sha256": manifest_digest,
        "gate_sha256": sha256_file(GATE_FILE),
    }


def read_labels_csv(path: Path, expected_obs: list[str]) -> Any:
    import numpy as np

    observation_ids: list[str] = []
    labels: list[int] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["observation_id", "cluster_label"]:
            raise RuntimeError(f"Unexpected labels schema: {path}")
        for row in reader:
            observation_ids.append(str(row["observation_id"]))
            labels.append(int(row["cluster_label"]))
    if observation_ids != expected_obs:
        raise RuntimeError(f"Checkpoint observation order drift: {path}")
    return np.asarray(labels, dtype=np.int32)


def coassociation_consensus(labels: Any, requested_k: int) -> Any:
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering

    if labels.shape[0] != 20:
        raise RuntimeError("Full SEDR consensus requires exactly 20 seeds")
    association = np.zeros((labels.shape[1], labels.shape[1]), dtype=np.float32)
    for partition in labels:
        association += partition[:, None] == partition[None, :]
    association /= 20.0
    model = AgglomerativeClustering(
        n_clusters=requested_k, metric="precomputed", linkage="average"
    )
    return model.fit_predict(1.0 - association).astype(np.int32)


def align_to_consensus(partition: Any, consensus: Any) -> Any:
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    left = np.sort(np.unique(partition))
    right = np.sort(np.unique(consensus))
    overlap = np.zeros((len(left), len(right)), dtype=np.int64)
    for i, source in enumerate(left):
        for j, target in enumerate(right):
            overlap[i, j] = np.sum((partition == source) & (consensus == target))
    row, column = linear_sum_assignment(-overlap)
    mapping = {left[i]: right[j] for i, j in zip(row, column)}
    # In the theoretical edge case observed K exceeds requested consensus K,
    # Hungarian assignment covers only ``requested K`` source domains.  Retain
    # the technically validated partition and deterministically map each extra
    # source domain to its maximum-overlap consensus domain (many-to-one).
    # When observed K <= requested K this loop is empty and the frozen
    # one-to-one Hungarian behavior is unchanged.
    for i, source in enumerate(left):
        if source not in mapping:
            mapping[source] = right[int(np.argmax(overlap[i]))]
    return np.asarray([mapping[value] for value in partition], dtype=np.int32)


def marker_universe(base: Any, dataset: str) -> Any:
    """Apply the exact inherited Project 9 dataset-specific marker universe."""
    import numpy as np

    if "highly_variable" not in base.var:
        raise RuntimeError(f"Frozen marker-universe flag is absent: {dataset}")
    selected = np.asarray(base.var["highly_variable"], dtype=bool)
    if selected.shape != (base.n_vars,) or not selected.any():
        raise RuntimeError(f"Frozen marker universe is empty or malformed: {dataset}")
    genes = base.var_names.astype(str).to_numpy()[selected]
    if len(set(genes.tolist())) != len(genes):
        raise RuntimeError(f"Frozen marker gene identifiers are not unique: {dataset}")
    if dataset.startswith("MERFISH_") and len(genes) != 155:
        raise RuntimeError(f"MERFISH marker universe drift: {dataset} has {len(genes)}")
    if len(genes) < PRIMARY_TOP_K:
        raise RuntimeError(f"Marker universe has fewer than 100 genes: {dataset}")
    return selected, genes


def rank_seed_markers(
    marker: Any, aligned: Any, domains: Any, genes: Any
) -> tuple[Any, str]:
    import numpy as np
    import pandas as pd
    import scanpy as sc
    from scipy import sparse, stats
    from anndata_null_compat import register_h5ad_null_reader

    register_h5ad_null_reader()

    present = np.sort(np.unique(aligned))
    marker.obs["domain"] = pd.Categorical(
        aligned.astype(str), categories=present.astype(str)
    )
    order = np.full((len(domains), len(genes)), -1, dtype=np.int32)
    if len(present) < 2:
        # A one-domain partition has no domain-vs-rest contrast.  It is a valid
        # completed stochastic outcome, but its marker ranking is not
        # estimable; the -1 rows propagate to pair-level marker NA values.
        return order, "not_estimable_single_observed_domain"
    pipeline = "scanpy_rank_genes_groups_wilcoxon_tie_correct_false"
    try:
        sc.tl.rank_genes_groups(
            marker,
            groupby="domain",
            groups=present.astype(str).tolist(),
            reference="rest",
            method="wilcoxon",
            use_raw=False,
            n_genes=marker.n_vars,
            pts=False,
            tie_correct=False,
        )
        for domain in present:
            q = int(np.flatnonzero(domains == domain)[0])
            ranked = marker.uns["rank_genes_groups"]["names"][str(domain)].astype(str)
            locations = pd.Index(genes).get_indexer(ranked)
            if (locations < 0).any() or len(np.unique(locations)) != len(genes):
                raise RuntimeError("Marker ranking is not a permutation of its universe")
            order[q] = locations
    except ValueError as error:
        if "only contain one sample" not in str(error):
            raise
        # Frozen Project 9 singleton-domain fallback: direct untied-score
        # Wilcoxon rank-sum ordering, keeping every valid domain.
        pipeline = "direct_equivalent_wilcoxon_rank_sum_singleton_fallback"
        matrix = marker.X.toarray() if sparse.issparse(marker.X) else np.asarray(marker.X)
        ranks = stats.rankdata(matrix, axis=0, method="average")
        for domain in present:
            q = int(np.flatnonzero(domains == domain)[0])
            mask = aligned == domain
            n1 = int(mask.sum())
            n0 = int((~mask).sum())
            if n1 == 0 or n0 == 0:
                raise RuntimeError("Domain-v-rest comparison is not estimable")
            u_value = ranks[mask].sum(axis=0) - n1 * (n1 + 1) / 2
            denominator = np.sqrt(n1 * n0 * (len(mask) + 1) / 12)
            score = (u_value - n1 * n0 / 2) / denominator
            order[q] = np.lexsort((genes, -score))
    return order, pipeline


def marker_jaccard(order_a: Any, order_b: Any, top_k: int) -> float:
    import numpy as np

    shared = np.intersect1d(
        order_a[:top_k], order_b[:top_k], assume_unique=True
    ).size
    return float(shared / (2 * top_k - shared))


def marker_rank_spearman(order_a: Any, order_b: Any) -> float:
    import numpy as np

    rank_a = np.empty_like(order_a, dtype=np.int64)
    rank_b = np.empty_like(order_b, dtype=np.int64)
    rank_a[order_a] = np.arange(len(order_a), dtype=np.int64)
    rank_b[order_b] = np.arange(len(order_b), dtype=np.int64)
    delta = rank_a - rank_b
    n = len(rank_a)
    if n < 2:
        return float("nan")
    return float(1.0 - 6.0 * (delta @ delta) / (n * (n * n - 1)))


def atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def dataframe_bytes(frame: Any) -> bytes:
    return frame.to_csv(index=False, lineterminator="\n", float_format="%.10g").encode(
        "utf-8"
    )


def safe_spearman(x: Any, y: Any, np: Any, stats: Any) -> float:
    """Return an estimable within-entry Spearman rho, otherwise NA.

    At least two primary iso-accuracy pairs are required for a correlation.
    Constant inputs are also nonestimable.  These are expected scientific edge
    cases, not pipeline failures, and are therefore encoded as missing values.
    """
    left = np.asarray(x, dtype=float)
    right = np.asarray(y, dtype=float)
    if left.shape != right.shape:
        raise RuntimeError("Spearman inputs have different shapes")
    if left.ndim != 1:
        left = left.reshape(-1)
        right = right.reshape(-1)
    complete = np.isfinite(left) & np.isfinite(right)
    left = left[complete]
    right = right[complete]
    if len(left) < 2:
        return float("nan")
    if np.all(left == left[0]) or np.all(right == right[0]):
        return float("nan")
    value = float(stats.spearmanr(left, right).statistic)
    return value if np.isfinite(value) else float("nan")


def summarize_marker_pairs(pairs: Any, pd: Any, np: Any, stats: Any) -> tuple[Any, Any, Any]:
    """Create complete 19-unit marker summaries, retaining empty units as NA."""
    missing = set(PAIR_COLUMNS) - set(pairs.columns)
    if missing:
        raise RuntimeError(f"Marker pair table lacks columns: {sorted(missing)}")
    unexpected = set(pairs["dataset"].astype(str)) - set(DATASETS)
    if unexpected:
        raise RuntimeError(f"Marker pair table contains unexpected datasets: {sorted(unexpected)}")

    stratified: list[Any] = []
    correlation_rows: list[dict[str, Any]] = []
    tertile_rows: list[dict[str, Any]] = []
    for dataset in DATASETS:
        group = pairs[pairs["dataset"].eq(dataset)].sort_values(
            ["pairwise_partition_ari", "seed_r", "seed_s"]
        ).copy()
        if len(group):
            codes = np.minimum(
                np.floor(np.arange(len(group)) * 3 / len(group)).astype(int), 2
            )
            group["partition_ari_tertile"] = [STRATA[code] for code in codes]
        else:
            group["partition_ari_tertile"] = pd.Series(
                index=group.index, dtype="object"
            )
        stratified.append(group)

        correlation_rows.append(
            {
                "dataset": dataset,
                "method": "SEDR",
                "n_iso_accuracy_pairs": len(group),
                "spearman_partition_ari_vs_top100_marker_jaccard": safe_spearman(
                    group["pairwise_partition_ari"],
                    group["top100_marker_jaccard"], np, stats,
                ),
                "spearman_partition_ari_vs_top50_marker_jaccard": safe_spearman(
                    group["pairwise_partition_ari"],
                    group["top50_marker_jaccard"], np, stats,
                ),
                "spearman_partition_ari_vs_marker_rank_spearman": safe_spearman(
                    group["pairwise_partition_ari"],
                    group["marker_rank_spearman"], np, stats,
                ),
            }
        )
        for stratum in STRATA:
            subset = group[group["partition_ari_tertile"].eq(stratum)]
            tertile_rows.append(
                {
                    "dataset": dataset,
                    "method": "SEDR",
                    "partition_ari_tertile": stratum,
                    "n_pairs": len(subset),
                    "median_pairwise_partition_ari": finite_median_or_nan(
                        subset["pairwise_partition_ari"], np
                    ),
                    "median_top100_marker_jaccard": finite_median_or_nan(
                        subset["top100_marker_jaccard"], np
                    ),
                    "median_top50_marker_jaccard": finite_median_or_nan(
                        subset["top50_marker_jaccard"], np
                    ),
                    "median_marker_rank_spearman": finite_median_or_nan(
                        subset["marker_rank_spearman"], np
                    ),
                }
            )

    stratified_pairs = pd.concat(stratified, ignore_index=True)
    correlations = pd.DataFrame(correlation_rows, columns=CORRELATION_COLUMNS)
    tertiles = pd.DataFrame(tertile_rows, columns=TERTILE_COLUMNS)
    return stratified_pairs, correlations, tertiles


def nullable_median(values: Any, np: Any) -> float | None:
    numeric = np.asarray(values, dtype=float)
    numeric = numeric[np.isfinite(numeric)]
    return float(np.median(numeric)) if len(numeric) else None


def finite_median_or_nan(values: Any, np: Any) -> float:
    numeric = np.asarray(values, dtype=float)
    numeric = numeric[np.isfinite(numeric)]
    return float(np.median(numeric)) if len(numeric) else float("nan")


def summarize_paired_high_low(tertiles: Any, np: Any, stats: Any) -> dict[str, Any]:
    """Apply the frozen paired test to complete Low/High unit pairs only."""
    wide = tertiles.pivot(
        index="dataset",
        columns="partition_ari_tertile",
        values="median_top100_marker_jaccard",
    ).reindex(index=DATASETS, columns=STRATA)
    paired = wide.dropna(subset=["Low", "High"])
    differences = (paired["High"] - paired["Low"]).to_numpy(float)
    estimable = bool(len(differences) and np.any(differences != 0))
    if estimable:
        test = stats.wilcoxon(
            paired["High"], paired["Low"], alternative="greater",
            zero_method="wilcox", method="auto",
        )
        test_statistic: float | None = float(test.statistic)
        test_p_value: float | None = float(test.pvalue)
    else:
        test_statistic = None
        test_p_value = None
    return {
        "analysis_unit": "SEDR dataset/section entry",
        "n_units": len(DATASETS),
        "n_estimable_units": len(paired),
        "comparison": (
            "unit median top-100 marker Jaccard: high vs low partition-ARI tertile"
        ),
        "alternative": "high > low",
        "estimable": estimable,
        "median_low": nullable_median(paired["Low"], np),
        "median_middle": nullable_median(wide["Middle"], np),
        "median_high": nullable_median(paired["High"], np),
        "median_paired_high_minus_low": nullable_median(differences, np),
        "units_high_greater_than_low": int(np.sum(differences > 0)),
        "units_equal": int(np.sum(differences == 0)),
        "units_high_less_than_low": int(np.sum(differences < 0)),
        "wilcoxon_statistic": test_statistic,
        "wilcoxon_p_value_one_sided": test_p_value,
    }


def refuse_overwrite() -> None:
    existing = [str(path.resolve()) for path in OUTPUTS.values() if path.exists()]
    if existing:
        raise RuntimeError("Refusing to overwrite existing marker outputs: " + ", ".join(existing))


def load_and_validate_core_tables() -> tuple[Any, Any, dict[str, str]]:
    """Require the complete, frozen core analyzer output before markers."""
    import numpy as np
    import pandas as pd

    missing = [str(path.resolve()) for path in CORE_OUTPUTS if not path.is_file()]
    if missing:
        raise RuntimeError("Required core SEDR output is missing: " + ", ".join(missing))
    seed = pd.read_csv(CORE_SEED, dtype={"dataset": str})
    pairwise = pd.read_csv(CORE_PAIRWISE, dtype={"dataset": str})
    iso = pd.read_csv(CORE_ISO, dtype={"dataset": str})
    consensus = pd.read_csv(CORE_CONSENSUS, dtype={"dataset": str})
    unit = pd.read_csv(CORE_UNIT, dtype={"dataset": str})

    if len(seed) != 380 or set(zip(seed["dataset"], seed["seed"])) != EXPECTED_IDENTITIES:
        raise RuntimeError("Core seed-level accuracy is not the complete 19 x 20 grid")
    if len(pairwise) != 19 * 190:
        raise RuntimeError("Core pairwise table does not contain 19 x 190 rows")
    if not pairwise.groupby("dataset").size().reindex(DATASETS).eq(190).all():
        raise RuntimeError("Core pairwise table does not contain 190 pairs per dataset")
    expected_pairs = {
        (dataset, seed_r, seed_s)
        for dataset in DATASETS
        for seed_r in range(1, 21)
        for seed_s in range(seed_r + 1, 21)
    }
    actual_pairs = set(
        zip(pairwise["dataset"], pairwise["seed_r"], pairwise["seed_s"])
    )
    if actual_pairs != expected_pairs:
        raise RuntimeError("Core pairwise identity grid is incomplete or duplicated")
    if len(iso) != 57 or len(consensus) != 19 or len(unit) != 19:
        raise RuntimeError("Core iso/consensus/unit row counts are not 57/19/19")
    for frame, name in ((iso, "iso"), (consensus, "consensus"), (unit, "unit")):
        if set(frame["dataset"]) != set(DATASETS):
            raise RuntimeError(f"Core {name} table does not cover all 19 datasets")
    primary_iso = iso[np.isclose(iso["threshold"].to_numpy(float), ISO_THRESHOLD)]
    if len(primary_iso) != 19:
        raise RuntimeError("Core primary 0.02 iso-accuracy summary is incomplete")
    derived_counts = (
        pairwise[pairwise["abs_reference_ari_difference"] <= ISO_THRESHOLD + 1e-12]
        .groupby("dataset").size().reindex(DATASETS, fill_value=0)
    )
    declared_counts = primary_iso.set_index("dataset")["n_iso_accuracy_pairs"].reindex(DATASETS)
    if not np.array_equal(
        derived_counts.to_numpy(dtype=int), declared_counts.to_numpy(dtype=int)
    ):
        raise RuntimeError("Core 0.02 iso-accuracy counts do not reconcile")
    required_numeric = [
        "ari_r", "ari_s", "abs_reference_ari_difference",
        "pairwise_partition_ari",
    ]
    if not np.isfinite(pairwise[required_numeric].to_numpy(dtype=float)).all():
        raise RuntimeError("Core pairwise SEDR metrics contain nonfinite values")
    seed_ari = seed.set_index(["dataset", "seed"])["reference_ari"]
    expected_ari_r = np.asarray(
        [seed_ari.loc[(row.dataset, int(row.seed_r))] for row in pairwise.itertuples()],
        dtype=float,
    )
    expected_ari_s = np.asarray(
        [seed_ari.loc[(row.dataset, int(row.seed_s))] for row in pairwise.itertuples()],
        dtype=float,
    )
    if not np.allclose(
        pairwise["ari_r"].to_numpy(float), expected_ari_r, rtol=0.0, atol=1e-12
    ) or not np.allclose(
        pairwise["ari_s"].to_numpy(float), expected_ari_s, rtol=0.0, atol=1e-12
    ):
        raise RuntimeError("Core seed and pairwise reference-ARI values do not reconcile")
    expected_gap = np.abs(expected_ari_r - expected_ari_s)
    if not np.allclose(
        pairwise["abs_reference_ari_difference"].to_numpy(float),
        expected_gap,
        rtol=0.0,
        atol=CORE_CSV_DERIVED_ATOL,
    ):
        raise RuntimeError("Core pairwise absolute reference-ARI differences drifted")
    return seed, pairwise, {
        path.name: sha256_file(path) for path in CORE_OUTPUTS
    }


def run_analysis(entries: dict[str, Any], provenance: dict[str, Any]) -> None:
    # Scientific imports are deliberately local and occur only after gate PASS.
    import anndata as ad
    import numpy as np
    import pandas as pd
    import scanpy as sc
    from scipy import sparse, stats

    refuse_overwrite()
    _core_seed, core_pairwise, core_hashes = load_and_validate_core_tables()
    pair_rows: list[dict[str, Any]] = []
    pipelines: set[str] = set()
    universe_rows: list[dict[str, Any]] = []

    for dataset in DATASETS:
        entry = entries.get(dataset)
        if not isinstance(entry, dict):
            raise RuntimeError(f"Technical input manifest lacks dataset: {dataset}")
        source_path = Path(entry["source_path"])
        if sha256_file(source_path) != str(entry["source_sha256"]).upper():
            raise RuntimeError(f"Frozen source input hash drift: {dataset}")
        base = ad.read_h5ad(source_path)
        expected_shape = tuple(int(value) for value in entry["shape"])
        if base.shape != expected_shape:
            raise RuntimeError(f"Frozen source shape drift: {dataset}")
        obs_names = base.obs_names.astype(str).tolist()
        obs_hash = sha256_bytes("\n".join(obs_names).encode("utf-8"))
        if obs_hash != str(entry["obs_order_sha256_newline_utf8"]).upper():
            raise RuntimeError(f"Frozen source observation order drift: {dataset}")
        checkpoint_records = [
            load_json(
                CHECKPOINT_ROOT / dataset / f"seed{seed:02d}" / "checkpoint.json"
            )
            for seed in SEEDS
        ]
        requested_values = {int(row["requested_k"]) for row in checkpoint_records}
        if len(requested_values) != 1:
            raise RuntimeError(f"Requested K varies across checkpoints: {dataset}")
        requested_k = requested_values.pop()

        labels = []
        for seed in SEEDS:
            label_path = CHECKPOINT_ROOT / dataset / f"seed{seed:02d}" / "labels.csv"
            labels.append(read_labels_csv(label_path, obs_names))
        labels = np.stack(labels)
        if labels.shape != (20, base.n_obs):
            raise RuntimeError(f"SEDR label panel shape drift: {dataset}")
        # Do not reject a normally completed output solely because observed K
        # differs from requested K.  Exact observed-K validity was already
        # bound to each strict technical checkpoint.
        for seed, partition, checkpoint in zip(SEEDS, labels, checkpoint_records):
            observed = int(np.unique(partition).size)
            if observed != int(checkpoint["observed_k"]):
                raise RuntimeError(
                    f"SEDR observed K differs from checkpoint: {dataset}/seed{seed:02d}"
                )

        consensus = coassociation_consensus(labels, requested_k)
        domains = np.sort(np.unique(consensus))
        if len(domains) != requested_k:
            raise RuntimeError(f"20-seed consensus did not produce requested K: {dataset}")

        selected, genes = marker_universe(base, dataset)
        if "counts" not in base.layers:
            raise RuntimeError(f"Frozen counts layer is absent: {dataset}")
        counts = base.layers["counts"][:, selected]
        counts = counts.tocsr() if sparse.issparse(counts) else sparse.csr_matrix(counts)
        marker = ad.AnnData(
            X=counts.copy(),
            obs=pd.DataFrame(index=base.obs_names.copy()),
            var=pd.DataFrame(index=genes),
        )
        sc.pp.normalize_total(marker, target_sum=TARGET_SUM)
        sc.pp.log1p(marker)
        if not np.isfinite(marker.X.data if sparse.issparse(marker.X) else marker.X).all():
            raise RuntimeError(f"Marker normalization produced nonfinite values: {dataset}")
        orders = []
        for seed_index in range(20):
            aligned = align_to_consensus(labels[seed_index], consensus)
            order, pipeline = rank_seed_markers(marker, aligned, domains, genes)
            orders.append(order)
            pipelines.add(pipeline)
        orders = np.stack(orders)
        universe_rows.append(
            {
                "dataset": dataset,
                "marker_gene_universe_n": len(genes),
                "marker_gene_order_sha256_newline_utf8": sha256_bytes(
                    ("\n".join(genes.tolist()) + "\n").encode("utf-8")
                ),
            }
        )

        eligible_pairs = core_pairwise[
            (core_pairwise["dataset"] == dataset)
            & (core_pairwise["abs_reference_ari_difference"] <= ISO_THRESHOLD + 1e-12)
        ].sort_values(["seed_r", "seed_s"])
        for core_pair in eligible_pairs.itertuples(index=False):
            seed_r = int(core_pair.seed_r) - 1
            seed_s = int(core_pair.seed_s) - 1
            reference_gap = float(core_pair.abs_reference_ari_difference)
            partition_ari = float(core_pair.pairwise_partition_ari)
            top100_values: list[float] = []
            top50_values: list[float] = []
            rank_values: list[float] = []
            used_domains: list[int] = []
            for q, domain in enumerate(domains):
                if orders[seed_r, q, 0] < 0 or orders[seed_s, q, 0] < 0:
                    continue
                top100_values.append(
                    marker_jaccard(
                        orders[seed_r, q], orders[seed_s, q], PRIMARY_TOP_K
                    )
                )
                top50_values.append(
                    marker_jaccard(
                        orders[seed_r, q], orders[seed_s, q], SENSITIVITY_TOP_K
                    )
                )
                rank_values.append(
                    marker_rank_spearman(orders[seed_r, q], orders[seed_s, q])
                )
                used_domains.append(int(domain))
            pair_rows.append(
                {
                    "dataset": dataset,
                    "method": "SEDR",
                    "seed_r": seed_r + 1,
                    "seed_s": seed_s + 1,
                    "abs_reference_ari_difference": float(reference_gap),
                    "pairwise_partition_ari": float(partition_ari),
                    "marker_set_size": PRIMARY_TOP_K,
                    "top100_marker_jaccard": (
                        float(np.median(top100_values))
                        if top100_values else float("nan")
                    ),
                    "top50_marker_jaccard": (
                        float(np.median(top50_values))
                        if top50_values else float("nan")
                    ),
                    "marker_rank_spearman": (
                        float(np.median(rank_values))
                        if rank_values else float("nan")
                    ),
                    "aligned_domains_compared_n": len(used_domains),
                    "aligned_domains_compared": ";".join(map(str, used_domains)),
                }
            )
        print(f"completed gated SEDR markers: {dataset}", flush=True)

    pairs = pd.DataFrame(pair_rows, columns=PAIR_COLUMNS)
    if not np.isfinite(pairs[[
        "abs_reference_ari_difference", "pairwise_partition_ari",
    ]].to_numpy(float)).all():
        raise RuntimeError("Marker pair identity metrics contain nonfinite values")
    marker_fields = [
        "top100_marker_jaccard", "top50_marker_jaccard", "marker_rank_spearman"
    ]
    for row in pairs.itertuples(index=False):
        marker_values = np.asarray(
            [getattr(row, field) for field in marker_fields], dtype=float
        )
        aligned_n = int(row.aligned_domains_compared_n)
        if aligned_n == 0 and not np.isnan(marker_values).all():
            raise RuntimeError("Zero-domain marker pair must contain three NA metrics")
        if aligned_n > 0 and not np.isfinite(marker_values).all():
            raise RuntimeError("Positive-domain marker pair has nonfinite marker metrics")

    pairs, correlations, tertiles = summarize_marker_pairs(pairs, pd, np, stats)
    if len(correlations) != 19 or len(tertiles) != 57:
        raise RuntimeError("SEDR marker unit/tertile aggregate is incomplete")
    paired_test = summarize_paired_high_low(tertiles, np, stats)

    output_payloads = {
        "pairwise": dataframe_bytes(pairs),
        "correlations": dataframe_bytes(correlations),
        "tertiles": dataframe_bytes(tertiles),
        "test": (json.dumps(paired_test, indent=2) + "\n").encode("utf-8"),
    }
    validation = {
        "status": "PASS",
        "method": "SEDR",
        "gate_revalidated_fresh_380_of_380": True,
        "dataset_units": 19,
        "iso_accuracy_threshold": ISO_THRESHOLD,
        "iso_accuracy_pairs": len(pairs),
        "normalization": "normalize_total(10000); log1p",
        "ranking": "Scanpy Wilcoxon domain-vs-rest; use_raw=False; tie_correct=False",
        "alignment": "maximum-overlap Hungarian to each entry's full 20-seed consensus",
        "consensus": "unweighted 20-seed co-association; D=1-C; average-linkage; project K",
        "primary_marker_set_size": PRIMARY_TOP_K,
        "sensitivity_marker_set_size": SENSITIVITY_TOP_K,
        "complete_rank_spearman": True,
        "deterministic_tertiles": "sort by partition ARI, seed_r, seed_s; floor(index*3/n)",
        "paired_high_vs_low_units": 19,
        "paired_high_vs_low_estimable_units": paired_test["n_estimable_units"],
        "core_output_sha256": core_hashes,
        "marker_universes": universe_rows,
        "pipeline_implementations_observed": sorted(pipelines),
        **provenance,
        "output_sha256": {
            OUTPUTS[key].name: sha256_bytes(value)
            for key, value in output_payloads.items()
        },
    }
    output_payloads["validation"] = (
        json.dumps(validation, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")

    # Publish only after every dataset, pair, tertile, and test has validated.
    for key in ("pairwise", "correlations", "tertiles", "test", "validation"):
        atomic_write_bytes(OUTPUTS[key], output_payloads[key])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate-protected frozen Project 9 SEDR marker analysis"
    )
    parser.add_argument(
        "--gate-check-only",
        action="store_true",
        help="Verify gate and fresh 380/380 only; never read reference annotations",
    )
    args = parser.parse_args()
    try:
        entries, provenance = verify_gate_and_fresh_380()
        if args.gate_check_only:
            print("SEDR_MARKER_GATE_READY_380_OF_380_NO_ANALYSIS")
            return 0
        run_analysis(entries, provenance)
        print("SEDR_MARKER_ANALYSIS_COMPLETE_19_OF_19")
        return 0
    except Exception as error:
        print(f"SEDR_MARKER_ANALYSIS_REFUSED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
