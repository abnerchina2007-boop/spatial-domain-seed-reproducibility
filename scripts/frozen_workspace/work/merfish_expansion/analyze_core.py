from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score


WORKSPACE = Path(__file__).resolve().parents[2]
ROOT = WORKSPACE / "outputs" / "PROJECT9_MERFISH_EXPANSION"
DATA = ROOT / "data"
PRED = ROOT / "predictions"
METHODS = ["GraphST", "STAGATE", "SpaGCN", "BANKSY"]
SECTIONS = [
    "MERFISH_Bregma_m0.04", "MERFISH_Bregma_m0.09", "MERFISH_Bregma_m0.14",
    "MERFISH_Bregma_m0.19", "MERFISH_Bregma_m0.24",
]
DISPLAY = {section: section.replace("MERFISH_Bregma_m", "Bregma -") for section in SECTIONS}
SEEDS = list(range(1, 21))


def input_path(section: str) -> Path:
    return DATA / section / f"{section}_frozen.h5ad"


def pred_path(section: str, method: str, seed: int) -> Path:
    return PRED / section / f"{method}__seed{seed}__primary.csv"


def verify_complete_panel() -> None:
    missing = []
    for section in SECTIONS:
        for method in METHODS:
            for seed in SEEDS:
                csv_path = pred_path(section, method, seed)
                json_path = csv_path.with_suffix(".json")
                if not csv_path.exists() or not json_path.exists():
                    missing.append(str(csv_path))
                    continue
                metadata = json.loads(json_path.read_text(encoding="utf-8"))
                observed_k = metadata.get("n_clusters_observed")
                if metadata.get("status") != "PASS" or (method != "SpaGCN" and observed_k != 8):
                    missing.append(str(json_path))
    if missing:
        raise RuntimeError(f"Full 400-run panel is incomplete; scientific analysis prohibited. Missing/invalid: {missing[:10]}")


def load_labels(section: str, method: str, names: np.ndarray) -> np.ndarray:
    labels = []
    for seed in SEEDS:
        frame = pd.read_csv(pred_path(section, method, seed), dtype={"barcode": str})
        if not np.array_equal(frame["barcode"].to_numpy(str), names):
            raise RuntimeError(f"Cell/order mismatch in {section}/{method}/seed{seed}")
        labels.append(frame["cluster"].to_numpy(np.int16))
    return np.vstack(labels)


def coassociation(labels: np.ndarray) -> np.ndarray:
    result = np.zeros((labels.shape[1], labels.shape[1]), dtype=np.float32)
    for partition in labels:
        result += partition[:, None] == partition[None, :]
    result /= labels.shape[0]
    return result


def consensus(labels: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    association = coassociation(labels)
    model = AgglomerativeClustering(n_clusters=k, metric="precomputed", linkage="average")
    partition = model.fit_predict(1.0 - association).astype(np.int16)
    support = np.zeros(len(partition), dtype=np.float32)
    for group in np.unique(partition):
        indices = np.flatnonzero(partition == group)
        if len(indices) == 1:
            support[indices] = 1.0
        else:
            block = association[np.ix_(indices, indices)]
            support[indices] = (block.sum(axis=1) - 1.0) / (len(indices) - 1)
    return partition, support


def rank_uncertainty(section: str, ari_by_method: dict[str, np.ndarray]):
    combinations = np.stack(
        np.meshgrid(*(ari_by_method[method] for method in METHODS), indexing="ij"), axis=-1
    ).reshape(-1, len(METHODS))
    if combinations.shape != (20 ** 4, 4):
        raise RuntimeError("Exhaustive rank enumeration is incomplete")
    # Freeze a non-arbitrary exact-tie policy before outcomes: midranks for the
    # full rank distribution and equal fractional rank-1 credit among tied
    # maxima. With no ties this is identical to ordinary ranks.
    ranks = np.empty_like(combinations, dtype=float)
    for i in range(4):
        greater = np.sum(combinations > combinations[:, [i]], axis=1)
        equal_other = np.sum(combinations == combinations[:, [i]], axis=1) - 1
        ranks[:, i] = 1.0 + greater + 0.5 * equal_other
    maximum_values = combinations.max(axis=1, keepdims=True)
    tied_maximum = combinations == maximum_values
    winner_credit = tied_maximum / tied_maximum.sum(axis=1, keepdims=True)
    method_rows = []
    rank_one = winner_credit.mean(axis=0)
    positive = rank_one[rank_one > 0]
    entropy = float(-(positive * np.log2(positive)).sum())
    maximum = float(rank_one.max())
    for i, method in enumerate(METHODS):
        for rank in sorted(np.unique(ranks[:, i])):
            method_rows.append({
                "section": section, "section_display": DISPLAY[section], "method": method,
                "rank": float(rank), "count": int(np.sum(ranks[:, i] == rank)),
                "probability": float(np.mean(ranks[:, i] == rank)),
                "p_rank1": float(rank_one[i]), "max_winner_probability": maximum,
                "winner_entropy_bits": entropy, "winner_entropy_normalized": entropy / 2.0,
                "enumerated_combinations": 20 ** 4,
                "interpretation_unit": "empirical combinations; not independent experiments",
            })
    pair_rows = []
    for i, j in itertools.combinations(range(4), 2):
        greater = combinations[:, i] > combinations[:, j]
        less = combinations[:, i] < combinations[:, j]
        pair_rows.append({
            "section": section, "section_display": DISPLAY[section],
            "method_A": METHODS[i], "method_B": METHODS[j],
            "p_A_gt_B": float(greater.mean()), "p_B_gt_A": float(less.mean()),
            "tie_probability": float((~greater & ~less).mean()),
            "enumerated_combinations": 20 ** 4,
        })
    return method_rows, pair_rows


def main() -> None:
    verify_complete_panel()
    seed_rows, pair_rows, iso_rows, unit_rows = [], [], [], []
    consensus_rows, cell_rows, rank_rows, superiority_rows = [], [], [], []

    for section in SECTIONS:
        base = ad.read_h5ad(input_path(section))
        names = base.obs_names.astype(str).to_numpy()
        reference = base.obs["manual_layer"].astype(str).to_numpy()
        valid = base.obs["manual_layer"].notna().to_numpy()
        k = int(base.uns["phase1_dataset"]["k"])
        ari_by_method = {}
        for method in METHODS:
            labels = load_labels(section, method, names)
            ari = np.array([adjusted_rand_score(reference[valid], x[valid]) for x in labels])
            nmi = np.array([normalized_mutual_info_score(reference[valid], x[valid]) for x in labels])
            ari_by_method[method] = ari
            for index, seed in enumerate(SEEDS):
                metadata = json.loads(pred_path(section, method, seed).with_suffix(".json").read_text(encoding="utf-8"))
                seed_rows.append({
                    "section": section, "section_display": DISPLAY[section], "method": method, "seed": seed,
                    "reference_ari": float(ari[index]), "reference_nmi": float(nmi[index]),
                    "n_cells": int(base.n_obs), "n_genes": int(base.n_vars),
                    "n_clusters": int(np.unique(labels[index]).size),
                    "elapsed_seconds": metadata.get("elapsed_seconds"), "device": metadata.get("device"),
                    "feature_hash": metadata.get("feature_hash"), "graph_hash": metadata.get("graph_hash"),
                })
            unit_pairs = []
            for i, j in itertools.combinations(range(20), 2):
                partition_ari = adjusted_rand_score(labels[i], labels[j])
                row = {
                    "section": section, "section_display": DISPLAY[section], "method": method,
                    "seed_r": i + 1, "seed_s": j + 1,
                    "ari_r": float(ari[i]), "ari_s": float(ari[j]),
                    "abs_reference_ari_difference": float(abs(ari[i] - ari[j])),
                    "pairwise_partition_ari": float(partition_ari),
                    "pairwise_partition_nmi": float(normalized_mutual_info_score(labels[i], labels[j])),
                }
                pair_rows.append(row)
                unit_pairs.append(row)
            pairs = pd.DataFrame(unit_pairs)
            pair_values = pairs["pairwise_partition_ari"].to_numpy(float)
            pair_nmi_values = pairs["pairwise_partition_nmi"].to_numpy(float)
            unit_rows.append({
                "section": section, "section_display": DISPLAY[section], "method": method, "n_seeds": 20,
                "median_reference_ari": float(np.median(ari)), "reference_ari_sd": float(ari.std(ddof=1)),
                "reference_ari_min": float(ari.min()), "reference_ari_max": float(ari.max()),
                "reference_ari_range": float(np.ptp(ari)),
                "median_reference_nmi": float(np.median(nmi)), "reference_nmi_sd": float(nmi.std(ddof=1)),
                "median_pairwise_partition_ari": float(np.median(pair_values)),
                "p05_pairwise_partition_ari": float(np.quantile(pair_values, 0.05)),
                "minimum_pairwise_partition_ari": float(np.min(pair_values)),
                "median_pairwise_partition_nmi": float(np.median(pair_nmi_values)),
                "p05_pairwise_partition_nmi": float(np.quantile(pair_nmi_values, 0.05)),
                "minimum_pairwise_partition_nmi": float(np.min(pair_nmi_values)),
                "partition_instability": float(1.0 - np.median(pair_values)),
            })
            for threshold in (0.01, 0.02, 0.03):
                subset = pairs[pairs["abs_reference_ari_difference"] <= threshold + 1e-12]
                values = subset["pairwise_partition_ari"].to_numpy(float)
                iso_rows.append({
                    "section": section, "section_display": DISPLAY[section], "method": method,
                    "threshold": threshold, "n_iso_accuracy_pairs": int(len(subset)),
                    "median_pairwise_partition_ari": float(np.median(values)) if len(values) else math.nan,
                    "n_partition_ari_below_0_50": int(np.sum(values < 0.50)),
                    "fraction_partition_ari_below_0_50": float(np.mean(values < 0.50)) if len(values) else math.nan,
                    "minimum_pairwise_partition_ari": float(np.min(values)) if len(values) else math.nan,
                })
            full_partition, support = consensus(labels, k)
            first_half, _ = consensus(labels[:10], k)
            second_half, _ = consensus(labels[10:], k)
            split_ari = adjusted_rand_score(first_half, second_half)
            median_pair = float(np.median(pair_values))
            consensus_rows.append({
                "section": section, "section_display": DISPLAY[section], "method": method,
                "median_single_seed_reference_ari": float(np.median(ari)),
                "best_single_seed_reference_ari": float(np.max(ari)),
                "consensus20_reference_ari": float(adjusted_rand_score(reference[valid], full_partition[valid])),
                "consensus20_reference_nmi": float(normalized_mutual_info_score(reference[valid], full_partition[valid])),
                "split_half_consensus_ari": float(split_ari),
                "median_single_seed_pairwise_ari": median_pair,
                "split_half_gain_over_median_single_seed_pairwise_ari": float(split_ari - median_pair),
                "algorithm": "average-linkage agglomeration of unweighted co-association matrix; K=8",
            })
            coordinates = np.asarray(base.obsm["spatial_original"])
            for q, barcode in enumerate(names):
                cell_rows.append({
                    "section": section, "method": method, "barcode": barcode,
                    "consensus_domain": int(full_partition[q]), "consensus_support": float(support[q]),
                    "x": float(coordinates[q, 0]), "y": float(coordinates[q, 1]),
                    "reference_annotation": reference[q],
                })
        rows, pairs = rank_uncertainty(section, ari_by_method)
        rank_rows.extend(rows)
        superiority_rows.extend(pairs)

    seed = pd.DataFrame(seed_rows)
    pairwise = pd.DataFrame(pair_rows)
    units = pd.DataFrame(unit_rows)
    iso = pd.DataFrame(iso_rows)
    consensus_frame = pd.DataFrame(consensus_rows)
    seed.to_csv(ROOT / "seed_level_accuracy.csv", index=False)
    pairwise.to_csv(ROOT / "pairwise_partition_reproducibility.csv", index=False)
    iso.to_csv(ROOT / "iso_accuracy_results.csv", index=False)
    pd.DataFrame(rank_rows).to_csv(ROOT / "ranking_uncertainty.csv", index=False)
    pd.DataFrame(superiority_rows).to_csv(ROOT / "ranking_pairwise_superiority.csv", index=False)
    consensus_frame.to_csv(ROOT / "consensus_results.csv", index=False)
    units.to_csv(ROOT / "method_section_summary.csv", index=False)
    pd.DataFrame(cell_rows).to_csv(ROOT / "consensus_cell_assignments.csv", index=False)
    section_summary = units.groupby(["section", "section_display"], as_index=False).agg(
        n_method_units=("method", "size"), median_reference_ari=("median_reference_ari", "median"),
        median_reference_ari_sd=("reference_ari_sd", "median"),
        median_pairwise_partition_ari=("median_pairwise_partition_ari", "median"),
        median_partition_instability=("partition_instability", "median"),
    )
    section_summary.to_csv(ROOT / "section_level_summary.csv", index=False)
    (ROOT / "CORE_ANALYSIS_VALIDATION.json").write_text(json.dumps({
        "status": "PASS", "successful_runs": int(len(seed)), "expected_runs": 400,
        "method_section_units": int(len(units)), "expected_units": 20,
        "pairwise_rows": int(len(pairwise)), "expected_pairwise_rows": 20 * 190,
        "ranking_combinations_per_section": 20 ** 4, "sections": len(SECTIONS),
        "scientific_analysis_started_only_after_400_run_panel_verified": True,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
