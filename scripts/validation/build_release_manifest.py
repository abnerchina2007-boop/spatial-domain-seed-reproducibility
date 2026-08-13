#!/usr/bin/env python3
"""Build or check SHA-256 manifest for immutable released outputs."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
MANIFEST = RESULTS / "provenance" / "RELEASE_FILE_HASHES.sha256"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def inventory() -> list[tuple[str, str]]:
    rows = []
    for path in sorted(RESULTS.rglob("*")):
        if path.is_file() and path != MANIFEST:
            rel = path.relative_to(ROOT).as_posix()
            rows.append((digest(path), rel))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = "".join(f"{sha}  {path}\n" for sha, path in inventory())
    if args.check:
        if not MANIFEST.is_file() or MANIFEST.read_text(encoding="utf-8") != rendered:
            print("FAIL: release-file manifest is missing or differs")
            return 1
        print(f"PASS: {len(inventory())} released files match SHA-256 manifest")
        return 0
    MANIFEST.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"WROTE: {MANIFEST.relative_to(ROOT)} ({len(inventory())} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

