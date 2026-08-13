from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]; TABLES = ROOT / "tables"
DLPFC = ["151507", "151508", "151509", "151510", "151669", "151670",
          "151671", "151672", "151673", "151674", "151675", "151676"]
tags = ["a", "b"]
freq = pd.concat([pd.read_csv(ROOT / f"marker_frequency__{tag}.csv", dtype={"dataset": str}) for tag in tags], ignore_index=True)
repro = pd.concat([pd.read_csv(ROOT / f"marker_reproducibility__{tag}.csv", dtype={"dataset": str}) for tag in tags], ignore_index=True)
unit = pd.concat([pd.read_csv(TABLES / f"main_table_3_marker_reproducibility__{tag}.csv", dtype={"dataset": str}) for tag in tags], ignore_index=True)
if len(unit) != 56 or unit[["dataset", "method"]].drop_duplicates().shape[0] != 56:
    raise RuntimeError("Marker partial merge does not contain exactly 56 unique method-dataset units")
freq.to_csv(ROOT / "marker_frequency.csv", index=False)
repro.to_csv(ROOT / "marker_reproducibility.csv", index=False)
unit.to_csv(TABLES / "main_table_3_marker_reproducibility.csv", index=False)

delta = unit.stable_marker_jaccard - unit.unstable_marker_jaccard
test = stats.wilcoxon(unit.stable_marker_jaccard, unit.unstable_marker_jaccard,
                      alternative="greater", zero_method="wilcox")
families = unit.assign(family=np.where(unit.dataset.isin(DLPFC), "DLPFC", unit.dataset)).groupby("family").agg(
    median_unstable=("unstable_marker_jaccard", "median"),
    median_stable=("stable_marker_jaccard", "median"), n_units=("method", "size")).reset_index()
trigger = int(((families.median_stable - families.median_unstable) >= .10).sum()) >= 2
(TABLES / "marker_stable_vs_unstable_test.json").write_text(json.dumps({
    "n_units": len(unit), "median_unstable_jaccard": float(unit.unstable_marker_jaccard.median()),
    "median_stable_jaccard": float(unit.stable_marker_jaccard.median()),
    "median_paired_difference": float(delta.median()),
    "wilcoxon_signed_rank_alternative": "stable > unstable",
    "wilcoxon_statistic": float(test.statistic), "wilcoxon_p_value": float(test.pvalue),
    "go_enrichment_triggered_across_multiple_families": bool(trigger),
    "family_summary": families.to_dict(orient="records")
}, indent=2))
print(json.dumps({"status": "complete", "units": len(unit), "go_trigger": bool(trigger)}, indent=2))
