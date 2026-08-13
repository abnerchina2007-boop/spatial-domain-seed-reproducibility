from __future__ import annotations

import itertools
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PRED = ROOT / "predictions"
TABLES = ROOT / "tables"
TABLES.mkdir(exist_ok=True)
METHODS = ["GraphST", "STAGATE", "SpaGCN", "BANKSY"]
SEEDS = list(range(1, 21))
DLPFC = ["151507", "151508", "151509", "151510", "151669", "151670",
          "151671", "151672", "151673", "151674", "151675", "151676"]
DATASETS = DLPFC + ["STARmap_20180505_BY3_1k", "HBCA1"]


def frozen_path(dataset: str) -> Path:
    hits = list((DATA / dataset).glob("*frozen.h5ad"))
    if len(hits) != 1:
        raise RuntimeError(f"Expected one frozen object for {dataset}, got {hits}")
    return hits[0]


def pred_path(dataset: str, method: str, seed: int) -> Path:
    return PRED / dataset / f"{method}__seed{seed}__primary.csv"


def load_unit(dataset: str, method: str, obs_names: np.ndarray) -> np.ndarray:
    rows = []
    for seed in SEEDS:
        p = pred_path(dataset, method, seed)
        if not p.exists():
            raise RuntimeError(f"Missing required prediction: {p}")
        d = pd.read_csv(p)
        if not np.array_equal(d["barcode"].astype(str).to_numpy(), obs_names):
            raise RuntimeError(f"Barcode/order mismatch: {p}")
        rows.append(d["cluster"].to_numpy(np.int16))
    return np.vstack(rows)


def coassociation(labels: np.ndarray) -> np.ndarray:
    n = labels.shape[1]
    out = np.zeros((n, n), dtype=np.float32)
    for x in labels:
        out += (x[:, None] == x[None, :])
    out /= labels.shape[0]
    return out


def consensus(labels: np.ndarray, k: int):
    c = coassociation(labels)
    model = AgglomerativeClustering(n_clusters=k, metric="precomputed", linkage="average")
    z = model.fit_predict(1.0 - c).astype(np.int16)
    support = np.zeros(len(z), dtype=np.float32)
    for g in np.unique(z):
        idx = np.flatnonzero(z == g)
        if len(idx) == 1:
            support[idx] = 1.0
        else:
            block = c[np.ix_(idx, idx)]
            support[idx] = (block.sum(axis=1) - 1.0) / (len(idx) - 1)
    return z, support


seed_rows, pair_rows, summary_rows, iso_rows = [], [], [], []
spot_rows, consensus_rows, manifest_rows, rank_rows = [], [], [], []
pair_selection_rows = []
cache = {}

for dataset in DATASETS:
    a = ad.read_h5ad(frozen_path(dataset))
    names = a.obs_names.astype(str).to_numpy()
    ref_series = a.obs["manual_layer"]
    valid = ref_series.notna().to_numpy()
    ref = ref_series.astype(str).to_numpy()
    k = int(a.uns.get("phase1_dataset", {}).get("k", 7))
    tech = a.uns.get("phase1_dataset", {}).get("technology", "10x Visium")
    manifest_rows.append({"dataset": dataset, "family": "DLPFC" if dataset in DLPFC else dataset,
                          "species": "mouse" if dataset.startswith("STARmap") else "human",
                          "tissue": "visual cortex" if dataset.startswith("STARmap") else
                                    ("breast cancer" if dataset == "HBCA1" else "dorsolateral prefrontal cortex"),
                          "technology": tech, "n_spots": a.n_obs, "n_genes": a.n_vars,
                          "k": k, "methods": ";".join(METHODS), "valid_runs": 80})
    for method in METHODS:
        labels = load_unit(dataset, method, names)
        ari = np.array([adjusted_rand_score(ref[valid], x[valid]) for x in labels])
        nmi = np.array([normalized_mutual_info_score(ref[valid], x[valid]) for x in labels])
        for i, seed in enumerate(SEEDS):
            meta = json.loads(pred_path(dataset, method, seed).with_suffix(".json").read_text())
            seed_rows.append({"dataset": dataset, "method": method, "seed": seed,
                              "reference_ari": ari[i], "reference_nmi": nmi[i],
                              "n_spots": len(names), "n_clusters": len(np.unique(labels[i])),
                              "feature_hash": meta.get("feature_hash"),
                              "coordinate_hash": meta.get("coordinate_hash"),
                              "graph_hash": meta.get("graph_hash"),
                              "elapsed_seconds": meta.get("elapsed_seconds"), "device": meta.get("device")})
        pmat = np.eye(20)
        unit_pairs = []
        for i, j in itertools.combinations(range(20), 2):
            par = adjusted_rand_score(labels[i], labels[j])
            pmat[i, j] = pmat[j, i] = par
            row = {"dataset": dataset, "method": method, "seed_r": i + 1, "seed_s": j + 1,
                   "ari_r": ari[i], "ari_s": ari[j],
                   "abs_reference_ari_difference": abs(ari[i] - ari[j]),
                   "pairwise_partition_ari": par,
                   "pairwise_partition_nmi": normalized_mutual_info_score(labels[i], labels[j])}
            pair_rows.append(row); unit_pairs.append(row)
        up = pd.DataFrame(unit_pairs)
        pair_values = up.pairwise_partition_ari.to_numpy()
        summary_rows.append({"dataset": dataset, "method": method, "n_seeds": 20,
                             "median_reference_ari": np.median(ari), "reference_ari_sd": ari.std(ddof=1),
                             "reference_ari_min": ari.min(), "reference_ari_max": ari.max(),
                             "reference_ari_range": ari.max() - ari.min(),
                             "median_reference_nmi": np.median(nmi), "reference_nmi_sd": nmi.std(ddof=1),
                             "median_pairwise_ari": np.median(pair_values),
                             "p05_pairwise_ari": np.quantile(pair_values, .05),
                             "minimum_pairwise_ari": pair_values.min(),
                             "median_pairwise_nmi": np.median(up.pairwise_partition_nmi),
                             "partition_instability": 1 - np.median(pair_values)})
        for threshold in (.01, .02, .03):
            sub = up[up.abs_reference_ari_difference <= threshold].sort_values(
                ["pairwise_partition_ari", "seed_r", "seed_s"])
            iso_rows.append({"dataset": dataset, "method": method, "threshold": threshold,
                             "n_iso_accuracy_pairs": len(sub),
                             "median_pairwise_partition_ari": sub.pairwise_partition_ari.median(),
                             "minimum_pairwise_partition_ari": sub.pairwise_partition_ari.min(),
                             "representative_seed_r": int(sub.iloc[0].seed_r) if len(sub) else np.nan,
                             "representative_seed_s": int(sub.iloc[0].seed_s) if len(sub) else np.nan})
        unstable = up[up.abs_reference_ari_difference <= .02].sort_values(
            ["pairwise_partition_ari", "seed_r", "seed_s"]).iloc[0]
        remaining = up[~((up.seed_r == unstable.seed_r) & (up.seed_s == unstable.seed_s))].copy()
        remaining["gap_distance"] = abs(remaining.abs_reference_ari_difference - unstable.abs_reference_ari_difference)
        caliper = remaining[remaining.gap_distance <= .002]
        candidates = caliper if len(caliper) else remaining[remaining.gap_distance == remaining.gap_distance.min()]
        stable = candidates.sort_values(["pairwise_partition_ari", "seed_r", "seed_s"],
                                        ascending=[False, True, True]).iloc[0]
        for kind, x in (("iso_accuracy_unstable", unstable), ("stable_control", stable)):
            pair_selection_rows.append({"dataset": dataset, "method": method, "pair_type": kind,
                                        "seed_r": int(x.seed_r), "seed_s": int(x.seed_s),
                                        "abs_reference_ari_difference": x.abs_reference_ari_difference,
                                        "pairwise_partition_ari": x.pairwise_partition_ari,
                                        "stable_match_gap_distance": 0.0 if kind.startswith("iso") else x.gap_distance})
        z20, support = consensus(labels, k)
        z10a, _ = consensus(labels[:10], k)
        z10b, _ = consensus(labels[10:], k)
        consensus_rows.append({"dataset": dataset, "method": method,
                               "median_single_seed_ari": np.median(ari), "best_single_seed_ari": ari.max(),
                               "consensus20_reference_ari": adjusted_rand_score(ref[valid], z20[valid]),
                               "consensus20_reference_nmi": normalized_mutual_info_score(ref[valid], z20[valid]),
                               "split10_consensus_partition_ari": adjusted_rand_score(z10a, z10b),
                               "algorithm": "average-linkage agglomeration of unweighted co-association matrix"})
        xy = np.asarray(a.obsm["spatial"])
        for q, barcode in enumerate(names):
            spot_rows.append({"dataset": dataset, "method": method, "barcode": barcode,
                              "consensus_domain": int(z20[q]), "consensus_support": float(support[q]),
                              "stability_class": "high" if support[q] >= .8 else ("low" if support[q] <= .5 else "intermediate"),
                              "x": xy[q, 0], "y": xy[q, 1],
                              "reference_annotation": ref[q] if valid[q] else np.nan})
        cache[(dataset, method)] = (ari, labels)

seed_df = pd.DataFrame(seed_rows)
for dataset in DATASETS:
    dg = seed_df[seed_df.dataset == dataset]
    seed_winner = []
    for seed in SEEDS:
        sg = dg[dg.seed == seed].copy()
        sg["rank"] = sg.reference_ari.rank(ascending=False, method="min")
        winner = sg.sort_values(["reference_ari", "method"], ascending=[False, True]).iloc[0].method
        seed_winner.append(winner)
        for _, x in sg.iterrows():
            rank_rows.append({"dataset": dataset, "method": x.method, "record_type": "seed_rank",
                              "seed": seed, "rank": x["rank"], "reference_ari": x.reference_ari})
    med = dg.groupby("method").reference_ari.median().sort_values(ascending=False)
    for method in METHODS:
        ranks = [r["rank"] for r in rank_rows if r["dataset"] == dataset and r["method"] == method and r["record_type"] == "seed_rank"]
        rank_rows.append({"dataset": dataset, "method": method, "record_type": "summary",
                          "median_rank": np.median(ranks), "rank_min": np.min(ranks), "rank_max": np.max(ranks),
                          "rank1_frequency": np.mean(np.asarray(ranks) == 1),
                          "top2_frequency": np.mean(np.asarray(ranks) <= 2),
                          "top3_frequency": np.mean(np.asarray(ranks) <= 3),
                          "seed1_rank": ranks[0], "median_ari_rank": list(med.index).index(method) + 1,
                          "top_method_change_frequency_vs_seed1": np.mean(np.asarray(seed_winner) != seed_winner[0]),
                          "n_distinct_seed_winners": len(set(seed_winner)), "median_ari_winner": med.index[0]})

seed_df.to_csv(ROOT / "seed_level_accuracy.csv", index=False)
pd.DataFrame(pair_rows).to_csv(ROOT / "pairwise_partition_reproducibility.csv", index=False)
pd.DataFrame(iso_rows).to_csv(ROOT / "iso_accuracy_results.csv", index=False)
pd.DataFrame(spot_rows).to_csv(ROOT / "spot_stability.csv", index=False)
pd.DataFrame(rank_rows).to_csv(ROOT / "ranking_uncertainty.csv", index=False)
pd.DataFrame(consensus_rows).to_csv(ROOT / "consensus_results.csv", index=False)
pd.DataFrame(manifest_rows).to_csv(ROOT / "dataset_manifest.csv", index=False)
pd.DataFrame(summary_rows).to_csv(TABLES / "main_table_2_performance_reproducibility.csv", index=False)
pd.DataFrame(pair_selection_rows).to_csv(TABLES / "deterministic_pair_selection.csv", index=False)

# Explicit tutorial/reference fixed-seed audit on the canonical 151507 section.
default_rows = []
a0 = ad.read_h5ad(frozen_path("151507")); ref0 = a0.obs["manual_layer"]
valid0 = ref0.notna().to_numpy(); y0 = ref0.astype(str).to_numpy()[valid0]
for method, default_seed in {"GraphST": 41, "STAGATE": 0, "SpaGCN": 100, "BANKSY": 1234}.items():
    p = PRED / "151507" / f"{method}__seed{default_seed}__official_default.csv"
    if p.exists():
        d = pd.read_csv(p); value = adjusted_rand_score(y0, d.cluster.to_numpy()[valid0])
        primary = seed_df[(seed_df.dataset == "151507") & (seed_df.method == method)].reference_ari
        default_rows.append({"dataset": "151507", "method": method, "tutorial_or_reference_seed": default_seed,
                             "reference_ari": value,
                             "percentile_within_20_seed_distribution": 100 * np.mean(primary <= value),
                             "interpretation": "fixed tutorial/reference seed is one arbitrary draw; no implication of cherry-picking"})
pd.DataFrame(default_rows).to_csv(TABLES / "official_default_seed_percentiles.csv", index=False)

summ = pd.DataFrame(summary_rows)
rho = stats.spearmanr(summ.reference_ari_sd, summ.partition_instability)
(TABLES / "accuracy_stability_vs_partition_instability.json").write_text(json.dumps({
    "n_method_dataset_units": len(summ), "spearman_rho": float(rho.statistic),
    "spearman_p_value_descriptive_only": float(rho.pvalue),
    "note": "P value is descriptive only and is not a paper-level endpoint."
}, indent=2))
print(json.dumps({"status": "complete", "valid_runs": len(seed_df), "units": len(summ),
                  "pairwise_rows": len(pair_rows), "spot_rows": len(spot_rows)}, indent=2))
