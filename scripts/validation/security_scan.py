#!/usr/bin/env python3
"""Fail-closed security and repository-hygiene scan for the public release.

The scanner reports only a path and a rule identifier. It never prints matched
text, so a suspected secret is not copied into CI logs. By default it scans the
repository containing this script; ``--root`` may point at a prepared staging
tree. Run it immediately before ``git add`` and again in CI.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TEN_MIB = 10 * 1024 * 1024
FIFTY_MIB = 50 * 1024 * 1024
MAX_TEXT_SCAN_BYTES = 20 * 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, order=True)
class Finding:
    severity: str
    rule: str
    path: str


# Every rule below is a blocker. Patterns are intentionally conservative for a
# small, source-code-and-derived-tables repository. Matches are never displayed.
CONTENT_RULES: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "private-key-header",
        re.compile(
            rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
            re.IGNORECASE,
        ),
    ),
    (
        "known-secret-token",
        re.compile(
            rb"(?:AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|"
            rb"github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
            rb"AIza[0-9A-Za-z_-]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|"
            rb"xox[baprs]-[A-Za-z0-9-]{10,})"
        ),
    ),
    (
        "jwt-token",
        re.compile(
            rb"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\."
            rb"[A-Za-z0-9_-]{10,}"
        ),
    ),
    (
        "credential-assignment",
        re.compile(
            rb"(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
            rb"client[_-]?secret|password|passwd|pwd)\s*[:=]\s*"
            rb"[\"'][^\"'\r\n]{8,}[\"']",
            re.IGNORECASE,
        ),
    ),
    (
        "credential-in-uri",
        re.compile(
            rb"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|https?)"
            rb"://[^\s/:@]+:[^\s/@]+@",
            re.IGNORECASE,
        ),
    ),
    (
        "personal-windows-path",
        re.compile(rb"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"'<>|]+", re.IGNORECASE),
    ),
    (
        "personal-macos-path",
        re.compile(rb"(?<![A-Za-z0-9_])" + b"/" + rb"Users/[^/\s\"'<>|]+"),
    ),
    (
        "personal-linux-path",
        re.compile(rb"(?<![A-Za-z0-9_])" + b"/" + rb"home/[^/\s\"'<>|]+"),
    ),
)


CREDENTIAL_NAMES = re.compile(
    r"(?:^|[._-])(?:id_rsa|id_ed25519|credentials?|secrets?|tokens?|cookies?|"
    r"passwd|password|auth|oauth|session)(?:[._-]|$)|"
    r"(?:\.pem|\.key|\.pfx|\.p12|\.kdbx)$|"
    r"^\.env(?:\..+)?$|^\.npmrc$|^\.pypirc$|^\.netrc$|"
    r"^(?:pip\.ini|pip\.conf|auth\.json|credentials\.json|token\.json)$",
    re.IGNORECASE,
)

DISALLOWED_EXTENSIONS = {
    ".7z",
    ".arrow",
    ".bam",
    ".bgen",
    ".bin",
    ".bz2",
    ".ckpt",
    ".cram",
    ".dat",
    ".dll",
    ".fastq",
    ".feather",
    ".fcs",
    ".fq",
    ".gz",
    ".h5",
    ".h5ad",
    ".key",
    ".kdbx",
    ".loom",
    ".mat",
    ".mtx",
    ".npy",
    ".npz",
    ".p12",
    ".parquet",
    ".pem",
    ".pfx",
    ".pickle",
    ".pkl",
    ".pt",
    ".pth",
    ".rar",
    ".rda",
    ".pyc",
    ".rdata",
    ".rds",
    ".sav",
    ".tar",
    ".vcf",
    ".xz",
    ".zip",
}

DISALLOWED_DIRECTORY_NAMES = {
    ".git",
    ".ipynb_checkpoints",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "cache",
    "checkpoint",
    "checkpoints",
    "log",
    "logs",
    "node_modules",
    "prediction",
    "predictions",
    "raw",
    "site-packages",
    "scratch",
    "temp",
    "third_party",
    "third-party",
    "tmp",
    "vendor",
    "zarr",
}

DISALLOWED_DIRECTORY_PATTERNS = (
    re.compile(r".*_cache$", re.IGNORECASE),
    re.compile(r".*(?:cache|checkpoint|prediction|render_scratch).*", re.IGNORECASE),
    re.compile(r"^lo_profile", re.IGNORECASE),
)

DISALLOWED_FILE_NAMES = {
    ".full_pipeline.process.lock",
    "checkpoint.json",
    "queue_state.json",
}

DISALLOWED_FILE_PATTERNS = (
    re.compile(r".*\.log$", re.IGNORECASE),
    re.compile(r".*\.pid$", re.IGNORECASE),
    re.compile(r"^\.lock$", re.IGNORECASE),
    re.compile(r".*(?:process|queue|run|session).*\.lock$", re.IGNORECASE),
    re.compile(r".*\.part\d*$", re.IGNORECASE),
    re.compile(r".*partial.*", re.IGNORECASE),
)

# Only text-like ZIP containers are inspected. Generic ZIP archives are blocked
# by the size rule when large and should not normally be part of this repository.
OFFICE_EXTENSIONS = {".docx", ".pptx", ".xlsx"}
OFFICE_TEXT_MEMBERS = (".xml", ".rels")


def display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def add(findings: set[Finding], rule: str, path: Path, root: Path) -> None:
    findings.add(Finding("BLOCKER", rule, display_path(path, root)))


def scan_content(data: bytes, label: Path, root: Path, findings: set[Finding]) -> None:
    for rule, pattern in CONTENT_RULES:
        if pattern.search(data):
            add(findings, rule, label, root)


def scan_office_archive(path: Path, root: Path, findings: set[Finding]) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if (
                    member.file_size > MAX_ARCHIVE_MEMBER_BYTES
                    or not member.filename.lower().endswith(OFFICE_TEXT_MEMBERS)
                ):
                    continue
                try:
                    data = archive.read(member)
                except (OSError, RuntimeError, zipfile.BadZipFile):
                    add(findings, "unreadable-office-member", path, root)
                    continue
                # Report the container only; member names can themselves contain
                # unwanted local information and are unnecessary for triage.
                scan_content(data, path, root, findings)
    except (OSError, RuntimeError, zipfile.BadZipFile):
        add(findings, "invalid-office-archive", path, root)


def iter_tree(root: Path) -> Iterable[tuple[Path, list[str], list[str]]]:
    """Yield an unpruned tree so a forbidden directory is still fully audited."""
    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames.sort(key=str.casefold)
        filenames.sort(key=str.casefold)
        yield Path(directory), dirnames, filenames


def scan(root: Path) -> tuple[set[Finding], int]:
    findings: set[Finding] = set()
    file_count = 0

    for directory, dirnames, filenames in iter_tree(root):
        pruned_directories: set[str] = set()
        for dirname in dirnames:
            path = directory / dirname
            lowered = dirname.casefold()

            # The repository's own Git database is expected after publication;
            # only nested Git metadata is a vendoring/privacy blocker.
            if lowered == ".git" and directory == root:
                pruned_directories.add(dirname)
                continue

            if path.is_symlink():
                add(findings, "symlink-not-allowed", path, root)
                pruned_directories.add(dirname)
                continue

            if lowered in DISALLOWED_DIRECTORY_NAMES or any(
                pattern.fullmatch(dirname) for pattern in DISALLOWED_DIRECTORY_PATTERNS
            ):
                rule = "nested-git-directory" if lowered == ".git" else "disallowed-directory"
                add(findings, rule, path, root)
                pruned_directories.add(dirname)

        # A single finding identifies a forbidden tree. Do not descend into it
        # and flood CI output with derivative findings.
        dirnames[:] = [name for name in dirnames if name not in pruned_directories]

        for filename in filenames:
            path = directory / filename
            file_count += 1

            # Git worktrees use a root-level .git pointer file. It is repository
            # administration, not release content. Nested .git files are blocked.
            if filename.casefold() == ".git":
                if directory != root:
                    add(findings, "nested-git-metadata", path, root)
                continue

            if path.is_symlink():
                add(findings, "symlink-not-allowed", path, root)
                continue

            if CREDENTIAL_NAMES.search(filename):
                add(findings, "credential-like-filename", path, root)

            lowered_name = filename.casefold()
            if lowered_name in DISALLOWED_FILE_NAMES or any(
                pattern.fullmatch(filename) for pattern in DISALLOWED_FILE_PATTERNS
            ):
                add(findings, "checkpoint-log-temp-file", path, root)

            suffix = path.suffix.casefold()
            if suffix in DISALLOWED_EXTENSIONS:
                add(findings, "raw-data-checkpoint-binary-extension", path, root)

            try:
                size = path.stat().st_size
            except OSError:
                add(findings, "unreadable-file-metadata", path, root)
                continue

            if size > FIFTY_MIB:
                add(findings, "file-over-50-mib", path, root)
            elif size > TEN_MIB:
                add(findings, "file-over-10-mib", path, root)

            if suffix in OFFICE_EXTENSIONS:
                scan_office_archive(path, root, findings)
                continue

            if size > MAX_TEXT_SCAN_BYTES:
                continue

            try:
                with path.open("rb") as handle:
                    data = handle.read(MAX_TEXT_SCAN_BYTES + 1)
            except OSError:
                add(findings, "unreadable-file-content", path, root)
                continue

            # Search binary containers too. Secrets and absolute paths are ASCII
            # byte sequences and may occur in PDF/image metadata or serialized
            # headers; regex searching does not require text decoding.
            scan_content(data, path, root, findings)

    return findings, file_count


def parse_args() -> argparse.Namespace:
    default_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Fail-closed public-repository security and size scan."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=default_root,
        help="Prepared repository root (default: repository containing this script).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print("BLOCKER root-not-directory <ROOT>", file=sys.stderr)
        return 2

    findings, file_count = scan(root)
    for finding in sorted(findings):
        print(f"{finding.severity} {finding.rule} {finding.path}")

    if findings:
        print(f"FAIL blockers={len(findings)} files_scanned={file_count}")
        return 1

    print(f"PASS blockers=0 files_scanned={file_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
