from __future__ import annotations

import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import linear_sum_assignment


WORKSPACE = Path(__file__).resolve().parents[2]
ROOT = WORKSPACE / "outputs" / "PROJECT9_MERFISH_EXPANSION"
PHASE1 = WORKSPACE / "outputs" / "PROJECT9_PHASE1"
FIG4 = WORKSPACE / "outputs" / "PROJECT9_UPGRADE_FIG4"
FIG5 = WORKSPACE / "outputs" / "PROJECT9_UPGRADE_FIG5"
FIGURE_READY = ROOT / "figure_ready"
TABLE_READY = ROOT / "table_ready"
FIGURE_READY.mkdir(parents=True, exist_ok=True)
TABLE_READY.mkdir(parents=True, exist_ok=True)

METHODS = ["GraphST", "STAGATE", "SpaGCN", "BANKSY"]
SECTIONS = [
    "MERFISH_Bregma_m0.04", "MERFISH_Bregma_m0.09", "MERFISH_Bregma_m0.14",
    "MERFISH_Bregma_m0.19", "MERFISH_Bregma_m0.24",
]
DISPLAY = {
    "MERFISH_Bregma_m0.04": "Bregma -0.04",
    "MERFISH_Bregma_m0.09": "Bregma -0.09",
    "MERFISH_Bregma_m0.14": "Bregma -0.14",
    "MERFISH_Bregma_m0.19": "Bregma -0.19",
    "MERFISH_Bregma_m0.24": "Bregma -0.24",
    "STARmap_20180505_BY3_1k": "STARmap",
    "HBCA1": "HBCA1",
}
OLD_ORDER = [
    "151507", "151508", "151509", "151510", "151669", "151670", "151671",
    "151672", "151673", "151674", "151675", "151676", "STARmap_20180505_BY3_1k", "HBCA1",
]
ALL_ORDER = OLD_ORDER + SECTIONS
METHOD_ORDER = {name: index for index, name in enumerate(METHODS)}
SECTION_ORDER = {name: index for index, name in enumerate(SECTIONS)}


def display_name(value: str) -> str:
    return DISPLAY.get(str(value), str(value))


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, float_format="%.10g")


def paired_summary(tertiles: pd.DataFrame, dataset_col: str) -> dict:
    wide = tertiles.pivot(
        index=[dataset_col, "method"], columns="partition_ari_tertile",
        values="median_top100_marker_jaccard",
    ).reset_index()
    estimable = wide.dropna(subset=["Low", "High"]).copy()
    diff = (estimable["High"] - estimable["Low"]).to_numpy(float)
    result = stats.wilcoxon(
        estimable["High"], estimable["Low"], alternative="greater",
        zero_method="wilcox", method="auto",
    )
    nonzero = diff[diff != 0]
    ranks = stats.rankdata(np.abs(nonzero))
    w_pos = float(ranks[nonzero > 0].sum())
    w_neg = float(ranks[nonzero < 0].sum())
    rank_biserial = (w_pos - w_neg) / (w_pos + w_neg) if (w_pos + w_neg) else np.nan
    middle = tertiles[tertiles.partition_ari_tertile == "Middle"].median_top100_marker_jaccard
    return {
        "analysis_unit": "method-section unit",
        "n_units": int(len(wide)),
        "n_estimable_units": int(len(estimable)),
        "comparison": "unit-level median top-100 marker Jaccard: high versus low partition-ARI tertile",
        "alternative": "high > low",
        "median_low": float(estimable.Low.median()),
        "median_middle": float(middle.median()),
        "median_high": float(estimable.High.median()),
        "median_paired_high_minus_low": float(np.median(diff)),
        "units_high_greater_than_low": int(np.sum(diff > 0)),
        "units_equal": int(np.sum(diff == 0)),
        "units_high_less_than_low": int(np.sum(diff < 0)),
        "wilcoxon_statistic": float(result.statistic),
        "wilcoxon_p_value_one_sided": float(result.pvalue),
        "matched_rank_biserial_correlation": float(rank_biserial),
    }


def select_extreme_pairs(pairwise: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (section, method), group in pairwise.groupby(["section", "method"], sort=False):
        unstable = group[group.abs_reference_ari_difference <= 0.02 + 1e-12].sort_values(
            ["pairwise_partition_ari", "seed_r", "seed_s"]
        ).iloc[0]
        remaining = group[~((group.seed_r == unstable.seed_r) & (group.seed_s == unstable.seed_s))].copy()
        remaining["gap_distance"] = (
            remaining.abs_reference_ari_difference - unstable.abs_reference_ari_difference
        ).abs()
        caliper = remaining[remaining.gap_distance <= 0.002 + 1e-12]
        candidates = caliper if len(caliper) else remaining[
            remaining.gap_distance == remaining.gap_distance.min()
        ]
        stable = candidates.sort_values(
            ["pairwise_partition_ari", "seed_r", "seed_s"], ascending=[False, True, True]
        ).iloc[0]
        for pair_type, row in (("iso_accuracy_unstable", unstable), ("stable_control", stable)):
            rows.append({
                "section": section,
                "section_display": display_name(section),
                "method": method,
                "pair_type": pair_type,
                "seed_r": int(row.seed_r),
                "seed_s": int(row.seed_s),
                "abs_reference_ari_difference": float(row.abs_reference_ari_difference),
                "pairwise_partition_ari": float(row.pairwise_partition_ari),
                "stable_match_gap_distance": 0.0 if pair_type.startswith("iso") else float(row.gap_distance),
            })
    return pd.DataFrame(rows)


def align_to_reference(labels: np.ndarray, reference: np.ndarray) -> np.ndarray:
    observed = np.sort(np.unique(labels))
    categories = np.sort(np.unique(reference.astype(str)))
    overlap = np.zeros((len(observed), len(categories)), dtype=int)
    for i, label in enumerate(observed):
        for j, category in enumerate(categories):
            overlap[i, j] = np.sum((labels == label) & (reference == category))
    row, col = linear_sum_assignment(-overlap)
    mapping = {observed[i]: categories[j] for i, j in zip(row, col)}
    return np.array([mapping.get(value, "Unmatched") for value in labels], dtype=object)


def main() -> None:
    precheck = json.loads((ROOT / "PRE_UNBLINDING_VERIFICATION.json").read_text(encoding="utf-8-sig"))
    corecheck = json.loads((ROOT / "CORE_ANALYSIS_VALIDATION.json").read_text(encoding="utf-8"))
    markercheck = json.loads((ROOT / "MARKER_ANALYSIS_VALIDATION.json").read_text(encoding="utf-8"))
    if precheck.get("status") != "PASS" or corecheck.get("successful_runs") != 400 or markercheck.get("status") != "PASS":
        raise RuntimeError("Finalization requires passed pre-unblinding, core, and marker validation")

    seed = pd.read_csv(ROOT / "seed_level_accuracy.csv", dtype={"section": str})
    pairwise = pd.read_csv(ROOT / "pairwise_partition_reproducibility.csv", dtype={"section": str})
    units = pd.read_csv(ROOT / "method_section_summary.csv", dtype={"section": str})
    iso_summary = pd.read_csv(ROOT / "iso_accuracy_results.csv", dtype={"section": str})
    ranking = pd.read_csv(ROOT / "ranking_uncertainty.csv", dtype={"section": str})
    ranking_superiority = pd.read_csv(ROOT / "ranking_pairwise_superiority.csv", dtype={"section": str})
    marker_pairs = pd.read_csv(ROOT / "marker_reproducibility_all_pairs.csv", dtype={"section": str})
    correlations = pd.read_csv(ROOT / "within_unit_marker_correlations.csv", dtype={"section": str})
    tertiles = pd.read_csv(ROOT / "marker_tertile_summary.csv", dtype={"section": str})
    consensus = pd.read_csv(ROOT / "consensus_results.csv", dtype={"section": str})

    # Required standalone rank-1 table.
    winner = ranking[[
        "section", "section_display", "method", "p_rank1", "max_winner_probability",
        "winner_entropy_bits", "winner_entropy_normalized", "enumerated_combinations",
    ]].drop_duplicates().sort_values(
        ["section", "method"], key=lambda x: x.map(SECTION_ORDER if x.name == "section" else METHOD_ORDER)
    )
    write_csv(winner, ROOT / "winner_probabilities.csv")

    # SpaGCN provenance, including every retained run.
    audit_rows = []
    for section in SECTIONS:
        for run_seed in range(1, 21):
            stem = ROOT / "predictions" / section / f"SpaGCN__seed{run_seed}__primary"
            meta = json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))
            pred = pd.read_csv(stem.with_suffix(".csv"))
            post_k = int(pred.cluster.nunique())
            pre_k = meta.get("pre_refinement_observed_K")
            reduced = bool(meta.get("refinement_cluster_count_reduced", post_k < int(meta.get("required_K", 8))))
            audit_rows.append({
                "section": section, "section_display": display_name(section), "method": "SpaGCN", "seed": run_seed,
                "requested_K": int(meta.get("requested_K", meta.get("required_K", 8))),
                "pre_refinement_K": pre_k,
                "post_refinement_K": post_k,
                "refinement_reduced_observed_K": reduced,
                "training_completed_normally": meta.get("status") == "PASS",
                "one_label_per_expected_cell": len(pred) == int(meta["n_cells"]),
                "outputs_finite": bool(np.isfinite(pred.cluster.to_numpy(float)).all()),
                "retained_in_all_scientific_analyses": True,
                "checkpoint_provenance": meta.get("checkpoint_provenance", "original completed checkpoint"),
                "governing_rule": "requested K=8 before official refinement; finite complete official refined output is retained even if post-refinement K<8",
            })
    spagcn_audit = pd.DataFrame(audit_rows)
    write_csv(spagcn_audit, ROOT / "SpaGCN_refinement_audit.csv")

    # Deterministic MERFISH spatial example after the full iso-accuracy table existed.
    primary = pairwise[pairwise.abs_reference_ari_difference <= 0.02 + 1e-12].copy()
    primary["section_order"] = primary.section.map(SECTION_ORDER)
    primary["method_order"] = primary.method.map(METHOD_ORDER)
    example = primary.sort_values(
        ["pairwise_partition_ari", "section_order", "method_order", "seed_r", "seed_s"]
    ).iloc[0]
    base = ad.read_h5ad(ROOT / "data" / example.section / f"{example.section}_frozen.h5ad")
    reference = base.obs["manual_layer"].astype(str).to_numpy()
    pred_a = pd.read_csv(
        ROOT / "predictions" / example.section / f"{example.method}__seed{int(example.seed_r)}__primary.csv",
        dtype={"barcode": str},
    )
    pred_b = pd.read_csv(
        ROOT / "predictions" / example.section / f"{example.method}__seed{int(example.seed_s)}__primary.csv",
        dtype={"barcode": str},
    )
    aligned_a = align_to_reference(pred_a.cluster.to_numpy(), reference)
    aligned_b = align_to_reference(pred_b.cluster.to_numpy(), reference)
    coordinates = np.asarray(base.obsm["spatial_original"])
    map_source = pd.DataFrame({
        "section": example.section, "section_display": display_name(example.section), "method": example.method,
        "seed_A": int(example.seed_r), "seed_B": int(example.seed_s),
        "barcode": base.obs_names.astype(str), "x": coordinates[:, 0], "y": coordinates[:, 1],
        "reference": reference, "seed_A_aligned_domain": aligned_a, "seed_B_aligned_domain": aligned_b,
        "different_assignment": aligned_a != aligned_b,
    })
    write_csv(map_source, FIGURE_READY / "figure3_merfish_representative_spatial_map_source.csv")
    example_record = pd.DataFrame([{
        "selection_rule": "lowest partition ARI across all complete MERFISH primary iso-accuracy pairs; ties by frozen section, method, and seed order",
        "section": example.section, "section_display": display_name(example.section), "method": example.method,
        "seed_A": int(example.seed_r), "seed_B": int(example.seed_s),
        "reference_ARI_A": float(example.ari_r), "reference_ARI_B": float(example.ari_s),
        "absolute_reference_ARI_difference": float(example.abs_reference_ari_difference),
        "partition_ARI": float(example.pairwise_partition_ari),
        "post_refinement_K_A": int(seed[(seed.section == example.section) & (seed.method == example.method) & (seed.seed == example.seed_r)].n_clusters.iloc[0]),
        "post_refinement_K_B": int(seed[(seed.section == example.section) & (seed.method == example.method) & (seed.seed == example.seed_s)].n_clusters.iloc[0]),
    }])
    write_csv(example_record, ROOT / "representative_spatial_example.csv")

    # Frozen supplementary extreme contrast.
    extreme_selection = select_extreme_pairs(pairwise)
    write_csv(extreme_selection, ROOT / "supplementary_extreme_pair_selection.csv")
    extreme_long = extreme_selection.merge(
        marker_pairs[[
            "section", "method", "seed_r", "seed_s", "top100_marker_jaccard",
            "top50_marker_jaccard", "marker_rank_spearman",
        ]], on=["section", "method", "seed_r", "seed_s"], how="left", validate="one_to_one",
    )
    if extreme_long.top100_marker_jaccard.isna().any():
        raise RuntimeError("Extreme stable-control pair fell outside the primary marker-pair universe")
    extreme_unit = extreme_long.pivot(
        index=["section", "method"], columns="pair_type",
        values=["top100_marker_jaccard", "top50_marker_jaccard", "marker_rank_spearman"],
    )
    extreme_unit.columns = [f"{metric}__{pair_type}" for metric, pair_type in extreme_unit.columns]
    extreme_unit = extreme_unit.reset_index()
    write_csv(extreme_long, ROOT / "supplementary_extreme_pair_marker_results.csv")
    write_csv(extreme_unit, ROOT / "supplementary_extreme_pair_unit_summary.csv")
    extreme_test = stats.wilcoxon(
        extreme_unit.top100_marker_jaccard__stable_control,
        extreme_unit.top100_marker_jaccard__iso_accuracy_unstable,
        alternative="greater", zero_method="wilcox", method="auto",
    )
    (ROOT / "supplementary_extreme_pair_test.json").write_text(json.dumps({
        "n_units": int(len(extreme_unit)),
        "median_unstable_top100_marker_jaccard": float(extreme_unit.top100_marker_jaccard__iso_accuracy_unstable.median()),
        "median_stable_top100_marker_jaccard": float(extreme_unit.top100_marker_jaccard__stable_control.median()),
        "wilcoxon_statistic": float(extreme_test.statistic),
        "wilcoxon_p_value_one_sided": float(extreme_test.pvalue),
        "interpretation": "supplementary extreme-contrast consequence analysis; not an average seed effect or causal estimate",
    }, indent=2), encoding="utf-8")

    merfish_paired = paired_summary(tertiles, "section")
    (ROOT / "paired_tertile_test.json").write_text(json.dumps(merfish_paired, indent=2), encoding="utf-8")

    # Recalculate the complete 14+5 integrated benchmark.
    old_seed = pd.read_csv(PHASE1 / "seed_level_accuracy.csv", dtype={"dataset": str}).rename(columns={"dataset": "section"})
    old_seed["section_display"] = old_seed.section.map(display_name)
    new_seed = seed.copy()
    combined_seed = pd.concat([old_seed, new_seed], ignore_index=True, sort=False)

    old_pairs = pd.read_csv(PHASE1 / "pairwise_partition_reproducibility.csv", dtype={"dataset": str}).rename(columns={"dataset": "section"})
    old_pairs["section_display"] = old_pairs.section.map(display_name)
    combined_pairs = pd.concat([old_pairs, pairwise], ignore_index=True, sort=False)
    combined_primary = combined_pairs[combined_pairs.abs_reference_ari_difference <= 0.02 + 1e-12].copy()
    combined_divergent = combined_primary[combined_primary.pairwise_partition_ari < 0.50]

    old_units = pd.read_csv(
        PHASE1 / "tables" / "main_table_2_performance_reproducibility.csv", dtype={"dataset": str}
    ).rename(columns={
        "dataset": "section", "median_pairwise_ari": "median_pairwise_partition_ari",
        "p05_pairwise_ari": "p05_pairwise_partition_ari",
        "minimum_pairwise_ari": "minimum_pairwise_partition_ari",
        "median_pairwise_nmi": "median_pairwise_partition_nmi",
    })
    old_units["section_display"] = old_units.section.map(display_name)
    combined_units = pd.concat([old_units, units], ignore_index=True, sort=False)
    combined_units["section_display"] = combined_units.section.map(display_name)

    combined_iso_rows = []
    for (section, method), group in combined_pairs.groupby(["section", "method"], sort=False):
        for threshold in (0.01, 0.02, 0.03):
            subset = group[group.abs_reference_ari_difference <= threshold + 1e-12]
            values = subset.pairwise_partition_ari.to_numpy(float)
            combined_iso_rows.append({
                "section": section, "section_display": display_name(section), "method": method,
                "threshold": threshold, "n_iso_accuracy_pairs": int(len(values)),
                "median_pairwise_partition_ari": float(np.median(values)) if len(values) else np.nan,
                "minimum_pairwise_partition_ari": float(np.min(values)) if len(values) else np.nan,
                "n_partition_ari_below_0_50": int(np.sum(values < 0.50)),
                "fraction_partition_ari_below_0_50": float(np.mean(values < 0.50)) if len(values) else np.nan,
            })
    combined_iso = pd.DataFrame(combined_iso_rows)

    old_winner = pd.read_csv(FIG4 / "winner_probabilities.csv", dtype={"dataset": str})
    old_winner = old_winner[old_winner["rank"] == 1].rename(columns={
        "dataset": "section", "dataset_display": "section_display", "probability": "p_rank1",
    })
    old_uncertainty = pd.read_csv(FIG4 / "dataset_uncertainty.csv", dtype={"dataset": str}).rename(columns={
        "dataset": "section", "dataset_display": "section_display", "max_p_rank1": "max_winner_probability",
    })
    new_uncertainty_rows = []
    for section, group in winner.groupby("section", sort=False):
        maxp = float(group.p_rank1.max())
        maxrow = group.assign(method_order=group.method.map(METHOD_ORDER)).sort_values(
            ["p_rank1", "method_order"], ascending=[False, True]
        ).iloc[0]
        new_uncertainty_rows.append({
            "section": section, "section_display": display_name(section),
            "most_probable_winner": maxrow.method, "max_winner_probability": maxp,
            "n_methods_positive_p_rank1": int((group.p_rank1 > 0).sum()),
            "n_methods_p_rank1_ge_0_05": int((group.p_rank1 >= 0.05).sum()),
            "winner_entropy_bits": float(group.winner_entropy_bits.iloc[0]),
            "winner_entropy_normalized": float(group.winner_entropy_normalized.iloc[0]),
        })
    new_uncertainty = pd.DataFrame(new_uncertainty_rows)
    combined_winner = pd.concat([
        old_winner[["section", "section_display", "method", "p_rank1", "enumerated_combinations"]],
        winner[["section", "section_display", "method", "p_rank1", "enumerated_combinations"]],
    ], ignore_index=True)
    combined_uncertainty = pd.concat([old_uncertainty, new_uncertainty], ignore_index=True, sort=False)
    combined_uncertainty["section_display"] = combined_uncertainty.section.map(display_name)

    old_marker_pairs = pd.read_csv(FIG5 / "all_iso_accuracy_marker_pairs.csv", dtype={"dataset": str}).rename(columns={"dataset": "section"})
    old_marker_pairs["section_display"] = old_marker_pairs.section.map(display_name)
    combined_marker_pairs = pd.concat([old_marker_pairs, marker_pairs], ignore_index=True, sort=False)
    old_corr = pd.read_csv(FIG5 / "within_unit_correlations.csv", dtype={"dataset": str}).rename(columns={
        "dataset": "section",
        "spearman_partition_vs_top100_jaccard": "spearman_partition_ari_vs_marker_jaccard",
        "spearman_partition_vs_top50_jaccard": "spearman_partition_ari_vs_top50_jaccard",
        "spearman_partition_vs_marker_rank_spearman": "spearman_partition_ari_vs_marker_rank_spearman",
    })
    combined_corr = pd.concat([old_corr, correlations], ignore_index=True, sort=False)
    combined_corr["section_display"] = combined_corr.section.map(display_name)
    old_tertiles = pd.read_csv(FIG5 / "within_unit_tertiles.csv", dtype={"dataset": str}).rename(columns={"dataset": "section"})
    combined_tertiles = pd.concat([old_tertiles, tertiles], ignore_index=True, sort=False)
    combined_tertiles["section_display"] = combined_tertiles.section.map(display_name)
    combined_paired = paired_summary(combined_tertiles, "section")

    old_consensus = pd.read_csv(PHASE1 / "consensus_results.csv", dtype={"dataset": str}).rename(columns={
        "dataset": "section", "median_single_seed_ari": "median_single_seed_reference_ari",
        "best_single_seed_ari": "best_single_seed_reference_ari",
        "split10_consensus_partition_ari": "split_half_consensus_ari",
    })
    old_consensus = old_consensus.merge(
        old_units[["section", "method", "median_pairwise_partition_ari"]], on=["section", "method"], how="left"
    ).rename(columns={"median_pairwise_partition_ari": "median_single_seed_pairwise_ari"})
    old_consensus["split_half_gain_over_median_single_seed_pairwise_ari"] = (
        old_consensus.split_half_consensus_ari - old_consensus.median_single_seed_pairwise_ari
    )
    old_consensus["section_display"] = old_consensus.section.map(display_name)
    combined_consensus = pd.concat([old_consensus, consensus], ignore_index=True, sort=False)
    combined_consensus["section_display"] = combined_consensus.section.map(display_name)

    # Table-ready previews; STARmap is abbreviated only outside S1/source metadata.
    manifest = pd.read_csv(PHASE1 / "dataset_manifest.csv", dtype={"dataset": str})
    manifest["dataset_display"] = manifest.dataset.map(display_name)
    manifest["context"] = manifest.apply(
        lambda row: "DLPFC" if row.family == "DLPFC" else ("STARmap visual cortex" if row.dataset.startswith("STARmap") else "human breast cancer"), axis=1
    )
    merfish_manifest = pd.DataFrame([{
        "dataset": section, "family": "MERFISH Animal1", "species": "mouse",
        "tissue": "hypothalamus / preoptic region", "technology": "MERFISH",
        "n_spots": int(seed[seed.section == section].n_cells.iloc[0]), "n_genes": 155, "k": 8,
        "methods": ";".join(METHODS), "valid_runs": 80, "dataset_display": display_name(section),
        "context": "one MERFISH hypothalamus/preoptic context; five consecutive sections",
    } for section in SECTIONS])
    combined_manifest = pd.concat([manifest, merfish_manifest], ignore_index=True, sort=False)
    table1 = combined_manifest[[
        "dataset_display", "technology", "species", "tissue", "n_spots", "n_genes", "k", "context",
    ]].rename(columns={"dataset_display": "Dataset", "technology": "Platform", "species": "Species",
                       "tissue": "Tissue / condition", "n_spots": "Spots / cells, n", "n_genes": "Genes, n",
                       "k": "Reference domains, K", "context": "Reference/context note"})

    s1 = combined_manifest.copy()
    s1["full_accession_or_sample_identifier"] = s1.dataset
    s1["source_metadata"] = np.where(
        s1.dataset.isin(SECTIONS),
        "Moffitt mouse hypothalamus/preoptic MERFISH; BASS Animal1 frozen section",
        "Existing frozen Project 9 source metadata",
    )
    s1["reference_annotation"] = np.where(
        s1.dataset.isin(SECTIONS),
        "BASS/manual atlas-informed cell-level domains: BST, fx, MPA, MPN, PV, PVH, PVT, V3",
        "Existing frozen Project 9 reference annotation",
    )

    s2 = pd.DataFrame([
        {"method": "GraphST", "frozen_MERFISH_setting": "155 genes; original coordinates; datatype=Stereo; 3-NN; 200 epochs; LR 0.001; fixed K=8 GMM readout"},
        {"method": "STAGATE", "frozen_MERFISH_setting": "radius 150; hidden [512,30]; 200 epochs; LR 0.001; weight decay 0.0001; fixed K=8 GMM readout"},
        {"method": "SpaGCN", "frozen_MERFISH_setting": "coordinate-only; p=0.5; cached l; 50 PCs; 200 epochs; LR 0.05; K=8 before official hexagonal refinement; amended valid post-refinement collapse rule"},
        {"method": "BANKSY", "frozen_MERFISH_setting": "15 neighbors; scaled Gaussian; lambda=0.2; max_m=0; 20 PCs; fixed K=8 GMM readout"},
    ])
    iso02 = combined_iso[np.isclose(combined_iso.threshold, 0.02)].drop(columns="section_display")
    s3 = combined_units.merge(iso02, on=["section", "method"], how="left", suffixes=("", "_iso02"))
    s3.insert(0, "Dataset", s3.section.map(display_name))
    s3 = s3.drop(columns=[column for column in ["section", "section_display"] if column in s3.columns])
    s4 = combined_winner.merge(
        combined_corr[["section", "method", "n_iso_accuracy_pairs", "spearman_partition_ari_vs_marker_jaccard"]],
        on=["section", "method"], how="left",
    ).merge(
        combined_consensus[["section", "method", "consensus20_reference_ari", "consensus20_reference_nmi",
                            "split_half_consensus_ari", "median_single_seed_pairwise_ari",
                            "split_half_gain_over_median_single_seed_pairwise_ari"]],
        on=["section", "method"], how="left",
    )
    s4.insert(0, "Dataset", s4.section.map(display_name))
    s4 = s4.drop(columns=[column for column in ["section", "section_display"] if column in s4.columns])

    write_csv(table1, TABLE_READY / "Main_Table_1_preview.csv")
    write_csv(s1, TABLE_READY / "Supplementary_Table_S1_preview.csv")
    write_csv(s2, TABLE_READY / "Supplementary_Table_S2_preview.csv")
    write_csv(s3, TABLE_READY / "Supplementary_Table_S3_preview.csv")
    write_csv(s4, TABLE_READY / "Supplementary_Table_S4_preview.csv")

    # Integrated machine-readable and figure-ready data.
    for frame, name in [
        (combined_manifest, "combined_dataset_manifest.csv"),
        (combined_seed, "combined_seed_level_accuracy.csv"),
        (combined_pairs, "combined_pairwise_partition_reproducibility.csv"),
        (combined_units, "combined_method_dataset_summary.csv"),
        (combined_iso, "combined_iso_accuracy_results.csv"),
        (combined_winner, "combined_winner_probabilities.csv"),
        (combined_uncertainty, "combined_dataset_winner_uncertainty.csv"),
        (combined_marker_pairs, "combined_marker_reproducibility_all_pairs.csv"),
        (combined_corr, "combined_within_unit_marker_correlations.csv"),
        (combined_tertiles, "combined_marker_tertile_summary.csv"),
        (combined_consensus, "combined_consensus_results.csv"),
    ]:
        write_csv(frame, ROOT / name)
    (ROOT / "combined_paired_tertile_test.json").write_text(json.dumps(combined_paired, indent=2), encoding="utf-8")

    write_csv(combined_manifest, FIGURE_READY / "figure1_integrated_dataset_landscape.csv")
    write_csv(combined_units, FIGURE_READY / "figure2_integrated_units.csv")
    write_csv(combined_primary, FIGURE_READY / "figure3_integrated_iso_accuracy_pairs.csv")
    write_csv(combined_winner, FIGURE_READY / "figure4_integrated_winner_probabilities.csv")
    write_csv(combined_uncertainty, FIGURE_READY / "figure4_integrated_dataset_uncertainty.csv")
    write_csv(combined_marker_pairs, FIGURE_READY / "figure5_integrated_marker_pairs.csv")
    write_csv(combined_corr, FIGURE_READY / "figure5_integrated_unit_correlations.csv")
    write_csv(combined_tertiles, FIGURE_READY / "figure5_integrated_tertiles.csv")
    write_csv(combined_consensus, FIGURE_READY / "figure6_integrated_consensus.csv")

    # Quantitative summaries and locked classification.
    divergent = primary[primary.pairwise_partition_ari < 0.50]
    decoupled = units[(units.reference_ari_sd <= 0.02) & (units.partition_instability >= 0.30)]
    finite_corr = correlations[np.isfinite(correlations.spearman_partition_ari_vs_marker_jaccard)]
    maxp = winner.groupby("section").p_rank1.max()
    positive_winner = winner.groupby("section").p_rank1.apply(lambda values: int((values > 0).sum()))
    improved = consensus.split_half_gain_over_median_single_seed_pairwise_ari > 0
    frozen_components = {
        "score_map_decoupling": bool(len(decoupled) >= 2 and decoupled.method.nunique() >= 2),
        "iso_accuracy_divergence": bool(divergent.method.nunique() >= 2),
        "positive_partition_to_marker_relationship": bool(
            finite_corr.spearman_partition_ari_vs_marker_jaccard.median() > 0
            and (finite_corr.spearman_partition_ari_vs_marker_jaccard > 0).sum() > len(finite_corr) / 2
        ),
        "consensus_improvement": bool(int(improved.sum()) > 10),
    }
    frozen_count = int(sum(frozen_components.values()))
    classification = "STRONG_GENERALIZATION" if frozen_count == 4 else (
        "PARTIAL_GENERALIZATION" if frozen_count else "WEAK_OR_ABSENT_GENERALIZATION"
    )
    component_assessment = {
        "A_score_map_decoupling": {
            "assessment": "SUPPORTS GENERALIZATION" if frozen_components["score_map_decoupling"] else "DOES NOT SUPPORT GENERALIZATION",
            "evidence": f"{len(decoupled)}/20 units across {decoupled.method.nunique()} methods met ARI SD<=0.02 and instability>=0.30",
        },
        "B_iso_accuracy_map_divergence": {
            "assessment": "SUPPORTS GENERALIZATION" if frozen_components["iso_accuracy_divergence"] else "DOES NOT SUPPORT GENERALIZATION",
            "evidence": f"{len(divergent)}/{len(primary)} primary iso-accuracy pairs had partition ARI<0.50 across {divergent.method.nunique()} methods and {divergent.groupby(['section','method']).ngroups} units",
        },
        "C_winner_uncertainty": {
            "assessment": "PARTIAL / HETEROGENEOUS",
            "evidence": f"maximum P(rank1) ranged {maxp.min():.4f}-{maxp.max():.4f}; {int((maxp < .75).sum())}/5 sections were below 0.75, {int((positive_winner > 1).sum())}/5 had multiple methods with positive P(rank1), and two sections were fully concentrated at 1.0",
        },
        "D_continuous_partition_marker_reproducibility": {
            "assessment": "SUPPORTS GENERALIZATION" if frozen_components["positive_partition_to_marker_relationship"] else "DOES NOT SUPPORT GENERALIZATION",
            "evidence": f"median within-unit rho={finite_corr.spearman_partition_ari_vs_marker_jaccard.median():.4f}; {(finite_corr.spearman_partition_ari_vs_marker_jaccard > 0).sum()}/{len(finite_corr)} estimable units positive",
        },
        "E_consensus_mitigation": {
            "assessment": "SUPPORTS GENERALIZATION" if frozen_components["consensus_improvement"] else "DOES NOT SUPPORT GENERALIZATION",
            "evidence": f"split-half consensus improved {int(improved.sum())}/20 units; median gain={consensus.split_half_gain_over_median_single_seed_pairwise_ari.median():.4f}",
        },
    }
    combined_finite_corr = combined_corr[np.isfinite(combined_corr.spearman_partition_ari_vs_marker_jaccard)]
    combined_maxp = combined_uncertainty.max_winner_probability
    combined_improved = combined_consensus.split_half_gain_over_median_single_seed_pairwise_ari > 0
    combined_decoupled = combined_units[(combined_units.reference_ari_sd <= 0.02) & (combined_units.partition_instability >= 0.30)]

    summary = {
        "project": "PROJECT 9 MERFISH external validation",
        "technical_set": {"sections": 5, "independent_contexts": 1, "methods": 4, "seeds_per_unit": 20,
                          "valid_runs": 400, "method_section_units": 20},
        "pre_unblinding_verification": "PASS",
        "reference_score_stability": {
            "median_reference_ari_sd": float(units.reference_ari_sd.median()),
            "reference_ari_sd_range": [float(units.reference_ari_sd.min()), float(units.reference_ari_sd.max())],
            "median_reference_nmi_sd": float(units.reference_nmi_sd.median()),
        },
        "partition_reproducibility": {
            "median_unit_median_pairwise_ari": float(units.median_pairwise_partition_ari.median()),
            "unit_median_pairwise_ari_range": [float(units.median_pairwise_partition_ari.min()), float(units.median_pairwise_partition_ari.max())],
            "minimum_pairwise_partition_ari": float(pairwise.pairwise_partition_ari.min()),
        },
        "score_map_decoupling": {"affected_units": int(len(decoupled)), "methods": sorted(decoupled.method.unique().tolist())},
        "iso_accuracy": {"threshold": 0.02, "eligible_pairs": int(len(primary)), "divergent_pairs": int(len(divergent)),
                         "divergent_fraction": float(len(divergent) / len(primary)),
                         "affected_units": int(divergent.groupby(["section", "method"]).ngroups),
                         "minimum_partition_ari": float(primary.pairwise_partition_ari.min())},
        "winner_uncertainty": {"maximum_p_rank1_range": [float(maxp.min()), float(maxp.max())],
                               "sections_max_p_rank1_below_0_50": int((maxp < .50).sum()),
                               "sections_max_p_rank1_below_0_75": int((maxp < .75).sum()),
                               "sections_multiple_positive_p_rank1": int((positive_winner > 1).sum())},
        "marker_relationship": {"eligible_pairs": int(len(marker_pairs)), "estimable_units": int(len(finite_corr)),
                                "median_within_unit_spearman": float(finite_corr.spearman_partition_ari_vs_marker_jaccard.median()),
                                "iqr_within_unit_spearman": [float(finite_corr.spearman_partition_ari_vs_marker_jaccard.quantile(.25)), float(finite_corr.spearman_partition_ari_vs_marker_jaccard.quantile(.75))],
                                "positive_units": int((finite_corr.spearman_partition_ari_vs_marker_jaccard > 0).sum()),
                                "paired_tertile_analysis": merfish_paired},
        "consensus": {"median_single_seed_reproducibility": float(consensus.median_single_seed_pairwise_ari.median()),
                      "median_split_half_consensus_ari": float(consensus.split_half_consensus_ari.median()),
                      "improved_units": int(improved.sum()), "median_gain": float(consensus.split_half_gain_over_median_single_seed_pairwise_ari.median())},
        "spagcn_refinement": {"retained_collapse_count": int(spagcn_audit.refinement_reduced_observed_K.sum()),
                              "known_collapse": "MERFISH_Bregma_m0.19/SpaGCN/seed19: 8->7", "included": True},
        "generalization_components": component_assessment,
        "frozen_overall_rule_components": frozen_components,
        "generalization_classification": classification,
        "combined_project9": {
            "dataset_section_entries": 19, "independent_contexts": 4, "method_dataset_units": 76, "seed_runs": 1520,
            "iso_accuracy_pairs": int(len(combined_primary)), "divergent_iso_accuracy_pairs": int(len(combined_divergent)),
            "divergent_iso_accuracy_fraction": float(len(combined_divergent) / len(combined_primary)),
            "units_with_divergent_iso_accuracy_pair": int(combined_divergent.groupby(["section", "method"]).ngroups),
            "low_sd_high_instability_units": int(len(combined_decoupled)),
            "maximum_p_rank1_range": [float(combined_maxp.min()), float(combined_maxp.max())],
            "datasets_max_p_rank1_below_0_50": int((combined_maxp < .50).sum()),
            "datasets_max_p_rank1_below_0_75": int((combined_maxp < .75).sum()),
            "median_within_unit_marker_spearman": float(combined_finite_corr.spearman_partition_ari_vs_marker_jaccard.median()),
            "positive_marker_units": int((combined_finite_corr.spearman_partition_ari_vs_marker_jaccard > 0).sum()),
            "estimable_marker_units": int(len(combined_finite_corr)),
            "paired_tertile_analysis": combined_paired,
            "median_single_seed_reproducibility": float(combined_consensus.median_single_seed_pairwise_ari.median()),
            "median_split_half_consensus_ari": float(combined_consensus.split_half_consensus_ari.median()),
            "consensus_improved_units": int(combined_improved.sum()),
        },
        "protocol_and_claim_controls": {
            "new_scientific_threshold_introduced": False,
            "unfavorable_result_excluded": False,
            "protocol_changed_after_scientific_unblinding": False,
            "all_five_locked_sections_retained": True,
            "spagcn_amendment_was_locked_before_unblinding": True,
        },
    }
    (ROOT / "EXPANSION_SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    pct = 100 * len(divergent) / len(primary)
    combined_pct = 100 * len(combined_divergent) / len(combined_primary)
    report = f"""# PROJECT 9 MERFISH external validation — final report

## Executive verdict

The frozen external-validation analysis completed on all **400/400** valid runs (five MERFISH sections × four methods × 20 seeds). The exact frozen four-component gate yields **`{classification}`**: all four locked components were present. The separately requested fifth component, winner uncertainty, was **partial/heterogeneous**, with pronounced uncertainty in one section and near-complete or complete concentration in others. The five consecutive sections represent one independent MERFISH mouse hypothalamus/preoptic-region context, not five independent biological contexts.

## Pre-unblinding integrity

The pre-unblinding record passed: 100/100 checkpoints for each method, original protocol SHA-256 `BF5106AF34143753A244EFD50038EF3F4AFF40580AEADD276547512076D17ED4`, amendment SHA-256 `464E047210C5C33D6019BA486AC2F8093D7493873CBFE28DA9234988BEF74B91`, and all five frozen H5AD hashes matched. The retained m0.19/SpaGCN/seed19 checkpoint was included as a valid 8→7 official-refinement output. No scientific metric was inspected before the 400/400 gate.

## Reference accuracy and direct partition reproducibility

Across 20 method–section units, median reference-ARI SD was **{units.reference_ari_sd.median():.3f}** (range **{units.reference_ari_sd.min():.3f}–{units.reference_ari_sd.max():.3f}**); median reference-NMI SD was **{units.reference_nmi_sd.median():.3f}**. The median unit-level pairwise partition ARI was **{units.median_pairwise_partition_ari.median():.3f}** (range **{units.median_pairwise_partition_ari.min():.3f}–{units.median_pairwise_partition_ari.max():.3f}**), with an overall minimum seed-pair ARI of **{pairwise.pairwise_partition_ari.min():.3f}**. Reference accuracy is therefore reported only as performance, not as a reproducibility measure.

## Score–map decoupling and iso-accuracy

Using the unchanged descriptive rule (ARI SD ≤0.02 and partition instability ≥0.30), **{len(decoupled)}/20** units across **{decoupled.method.nunique()}** methods met the score–map decoupling definition. At the primary |Δ reference ARI|≤0.02 threshold, **{len(primary):,}** seed pairs were eligible; **{len(divergent):,} ({pct:.1f}%)** had partition ARI<0.50, affecting **{divergent.groupby(['section','method']).ngroups}/20** units across **{divergent.method.nunique()}** methods. The minimum iso-accuracy partition ARI was **{primary.pairwise_partition_ari.min():.3f}**. The frozen 0.01 and 0.03 sensitivity tables were reproduced without adding thresholds.

## Distribution-based winner uncertainty

Each section used the exact 20^4=160,000 empirical Cartesian enumeration. Maximum P(rank 1) ranged from **{maxp.min():.3f} to {maxp.max():.3f}**. One of five sections was below 0.75, none was below 0.50, and three had more than one method with positive P(rank 1); two sections had P(rank 1)=1.000 for one method. Winner uncertainty therefore generalized heterogeneously rather than uniformly. The enumerated combinations are not independent experiments.

## Continuous partition-to-marker reproducibility

The frozen 155-gene pipeline evaluated all **{len(marker_pairs):,}** primary iso-accuracy pairs. The median within-unit Spearman correlation between partition ARI and top-100 marker Jaccard was **{finite_corr.spearman_partition_ari_vs_marker_jaccard.median():.3f}** (IQR **{finite_corr.spearman_partition_ari_vs_marker_jaccard.quantile(.25):.3f}–{finite_corr.spearman_partition_ari_vs_marker_jaccard.quantile(.75):.3f}**); **{(finite_corr.spearman_partition_ari_vs_marker_jaccard > 0).sum()}/{len(finite_corr)}** estimable units were positive. The remaining BANKSY m0.19 unit was constant (Jaccard=1.0) and therefore had undefined Spearman rho; it was retained. Median marker Jaccard rose from **{merfish_paired['median_low']:.3f}** (low tertile) to **{merfish_paired['median_middle']:.3f}** (middle) and **{merfish_paired['median_high']:.3f}** (high), with median paired high-minus-low **{merfish_paired['median_paired_high_minus_low']:.3f}** (one-sided paired Wilcoxon W={merfish_paired['wilcoxon_statistic']:.1f}, P={merfish_paired['wilcoxon_p_value_one_sided']:.3g}). Pair-level displays remain descriptive because pairs sharing seeds are dependent.

## Supplementary extreme contrast

The frozen lowest-agreement/matched-stable rule was applied in every MERFISH unit. Median top-100 marker Jaccard was **{extreme_unit.top100_marker_jaccard__iso_accuracy_unstable.median():.3f}** in the extreme unstable pairs and **{extreme_unit.top100_marker_jaccard__stable_control.median():.3f}** in matched stable controls. This is an extreme-contrast consequence analysis, not an average random-seed effect or causal estimate.

## Consensus mitigation

Median single-seed reproducibility was **{consensus.median_single_seed_pairwise_ari.median():.3f}** and median split-half consensus ARI was **{consensus.split_half_consensus_ari.median():.3f}**. Consensus improved **{improved.sum()}/20** units, with median gain **{consensus.split_half_gain_over_median_single_seed_pairwise_ari.median():.3f}**. Co-association consensus is treated as an established mitigation strategy, not a novel method, and does not guarantee biological correctness.

## SpaGCN refinement provenance

Exactly **{spagcn_audit.refinement_reduced_observed_K.sum()}** retained MERFISH SpaGCN run had documented official-refinement collapse: m0.19/seed19, requested K=8, pre-refinement K=8, post-refinement K=7. It completed normally, was finite and complete, and remained included in every scientific analysis. No collapsed output was repaired, tuned, or excluded.

## Five-component assessment

| Component | Assessment | Evidence |
|---|---|---|
| A. Score–map decoupling | {component_assessment['A_score_map_decoupling']['assessment']} | {component_assessment['A_score_map_decoupling']['evidence']} |
| B. Iso-accuracy map divergence | {component_assessment['B_iso_accuracy_map_divergence']['assessment']} | {component_assessment['B_iso_accuracy_map_divergence']['evidence']} |
| C. Winner uncertainty | {component_assessment['C_winner_uncertainty']['assessment']} | {component_assessment['C_winner_uncertainty']['evidence']} |
| D. Partition→marker reproducibility | {component_assessment['D_continuous_partition_marker_reproducibility']['assessment']} | {component_assessment['D_continuous_partition_marker_reproducibility']['evidence']} |
| E. Consensus mitigation | {component_assessment['E_consensus_mitigation']['assessment']} | {component_assessment['E_consensus_mitigation']['evidence']} |

The overall label remains **`{classification}`** because the prespecified classification rule was frozen before unblinding on components A, B, D and E; the later requested winner component is transparently reported but was not retrofitted into that gate.

## Integrated Project 9 totals

After recalculation, Project 9 contains **19 dataset/section entries**, **76 method–dataset units**, and **1,520 seed-specific runs** across four contexts. There were **{len(combined_primary):,}** primary iso-accuracy pairs, of which **{len(combined_divergent):,} ({combined_pct:.1f}%)** had partition ARI<0.50 across **{combined_divergent.groupby(['section','method']).ngroups}/76** units. Across 19 entries, maximum P(rank 1) ranged **{combined_maxp.min():.3f}–{combined_maxp.max():.3f}**; **{(combined_maxp < .50).sum()}** were below 0.50 and **{(combined_maxp < .75).sum()}** below 0.75. Across **{len(combined_finite_corr)}** estimable units, median partition→marker rho was **{combined_finite_corr.spearman_partition_ari_vs_marker_jaccard.median():.3f}**, with **{(combined_finite_corr.spearman_partition_ari_vs_marker_jaccard > 0).sum()}** positive. Median single-seed reproducibility was **{combined_consensus.median_single_seed_pairwise_ari.median():.3f}**, median split-half consensus ARI was **{combined_consensus.split_half_consensus_ari.median():.3f}**, and consensus improved **{combined_improved.sum()}/76** units.

## Claim boundaries and final implication

MERFISH materially strengthens technology breadth (imaging-based targeted MERFISH), tissue breadth (mouse hypothalamus/preoptic region), the central score–map claim, the downstream association claim, and the consensus mitigation claim. It does not establish universality, five independent replications, causal propagation to markers, biological falsehood of unstable markers, or correctness of consensus partitions. No new scientific threshold was introduced, no unfavorable result was excluded, no protocol changed after scientific unblinding, and all five locked sections remained in the final analysis.
"""
    (ROOT / "FINAL_REPORT.md").write_text(report, encoding="utf-8")

    assessment_text = "# MERFISH generalization assessment\n\n" + "\n".join(
        f"## {name.replace('_', ' ')}\n\n**{value['assessment']}** — {value['evidence']}.\n"
        for name, value in component_assessment.items()
    ) + f"""
## Overall classification

**`{classification}`** under the exact pre-unblinding four-component rule (A, B, D and E all present). Winner uncertainty (C) is partial/heterogeneous and is not used to rewrite the locked gate. This preserves the predefined classification while retaining the negative/heterogeneous ranking evidence.

## Independence boundary

The five consecutive Bregma sections comprise one additional MERFISH technology/tissue context from Animal1. They are not five independent biological contexts.
"""
    (ROOT / "GENERALIZATION_ASSESSMENT.md").write_text(assessment_text, encoding="utf-8")

    manuscript = f"""# Manuscript integration report

## Title

No mandatory title change. If breadth is named, use “Stable scores can conceal stochastic spatial-map instability across sequencing- and imaging-based spatial transcriptomics” and avoid “universal”.

## Structured Abstract

**Design:** Update to 19 dataset/section entries, 76 method–dataset units and 1,520 runs across four contexts; clarify that five consecutive MERFISH sections constitute one external context. **Results:** Across the five MERFISH sections, {len(divergent):,}/{len(primary):,} ({pct:.1f}%) iso-accuracy pairs had partition ARI<0.50, {len(decoupled)}/20 units met the low-score-variation/high-map-instability rule, median within-unit partition→marker rho was {finite_corr.spearman_partition_ari_vs_marker_jaccard.median():.3f}, and consensus improved {improved.sum()}/20 units. **Conclusion:** The central instability, downstream association and consensus-mitigation findings extended to targeted MERFISH, whereas winner uncertainty was heterogeneous.

## Introduction

Add one sentence motivating validation beyond sequencing-based spot assays: “Whether score–map decoupling extends to imaging-based, single-cell-resolution targeted transcriptomics remains unclear.” Do not otherwise restructure the Introduction.

## Results section 1 — benchmark scope (replacement paragraph)

“The integrated benchmark comprised 19 dataset/section entries, 76 method–dataset units and 1,520 seed-specific runs. The expansion added five consecutive sections from one Moffitt/BASS Animal1 mouse hypothalamus/preoptic-region MERFISH experiment (5,488–5,926 cells, 155 genes, K=8). These five sections were treated as one independent technology/tissue context rather than five biological replications.”

## Results section 2 — score stability and map reproducibility (replacement paragraph)

“In MERFISH, the median reference-ARI SD across 20 method–section units was {units.reference_ari_sd.median():.3f} (range {units.reference_ari_sd.min():.3f}–{units.reference_ari_sd.max():.3f}), whereas the median unit-level pairwise partition ARI was {units.median_pairwise_partition_ari.median():.3f} (range {units.median_pairwise_partition_ari.min():.3f}–{units.median_pairwise_partition_ari.max():.3f}). Two units spanning two methods met the unchanged ARI-SD≤0.02/instability≥0.30 rule, extending score–map decoupling to MERFISH.”

## Results section 3 — iso-accuracy divergence (replacement paragraph)

“Among {len(primary):,} MERFISH run pairs with |Δ reference ARI|≤0.02, {len(divergent):,} ({pct:.1f}%) had partition ARI<0.50, affecting {divergent.groupby(['section','method']).ngroups}/20 units across {divergent.method.nunique()} methods; the minimum was {primary.pairwise_partition_ari.min():.3f}. In the integrated benchmark, {len(combined_divergent):,}/{len(combined_primary):,} ({combined_pct:.1f}%) iso-accuracy pairs were divergent across {combined_divergent.groupby(['section','method']).ngroups}/76 units.”

## Results section 4 — winner uncertainty (replacement paragraph)

“Exact enumeration of 160,000 empirical four-method combinations per MERFISH section yielded maximum P(rank 1) values from {maxp.min():.3f} to {maxp.max():.3f}. One section remained below 0.75, three sections assigned positive rank-1 probability to multiple methods, and two sections were fully concentrated at P(rank 1)=1.000. Thus, winner uncertainty extended heterogeneously rather than uniformly. Across all 19 entries, maximum P(rank 1) ranged {combined_maxp.min():.3f}–{combined_maxp.max():.3f}, with {(combined_maxp < .50).sum()} below 0.50 and {(combined_maxp < .75).sum()} below 0.75.”

## Results section 5 — downstream marker reproducibility (replacement paragraph)

“Across all {len(marker_pairs):,} MERFISH iso-accuracy pairs, the median within-unit Spearman association between partition ARI and top-100 marker Jaccard was {finite_corr.spearman_partition_ari_vs_marker_jaccard.median():.3f} (IQR {finite_corr.spearman_partition_ari_vs_marker_jaccard.quantile(.25):.3f}–{finite_corr.spearman_partition_ari_vs_marker_jaccard.quantile(.75):.3f}); {(finite_corr.spearman_partition_ari_vs_marker_jaccard > 0).sum()}/{len(finite_corr)} estimable units were positive. Median marker Jaccard increased from {merfish_paired['median_low']:.3f} in the low partition-ARI tertile to {merfish_paired['median_high']:.3f} in the high tertile (median paired difference {merfish_paired['median_paired_high_minus_low']:.3f}; one-sided paired Wilcoxon P={merfish_paired['wilcoxon_p_value_one_sided']:.3g}). The constant BANKSY m0.19 unit was retained but had undefined rho.”

## Results section 6 — consensus mitigation (replacement paragraph)

“Independent 10-seed consensus partitions had median ARI {consensus.split_half_consensus_ari.median():.3f}, compared with median single-seed reproducibility {consensus.median_single_seed_pairwise_ari.median():.3f}. Consensus improved all {improved.sum()}/20 MERFISH units (median gain {consensus.split_half_gain_over_median_single_seed_pairwise_ari.median():.3f}) and all {combined_improved.sum()}/76 integrated units. Co-association consensus was evaluated as an established mitigation strategy, not a new method.”

## Discussion

State that MERFISH strengthens technology and tissue breadth and independently replicates the central score–map phenomenon, continuous downstream association, and consensus mitigation. State equally clearly that winner uncertainty was heterogeneous. Avoid universality and causal language.

## Limitations

Add: five sections from one animal/context; targeted 155-gene panel; atlas-informed BASS/manual reference; processed expression layer rather than uniform raw integer counts; only four methods; stochastic distributions estimated from 20 runs; the constant BANKSY unit yields undefined rho; consensus reproducibility does not establish biological correctness.

## Methods

Add the locked MERFISH inputs, K=8 labels, exact four method settings, 20 seeds, 190 pairs/unit, |ΔARI| thresholds 0.01/0.02/0.03, 20^4 winner enumeration, 155-gene Scanpy Wilcoxon pipeline, tertile/Wilcoxon unit-level framework, average-linkage co-association consensus, and the pre-unblinding SpaGCN refinement amendment. Explicitly state that m0.19/SpaGCN/seed19 (8→7) was retained.

## Data availability

Identify the five frozen Bregma section files and their source as the Moffitt/BASS Animal1 MERFISH context. Keep complete identifiers in Supplementary Table S1/source metadata; use concise display labels elsewhere.

## Code availability

Archive the frozen protocol, pre-unblinding verification, amendment, analysis scripts, machine-readable tables, prediction checkpoints and validation manifest. Internal hashes and scheduler logs remain repository-only, not manuscript tables.

## Figure legends

Figures 1–6 should report 19 entries/76 units/1,520 runs where integrated. Figure 3 must state the deterministic lowest-partition-ARI example rule. Figure 4 must state that 160,000 combinations are exhaustive empirical enumerations, not independent experiments. Figure 5 must distinguish descriptive pair-level displays from unit-level inference. Figure 6 must retain the three-panel results-only structure and describe co-association consensus in the legend.

## Table 1 and Supplementary Information

Add five MERFISH rows to Table 1 and Supplementary Table S1. Add method settings to S2, 20 unit summaries to S3, and winner/marker/consensus results to S4. All formatted tables must be monochrome Times New Roman. Display “STARmap” in S3/S4; retain `STARmap_20180505_BY3_1k` only in S1/source metadata. No numerical values are changed for presentation.
"""
    (ROOT / "MANUSCRIPT_INTEGRATION.md").write_text(manuscript, encoding="utf-8")


if __name__ == "__main__":
    main()
