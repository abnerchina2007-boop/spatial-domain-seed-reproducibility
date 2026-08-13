from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd


WORKSPACE = Path(__file__).resolve().parents[2]
ROOT = WORKSPACE / "outputs" / "PROJECT9_MERFISH_EXPANSION"
FIGURE_READY = ROOT / "figure_ready"
FIGURE_READY.mkdir(parents=True, exist_ok=True)
PROTOCOL_SHA = "BF5106AF34143753A244EFD50038EF3F4AFF40580AEADD276547512076D17ED4"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def f3(value: float) -> str:
    return f"{value:.3f}"


def main() -> None:
    if sha256(ROOT / "FROZEN_MERFISH_EXPANSION_PROTOCOL.md") != PROTOCOL_SHA:
        raise RuntimeError("Frozen protocol hash drift; reporting prohibited")
    core = json.loads((ROOT / "CORE_ANALYSIS_VALIDATION.json").read_text(encoding="utf-8"))
    marker_validation = json.loads((ROOT / "MARKER_ANALYSIS_VALIDATION.json").read_text(encoding="utf-8"))
    if core.get("successful_runs") != 400 or marker_validation.get("status") != "PASS":
        raise RuntimeError("Validated core and marker analyses are required")

    seed = pd.read_csv(ROOT / "seed_level_accuracy.csv")
    units = pd.read_csv(ROOT / "method_section_summary.csv")
    pairwise = pd.read_csv(ROOT / "pairwise_partition_reproducibility.csv")
    iso = pd.read_csv(ROOT / "iso_accuracy_results.csv")
    ranking = pd.read_csv(ROOT / "ranking_uncertainty.csv")
    marker_pairs = pd.read_csv(ROOT / "marker_reproducibility_all_pairs.csv")
    correlations = pd.read_csv(ROOT / "within_unit_marker_correlations.csv")
    tertiles = pd.read_csv(ROOT / "marker_tertile_summary.csv")
    consensus = pd.read_csv(ROOT / "consensus_results.csv")

    primary_pairs = pairwise[pairwise.abs_reference_ari_difference <= 0.02 + 1e-12]
    divergent = primary_pairs[primary_pairs.pairwise_partition_ari < 0.50]
    low_sd_high_instability = units[(units.reference_ari_sd <= 0.02) & (units.partition_instability >= 0.30)]
    divergent_methods = divergent.method.nunique()
    finite_correlations = correlations[np.isfinite(correlations.spearman_partition_ari_vs_marker_jaccard)]
    positive_correlations = int((finite_correlations.spearman_partition_ari_vs_marker_jaccard > 0).sum())
    consensus_improved = int((consensus.split_half_gain_over_median_single_seed_pairwise_ari > 0).sum())
    components = {
        "score_map_decoupling": bool(len(low_sd_high_instability) >= 2 and low_sd_high_instability.method.nunique() >= 2),
        "iso_accuracy_divergence": bool(divergent_methods >= 2),
        "positive_partition_to_marker_relationship": bool(
            len(finite_correlations) > 0
            and finite_correlations.spearman_partition_ari_vs_marker_jaccard.median() > 0
            and positive_correlations > len(finite_correlations) / 2
        ),
        "consensus_improvement": bool(consensus_improved > 10),
    }
    component_count = sum(components.values())
    classification = (
        "STRONG_GENERALIZATION" if component_count == 4
        else ("PARTIAL_GENERALIZATION" if component_count else "WEAK_OR_ABSENT_GENERALIZATION")
    )
    winner = ranking[["section", "section_display", "method", "p_rank1", "max_winner_probability",
                      "winner_entropy_bits", "winner_entropy_normalized"]].drop_duplicates()
    winner_methods_positive = winner.groupby("section").p_rank1.apply(lambda x: int((x > 0).sum()))
    consensus_reference_gain = consensus.consensus20_reference_ari - consensus.median_single_seed_reference_ari
    tertile_unit = tertiles.pivot(index=["section", "method"], columns="partition_ari_tertile",
                                  values="median_top100_marker_jaccard").reset_index()

    summary = {
        "project": "PROJECT 9 MERFISH breadth expansion",
        "preflight_decision": "LOCK_MERFISH_5SECTIONS",
        "protocol_sha256": PROTOCOL_SHA,
        "protocol_changed_after_results": False,
        "dataset": {
            "identity": "Moffitt hypothalamus/preoptic-region MERFISH; BASS Animal1",
            "section_ids": sorted(seed.section.unique().tolist()),
            "sections": 5, "independent_contexts": 1,
            "cells_by_section": seed.groupby("section").n_cells.first().astype(int).to_dict(),
            "genes": 155, "reference_K": 8,
            "reference_labels": ["BST", "fx", "MPA", "MPN", "PV", "PVH", "PVT", "V3"],
        },
        "execution": {"successful_runs": int(len(seed)), "expected_runs": 400,
                      "method_section_units": int(len(units)), "seeds_per_unit": 20},
        "reference_score_stability": {
            "median_reference_ari_sd": float(units.reference_ari_sd.median()),
            "reference_ari_sd_range": [float(units.reference_ari_sd.min()), float(units.reference_ari_sd.max())],
            "median_reference_nmi_sd": float(units.reference_nmi_sd.median()),
            "low_sd_le_0_02_high_instability_ge_0_30_units": int(len(low_sd_high_instability)),
            "methods_represented": sorted(low_sd_high_instability.method.unique().tolist()),
        },
        "partition_reproducibility": {
            "pairwise_pairs": int(len(pairwise)),
            "median_unit_median_pairwise_ari": float(units.median_pairwise_partition_ari.median()),
            "unit_median_pairwise_ari_range": [float(units.median_pairwise_partition_ari.min()),
                                                float(units.median_pairwise_partition_ari.max())],
            "median_partition_instability": float(units.partition_instability.median()),
        },
        "iso_accuracy": {
            "primary_threshold": 0.02, "pairs": int(len(primary_pairs)),
            "pairs_partition_ari_below_0_50": int(len(divergent)),
            "fraction_partition_ari_below_0_50": float(len(divergent) / len(primary_pairs)) if len(primary_pairs) else None,
            "units_with_any_partition_ari_below_0_50": int(divergent.groupby(["section", "method"]).ngroups),
            "methods_with_any_partition_ari_below_0_50": sorted(divergent.method.unique().tolist()),
            "minimum_partition_ari": float(primary_pairs.pairwise_partition_ari.min()) if len(primary_pairs) else None,
        },
        "winner_uncertainty": {
            "combinations_per_section": 160000,
            "sections_with_more_than_one_method_positive_p_rank1": int((winner_methods_positive > 1).sum()),
            "median_maximum_winner_probability": float(winner.groupby("section").max_winner_probability.first().median()),
            "median_winner_entropy_bits": float(winner.groupby("section").winner_entropy_bits.first().median()),
        },
        "marker_relationship": {
            "iso_accuracy_pairs": int(len(marker_pairs)), "estimable_units": int(len(finite_correlations)),
            "median_within_unit_spearman": float(finite_correlations.spearman_partition_ari_vs_marker_jaccard.median()),
            "positive_units": positive_correlations,
            "median_low_tertile_jaccard": float(tertile_unit.Low.median()),
            "median_middle_tertile_jaccard": float(tertile_unit.Middle.median()),
            "median_high_tertile_jaccard": float(tertile_unit.High.median()),
            "median_high_minus_low_jaccard": float((tertile_unit.High - tertile_unit.Low).median()),
        },
        "consensus": {
            "median_split_half_consensus_ari": float(consensus.split_half_consensus_ari.median()),
            "split_half_consensus_ari_range": [float(consensus.split_half_consensus_ari.min()),
                                                float(consensus.split_half_consensus_ari.max())],
            "improved_units": consensus_improved, "total_units": 20,
            "median_gain_over_median_single_seed_pairwise_ari": float(
                consensus.split_half_gain_over_median_single_seed_pairwise_ari.median()),
            "consensus_reference_ari_improved_over_median_single_seed_units": int((consensus_reference_gain > 0).sum()),
        },
        "generalization_components": components,
        "generalization_component_count": component_count,
        "generalization_classification": classification,
    }
    (ROOT / "EXPANSION_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    scope = pd.DataFrame([
        {"context": "DLPFC Visium", "section_level_datasets": 12, "method_dataset_units": 48, "runs": 960},
        {"context": "STARmap visual cortex", "section_level_datasets": 1, "method_dataset_units": 4, "runs": 80},
        {"context": "Breast cancer Visium", "section_level_datasets": 1, "method_dataset_units": 4, "runs": 80},
        {"context": "MERFISH hypothalamus", "section_level_datasets": 5, "method_dataset_units": 20, "runs": 400},
    ])
    scope.to_csv(FIGURE_READY / "figure1_integrated_scope.csv", index=False)
    for source, target in [
        (ROOT / "seed_level_accuracy.csv", "figure2_merfish_seed_accuracy.csv"),
        (ROOT / "method_section_summary.csv", "figure3_merfish_accuracy_instability.csv"),
        (ROOT / "marker_reproducibility_all_pairs.csv", "figure5_merfish_continuous_marker.csv"),
        (ROOT / "consensus_results.csv", "figure6_merfish_consensus.csv"),
    ]:
        shutil.copy2(source, FIGURE_READY / target)
    winner.to_csv(FIGURE_READY / "figure4_merfish_winner_probabilities.csv", index=False)

    report = f"""# PROJECT 9 MERFISH breadth expansion — final report

## Executive result

The frozen five-section MERFISH expansion completed **400/400** required runs without changing the prespecified protocol. The external-validation classification is **`{classification}`** ({component_count}/4 frozen components present).

## Locked dataset

The validation set is BASS Animal1 from the Moffitt mouse hypothalamus/preoptic-region MERFISH experiment: Bregma −0.04 (5,488 cells), −0.09 (5,557), −0.14 (5,926), −0.19 (5,803) and −0.24 mm (5,543), each with the same 155-gene targeted panel. The complete cell-level BASS/manual reference has K=8: BST, fx, MPA, MPN, PV, PVH, PVT and V3. The five sections constitute one independent MERFISH biological/technology context.

## Reference-score stability

Across 20 method–section units, median reference-ARI SD was **{f3(summary['reference_score_stability']['median_reference_ari_sd'])}** (range {f3(units.reference_ari_sd.min())}–{f3(units.reference_ari_sd.max())}). Median reference-NMI SD was **{f3(units.reference_nmi_sd.median())}**. The frozen low-SD/high-instability definition was met by **{len(low_sd_high_instability)}/20** units spanning **{low_sd_high_instability.method.nunique()}** methods.

## Partition reproducibility and iso-accuracy

The median of the 20 unit-level median seed-pair ARIs was **{f3(units.median_pairwise_partition_ari.median())}** (range {f3(units.median_pairwise_partition_ari.min())}–{f3(units.median_pairwise_partition_ari.max())}); median partition instability was **{f3(units.partition_instability.median())}**.

At |Δ reference ARI| ≤0.02, **{len(primary_pairs):,}** seed pairs were eligible. **{len(divergent):,}** ({(100*len(divergent)/len(primary_pairs) if len(primary_pairs) else 0):.1f}%) had partition ARI <0.50, spanning **{divergent.groupby(['section','method']).ngroups}/20** units and **{divergent_methods}** methods. The minimum iso-accuracy partition ARI was **{f3(primary_pairs.pairwise_partition_ari.min()) if len(primary_pairs) else 'NA'}**.

## Winner uncertainty

All 160,000 empirical four-method score combinations were enumerated per section. More than one method had positive P(rank 1) in **{int((winner_methods_positive > 1).sum())}/5** sections. The median section-level maximum winner probability was **{f3(winner.groupby('section').max_winner_probability.first().median())}** and median winner entropy was **{f3(winner.groupby('section').winner_entropy_bits.first().median())} bits**. Combinations are empirical enumerations, not independent experiments.

## Continuous partition-to-marker relationship

The frozen marker pipeline evaluated **{len(marker_pairs):,}** primary iso-accuracy pairs using the full 155-gene universe and top-100 marker sets. Median within-unit Spearman correlation between partition ARI and marker Jaccard was **{f3(finite_correlations.spearman_partition_ari_vs_marker_jaccard.median())}**; **{positive_correlations}/{len(finite_correlations)}** estimable units were positive. Across units, median low/middle/high-tertile marker Jaccards were **{f3(tertile_unit.Low.median())}**, **{f3(tertile_unit.Middle.median())}** and **{f3(tertile_unit.High.median())}**, with median high-minus-low difference **{f3((tertile_unit.High-tertile_unit.Low).median())}**. Pair observations were not used as independent units for global inference.

## Consensus mitigation

Independent seed-1–10 versus seed-11–20 consensus partitions achieved median ARI **{f3(consensus.split_half_consensus_ari.median())}** (range {f3(consensus.split_half_consensus_ari.min())}–{f3(consensus.split_half_consensus_ari.max())}). Split-half reproducibility exceeded the corresponding median seed-pair ARI in **{consensus_improved}/20** units, with median gain **{f3(consensus.split_half_gain_over_median_single_seed_pairwise_ari.median())}**. Full-consensus reference ARI exceeded the median single-seed reference ARI in **{int((consensus_reference_gain > 0).sum())}/20** units.

## Frozen classification components

- Score–map decoupling: **{'present' if components['score_map_decoupling'] else 'absent'}**.
- Iso-accuracy divergence across at least two methods: **{'present' if components['iso_accuracy_divergence'] else 'absent'}**.
- Positive within-unit partition-to-marker relationship: **{'present' if components['positive_partition_to_marker_relationship'] else 'absent'}**.
- Consensus improvement in a majority of units: **{'present' if components['consensus_improvement'] else 'absent'}**.

Final classification: **`{classification}`**.

## Integrity and protocol adherence

All scientific analysis began only after the full 400-run prediction panel passed technical validation. The frozen protocol SHA-256 remained `{PROTOCOL_SHA}`. No input, label, K, graph rule, method parameter, epoch, seed, threshold, marker pipeline, consensus rule, section, example-selection rule or classification rule changed after results were observed. No pathway enrichment or optional analysis was run.
"""
    (ROOT / "FINAL_REPORT.md").write_text(report, encoding="utf-8")

    integration = f"""# Manuscript integration report

## Scope change

Add one independent biological/technology context: Moffitt/BASS mouse hypothalamus/preoptic-region MERFISH, represented by five consecutive sections. Report **19 section-level datasets**, **76 method–dataset units**, and **1,520 primary runs** after integration, while explicitly stating that the five MERFISH sections are one context rather than five independent biological contexts.

## Figure changes

- **Figure 1:** add MERFISH as the fourth context and list the five frozen Bregma sections, 155 genes, K=8, four methods and 20 seeds. Do not present the sections as independent contexts.
- **Figure 2:** append 400 MERFISH seed-level ARI/NMI observations and 20 method–section stability summaries. The MERFISH median ARI SD is {f3(units.reference_ari_sd.median())}.
- **Figure 3:** append the 20 MERFISH units to score-stability versus partition-instability displays; MERFISH median unit median pairwise ARI is {f3(units.median_pairwise_partition_ari.median())}.
- **Upgraded Figure 4:** append five MERFISH rows to the empirical P(rank 1) heatmap and related uncertainty summaries. Each row retains 160,000 enumerated combinations.
- **Upgraded Figure 5:** append {len(marker_pairs):,} MERFISH primary iso-accuracy pairs and the 20 within-unit correlations/tertile summaries; distinguish pair-level visualization from unit-level summaries.
- **Figure 6:** append 20 MERFISH paired consensus units and five rows to the four-method split-half heatmap. Do not add a consensus-method schematic.

## Tables and supplements

- **Table 1:** add five rows, one per Bregma section, under a shared MERFISH Animal1 context; 5,488/5,557/5,926/5,803/5,543 cells, 155 genes, K=8.
- **Main performance table:** append 20 method–section units.
- **Supplementary seed table:** append 400 seed-level rows.
- **Supplementary pairwise table:** append 3,800 unordered seed-pair rows.
- **Supplementary iso-accuracy table:** append all 0.01/0.02/0.03 summaries.
- **Supplementary ranking table:** append five sections and all four methods.
- **Supplementary marker tables:** append {len(marker_pairs):,} primary iso-accuracy marker-pair rows, 20 correlation rows and 60 tertile rows.
- **Supplementary consensus table:** append 20 rows.

All manuscript tables must remain uncolored and use Times New Roman in the formatted manuscript source; CSV deliverables are style-neutral.

## Abstract and Results numbers

Update the design counts from 14 to 19 section-level datasets, 56 to 76 units and 1,120 to 1,520 runs. Add the external-validation classification **`{classification}`** and the MERFISH-specific statistics from `EXPANSION_SUMMARY.json`. Preserve the distinction between five sections and one independent context.

## Discussion and limitations

Breadth claims may now extend to an imaging-based targeted MERFISH technology and mouse hypothalamus/preoptic anatomy. Interpret the result according to the frozen classification, including negative or heterogeneous components. State that all five sections came from the same Animal1, the 155-gene panel is targeted, expression is processed rather than uniform raw integer counts, the BASS domains are atlas-informed manual references, and the active PyTorch runtime used CPU. Do not claim five independent biological replications.

## Recommendation

Integrate the complete frozen MERFISH result without outcome-based exclusions. Use the supplied diagnostic previews for layout planning only; do not overwrite locked manuscript figures until the manuscript-wide numerical update is approved.
"""
    (ROOT / "MANUSCRIPT_INTEGRATION.md").write_text(integration, encoding="utf-8")


if __name__ == "__main__":
    main()
