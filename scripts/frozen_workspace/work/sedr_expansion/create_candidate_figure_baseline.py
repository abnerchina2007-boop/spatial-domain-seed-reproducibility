from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]
PUBLICATION_ROOT = WORKSPACE / "outputs" / "PROJECT9_FINAL_PUBLICATION_PACKAGE"
PRIOR_BASELINE = (
    WORKSPACE
    / "outputs"
    / "PROJECT9_SEDR_EXPANSION"
    / "provenance"
    / "EXISTING_PROJECT9_IMMUTABILITY_BASELINE.json"
)
FIGURE_ROOT = (
    WORKSPACE
    / "outputs"
    / "PROJECT9_SEDR_EXPANSION"
    / "candidate_integration"
    / "figures"
)
QC_ROOT = FIGURE_ROOT / "QC"
MANIFEST = QC_ROOT / "CANDIDATE_FIGURE_IMMUTABILITY_BASELINE.json"

EXPLICIT_FIVE_METHOD_INPUTS = (
    "outputs/PROJECT9_SEDR_EXPANSION/FINAL_SEDR_REPORT.md",
    "outputs/PROJECT9_SEDR_EXPANSION/FINAL_SUMMARY.json",
    "outputs/PROJECT9_SEDR_EXPANSION/VALIDATION_REPORT.md",
    "outputs/PROJECT9_SEDR_EXPANSION/seed_level_accuracy.csv",
    "outputs/PROJECT9_SEDR_EXPANSION/pairwise_partition_reproducibility.csv",
    "outputs/PROJECT9_SEDR_EXPANSION/iso_accuracy_results.csv",
    "outputs/PROJECT9_SEDR_EXPANSION/marker_reproducibility_all_pairs.csv",
    "outputs/PROJECT9_SEDR_EXPANSION/within_unit_marker_correlations.csv",
    "outputs/PROJECT9_SEDR_EXPANSION/marker_tertile_summary.csv",
    "outputs/PROJECT9_SEDR_EXPANSION/consensus_results.csv",
    "outputs/PROJECT9_SEDR_EXPANSION/five_method_winner_probabilities.csv",
    "outputs/PROJECT9_SEDR_EXPANSION/five_method_rank_distributions.csv",
    "outputs/PROJECT9_SEDR_EXPANSION/five_method_pairwise_superiority.csv",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def record(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": path.relative_to(WORKSPACE).as_posix(),
        "bytes": stat.st_size,
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "sha256": sha256(path),
    }


def canonical_digest(records: list[dict[str, object]]) -> str:
    stable = [
        {"path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"]}
        for row in sorted(records, key=lambda item: str(item["path"]))
    ]
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def main() -> None:
    if MANIFEST.exists():
        raise RuntimeError(f"Refusing to overwrite existing baseline: {MANIFEST}")

    target_existed = FIGURE_ROOT.exists()
    preexisting_candidate_files = (
        sorted(
            path.relative_to(WORKSPACE).as_posix()
            for path in FIGURE_ROOT.rglob("*")
            if path.is_file()
        )
        if target_existed
        else []
    )

    prior = json.loads(PRIOR_BASELINE.read_text(encoding="utf-8"))
    prior_records = prior["protected_publication_package"]["files"]
    prior_by_path = {row["path"]: row for row in prior_records}
    current_package_paths = sorted(
        path.relative_to(WORKSPACE).as_posix()
        for path in PUBLICATION_ROOT.rglob("*")
        if path.is_file()
    )
    if current_package_paths != sorted(prior_by_path):
        missing = sorted(set(prior_by_path) - set(current_package_paths))
        added = sorted(set(current_package_paths) - set(prior_by_path))
        raise RuntimeError(f"Publication package file-set drift: missing={missing}, added={added}")

    publication_records: list[dict[str, object]] = []
    mismatches: list[dict[str, object]] = []
    for relative in current_package_paths:
        path = WORKSPACE / relative
        current = record(path)
        expected = prior_by_path[relative]
        if current["bytes"] != expected["bytes"] or current["sha256"] != expected["sha256"]:
            mismatches.append(
                {
                    "path": relative,
                    "expected_bytes": expected["bytes"],
                    "observed_bytes": current["bytes"],
                    "expected_sha256": expected["sha256"],
                    "observed_sha256": current["sha256"],
                }
            )
        publication_records.append(current)
    if mismatches:
        raise RuntimeError(f"Publication package byte drift: {mismatches}")

    sedr_root = WORKSPACE / "outputs" / "PROJECT9_SEDR_EXPANSION"
    scientific_paths = {WORKSPACE / relative for relative in EXPLICIT_FIVE_METHOD_INPUTS}
    scientific_paths.update(sedr_root.glob("integrated_*.csv"))
    for relative_dir in (
        "candidate_integration/all_outputs",
        "candidate_integration/five_method",
        "candidate_integration/sedr_markers",
    ):
        scientific_paths.update(
            path for path in (sedr_root / relative_dir).rglob("*") if path.is_file()
        )
    missing_inputs = sorted(
        path.relative_to(WORKSPACE).as_posix()
        for path in scientific_paths
        if not path.is_file()
    )
    if missing_inputs:
        raise FileNotFoundError(f"Missing authoritative five-method inputs: {missing_inputs}")

    scientific_records = [record(path) for path in sorted(scientific_paths)]
    publication_digest = canonical_digest(publication_records)
    scientific_digest = canonical_digest(scientific_records)
    all_records = publication_records + scientific_records
    combined_digest = canonical_digest(all_records)

    payload = {
        "schema_version": 1,
        "baseline_type": "PROJECT9_FIVE_METHOD_CANDIDATE_FIGURE_IMMUTABILITY",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "hash_algorithm": "SHA-256",
        "task_scope": "Figure candidates only; protected publication and scientific inputs are read-only.",
        "candidate_directory_collision_audit": {
            "target": FIGURE_ROOT.relative_to(WORKSPACE).as_posix(),
            "target_existed_before_baseline": target_existed,
            "preexisting_file_count": len(preexisting_candidate_files),
            "preexisting_files": preexisting_candidate_files,
            "candidate_filename_collision_detected": bool(preexisting_candidate_files),
        },
        "prior_publication_lock_verification": {
            "status": "PASS",
            "prior_baseline": PRIOR_BASELINE.relative_to(WORKSPACE).as_posix(),
            "prior_combined_protected_scope_sha256": prior[
                "combined_protected_scope_sha256"
            ],
            "publication_file_set_exact": True,
            "publication_bytes_and_sha256_exact": True,
            "mismatch_count": 0,
        },
        "protected_locked_four_method_publication_package": {
            "root": PUBLICATION_ROOT.relative_to(WORKSPACE).as_posix(),
            "scope_note": (
                "Superset protection covers every locked figure/export/source-data table, "
                "manuscript, supplement, final table, archive, QC artifact, and package ZIP."
            ),
            "file_count": len(publication_records),
            "total_bytes": sum(int(row["bytes"]) for row in publication_records),
            "canonical_manifest_sha256": publication_digest,
            "files": publication_records,
        },
        "authoritative_five_method_scientific_inputs": {
            "scope_note": (
                "Explicit SEDR final sources plus all root integrated CSV aliases and all "
                "scientific files in candidate_integration/all_outputs, five_method, and "
                "sedr_markers present before candidate figure generation."
            ),
            "file_count": len(scientific_records),
            "total_bytes": sum(int(row["bytes"]) for row in scientific_records),
            "canonical_manifest_sha256": scientific_digest,
            "files": scientific_records,
        },
        "combined_protected_file_count": len(all_records),
        "combined_protected_total_bytes": sum(int(row["bytes"]) for row in all_records),
        "combined_protected_scope_sha256": combined_digest,
        "verification_rule": (
            "After candidate generation, every listed path must retain the exact byte count "
            "and SHA-256 recorded here; the 192-file publication-package set must remain exact."
        ),
    }

    QC_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = MANIFEST.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(MANIFEST)
    print(
        json.dumps(
            {
                "status": "BASELINE_CAPTURED",
                "manifest": str(MANIFEST),
                "manifest_sha256": sha256(MANIFEST),
                "publication_files": len(publication_records),
                "five_method_input_files": len(scientific_records),
                "combined_files": len(all_records),
                "combined_protected_scope_sha256": combined_digest,
                "candidate_root_existed": target_existed,
                "candidate_preexisting_files": len(preexisting_candidate_files),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
