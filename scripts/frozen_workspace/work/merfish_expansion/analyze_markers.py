from __future__ import annotations

import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import scanpy as sc
from scipy import sparse, stats
from scipy.optimize import linear_sum_assignment


WORKSPACE = Path(__file__).resolve().parents[2]
ROOT = WORKSPACE / "outputs" / "PROJECT9_MERFISH_EXPANSION"
DATA = ROOT / "data"
PRED = ROOT / "predictions"
CACHE = ROOT / "marker_cache"
CACHE.mkdir(parents=True, exist_ok=True)
METHODS = ["GraphST", "STAGATE", "SpaGCN", "BANKSY"]
SECTIONS = [
    "MERFISH_Bregma_m0.04", "MERFISH_Bregma_m0.09", "MERFISH_Bregma_m0.14",
    "MERFISH_Bregma_m0.19", "MERFISH_Bregma_m0.24",
]
DISPLAY = {section: section.replace("MERFISH_Bregma_m", "Bregma -") for section in SECTIONS}
STRATA = ["Low", "Middle", "High"]


def align(partition: np.ndarray, consensus: np.ndarray) -> np.ndarray:
    left, right = np.unique(partition), np.unique(consensus)
    overlap = np.zeros((len(left), len(right)), dtype=np.int64)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            overlap[i, j] = np.sum((partition == a) & (consensus == b))
    row, column = linear_sum_assignment(-overlap)
    mapping = {left[i]: right[j] for i, j in zip(row, column)}
    if len(mapping) != len(left):
        raise RuntimeError("Hungarian alignment did not assign every observed seed domain")
    return np.array([mapping[value] for value in partition], dtype=np.int16)


def rank_seed(marker: ad.AnnData, aligned: np.ndarray, domains: np.ndarray, genes: np.ndarray) -> tuple[np.ndarray, str]:
    present = np.sort(np.unique(aligned))
    marker.obs["domain"] = pd.Categorical(aligned.astype(str), categories=present.astype(str))
    order = np.full((len(domains), len(genes)), -1, dtype=np.int32)
    pipeline = "scanpy_rank_genes_groups_wilcoxon_tie_correct_false"
    try:
        sc.tl.rank_genes_groups(marker, groupby="domain", method="wilcoxon", use_raw=False,
                                n_genes=marker.n_vars, pts=False, tie_correct=False)
        for domain in present:
            q = int(np.flatnonzero(domains == domain)[0])
            ranked = marker.uns["rank_genes_groups"]["names"][str(domain)].astype(str)
            locations = pd.Index(genes).get_indexer(ranked)
            if (locations < 0).any() or len(np.unique(locations)) != len(genes):
                raise RuntimeError("Marker ranks are not a permutation of the frozen gene universe")
            order[q] = locations
    except ValueError as exc:
        if "only contain one sample" not in str(exc):
            raise
        pipeline = "direct_equivalent_wilcoxon_rank_sum_singleton_fallback"
        matrix = marker.X.toarray() if sparse.issparse(marker.X) else np.asarray(marker.X)
        ranks = stats.rankdata(matrix, axis=0, method="average")
        for domain in present:
            q = int(np.flatnonzero(domains == domain)[0])
            mask = aligned == domain
            n1, n0 = int(mask.sum()), int((~mask).sum())
            u_value = ranks[mask].sum(axis=0) - n1 * (n1 + 1) / 2
            denominator = np.sqrt(n1 * n0 * (len(mask) + 1) / 12)
            score = (u_value - n1 * n0 / 2) / denominator
            order[q] = np.lexsort((genes, -score))
    return order, pipeline


def jaccard(a: np.ndarray, b: np.ndarray, k: int) -> float:
    shared = np.intersect1d(a[:k], b[:k], assume_unique=True).size
    return float(shared / (2 * k - shared))


def rank_spearman(order_a: np.ndarray, order_b: np.ndarray) -> float:
    inverse_a = np.empty_like(order_a); inverse_a[order_a] = np.arange(len(order_a))
    inverse_b = np.empty_like(order_b); inverse_b[order_b] = np.arange(len(order_b))
    return float(stats.spearmanr(inverse_a, inverse_b).statistic)


def main() -> None:
    core_check = json.loads((ROOT / "CORE_ANALYSIS_VALIDATION.json").read_text(encoding="utf-8"))
    if core_check.get("status") != "PASS" or core_check.get("successful_runs") != 400:
        raise RuntimeError("Marker analysis cannot begin before the complete 400-run panel is validated")
    pairwise = pd.read_csv(ROOT / "pairwise_partition_reproducibility.csv")
    iso = pairwise[pairwise["abs_reference_ari_difference"] <= 0.02 + 1e-12].copy()
    cells = pd.read_csv(ROOT / "consensus_cell_assignments.csv", dtype={"barcode": str})
    marker_pair_rows = []
    pipelines = set()

    for section in SECTIONS:
        base = ad.read_h5ad(DATA / section / f"{section}_frozen.h5ad")
        valid_genes = np.asarray(base.var["highly_variable"], dtype=bool)
        genes = base.var_names.astype(str).to_numpy()[valid_genes]
        if len(genes) != 155:
            raise RuntimeError(f"Frozen targeted-gene universe drift in {section}: {len(genes)}")
        top_k = min(100, len(genes))
        counts = base.layers["counts"][:, valid_genes]
        counts = counts.tocsr() if sparse.issparse(counts) else sparse.csr_matrix(counts)
        marker = ad.AnnData(X=counts.copy(), obs=pd.DataFrame(index=base.obs_names.copy()),
                            var=pd.DataFrame(index=genes))
        sc.pp.normalize_total(marker, target_sum=10000)
        sc.pp.log1p(marker)
        for method in METHODS:
            unit_cells = cells[(cells.section == section) & (cells.method == method)]
            if not np.array_equal(unit_cells.barcode.to_numpy(str), base.obs_names.astype(str).to_numpy()):
                raise RuntimeError(f"Consensus cell order mismatch in {section}/{method}")
            consensus = unit_cells.consensus_domain.to_numpy(np.int16)
            domains = np.sort(np.unique(consensus))
            all_orders = []
            for seed in range(1, 21):
                cache_path = CACHE / f"{section}__{method}__seed{seed}__wilcoxon.npz"
                if cache_path.exists():
                    cached = np.load(cache_path, allow_pickle=True)
                    if not np.array_equal(cached["genes"].astype(str), genes) or not np.array_equal(cached["domains"], domains):
                        raise RuntimeError(f"Marker cache schema drift: {cache_path}")
                    order = cached["orders"].astype(np.int32)
                    pipelines.update(cached["pipeline"].astype(str).tolist())
                else:
                    prediction = pd.read_csv(
                        PRED / section / f"{method}__seed{seed}__primary.csv", dtype={"barcode": str}
                    )
                    if not np.array_equal(prediction.barcode.to_numpy(str), base.obs_names.astype(str).to_numpy()):
                        raise RuntimeError(f"Prediction cell order mismatch in {section}/{method}/seed{seed}")
                    aligned = align(prediction.cluster.to_numpy(np.int16), consensus)
                    order, pipeline = rank_seed(marker, aligned, domains, genes)
                    np.savez_compressed(cache_path, orders=order, genes=genes, domains=domains,
                                        pipeline=np.array([pipeline]))
                    pipelines.add(pipeline)
                all_orders.append(order)
            all_orders = np.stack(all_orders)
            unit_pairs = iso[(iso.section == section) & (iso.method == method)]
            for row in unit_pairs.itertuples(index=False):
                i, j = int(row.seed_r) - 1, int(row.seed_s) - 1
                top100_values, top50_values, rank_values, used = [], [], [], []
                for q, domain in enumerate(domains):
                    if all_orders[i, q, 0] < 0 or all_orders[j, q, 0] < 0:
                        continue
                    top100_values.append(jaccard(all_orders[i, q], all_orders[j, q], top_k))
                    top50_values.append(jaccard(all_orders[i, q], all_orders[j, q], min(50, len(genes))))
                    rank_values.append(rank_spearman(all_orders[i, q], all_orders[j, q]))
                    used.append(int(domain))
                if not used:
                    raise RuntimeError(f"No mutually present aligned domains in {section}/{method}/{row.seed_r}-{row.seed_s}")
                marker_pair_rows.append({
                    "section": section, "section_display": DISPLAY[section], "method": method,
                    "seed_r": int(row.seed_r), "seed_s": int(row.seed_s),
                    "abs_reference_ari_difference": float(row.abs_reference_ari_difference),
                    "pairwise_partition_ari": float(row.pairwise_partition_ari),
                    "marker_set_size": top_k,
                    "top100_marker_jaccard": float(np.median(top100_values)),
                    "top50_marker_jaccard": float(np.median(top50_values)),
                    "marker_rank_spearman": float(np.median(rank_values)),
                    "aligned_domains_compared_n": len(used),
                    "aligned_domains_compared": ";".join(map(str, used)),
                })

    pairs = pd.DataFrame(marker_pair_rows)
    stratified = []
    correlation_rows, tertile_rows = [], []
    for section in SECTIONS:
        for method in METHODS:
            group = pairs[(pairs.section == section) & (pairs.method == method)].sort_values(
                ["pairwise_partition_ari", "seed_r", "seed_s"]
            ).copy()
            if group.empty:
                group["partition_ari_tertile"] = pd.Series(dtype=str)
                stratified.append(group)
                for stratum in STRATA:
                    tertile_rows.append({
                        "section": section, "section_display": DISPLAY[section], "method": method,
                        "partition_ari_tertile": stratum, "n_pairs": 0,
                        "median_pairwise_partition_ari": np.nan,
                        "median_top100_marker_jaccard": np.nan,
                        "median_top50_marker_jaccard": np.nan,
                        "median_marker_rank_spearman": np.nan,
                    })
                correlation_rows.append({
                    "section": section, "section_display": DISPLAY[section], "method": method,
                    "n_iso_accuracy_pairs": 0,
                    "spearman_partition_ari_vs_marker_jaccard": np.nan,
                    "low_tertile_median_marker_jaccard": np.nan,
                    "middle_tertile_median_marker_jaccard": np.nan,
                    "high_tertile_median_marker_jaccard": np.nan,
                    "high_minus_low_marker_jaccard": np.nan,
                })
                continue
            codes = np.minimum(np.floor(np.arange(len(group)) * 3 / len(group)).astype(int), 2)
            group["partition_ari_tertile"] = [STRATA[code] for code in codes]
            stratified.append(group)
            rho = stats.spearmanr(group.pairwise_partition_ari, group.top100_marker_jaccard).statistic
            medians = {}
            for stratum in STRATA:
                subset = group[group.partition_ari_tertile == stratum]
                medians[stratum] = float(subset.top100_marker_jaccard.median())
                tertile_rows.append({
                    "section": section, "section_display": DISPLAY[section], "method": method,
                    "partition_ari_tertile": stratum, "n_pairs": int(len(subset)),
                    "median_pairwise_partition_ari": float(subset.pairwise_partition_ari.median()),
                    "median_top100_marker_jaccard": medians[stratum],
                    "median_top50_marker_jaccard": float(subset.top50_marker_jaccard.median()),
                    "median_marker_rank_spearman": float(subset.marker_rank_spearman.median()),
                })
            correlation_rows.append({
                "section": section, "section_display": DISPLAY[section], "method": method,
                "n_iso_accuracy_pairs": int(len(group)),
                "spearman_partition_ari_vs_marker_jaccard": float(rho),
                "low_tertile_median_marker_jaccard": medians["Low"],
                "middle_tertile_median_marker_jaccard": medians["Middle"],
                "high_tertile_median_marker_jaccard": medians["High"],
                "high_minus_low_marker_jaccard": medians["High"] - medians["Low"],
            })
    pairs = pd.concat(stratified, ignore_index=True)
    pairs.to_csv(ROOT / "marker_reproducibility_all_pairs.csv", index=False)
    pd.DataFrame(correlation_rows).to_csv(ROOT / "within_unit_marker_correlations.csv", index=False)
    pd.DataFrame(tertile_rows).to_csv(ROOT / "marker_tertile_summary.csv", index=False)
    (ROOT / "MARKER_ANALYSIS_VALIDATION.json").write_text(json.dumps({
        "status": "PASS", "iso_accuracy_threshold": 0.02,
        "iso_accuracy_pairs": int(len(pairs)), "method_section_units": 20,
        "targeted_gene_universe": 155, "primary_marker_set_size": 100,
        "normalization": "normalize_total(10000); log1p",
        "ranking": "Scanpy Wilcoxon domain-vs-rest; use_raw=False; tie_correct=False",
        "alignment": "Hungarian maximum-overlap to corresponding 20-seed consensus; mutually present aligned domains compared",
        "pipeline_implementations_observed": sorted(pipelines),
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
