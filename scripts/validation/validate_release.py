#!/usr/bin/env python3
"""Read-only validation of the released source-data snapshot.

This script checks structure and manuscript-number consistency. It does not
train a model, inspect raw annotations, or replace any frozen result.
"""

from __future__ import annotations

import csv
import json
import math
import sys
import traceback
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = ROOT / "results" / "source_data" / "analysis"
FIGURES = ROOT / "results" / "source_data" / "figures"
TABLES = ROOT / "results" / "source_data" / "tables"
PROVENANCE = ROOT / "results" / "provenance"


def read_csv(name: str, base: Path = ANALYSIS) -> list[dict[str, str]]:
    path = base / name
    if not path.is_file():
        raise AssertionError(f"missing: {path.relative_to(ROOT)}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def near(value: float, expected: float, tolerance: float) -> None:
    if not math.isfinite(value) or abs(value - expected) > tolerance:
        raise AssertionError(f"{value!r} != {expected!r} within {tolerance}")


def main() -> int:
    failures: list[str] = []

    try:
        seeds = read_csv("integrated_seed_level_accuracy.csv")
        pairs = read_csv("integrated_pairwise_reproducibility.csv")
        iso = read_csv("integrated_iso_accuracy.csv")
        units = read_csv("integrated_method_dataset_summary.csv")
        marker_pairs = read_csv("integrated_marker_reproducibility_all_pairs.csv")
        marker_units = read_csv("integrated_marker_unit_summary.csv")
        marker_tertiles = read_csv("integrated_marker_tertile_summary.csv")
        consensus = read_csv("integrated_consensus_summary.csv")
        ranks = read_csv("five_method_rank_summary.csv")

        assert len(seeds) == 1900
        assert len(pairs) == 18050
        assert len(iso) == 285
        assert len(units) == 95
        assert len(marker_pairs) == 6928
        assert len(marker_units) == 95
        assert len(marker_tertiles) == 285
        assert len(consensus) == 95
        assert len(ranks) == 95

        methods = Counter(row["method"] for row in seeds)
        assert set(methods) == {"GraphST", "STAGATE", "SpaGCN", "BANKSY", "SEDR"}
        assert set(methods.values()) == {380}
        unit_keys = {(row["section"], row["method"]) for row in seeds}
        assert len(unit_keys) == 95
        assert all(
            sum(1 for r in seeds if (r["section"], r["method"]) == key) == 20
            for key in unit_keys
        )

        primary = [r for r in iso if abs(float(r["threshold"]) - 0.02) <= 1e-12]
        assert len(primary) == 95
        eligible = sum(int(float(r["n_iso_accuracy_pairs"])) for r in primary)
        divergent = sum(int(float(r["n_partition_ari_below_0_50"])) for r in primary)
        affected = sum(int(float(r["n_partition_ari_below_0_50"])) > 0 for r in primary)
        assert eligible == 6928
        assert divergent == 1125
        assert affected == 55
        near(100.0 * divergent / eligible, 16.238452655889144, 1e-12)

        finite_rho = []
        for row in marker_units:
            token = row.get("spearman_partition_ari_vs_marker_jaccard", "")
            if token not in {"", "NA", "NaN", "nan"}:
                finite_rho.append(float(token))
        assert len(finite_rho) == 94
        assert all(x > 0 for x in finite_rho)
        finite_rho.sort()
        median_rho = (finite_rho[46] + finite_rho[47]) / 2
        near(median_rho, 0.6945763796, 1e-10)

        headline_path = ANALYSIS / "integrated_headline_summary.json"
        headline = json.loads(headline_path.read_text(encoding="utf-8"))
        medians = headline["marker_tertiles"]
        near(float(medians["low"]["median"]), 0.72413793, 1e-10)
        near(float(medians["middle"]["median"]), 0.7699115, 1e-10)
        near(float(medians["high"]["median"]), 0.8181818182, 1e-10)
        assert headline["consensus"]["improved_units"] == 95
        near(float(headline["consensus"]["split_half_consensus_ari"]["median"]), 0.777284727665, 1e-12)
        near(float(headline["consensus"]["gain"]["median"]), 0.1715913051, 1e-10)

        paired = read_csv("Figure4_paired_tertile_test.csv", FIGURES)
        assert len(paired) == 1
        w_key = next(
            k for k in paired[0]
            if k.lower() in {"wilcoxon_w", "w", "statistic", "wilcoxon_statistic"}
        )
        p_key = "wilcoxon_p_value_one_sided"
        near(float(paired[0][w_key]), 4459.0, 1e-12)
        near(float(paired[0][p_key]), 2.3097164857133306e-17, 5e-29)

        expected_figure_csv = 27
        expected_table_csv = 5
        assert len(list(FIGURES.glob("*.csv"))) == expected_figure_csv
        assert len(list(TABLES.glob("*.csv"))) == expected_table_csv
        assert (PROVENANCE / "FINAL_GATE.json").is_file()
        gate = json.loads((PROVENANCE / "FINAL_GATE.json").read_text(encoding="utf-8"))
        assert gate["status"] == "PASS"
        assert gate["numeric"]["status"] == "PASS"
    except Exception as exc:  # report a fail-closed result with the failing line
        location = traceback.extract_tb(exc.__traceback__)[-1]
        failures.append(
            f"{type(exc).__name__} at {Path(location.filename).name}:{location.lineno}: {exc}"
        )

    result = {
        "status": "PASS" if not failures else "FAIL",
        "checks": {
            "method_entry_units": 95,
            "seed_runs": 1900,
            "seed_pairs": 18050,
            "primary_iso_pairs": 6928,
            "divergent_pairs": 1125,
            "affected_units": 55,
            "marker_estimable_positive": "94/94",
            "consensus_improved": "95/95",
        },
        "failures": failures,
    }
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
