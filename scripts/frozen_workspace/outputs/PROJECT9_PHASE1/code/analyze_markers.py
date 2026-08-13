from __future__ import annotations

import argparse
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import scanpy as sc
from scipy import sparse, stats
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PRED = ROOT / "predictions"
TABLES = ROOT / "tables"
CACHE = ROOT / "environment" / "marker_cache"
CACHE.mkdir(parents=True, exist_ok=True)
METHODS = ["GraphST", "STAGATE", "SpaGCN", "BANKSY"]
DLPFC = ["151507", "151508", "151509", "151510", "151669", "151670",
          "151671", "151672", "151673", "151674", "151675", "151676"]
DATASETS = DLPFC + ["STARmap_20180505_BY3_1k", "HBCA1"]
SEEDS = range(1, 21)

parser = argparse.ArgumentParser()
parser.add_argument("--datasets", nargs="+", choices=DATASETS, default=DATASETS)
parser.add_argument("--output-tag", default="")
args = parser.parse_args()
DATASETS = args.datasets
suffix = f"__{args.output_tag}" if args.output_tag else ""


def frozen_path(dataset):
    return next((DATA / dataset).glob("*frozen.h5ad"))


def align(x, reference):
    ux, ur = np.unique(x), np.unique(reference)
    overlap = np.zeros((len(ux), len(ur)), dtype=int)
    for i, a in enumerate(ux):
        for j, b in enumerate(ur):
            overlap[i, j] = np.sum((x == a) & (reference == b))
    ri, ci = linear_sum_assignment(-overlap)
    mapping = {ux[i]: ur[j] for i, j in zip(ri, ci)}
    if len(mapping) != len(ux):
        raise RuntimeError("Non-bijective domain alignment")
    return np.array([mapping[v] for v in x], dtype=np.int16)


spots = pd.read_csv(ROOT / "spot_stability.csv", dtype={"dataset": str, "barcode": str}, low_memory=False)
selection = pd.read_csv(TABLES / "deterministic_pair_selection.csv", dtype={"dataset": str})
frequency_rows, reproducibility_rows, unit_summary_rows = [], [], []

for dataset in DATASETS:
    base = ad.read_h5ad(frozen_path(dataset))
    hvg = base.var["highly_variable"].to_numpy() if "highly_variable" in base.var else np.ones(base.n_vars, bool)
    genes = base.var_names.astype(str).to_numpy()[hvg]
    counts = base.layers["counts"][:, hvg]
    counts = counts.tocsr() if sparse.issparse(counts) else sparse.csr_matrix(counts)
    marker = ad.AnnData(X=counts.copy(), obs=pd.DataFrame(index=base.obs_names.copy()),
                        var=pd.DataFrame(index=genes))
    sc.pp.normalize_total(marker, target_sum=1e4)
    sc.pp.log1p(marker)
    for method in METHODS:
        sg = spots[(spots.dataset == dataset) & (spots.method == method)]
        if not np.array_equal(sg.barcode.astype(str).to_numpy(), base.obs_names.astype(str).to_numpy()):
            raise RuntimeError(f"Spot stability order mismatch {dataset}/{method}")
        consensus = sg.consensus_domain.to_numpy(np.int16)
        domains = np.sort(np.unique(consensus))
        orders = []
        for seed in SEEDS:
            cp = CACHE / f"{dataset}__{method}__seed{seed}__wilcoxon.npz"
            if cp.exists():
                z = np.load(cp, allow_pickle=True)
                if not np.array_equal(z["genes"].astype(str), genes) or not np.array_equal(z["domains"], domains):
                    raise RuntimeError(f"Marker checkpoint drift: {cp}")
                order = z["orders"]
            else:
                p = PRED / dataset / f"{method}__seed{seed}__primary.csv"
                d = pd.read_csv(p)
                if not np.array_equal(d.barcode.astype(str).to_numpy(), base.obs_names.astype(str).to_numpy()):
                    raise RuntimeError(f"Prediction order mismatch {p}")
                aligned = align(d.cluster.to_numpy(np.int16), consensus)
                present_domains = np.sort(np.unique(aligned))
                marker.obs["domain"] = pd.Categorical(aligned.astype(str), categories=present_domains.astype(str))
                order = np.full((len(domains), len(genes)), -1, dtype=np.int32)
                fallback = False
                try:
                    sc.tl.rank_genes_groups(marker, groupby="domain", method="wilcoxon", use_raw=False,
                                            n_genes=marker.n_vars, pts=False, tie_correct=False)
                    for domain in present_domains:
                        q = int(np.flatnonzero(domains == domain)[0])
                        ranked_names = marker.uns["rank_genes_groups"]["names"][str(domain)].astype(str)
                        loc = pd.Index(genes).get_indexer(ranked_names)
                        if (loc < 0).any() or len(np.unique(loc)) != len(genes):
                            raise RuntimeError("Ranked marker universe is not a permutation of frozen genes")
                        order[q] = loc
                except ValueError as exc:
                    if "only contain one sample" not in str(exc):
                        raise
                    # Scanpy blocks singleton groups before calculating its
                    # Wilcoxon rank-sum statistic. Apply the same untied-score
                    # rank-sum calculation directly for every group in this
                    # seed, preserving singleton domains rather than merging or
                    # dropping them. Sorting is descending by standardized U.
                    fallback = True
                    matrix = marker.X.toarray() if sparse.issparse(marker.X) else np.asarray(marker.X)
                    ranks = stats.rankdata(matrix, axis=0, method="average")
                    for domain in present_domains:
                        q = int(np.flatnonzero(domains == domain)[0])
                        mask = aligned == domain; n1 = int(mask.sum()); n0 = len(mask) - n1
                        u = ranks[mask].sum(axis=0) - n1 * (n1 + 1) / 2
                        denom = np.sqrt(n1 * n0 * (len(mask) + 1) / 12)
                        score = (u - n1 * n0 / 2) / denom
                        order[q] = np.lexsort((genes, -score))
                np.savez_compressed(cp, orders=order, genes=genes, domains=domains,
                                    pipeline=np.array(["direct_equivalent_wilcoxon_rank_sum_singleton_fallback"
                                                       if fallback else
                                                       "scanpy_rank_genes_groups_wilcoxon_default_tie_correction_false"]))
            orders.append(order)
        orders = np.stack(orders)  # seed, domain, ranked gene index
        for q, domain in enumerate(domains):
            hits = np.zeros(len(genes), dtype=np.int16)
            for seed_i in range(20):
                if orders[seed_i, q, 0] >= 0:
                    hits[orders[seed_i, q, :100]] += 1
            for gene_i, gene in enumerate(genes):
                f = hits[gene_i] / 20
                category = ">=80%" if f >= .8 else ("<=20%" if f <= .2 else "20-80%")
                frequency_rows.append({"dataset": dataset, "method": method,
                                       "aligned_consensus_domain": int(domain), "gene": gene,
                                       "marker_frequency": f, "frequency_category": category,
                                       "top_k": 100})
        unit_pair_summaries = {}
        for _, pick in selection[(selection.dataset == dataset) & (selection.method == method)].iterrows():
            i, j = int(pick.seed_r) - 1, int(pick.seed_s) - 1
            domain_jaccard, domain_rankcorr = [], []
            for q, domain in enumerate(domains):
                if orders[i, q, 0] < 0 or orders[j, q, 0] < 0:
                    continue
                a100, b100 = set(orders[i, q, :100]), set(orders[j, q, :100])
                jac = len(a100 & b100) / len(a100 | b100)
                rank_a = np.empty(len(genes), dtype=np.int32); rank_a[orders[i, q]] = np.arange(len(genes))
                rank_b = np.empty(len(genes), dtype=np.int32); rank_b[orders[j, q]] = np.arange(len(genes))
                rc = stats.spearmanr(rank_a, rank_b).statistic
                domain_jaccard.append(jac); domain_rankcorr.append(rc)
                reproducibility_rows.append({"record_type": "aligned_domain", "dataset": dataset,
                                             "method": method, "pair_type": pick.pair_type,
                                             "seed_r": i + 1, "seed_s": j + 1,
                                             "abs_reference_ari_difference": pick.abs_reference_ari_difference,
                                             "pairwise_partition_ari": pick.pairwise_partition_ari,
                                             "aligned_consensus_domain": int(domain),
                                             "top100_marker_jaccard": jac,
                                             "marker_rank_spearman": rc,
                                             "gene_universe_n": len(genes),
                                             "pipeline": "Scanpy rank_genes_groups; Wilcoxon; domain-vs-rest"})
            unit_pair_summaries[pick.pair_type] = (np.median(domain_jaccard), np.median(domain_rankcorr))
            reproducibility_rows.append({"record_type": "method_dataset_pair_summary", "dataset": dataset,
                                         "method": method, "pair_type": pick.pair_type,
                                         "seed_r": i + 1, "seed_s": j + 1,
                                         "abs_reference_ari_difference": pick.abs_reference_ari_difference,
                                         "pairwise_partition_ari": pick.pairwise_partition_ari,
                                         "top100_marker_jaccard": np.median(domain_jaccard),
                                         "marker_rank_spearman": np.median(domain_rankcorr),
                                         "gene_universe_n": len(genes),
                                         "pipeline": "Scanpy rank_genes_groups; Wilcoxon; domain-vs-rest"})
        unit_summary_rows.append({"dataset": dataset, "method": method,
                                  "unstable_marker_jaccard": unit_pair_summaries["iso_accuracy_unstable"][0],
                                  "stable_marker_jaccard": unit_pair_summaries["stable_control"][0],
                                  "unstable_marker_rank_spearman": unit_pair_summaries["iso_accuracy_unstable"][1],
                                  "stable_marker_rank_spearman": unit_pair_summaries["stable_control"][1]})
        print(f"completed markers {dataset}/{method}", flush=True)

freq = pd.DataFrame(frequency_rows)
repro = pd.DataFrame(reproducibility_rows)
unit = pd.DataFrame(unit_summary_rows)
freq.to_csv(ROOT / f"marker_frequency{suffix}.csv", index=False)
repro.to_csv(ROOT / f"marker_reproducibility{suffix}.csv", index=False)
unit.to_csv(TABLES / f"main_table_3_marker_reproducibility{suffix}.csv", index=False)

if suffix:
    print(json.dumps({"status": "partial_complete", "tag": args.output_tag, "units": len(unit)}, indent=2))
    raise SystemExit(0)

delta = unit.stable_marker_jaccard - unit.unstable_marker_jaccard
test = stats.wilcoxon(unit.stable_marker_jaccard, unit.unstable_marker_jaccard,
                      alternative="greater", zero_method="wilcox") if len(unit) >= 10 else None
families = unit.assign(family=np.where(unit.dataset.isin(DLPFC), "DLPFC", unit.dataset)).groupby("family").agg(
    median_unstable=("unstable_marker_jaccard", "median"),
    median_stable=("stable_marker_jaccard", "median"), n_units=("method", "size")).reset_index()
trigger = int(((families.median_stable - families.median_unstable) >= .10).sum()) >= 2
(TABLES / "marker_stable_vs_unstable_test.json").write_text(json.dumps({
    "n_units": len(unit), "median_unstable_jaccard": float(unit.unstable_marker_jaccard.median()),
    "median_stable_jaccard": float(unit.stable_marker_jaccard.median()),
    "median_paired_difference": float(delta.median()),
    "wilcoxon_signed_rank_alternative": "stable > unstable",
    "wilcoxon_statistic": float(test.statistic) if test else None,
    "wilcoxon_p_value": float(test.pvalue) if test else None,
    "go_enrichment_triggered_across_multiple_families": bool(trigger),
    "family_summary": families.to_dict(orient="records")
}, indent=2))
print(json.dumps({"status": "complete", "units": len(unit), "go_trigger": bool(trigger)}, indent=2))
