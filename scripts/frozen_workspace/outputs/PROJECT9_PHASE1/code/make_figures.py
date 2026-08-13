from __future__ import annotations

from pathlib import Path

import anndata as ad
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "figures"; FIG.mkdir(exist_ok=True)
TABLES = ROOT / "tables"
PRED = ROOT / "predictions"
DATA = ROOT / "data"
COLORS = {"GraphST": "#D55E00", "STAGATE": "#0072B2", "SpaGCN": "#CC79A7", "BANKSY": "#009E73"}
METHODS = list(COLORS)
DLPFC = ["151507", "151508", "151509", "151510", "151669", "151670",
          "151671", "151672", "151673", "151674", "151675", "151676"]


def save(name):
    plt.savefig(FIG / f"{name}.png", dpi=240, bbox_inches="tight", facecolor="white")
    plt.savefig(FIG / f"{name}.pdf", bbox_inches="tight", facecolor="white")
    plt.close()


def align(x, ref):
    ux, ur = np.unique(x), np.unique(ref); mat = np.zeros((len(ux), len(ur)), int)
    for i, a in enumerate(ux):
        for j, b in enumerate(ur): mat[i, j] = np.sum((x == a) & (ref == b))
    ri, ci = linear_sum_assignment(-mat); mp = {ux[i]: ur[j] for i, j in zip(ri, ci)}
    return np.array([mp[v] for v in x])


sns.set_theme(style="whitegrid", context="paper", font_scale=1.05)

# Figure 1: study design concept.
fig, ax = plt.subplots(figsize=(11, 3.5)); ax.set_axis_off()
boxes = [(0.02, "Frozen method × tissue\n20 distinct seeds"), (0.27, "Conventional score\nARI / NMI"),
         (0.51, "Map reproducibility\npairwise ARI + iso-accuracy"),
         (0.76, "Biological propagation\nmarkers + consensus mitigation")]
for x, text in boxes:
    ax.add_patch(FancyBboxPatch((x, .32), .20, .38, boxstyle="round,pad=.02", fc="#F2F4F8", ec="#415A77", lw=1.5))
    ax.text(x + .10, .51, text, ha="center", va="center", fontsize=11)
for x in (.225, .475, .725): ax.annotate("", xy=(x + .035, .51), xytext=(x, .51), arrowprops=dict(arrowstyle="->", lw=1.6))
ax.text(.5, .90, "Stable benchmark scores can conceal unstable spatial maps", ha="center", weight="bold", fontsize=14)
ax.text(.5, .12, "12 DLPFC sections  •  STARmap visual cortex  •  human breast-cancer Visium  •  four fixed methods",
        ha="center", color="#444")
save("Figure_1_study_design")

seed = pd.read_csv(ROOT / "seed_level_accuracy.csv", dtype={"dataset": str})
pairs = pd.read_csv(ROOT / "pairwise_partition_reproducibility.csv", dtype={"dataset": str})
summ = pd.read_csv(TABLES / "main_table_2_performance_reproducibility.csv", dtype={"dataset": str})

# Figure 2: conventional accuracy versus partition reproducibility.
fig, axes = plt.subplots(1, 3, figsize=(14, 4.1))
sns.boxplot(data=seed, x="method", y="reference_ari", order=METHODS, palette=COLORS, ax=axes[0], fliersize=1)
axes[0].set(xlabel="", ylabel="ARI to reference", title="A  Seed-wise benchmark accuracy"); axes[0].tick_params(axis="x", rotation=25)
sns.boxplot(data=pairs, x="method", y="pairwise_partition_ari", order=METHODS, palette=COLORS, ax=axes[1], fliersize=1)
axes[1].set(xlabel="", ylabel="Pairwise partition ARI", title="B  Map reproducibility"); axes[1].tick_params(axis="x", rotation=25)
for m in METHODS:
    g = summ[summ.method == m]
    axes[2].scatter(g.reference_ari_sd, g.partition_instability, label=m, color=COLORS[m], s=34, alpha=.82)
axes[2].set(xlabel="AccuracySD (reference ARI)", ylabel="PartitionInstability\n(1 − median pairwise ARI)",
            title="C  Accuracy stability vs map stability"); axes[2].legend(frameon=False, fontsize=8)
fig.tight_layout(); save("Figure_2_accuracy_vs_partition")

# Figure 3: deterministic iso-accuracy examples plus consensus support.
pick = pd.read_csv(TABLES / "deterministic_pair_selection.csv", dtype={"dataset": str})
choices = []
for method in ("GraphST", "STAGATE"):
    g = pick[(pick.method == method) & (pick.dataset.isin(DLPFC)) & (pick.pair_type == "iso_accuracy_unstable")]
    choices.append(g.sort_values("pairwise_partition_ari").iloc[0])
g = pick[(~pick.dataset.isin(DLPFC)) & (pick.pair_type == "iso_accuracy_unstable")]
choices.append(g.sort_values("pairwise_partition_ari").iloc[0])
spots = pd.read_csv(ROOT / "spot_stability.csv", dtype={"dataset": str, "barcode": str}, low_memory=False)
fig, axes = plt.subplots(3, 3, figsize=(10.5, 10))
for row, x in enumerate(choices):
    dataset, method = x.dataset, x.method
    sg = spots[(spots.dataset == dataset) & (spots.method == method)]
    xy = sg[["x", "y"]].to_numpy(); a = pd.read_csv(PRED / dataset / f"{method}__seed{int(x.seed_r)}__primary.csv").cluster.to_numpy()
    b = pd.read_csv(PRED / dataset / f"{method}__seed{int(x.seed_s)}__primary.csv").cluster.to_numpy(); b = align(b, a)
    for col, (z, title) in enumerate(((a, f"seed {int(x.seed_r)}"), (b, f"seed {int(x.seed_s)}"))):
        axes[row, col].scatter(xy[:, 0], xy[:, 1], c=z, cmap="tab20", s=3, rasterized=True)
        axes[row, col].set_title(title); axes[row, col].invert_yaxis(); axes[row, col].set_axis_off()
    im = axes[row, 2].scatter(xy[:, 0], xy[:, 1], c=sg.consensus_support, cmap="viridis", vmin=0, vmax=1, s=3, rasterized=True)
    axes[row, 2].set_title("consensus support"); axes[row, 2].invert_yaxis(); axes[row, 2].set_axis_off()
    axes[row, 0].text(-.08, .5, f"{dataset}\n{method}\nΔARI={x.abs_reference_ari_difference:.3f}\nmap ARI={x.pairwise_partition_ari:.3f}",
                      transform=axes[row, 0].transAxes, ha="right", va="center", fontsize=8)
fig.colorbar(im, ax=axes[:, 2], fraction=.025, pad=.02, label="fractional consensus support")
fig.suptitle("Iso-accuracy pairs selected by the prespecified lowest-partition-ARI rule", y=.995, weight="bold")
fig.subplots_adjust(wspace=.06, hspace=.16); save("Figure_3_iso_accuracy_maps")

# Figure 4: complete cross-dataset/cross-method reproducibility map.
pivot = summ.pivot(index="dataset", columns="method", values="median_pairwise_ari").loc[DLPFC + ["STARmap_20180505_BY3_1k", "HBCA1"], METHODS]
fig, ax = plt.subplots(figsize=(7.2, 8.5)); sns.heatmap(pivot, cmap="mako", vmin=0, vmax=1, annot=True, fmt=".2f", ax=ax,
                                                     cbar_kws={"label": "median pairwise partition ARI"})
ax.set(xlabel="", ylabel="", title="Cross-dataset partition reproducibility (20 seeds)"); ax.tick_params(axis="x", rotation=25)
fig.tight_layout(); save("Figure_4_cross_dataset_reproducibility")

# Figure 5: ranking uncertainty.
rank = pd.read_csv(ROOT / "ranking_uncertainty.csv", dtype={"dataset": str}); rs = rank[rank.record_type == "summary"].copy()
fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
rh = rs.pivot(index="dataset", columns="method", values="rank1_frequency").loc[pivot.index, METHODS]
sns.heatmap(rh, cmap="rocket_r", vmin=0, vmax=1, annot=True, fmt=".2f", ax=axes[0], cbar_kws={"label": "rank-1 frequency"})
axes[0].set(xlabel="", ylabel="", title="A  Apparent winner across seed indices"); axes[0].tick_params(axis="x", rotation=25)
for k, (_, x) in enumerate(rs.iterrows()):
    y = k % 4 + (k // 4) * .03
    axes[1].plot([0, 1], [x.seed1_rank, x.median_ari_rank], color=COLORS[x.method], alpha=.25)
axes[1].set_xticks([0, 1], ["single seed (1)", "20-seed median"]); axes[1].set_yticks([1, 2, 3, 4]); axes[1].invert_yaxis()
axes[1].set(ylabel="Method rank", title="B  Single-seed vs median ranking");
for m in METHODS: axes[1].plot([], [], color=COLORS[m], label=m)
axes[1].legend(frameon=False, fontsize=8)
fig.tight_layout(); save("Figure_5_ranking_uncertainty")

# Figure 6: downstream markers and consensus mitigation.
marker = pd.read_csv(TABLES / "main_table_3_marker_reproducibility.csv", dtype={"dataset": str})
freq = pd.read_csv(ROOT / "marker_frequency.csv", dtype={"dataset": str})
cons = pd.read_csv(ROOT / "consensus_results.csv", dtype={"dataset": str})
cons = cons.merge(summ[["dataset", "method", "median_pairwise_ari"]], on=["dataset", "method"], how="left")
fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
for _, x in marker.iterrows():
    axes[0].plot([0, 1], [x.unstable_marker_jaccard, x.stable_marker_jaccard], color=COLORS[x.method], alpha=.25, lw=.8)
axes[0].scatter(np.zeros(len(marker)), marker.unstable_marker_jaccard, c=[COLORS[x] for x in marker.method], s=10)
axes[0].scatter(np.ones(len(marker)), marker.stable_marker_jaccard, c=[COLORS[x] for x in marker.method], s=10)
axes[0].set_xticks([0, 1], ["iso-accuracy\nunstable", "stable control"]); axes[0].set(ylabel="Median aligned-domain\ntop-100 marker Jaccard", title="A  Marker reproducibility")
rep = freq[(freq.dataset == "151507") & (freq.method == "GraphST")]
top = rep.groupby("gene").marker_frequency.mean().sort_values(ascending=False).head(18).index
fh = rep[rep.gene.isin(top)].pivot(index="gene", columns="aligned_consensus_domain", values="marker_frequency").loc[top]
sns.heatmap(fh, cmap="YlGnBu", vmin=0, vmax=1, ax=axes[1], cbar_kws={"label": "top-100 frequency"})
axes[1].set(xlabel="Aligned domain", ylabel="", title="B  Representative stable marker core")
for _, x in cons.iterrows():
    axes[2].plot([0, 1], [x.median_pairwise_ari, x.split10_consensus_partition_ari], color=COLORS[x.method], alpha=.28, lw=.8)
axes[2].scatter(np.zeros(len(cons)), cons.median_pairwise_ari, c=[COLORS[x] for x in cons.method], s=10)
axes[2].scatter(np.ones(len(cons)), cons.split10_consensus_partition_ari, c=[COLORS[x] for x in cons.method], s=10)
axes[2].set_xticks([0, 1], ["median seed-pair", "independent 10-seed\nconsensus maps"]); axes[2].set(ylabel="Partition ARI", title="C  Simple consensus mitigation")
fig.tight_layout(); save("Figure_6_downstream_and_consensus")
print("wrote six main figures (PNG and PDF)")
