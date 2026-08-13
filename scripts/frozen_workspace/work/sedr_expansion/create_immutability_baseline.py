from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]
PUBLICATION_ROOT = WORKSPACE / "outputs" / "PROJECT9_FINAL_PUBLICATION_PACKAGE"
OUTPUT_ROOT = WORKSPACE / "outputs" / "PROJECT9_SEDR_EXPANSION" / "provenance"
JSON_PATH = OUTPUT_ROOT / "EXISTING_PROJECT9_IMMUTABILITY_BASELINE.json"
MD_PATH = OUTPUT_ROOT / "EXISTING_PROJECT9_IMMUTABILITY_BASELINE.md"

# These are the frozen integrated four-method scientific sources used to build
# the current publication package.  The list is explicit so a later unrelated
# file cannot silently enter or leave the protected baseline.
AUTHORITATIVE_FOUR_METHOD_SOURCES = (
    "outputs/PROJECT9_MERFISH_EXPANSION/combined_consensus_results.csv",
    "outputs/PROJECT9_MERFISH_EXPANSION/combined_dataset_manifest.csv",
    "outputs/PROJECT9_MERFISH_EXPANSION/combined_dataset_winner_uncertainty.csv",
    "outputs/PROJECT9_MERFISH_EXPANSION/combined_iso_accuracy_results.csv",
    "outputs/PROJECT9_MERFISH_EXPANSION/combined_marker_reproducibility_all_pairs.csv",
    "outputs/PROJECT9_MERFISH_EXPANSION/combined_marker_tertile_summary.csv",
    "outputs/PROJECT9_MERFISH_EXPANSION/combined_method_dataset_summary.csv",
    "outputs/PROJECT9_MERFISH_EXPANSION/combined_paired_tertile_test.json",
    "outputs/PROJECT9_MERFISH_EXPANSION/combined_pairwise_partition_reproducibility.csv",
    "outputs/PROJECT9_MERFISH_EXPANSION/combined_seed_level_accuracy.csv",
    "outputs/PROJECT9_MERFISH_EXPANSION/combined_winner_probabilities.csv",
    "outputs/PROJECT9_MERFISH_EXPANSION/combined_within_unit_marker_correlations.csv",
    "outputs/PROJECT9_MERFISH_EXPANSION/EXPANSION_SUMMARY.json",
    "outputs/PROJECT9_MERFISH_EXPANSION/FINAL_VALIDATION.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def file_record(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": path.relative_to(WORKSPACE).as_posix(),
        "bytes": stat.st_size,
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "sha256": sha256(path),
    }


def records_digest(records: list[dict[str, object]]) -> str:
    stable = [
        {"path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"]}
        for row in records
    ]
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def package_group(relative_path: str) -> str:
    path = Path(relative_path)
    package_parts = path.parts[2:]
    return package_parts[0] if package_parts else "."


def atomic_write(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def main() -> None:
    if not PUBLICATION_ROOT.is_dir():
        raise FileNotFoundError(PUBLICATION_ROOT)

    package_files = sorted(
        (path for path in PUBLICATION_ROOT.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(WORKSPACE).as_posix(),
    )
    if not package_files:
        raise RuntimeError("The protected publication package is empty")

    source_files = [WORKSPACE / relative for relative in AUTHORITATIVE_FOUR_METHOD_SOURCES]
    missing = [str(path) for path in source_files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing authoritative four-method sources: {missing}")

    package_records = [file_record(path) for path in package_files]
    source_records = [file_record(path) for path in source_files]

    groups: dict[str, dict[str, int]] = {}
    for row in package_records:
        group = package_group(str(row["path"]))
        summary = groups.setdefault(group, {"files": 0, "bytes": 0})
        summary["files"] += 1
        summary["bytes"] += int(row["bytes"])

    package_digest = records_digest(package_records)
    source_digest = records_digest(source_records)
    combined_digest = hashlib.sha256(
        f"{package_digest}\n{source_digest}\n".encode("ascii")
    ).hexdigest().upper()

    payload = {
        "schema_version": 1,
        "baseline_type": "PROJECT9_EXISTING_PUBLICATION_AND_FOUR_METHOD_IMMUTABILITY",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "hash_algorithm": "SHA-256",
        "scope_note": (
            "Read-only byte-level baseline created before additive SEDR work. "
            "No protected publication or four-method scientific source was modified."
        ),
        "protected_publication_package": {
            "root": PUBLICATION_ROOT.relative_to(WORKSPACE).as_posix(),
            "file_count": len(package_records),
            "total_bytes": sum(int(row["bytes"]) for row in package_records),
            "canonical_file_manifest_sha256": package_digest,
            "top_level_groups": groups,
            "files": package_records,
        },
        "authoritative_four_method_sources": {
            "file_count": len(source_records),
            "total_bytes": sum(int(row["bytes"]) for row in source_records),
            "canonical_file_manifest_sha256": source_digest,
            "files": source_records,
        },
        "combined_protected_scope_sha256": combined_digest,
        "verification_rule": (
            "Re-hash every listed path and require exact byte count and SHA-256 equality; "
            "also require the protected publication-package file set to match exactly."
        ),
    }

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    atomic_write(JSON_PATH, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    json_file_sha = sha256(JSON_PATH)

    group_lines = "\n".join(
        f"| `{name}` | {value['files']} | {value['bytes']:,} |"
        for name, value in sorted(groups.items())
    )
    markdown = f"""# Existing Project 9 immutability baseline

Status: **BASELINE_CAPTURED**

This is a read-only byte-level baseline created before additive SEDR work. It does not authorize changes to the existing publication package or four-method scientific sources.

## Protected scope

| Scope | Files | Bytes | Canonical manifest SHA-256 |
|---|---:|---:|---|
| Final publication package | {len(package_records)} | {sum(int(row['bytes']) for row in package_records):,} | `{package_digest}` |
| Authoritative integrated four-method sources | {len(source_records)} | {sum(int(row['bytes']) for row in source_records):,} | `{source_digest}` |

Combined protected-scope SHA-256: `{combined_digest}`

Baseline JSON SHA-256: `{json_file_sha}`

## Publication-package inventory

| Top-level group | Files | Bytes |
|---|---:|---:|
{group_lines}

## Verification rule

Re-hash every path listed in the JSON and require exact byte-count and SHA-256 equality. The publication-package file set must also match exactly; an added, removed, renamed, or changed file is an integrity failure.

No protected file was written or altered while creating this baseline.
"""
    atomic_write(MD_PATH, markdown)

    print(
        json.dumps(
            {
                "status": "BASELINE_CAPTURED",
                "publication_files": len(package_records),
                "authoritative_source_files": len(source_records),
                "combined_protected_scope_sha256": combined_digest,
                "json_sha256": json_file_sha,
                "json": str(JSON_PATH),
                "markdown": str(MD_PATH),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
