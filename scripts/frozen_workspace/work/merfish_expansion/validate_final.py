from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd


WORKSPACE = Path(__file__).resolve().parents[2]
ROOT = WORKSPACE / "outputs" / "PROJECT9_MERFISH_EXPANSION"
METHODS = ["GraphST", "STAGATE", "SpaGCN", "BANKSY"]
SECTIONS = [
    "MERFISH_Bregma_m0.04", "MERFISH_Bregma_m0.09", "MERFISH_Bregma_m0.14",
    "MERFISH_Bregma_m0.19", "MERFISH_Bregma_m0.24",
]
INPUT_HASHES = {
    "MERFISH_Bregma_m0.04": "1369641CFABB62572C67AE2DB454F7E2FA65702B81E44365C2E772AFE2CA3F12",
    "MERFISH_Bregma_m0.09": "91E912D7F53E8C7A985B6F152BFB3982F975F3BF82ED135601D1D54C61522D48",
    "MERFISH_Bregma_m0.14": "F46C60973AE99E223A612B148DD068B8A9568E46702245703F6A0C8975D8200F",
    "MERFISH_Bregma_m0.19": "DE986E9212813224BF60F936D08C890EDBD915A1004B99EBA57F176470BACDB3",
    "MERFISH_Bregma_m0.24": "13C3ED6478D3396F152B6016096AA7C13D0761D984061F395930E29B6C641A8E",
}
PROTOCOL_SHA = "BF5106AF34143753A244EFD50038EF3F4AFF40580AEADD276547512076D17ED4"
AMENDMENT_SHA = "464E047210C5C33D6019BA486AC2F8093D7493873CBFE28DA9234988BEF74B91"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def in_unit_interval(frame: pd.DataFrame, columns: list[str]) -> bool:
    values = frame[columns].to_numpy(float)
    finite = values[np.isfinite(values)]
    return bool(np.all((finite >= -1e-12) & (finite <= 1 + 1e-12)))


def main() -> None:
    checks = {}
    checks["frozen_protocol_hash_unchanged"] = sha256(ROOT / "FROZEN_MERFISH_EXPANSION_PROTOCOL.md") == PROTOCOL_SHA
    checks["spagcn_amendment_hash_unchanged"] = sha256(ROOT / "PROTOCOL_AMENDMENT_SPAGCN_REFINEMENT.md") == AMENDMENT_SHA
    checks["pre_unblinding_verification_passed"] = json.loads(
        (ROOT / "PRE_UNBLINDING_VERIFICATION.json").read_text(encoding="utf-8-sig")
    ).get("status") == "PASS"
    checks["all_frozen_input_hashes_match"] = all(
        sha256(ROOT / "data" / section / f"{section}_frozen.h5ad") == expected
        for section, expected in INPUT_HASHES.items()
    )
    prediction_rows = []
    unit_hash_checks = []
    for section in SECTIONS:
        base = ad.read_h5ad(ROOT / "data" / section / f"{section}_frozen.h5ad")
        names = base.obs_names.astype(str).to_numpy()
        for method in METHODS:
            feature_hashes, coordinate_hashes, graph_hashes = set(), set(), set()
            for seed in range(1, 21):
                stem = ROOT / "predictions" / section / f"{method}__seed{seed}__primary"
                csv_path, json_path = stem.with_suffix(".csv"), stem.with_suffix(".json")
                if not csv_path.exists() or not json_path.exists():
                    raise RuntimeError(f"Missing prediction checkpoint: {stem}")
                prediction = pd.read_csv(csv_path, dtype={"barcode": str})
                metadata = json.loads(json_path.read_text(encoding="utf-8"))
                labels = prediction.cluster.to_numpy()
                observed_k = int(np.unique(labels).size)
                method_k_valid = method == "SpaGCN" or observed_k == 8
                valid = (
                    np.array_equal(prediction.barcode.to_numpy(str), names)
                    and len(prediction) == base.n_obs and np.isfinite(labels).all()
                    and method_k_valid and metadata.get("status") == "PASS"
                    and metadata.get("seed") == seed and metadata.get("epochs") == 200
                    and metadata.get("n_clusters_observed") == observed_k
                )
                prediction_rows.append({"section": section, "method": method, "seed": seed, "valid": valid})
                feature_hashes.add(metadata.get("feature_hash")); coordinate_hashes.add(metadata.get("coordinate_hash")); graph_hashes.add(metadata.get("graph_hash"))
            unit_hash_checks.append({
                "section": section, "method": method,
                "one_feature_hash": len(feature_hashes) == 1,
                "one_coordinate_hash": len(coordinate_hashes) == 1,
                "one_graph_hash": len(graph_hashes) == 1,
            })
    prediction_checks = pd.DataFrame(prediction_rows)
    hashes = pd.DataFrame(unit_hash_checks)
    checks["prediction_checkpoints_400"] = len(prediction_checks) == 400
    checks["all_predictions_valid_under_method_specific_K_rule_and_ordered"] = bool(prediction_checks.valid.all())
    checks["all_unit_inputs_and_graphs_frozen_across_seeds"] = bool(hashes.drop(columns=["section", "method"]).all().all())

    seed = pd.read_csv(ROOT / "seed_level_accuracy.csv")
    pairwise = pd.read_csv(ROOT / "pairwise_partition_reproducibility.csv")
    iso = pd.read_csv(ROOT / "iso_accuracy_results.csv")
    ranking = pd.read_csv(ROOT / "ranking_uncertainty.csv")
    marker = pd.read_csv(ROOT / "marker_reproducibility_all_pairs.csv")
    correlations = pd.read_csv(ROOT / "within_unit_marker_correlations.csv")
    tertiles = pd.read_csv(ROOT / "marker_tertile_summary.csv")
    consensus = pd.read_csv(ROOT / "consensus_results.csv")
    winner = pd.read_csv(ROOT / "winner_probabilities.csv")
    spagcn = pd.read_csv(ROOT / "SpaGCN_refinement_audit.csv")
    units = pd.read_csv(ROOT / "method_section_summary.csv")
    sections = pd.read_csv(ROOT / "section_level_summary.csv")
    checks["seed_rows_400"] = len(seed) == 400 and seed.groupby(["section", "method"]).size().eq(20).all()
    checks["pairwise_rows_3800"] = len(pairwise) == 3800 and pairwise.groupby(["section", "method"]).size().eq(190).all()
    checks["iso_summary_rows_60"] = len(iso) == 60 and set(np.round(iso.threshold, 2)) == {0.01, 0.02, 0.03}
    checks["method_section_summary_rows_20"] = len(units) == 20
    checks["section_summary_rows_5"] = len(sections) == 5
    checks["ranking_probability_sums_valid"] = bool(
        np.allclose(ranking.groupby(["section", "method"]).probability.sum().to_numpy(), 1.0)
        and np.allclose(ranking[["section", "method", "p_rank1"]].drop_duplicates().groupby("section").p_rank1.sum().to_numpy(), 1.0)
    )
    primary_pair_count = int((pairwise.abs_reference_ari_difference <= 0.02 + 1e-12).sum())
    checks["marker_rows_equal_primary_iso_pairs"] = len(marker) == primary_pair_count
    checks["marker_unit_rows_20_and_tertiles_60"] = len(correlations) == 20 and len(tertiles) == 60
    checks["consensus_rows_20"] = len(consensus) == 20
    checks["winner_probability_rows_20"] = len(winner) == 20 and winner.groupby("section").p_rank1.sum().round(12).eq(1).all()
    checks["spagcn_audit_rows_100_and_collapse_retained"] = (
        len(spagcn) == 100 and int(spagcn.refinement_reduced_observed_K.sum()) == 1
        and bool(spagcn.retained_in_all_scientific_analyses.all())
    )
    checks["accuracy_values_valid"] = in_unit_interval(seed, ["reference_ari", "reference_nmi"])
    checks["pairwise_values_valid"] = in_unit_interval(pairwise, ["pairwise_partition_ari", "pairwise_partition_nmi"])
    checks["marker_values_valid"] = in_unit_interval(marker, ["pairwise_partition_ari", "top100_marker_jaccard", "top50_marker_jaccard"])
    checks["consensus_values_valid"] = in_unit_interval(consensus, ["consensus20_reference_ari", "consensus20_reference_nmi", "split_half_consensus_ari"])
    expected_preview = {f"Figure{i}_MERFISH_integration_preview.{suffix}" for i in range(1, 7) for suffix in ("pdf", "svg", "png", "tiff")}
    checks["all_24_preview_exports_present"] = expected_preview.issubset({path.name for path in (ROOT / "previews").iterdir()})
    required = [
        "FINAL_REPORT.md", "EXPANSION_SUMMARY.json", "GENERALIZATION_ASSESSMENT.md", "seed_level_accuracy.csv",
        "pairwise_partition_reproducibility.csv", "iso_accuracy_results.csv", "ranking_uncertainty.csv",
        "marker_reproducibility_all_pairs.csv", "within_unit_marker_correlations.csv",
        "marker_tertile_summary.csv", "consensus_results.csv", "section_level_summary.csv",
        "MANUSCRIPT_INTEGRATION.md", "SpaGCN_refinement_audit.csv", "winner_probabilities.csv",
        "CORE_ANALYSIS_VALIDATION.json", "MARKER_ANALYSIS_VALIDATION.json",
    ]
    checks["all_required_root_deliverables_present"] = all((ROOT / name).exists() for name in required)
    checks["core_analysis_started_only_after_full_panel"] = bool(
        json.loads((ROOT / "CORE_ANALYSIS_VALIDATION.json").read_text(encoding="utf-8")).get(
            "scientific_analysis_started_only_after_400_run_panel_verified")
    )
    combined_seed = pd.read_csv(ROOT / "combined_seed_level_accuracy.csv")
    combined_pair = pd.read_csv(ROOT / "combined_pairwise_partition_reproducibility.csv")
    combined_marker = pd.read_csv(ROOT / "combined_marker_reproducibility_all_pairs.csv")
    combined_consensus = pd.read_csv(ROOT / "combined_consensus_results.csv")
    checks["combined_totals_reconcile"] = (
        len(combined_seed) == 1520 and len(combined_pair) == 76 * 190
        and len(combined_marker) == int((combined_pair.abs_reference_ari_difference <= 0.02 + 1e-12).sum())
        and len(combined_consensus) == 76
    )
    s3 = pd.read_csv(ROOT / "table_ready" / "Supplementary_Table_S3_preview.csv", dtype=str)
    s4 = pd.read_csv(ROOT / "table_ready" / "Supplementary_Table_S4_preview.csv", dtype=str)
    checks["s3_s4_starmap_display_label_only"] = (
        not s3.astype(str).apply(lambda col: col.str.contains("STARmap_20180505_BY3_1k").any()).any()
        and not s4.astype(str).apply(lambda col: col.str.contains("STARmap_20180505_BY3_1k").any()).any()
        and s3.astype(str).apply(lambda col: col.str.fullmatch("STARmap").any()).any()
        and s4.astype(str).apply(lambda col: col.str.fullmatch("STARmap").any()).any()
    )
    checks["publication_table_workbook_present"] = (ROOT / "table_ready" / "PROJECT9_MERFISH_PUBLICATION_TABLES.xlsx").exists()
    status = "PASS" if all(bool(value) for value in checks.values()) else "FAIL"
    checks = {key: bool(value) for key, value in checks.items()}
    status = "PASS" if all(checks.values()) else "FAIL"
    validation = {"status": status, "checks": checks, "protocol_sha256": PROTOCOL_SHA,
                  "prediction_checkpoints": len(prediction_checks), "primary_iso_pairs": primary_pair_count}
    (ROOT / "FINAL_VALIDATION.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    prediction_checks.to_csv(ROOT / "prediction_integrity_checks.csv", index=False)
    hashes.to_csv(ROOT / "unit_hash_consistency.csv", index=False)
    if status != "PASS":
        raise RuntimeError(f"Final validation failed: {[key for key, value in checks.items() if not value]}")

    rows = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and path.name != "INTEGRITY_SHA256.csv":
            rows.append({"relative_path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
                         "sha256": sha256(path)})
    pd.DataFrame(rows).to_csv(ROOT / "INTEGRITY_SHA256.csv", index=False)


if __name__ == "__main__":
    main()
