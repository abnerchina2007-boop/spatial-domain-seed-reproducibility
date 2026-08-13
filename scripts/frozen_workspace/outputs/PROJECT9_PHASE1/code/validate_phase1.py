from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PHASE0 = ROOT.parent / "PROJECT9_PHASE0"
METHODS = ["GraphST", "STAGATE", "SpaGCN", "BANKSY"]
DLPFC = ["151507", "151508", "151509", "151510", "151669", "151670",
          "151671", "151672", "151673", "151674", "151675", "151676"]
DATASETS = DLPFC + ["STARmap_20180505_BY3_1k", "HBCA1"]
REQUIRED = ["README.md", "PHASE1_REPORT.md", "PHASE1_DECISION.json", "PHASE0_PROVENANCE.md",
            "METHOD_SEED_AUDIT.md", "INTEGRITY_AUDIT.md", "dataset_manifest.csv",
            "seed_level_accuracy.csv", "pairwise_partition_reproducibility.csv",
            "iso_accuracy_results.csv", "spot_stability.csv", "ranking_uncertainty.csv",
            "marker_reproducibility.csv", "marker_frequency.csv", "consensus_results.csv",
            "go_enrichment.csv"]


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()


checks, unit_rows = {}, []
checks["all_required_files_present"] = all((ROOT / x).exists() for x in REQUIRED)
checks["required_directories_present"] = all((ROOT / x).is_dir() for x in
                                               ["code", "data", "predictions", "logs", "figures", "tables", "environment"])

for dataset in DATASETS:
    frozen = next((ROOT / "data" / dataset).glob("*frozen.h5ad"))
    a = ad.read_h5ad(frozen, backed="r")
    expected_names = a.obs_names.astype(str).to_numpy(); k = int(a.uns.get("phase1_dataset", {}).get("k", 7))
    for method in METHODS:
        files = [ROOT / "predictions" / dataset / f"{method}__seed{s}__primary.csv" for s in range(1, 21)]
        present = all(x.exists() and x.with_suffix(".json").exists() for x in files)
        order_ok = present; k_ok = present; meta_seed_ok = present
        feature, coordinate, graph = set(), set(), set()
        if present:
            for seed, p in enumerate(files, 1):
                d = pd.read_csv(p); m = json.loads(p.with_suffix(".json").read_text())
                order_ok &= np.array_equal(d.barcode.astype(str).to_numpy(), expected_names)
                if method == "SpaGCN":
                    k_ok &= int(m["method_parameters"]["n_clusters"]) == k and 1 <= d.cluster.nunique() <= k
                else:
                    k_ok &= d.cluster.nunique() == k
                meta_seed_ok &= int(m["seed"]) == seed and m["run_id"] == "primary"
                feature.add(m.get("feature_hash")); coordinate.add(m.get("coordinate_hash")); graph.add(m.get("graph_hash"))
        unit_rows.append({"dataset": dataset, "method": method, "n_seed_files": sum(x.exists() for x in files),
                          "present_with_metadata": present, "barcode_order_ok": order_ok,
                          "target_k_and_postprocessing_count_ok": k_ok, "metadata_seed_ok": meta_seed_ok,
                          "feature_hash_count": len(feature), "coordinate_hash_count": len(coordinate),
                          "graph_hash_count": len(graph)})
    a.file.close()

units = pd.DataFrame(unit_rows)
units.to_csv(ROOT / "tables" / "integrity_unit_checks.csv", index=False)
checks["all_56_units_have_20_runs"] = bool((units.n_seed_files == 20).all())
checks["all_prediction_metadata_pairs_present"] = bool(units.present_with_metadata.all())
checks["all_barcode_orders_match_frozen_objects"] = bool(units.barcode_order_ok.all())
checks["all_target_k_and_postprocessing_cluster_counts_valid"] = bool(units.target_k_and_postprocessing_count_ok.all())
checks["all_metadata_seed_indices_match"] = bool(units.metadata_seed_ok.all())
checks["all_unit_feature_hashes_frozen"] = bool((units.feature_hash_count == 1).all())
checks["all_unit_coordinate_hashes_frozen"] = bool((units.coordinate_hash_count == 1).all())
checks["all_unit_graph_hashes_frozen"] = bool((units.graph_hash_count == 1).all())

reused = {"STAGATE": ["151507", "151508", "151509"],
          "GraphST": ["151507", "151508", "151509", "151510", "151669", "151670"],
          "BANKSY": DLPFC}
reuse_rows = []
for method, datasets in reused.items():
    for dataset in datasets:
        for seed in range(1, 21):
            src = PHASE0 / "predictions" / dataset / f"{method}__seed{seed}__primary.csv"
            dst = ROOT / "predictions" / dataset / src.name
            reuse_rows.append({"dataset": dataset, "method": method, "seed": seed,
                               "phase0_sha256": sha(src), "phase1_sha256": sha(dst),
                               "identical": sha(src) == sha(dst)})
for seed in range(1, 6):
    src = PHASE0 / "predictions" / "151510" / f"STAGATE__seed{seed}__primary.csv"
    dst = ROOT / "predictions" / "151510" / src.name
    reuse_rows.append({"dataset": "151510", "method": "STAGATE", "seed": seed,
                       "phase0_sha256": sha(src), "phase1_sha256": sha(dst),
                       "identical": sha(src) == sha(dst)})
reuse = pd.DataFrame(reuse_rows); reuse.to_csv(ROOT / "tables" / "phase0_reuse_hash_checks.csv", index=False)
checks["all_reused_phase0_predictions_byte_identical"] = bool(reuse.identical.all())

data_reuse_rows = []
for dataset in DLPFC:
    src = next((PHASE0 / "data" / dataset).glob("*frozen.h5ad"))
    dst = next((ROOT / "data" / dataset).glob("*frozen.h5ad"))
    src_hash, dst_hash = sha(src), sha(dst)
    data_reuse_rows.append({"dataset": dataset, "phase0_frozen_sha256": src_hash,
                            "phase1_frozen_sha256": dst_hash, "identical": src_hash == dst_hash})
data_reuse = pd.DataFrame(data_reuse_rows)
data_reuse.to_csv(ROOT / "tables" / "phase0_frozen_data_hash_checks.csv", index=False)
checks["all_reused_phase0_frozen_objects_byte_identical"] = bool(data_reuse.identical.all())

if (ROOT / "seed_level_accuracy.csv").exists():
    checks["seed_level_row_count_1120"] = len(pd.read_csv(ROOT / "seed_level_accuracy.csv")) == 1120
if (ROOT / "pairwise_partition_reproducibility.csv").exists():
    checks["pairwise_row_count_10640"] = len(pd.read_csv(ROOT / "pairwise_partition_reproducibility.csv")) == 10640
if (ROOT / "iso_accuracy_results.csv").exists():
    checks["iso_summary_row_count_168"] = len(pd.read_csv(ROOT / "iso_accuracy_results.csv")) == 168
if (ROOT / "consensus_results.csv").exists():
    checks["consensus_row_count_56"] = len(pd.read_csv(ROOT / "consensus_results.csv")) == 56
if (ROOT / "marker_reproducibility.csv").exists():
    marker = pd.read_csv(ROOT / "marker_reproducibility.csv", dtype={"dataset": str})
    ms = marker[marker.record_type == "method_dataset_pair_summary"]
    checks["marker_summary_has_56_units_times_2_pairs"] = len(ms) == 112 and ms[["dataset", "method", "pair_type"]].drop_duplicates().shape[0] == 112
    checks["marker_primary_endpoints_are_finite"] = bool(np.isfinite(ms.top100_marker_jaccard).all() and np.isfinite(ms.marker_rank_spearman).all())
checks["all_1120_marker_seed_checkpoints_present"] = len(list((ROOT / "environment" / "marker_cache").glob("*.npz"))) == 1120
checks["go_bp_results_present_after_trigger"] = (ROOT / "go_enrichment.csv").exists() and len(pd.read_csv(ROOT / "go_enrichment.csv")) > 0
checks["three_main_tables_present"] = all((ROOT / "tables" / x).exists() for x in
    ["main_table_1_datasets_methods_runs.csv", "main_table_2_performance_reproducibility.csv",
     "main_table_3_marker_reproducibility.csv"])
checks["planned_supplementary_tables_present"] = all((ROOT / "tables" / x).exists() for x in
    ["supplementary_table_S1_software_versions_seeds.csv", "supplementary_table_S2_seed_level_accuracy.csv",
     "supplementary_table_S3_pairwise_partition_reproducibility.csv",
     "supplementary_table_S4_ranking_uncertainty.csv", "supplementary_table_S5_marker_frequency.csv",
     "supplementary_table_S6_go_results.csv", "supplementary_table_iso_accuracy_thresholds.csv"])
checks["six_main_figures_png_pdf"] = all((ROOT / "figures" / f"Figure_{i}_{name}.{ext}").exists()
    for i, name in [(1,"study_design"),(2,"accuracy_vs_partition"),(3,"iso_accuracy_maps"),
                    (4,"cross_dataset_reproducibility"),(5,"ranking_uncertainty"),(6,"downstream_and_consensus")]
    for ext in ("png", "pdf"))

if (ROOT / "PHASE1_DECISION.json").exists():
    decision = json.loads((ROOT / "PHASE1_DECISION.json").read_text())
    allowed = {"GO_MANUSCRIPT", "GO_MANUSCRIPT_DLPFC_FOCUSED", "GO_PARTITION_REPRODUCIBILITY_PAPER",
               "SIGNAL_METHOD_SPECIFIC", "EXTERNAL_REPLICATION_FAIL", "STOP_AFTER_PHASE1"}
    checks["decision_is_exact_predefined_value"] = decision.get("verdict") in allowed
checks["report_begins_with_executive_summary"] = (ROOT / "PHASE1_REPORT.md").read_text(encoding="utf-8").startswith("# Executive summary")

result = {"status": "PASS" if checks and all(checks.values()) else "FAIL",
          "checks": checks, "n_checks": len(checks), "n_failed": sum(not x for x in checks.values())}
(ROOT / "tables" / "validation_results.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
if result["status"] != "PASS": raise SystemExit(1)
