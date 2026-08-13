#!/usr/bin/env python3
"""Safe high-level entry point for the frozen Project 9 workflow.

The default actions are read-only. Expensive model execution is intentionally
not hidden behind a single command: reviewers select a platform-specific frozen
runner after preparing the corresponding public dataset locally.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

STAGES = (
    "01_prepare_data",
    "02_run_method",
    "03_collect_seed_outputs",
    "04_partition_reproducibility",
    "05_iso_accuracy",
    "06_marker_reproducibility",
    "07_method_rankings",
    "08_consensus",
    "09_generate_figures",
)


def print_plan() -> None:
    print("Frozen Project 9 workflow (no jobs launched):")
    for stage in STAGES:
        print(f"  {stage}")
    print("\nExpensive: stages 02 and 06; GPU method environments may be required.")
    print("Fast reviewer path: validate released source data and inspect figures.")


def run_checked(script: Path, *extra: str) -> int:
    if not script.is_file():
        raise SystemExit(f"Required script is missing: {script.relative_to(ROOT)}")
    return subprocess.call([sys.executable, str(script), *extra], cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan or validate the frozen spatial-domain seed benchmark."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="print the complete frozen workflow; no execution")
    sub.add_parser("validate", help="run fast source-data/manuscript consistency checks")
    sub.add_parser("security-scan", help="scan this repository for publication blockers")
    args = parser.parse_args()

    if args.command == "plan":
        print_plan()
        return 0
    if args.command == "validate":
        return run_checked(ROOT / "scripts" / "validation" / "validate_release.py")
    if args.command == "security-scan":
        return run_checked(ROOT / "scripts" / "validation" / "security_scan.py")
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())

