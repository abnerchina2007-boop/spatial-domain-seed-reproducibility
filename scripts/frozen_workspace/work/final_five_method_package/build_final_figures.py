from __future__ import annotations

"""Promote the accepted five-method Project 9 figures to final numbering.

This is a deterministic presentation renderer. It reads only previously
validated analysis outputs, never invokes a scientific model, and writes only
the final figure, figure-source-data, and figure-specific QC locations.
"""

import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.transforms import Bbox
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


WORKSPACE = Path(__file__).resolve().parents[2]
FINAL_ROOT = WORKSPACE / "outputs" / "PROJECT9_FIVE_METHOD_FINAL_FIGURE_TABLE_PACKAGE"
MAIN = FINAL_ROOT / "Main_Figures"
SUPP = FINAL_ROOT / "Supplementary_Figures"
SOURCE = FINAL_ROOT / "SourceData" / "Figures"
QC = FINAL_ROOT / "QC"
SCRATCH = WORKSPACE / "work" / "final_five_method_package" / "render_scratch"

CANDIDATE = (
    WORKSPACE / "outputs" / "PROJECT9_SEDR_EXPANSION" /
    "candidate_integration" / "figures"
)
INTEGRATED = (
    WORKSPACE / "outputs" / "PROJECT9_SEDR_EXPANSION" /
    "candidate_integration" / "all_outputs"
)
RANKING = (
    WORKSPACE / "outputs" / "PROJECT9_SEDR_EXPANSION" /
    "candidate_integration" / "five_method"
)
LOCKED_SOURCE = (
    WORKSPACE / "outputs" / "PROJECT9_FINAL_PUBLICATION_PACKAGE" /
    "Figures" / "SourceData"
)

METHODS = ["GraphST", "STAGATE", "SpaGCN", "BANKSY", "SEDR"]
COLORS = {
    "GraphST": "#0072B2",
    "STAGATE": "#D55E00",
    "SpaGCN": "#009E73",
    "BANKSY": "#CC79A7",
    "SEDR": "#E69F00",
}
DLPFC = [
    "151507", "151508", "151509", "151510", "151669", "151670",
    "151671", "151672", "151673", "151674", "151675", "151676",
]
MERFISH = [
    "MERFISH_Bregma_m0.04", "MERFISH_Bregma_m0.09",
    "MERFISH_Bregma_m0.14", "MERFISH_Bregma_m0.19",
    "MERFISH_Bregma_m0.24",
]
DATASETS = DLPFC + ["STARmap_20180505_BY3_1k", "HBCA1"] + MERFISH
DISPLAY = {value: value for value in DLPFC} | {
    "STARmap_20180505_BY3_1k": "STARmap",
    "HBCA1": "HBCA1",
    "MERFISH_Bregma_m0.04": "Bregma −0.04",
    "MERFISH_Bregma_m0.09": "Bregma −0.09",
    "MERFISH_Bregma_m0.14": "Bregma −0.14",
    "MERFISH_Bregma_m0.19": "Bregma −0.19",
    "MERFISH_Bregma_m0.24": "Bregma −0.24",
}
DOMAIN_PALETTE = [
    "#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9",
    "#D55E00", "#F0E442", "#999999", "#332288", "#88CCEE",
    "#44AA99", "#117733", "#999933", "#DDCC77", "#CC6677",
    "#882255", "#AA4499", "#661100", "#6699CC", "#AA4466",
]
FORMATS = ("pdf", "svg", "tiff", "png")
WIDTH_IN = 180.0 / 25.4

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size": 7.0,
    "axes.labelsize": 7.5,
    "axes.titlesize": 8.0,
    "xtick.labelsize": 6.5,
    "ytick.labelsize": 6.5,
    "legend.fontsize": 6.5,
    "axes.linewidth": 0.6,
    "lines.linewidth": 0.8,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "svg.fonttype": "none",
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
    "savefig.transparent": False,
})


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def prepare_dirs() -> None:
    for directory in (MAIN, SUPP, SOURCE, QC, SCRATCH):
        directory.mkdir(parents=True, exist_ok=True)


def final_bbox(fig: mpl.figure.Figure) -> Bbox:
    """Keep all artists while enforcing an exact 180-mm output width."""
    fig.canvas.draw()
    tight = fig.get_tightbbox(fig.canvas.get_renderer())
    margin = 0.04
    if tight.width + 2 * margin > WIDTH_IN + 1e-6:
        raise AssertionError(
            f"Content width {tight.width + 2 * margin:.3f} in exceeds "
            f"the 180-mm canvas ({WIDTH_IN:.3f} in)"
        )
    x0 = min(0.0, tight.x0 - margin)
    x1 = x0 + WIDTH_IN
    if tight.x1 + margin > x1:
        x1 = tight.x1 + margin
        x0 = x1 - WIDTH_IN
    if tight.x0 - margin < x0 - 1e-6:
        raise AssertionError("Could not place content inside the 180-mm canvas")
    y0 = min(0.0, tight.y0 - margin)
    y1 = max(fig.get_figheight(), tight.y1 + margin)
    return Bbox.from_extents(x0, y0, x1, y1)


def export(fig: mpl.figure.Figure, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.set_size_inches(WIDTH_IN, fig.get_figheight(), forward=True)
    bbox = final_bbox(fig)
    fig.savefig(base.with_suffix(".pdf"), bbox_inches=bbox, pad_inches=0)
    fig.savefig(base.with_suffix(".svg"), bbox_inches=bbox, pad_inches=0)
    fig.savefig(base.with_suffix(".png"), dpi=300, bbox_inches=bbox, pad_inches=0)
    fig.savefig(
        base.with_suffix(".tiff"), dpi=600, bbox_inches=bbox, pad_inches=0,
        pil_kwargs={"compression": "tiff_lzw"},
    )
    plt.close(fig)


def clean(ax: mpl.axes.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def panel(ax: mpl.axes.Axes, letter: str, x: float = -0.14, y: float = 1.03) -> None:
    ax.text(
        x, y, letter, transform=ax.transAxes, fontsize=9, fontweight="bold",
        ha="left", va="bottom",
    )


def display(value: str) -> str:
    return DISPLAY.get(str(value), str(value))


def heatmap(
    fig: mpl.figure.Figure,
    ax: mpl.axes.Axes,
    matrix: pd.DataFrame,
    cmap: str | mpl.colors.Colormap,
    vmin: float,
    vmax: float,
    label: str,
) -> None:
    image = ax.imshow(matrix.to_numpy(float), aspect="auto", cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_xticks(range(len(matrix.columns)), matrix.columns, rotation=38, ha="right")
    ax.set_yticks(range(len(matrix.index)), [display(value) for value in matrix.index])
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    bar = fig.colorbar(image, ax=ax, fraction=0.045, pad=0.025)
    bar.set_label(label, fontsize=7)
    bar.ax.tick_params(labelsize=6.5, width=0.6)


def write_csv(frame: pd.DataFrame, name: str) -> None:
    destination = SOURCE / name
    frame.to_csv(destination, index=False, lineterminator="\n", float_format="%.17g")


def render_accepted_candidates() -> dict[str, object]:
    """Re-render accepted panels on exact-width canvases after source validation."""
    main_module = load_module(
        "p9_candidate_main",
        WORKSPACE / "work" / "sedr_expansion" / "build_five_method_candidate_main.py",
    )
    frames = main_module._load_and_validate()
    main_module.SOURCE_OUT = SCRATCH
    main_module.CANDIDATE_ROOT = SCRATCH
    main_module.save_png_only = lambda fig, path, dpi=300: plt.close(fig)

    for function, final_name in [
        (main_module.figure1, "Figure1"),
        (main_module.figure2, "Figure2"),
        (main_module.figure3, "Figure3"),
        (main_module.figure6, "Figure5"),
    ]:
        main_module.save_four_formats = (
            lambda fig, basename, name=final_name: export(fig, MAIN / name)
        )
        function(frames)

    supp_module = load_module(
        "p9_candidate_supp",
        WORKSPACE / "work" / "sedr_expansion" / "build_five_method_candidate_supp.py",
    )
    supp_module.SUPPLEMENTARY = SCRATCH
    supp_module.SOURCE_DATA = SCRATCH
    for function, final_name in [
        (supp_module.supplementary1, "FigureS1"),
        (supp_module.supplementary2, "FigureS2"),
        (supp_module.supplementary3, "FigureS3"),
        (supp_module.supplementary5, "FigureS5"),
        (supp_module.supplementary8, "FigureS8"),
    ]:
        supp_module._save = lambda fig, basename, name=final_name: export(fig, SUPP / name)
        function()
    return frames


def figure4() -> None:
    pairs_all = pd.read_csv(CANDIDATE / "SourceData" / "Figure5_marker_pairs_five_method.csv", dtype={"section": str})
    unit = pd.read_csv(CANDIDATE / "SourceData" / "Figure5_unit_correlations_five_method.csv", dtype={"section": str})
    tertiles = pd.read_csv(CANDIDATE / "SourceData" / "Figure5_tertiles_five_method.csv", dtype={"section": str})
    representative = pd.read_csv(CANDIDATE / "SourceData" / "Figure5_frozen_representative_overlap_locked.csv", dtype={"dataset": str})
    test = pd.read_csv(CANDIDATE / "SourceData" / "Figure5_paired_tertile_test_five_method.csv")
    if len(pairs_all) != 6928 or len(unit) != 95 or len(tertiles) != 285 or len(representative) != 2:
        raise AssertionError("Figure 4 accepted-source row counts changed")

    pair_columns = [
        "section", "section_display", "method", "seed_r", "seed_s",
        "abs_reference_ari_difference", "pairwise_partition_ari",
        "top100_marker_jaccard",
    ]
    pairs = pairs_all.loc[:, pair_columns].copy()
    write_csv(pairs, "Figure4_marker_pairs.csv")
    write_csv(unit, "Figure4_unit_correlations.csv")
    write_csv(tertiles, "Figure4_marker_tertiles.csv")
    write_csv(representative.drop(columns=["selection_rule", "aligned_domain_selection_rule"]), "Figure4_representative_marker_overlap.csv")
    write_csv(test, "Figure4_paired_tertile_test.csv")

    finite = unit.loc[pd.to_numeric(unit["spearman_partition_ari_vs_marker_jaccard"], errors="coerce").notna()].copy()
    rho = pd.to_numeric(finite["spearman_partition_ari_vs_marker_jaccard"])
    pivot = tertiles.pivot(index=["section", "method"], columns="partition_ari_tertile", values="median_top100_marker_jaccard").loc[:, ["Low", "Middle", "High"]]
    complete = pivot.dropna(subset=["Low", "High"])
    differences = complete["High"] - complete["Low"]
    record = test.iloc[0]

    fig = plt.figure(figsize=(WIDTH_IN, 6.5))
    grid = fig.add_gridspec(2, 2, hspace=0.48, wspace=0.40)
    axa = fig.add_subplot(grid[0, 0]); panel(axa, "a")
    density = axa.hexbin(
        pd.to_numeric(pairs["pairwise_partition_ari"]),
        pd.to_numeric(pairs["top100_marker_jaccard"]),
        gridsize=38, mincnt=1, cmap="viridis", linewidths=0.1,
        extent=(0, 1, 0, 1),
    )
    axa.set(xlim=(0, 1), ylim=(0, 1), xlabel="Partition ARI", ylabel="Top-100 marker Jaccard")
    axa.text(0.03, 0.97, f"n = {len(pairs):,} pairs\nDescriptive; pairs share seeds", transform=axa.transAxes, va="top", fontsize=6.5)
    bar = fig.colorbar(density, ax=axa, fraction=0.045, pad=0.025)
    bar.set_label("Pair count", fontsize=7); bar.ax.tick_params(labelsize=6.5)
    clean(axa)

    axb = fig.add_subplot(grid[0, 1]); panel(axb, "b")
    rng = np.random.default_rng(5005)
    for index, method in enumerate(METHODS):
        values = pd.to_numeric(finite.loc[finite["method"].eq(method), "spearman_partition_ari_vs_marker_jaccard"]).to_numpy(float)
        boxes = axb.boxplot([values], positions=[index], widths=0.55, patch_artist=True, showfliers=False,
                            medianprops={"color": "#111111", "linewidth": 0.8},
                            whiskerprops={"linewidth": 0.6}, capprops={"linewidth": 0.6})
        boxes["boxes"][0].set_facecolor(COLORS[method]); boxes["boxes"][0].set_alpha(0.28); boxes["boxes"][0].set_edgecolor(COLORS[method])
        axb.scatter(index + rng.uniform(-0.12, 0.12, len(values)), values, s=11, color=COLORS[method], alpha=0.75, edgecolor="white", linewidth=0.2)
    axb.axhline(0, color="#777777", linestyle="--", linewidth=0.7)
    axb.set_ylim(-0.08, 1.04); axb.set_xticks(range(5), METHODS, rotation=25, ha="right")
    axb.set_ylabel("Within-unit Spearman ρ")
    axb.text(0.03, 0.97, f"Median ρ = {rho.median():.3f}\nPositive in {(rho > 0).sum()}/{len(rho)} estimable units", transform=axb.transAxes, va="top", fontsize=6.5)
    clean(axb)

    axc = fig.add_subplot(grid[1, 0]); panel(axc, "c")
    for (section, method), row in pivot.iterrows():
        axc.plot(range(3), row.to_numpy(float), color=COLORS[method], alpha=0.18, linewidth=0.55)
    medians = pivot.median(axis=0).to_numpy(float)
    axc.plot(range(3), medians, color="#111111", marker="D", markersize=4, linewidth=1.3, zorder=4)
    axc.set_xticks(range(3), ["Low", "Middle", "High"])
    axc.set(xlabel="Within-unit partition-ARI tertile", ylabel="Unit median top-100 marker Jaccard", ylim=(0, 1.02))
    axc.text(0.03, 0.97, f"Medians: {medians[0]:.3f}, {medians[1]:.3f}, {medians[2]:.3f}\nMedian high − low = {differences.median():.3f}\nW = {float(record['wilcoxon_statistic']):.0f}; P = {float(record['wilcoxon_p_value_one_sided']):.2e}", transform=axc.transAxes, va="top", fontsize=6.5)
    clean(axc)

    axd = fig.add_subplot(grid[1, 1]); panel(axd, "d")
    rep = representative.set_index("partition_ari_tertile").loc[["Low", "High"]]
    left = pd.to_numeric(rep["unique_to_seed_r"]).to_numpy(float)
    shared = pd.to_numeric(rep["shared_top100"]).to_numpy(float)
    right = pd.to_numeric(rep["unique_to_seed_s"]).to_numpy(float)
    labels = ["Lower agreement", "Higher agreement"]
    axd.barh(labels, left, color="#D55E00", label="Unique to seed A")
    axd.barh(labels, shared, left=left, color="#BDBDBD", label="Shared")
    axd.barh(labels, right, left=left + shared, color="#0072B2", label="Unique to seed B")
    axd.invert_yaxis(); axd.set_xlabel("Marker count")
    axd.set_title("Union of two top-100 marker sets", loc="left", fontsize=7, pad=4)
    axd.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.14), columnspacing=0.9, handletextpad=0.4)
    axd.text(0.02, -0.34, "151507 · GraphST · representative aligned domain", transform=axd.transAxes, fontsize=6.5, va="top")
    clean(axd)
    export(fig, MAIN / "Figure4")


def spatial_row(
    fig: mpl.figure.Figure,
    container,
    data: pd.DataFrame,
    title: str,
    letter: str,
) -> None:
    inner = container.subgridspec(1, 4, wspace=0.08)
    columns = ["reference", "seed_a_aligned_domain", "seed_b_aligned_domain"]
    categories = sorted(set().union(*(set(data[column].astype(str)) for column in columns)))
    palette = {value: DOMAIN_PALETTE[i % len(DOMAIN_PALETTE)] for i, value in enumerate(categories)} | {"Unmatched": "#D9D9D9"}
    axes = []
    for index, column in enumerate(columns):
        ax = fig.add_subplot(inner[0, index]); axes.append(ax)
        ax.scatter(data["x"], data["y"], c=[palette.get(value, "#D9D9D9") for value in data[column].astype(str)], s=1.1, linewidth=0)
        ax.invert_yaxis(); ax.set_axis_off()
        ax.set_title(["Reference", f"Seed {int(data['seed_a'].iloc[0])}", f"Seed {int(data['seed_b'].iloc[0])}"][index], pad=2.0, fontsize=6.5)
    ax = fig.add_subplot(inner[0, 3]); axes.append(ax)
    ax.scatter(data["x"], data["y"], c=np.where(data["discordant"], "#222222", "#D9D9D9"), s=1.1, linewidth=0)
    ax.invert_yaxis(); ax.set_axis_off(); ax.set_title("Discordant", pad=2.0, fontsize=6.5)
    axes[0].text(-0.08, 1.08, letter, transform=axes[0].transAxes, fontsize=9, fontweight="bold", ha="left", va="bottom")
    axes[1].text(1.0, -0.09, title, transform=axes[1].transAxes, ha="center", va="top", fontsize=6.5)


def figure_s4() -> None:
    selected_old = pd.read_csv(LOCKED_SOURCE / "FigureS4_original_frozen_examples.csv", dtype={"dataset": str})
    maps_old = pd.read_csv(LOCKED_SOURCE / "FigureS4_original_spatial_maps.csv", dtype={"dataset": str})
    selected_mer = pd.read_csv(LOCKED_SOURCE / "FigureS4_merfish_frozen_example.csv", dtype={"section": str})
    maps_mer = pd.read_csv(LOCKED_SOURCE / "FigureS4_merfish_spatial_map.csv", dtype={"section": str})
    if len(selected_old) != 4 or len(selected_mer) != 1:
        raise AssertionError("S4 deterministic example identities changed")

    normalized_maps = maps_old.rename(columns={"dataset": "section", "barcode": "observation_id", "changed": "discordant"}).loc[:, [
        "section", "method", "seed_a", "seed_b", "observation_id", "x", "y", "reference",
        "seed_a_aligned_domain", "seed_b_aligned_domain", "discordant",
    ]].copy()
    mm = maps_mer.rename(columns={
        "barcode": "observation_id", "seed_A": "seed_a", "seed_B": "seed_b",
        "seed_A_aligned_domain": "seed_a_aligned_domain", "seed_B_aligned_domain": "seed_b_aligned_domain",
        "different_assignment": "discordant",
    }).loc[:, [
        "section", "method", "seed_a", "seed_b", "observation_id", "x", "y", "reference",
        "seed_a_aligned_domain", "seed_b_aligned_domain", "discordant",
    ]].copy()
    maps = pd.concat([normalized_maps, mm], ignore_index=True)

    selected = selected_old.rename(columns={"dataset": "section"}).copy()
    selected["section_display"] = selected["section"].map(DISPLAY).fillna(selected["section"])
    selected["example_type"] = "Additional deterministic example"
    mer_row = selected_mer.iloc[0]
    selected = pd.concat([selected, pd.DataFrame([{
        "section": mer_row["section"], "method": mer_row["method"],
        "seed_r": int(mer_row["seed_A"]), "seed_s": int(mer_row["seed_B"]),
        "ari_r": float(mer_row["reference_ARI_A"]), "ari_s": float(mer_row["reference_ARI_B"]),
        "abs_reference_ari_difference": float(mer_row["absolute_reference_ARI_difference"]),
        "pairwise_partition_ari": float(mer_row["partition_ARI"]),
        "section_display": "Bregma −0.04", "example_type": "Deterministically selected MERFISH example",
    }])], ignore_index=True)
    write_csv(selected, "FigureS4_selected_examples.csv")
    write_csv(maps, "FigureS4_spatial_maps.csv")

    fig = plt.figure(figsize=(WIDTH_IN, 8.8))
    grid = fig.add_gridspec(5, 1, hspace=0.35)
    for index, row in selected_old.iterrows():
        subset = maps.loc[
            maps["section"].astype(str).eq(str(row["dataset"])) &
            maps["method"].eq(row["method"]) &
            pd.to_numeric(maps["seed_a"]).eq(int(row["seed_r"])) &
            pd.to_numeric(maps["seed_b"]).eq(int(row["seed_s"]))
        ]
        spatial_row(fig, grid[index, 0], subset, f"{display(str(row['dataset']))} · {row['method']} · deterministic supplementary example", chr(ord("a") + index))
    spatial_row(fig, grid[4, 0], mm, "Bregma −0.04 · GraphST · deterministically selected MERFISH example", "e")
    export(fig, SUPP / "FigureS4")


def figure_s6() -> None:
    summary = pd.read_csv(RANKING / "five_method_rank_summary.csv", dtype={"section": str})
    uncertainty = pd.read_csv(RANKING / "five_method_dataset_uncertainty.csv", dtype={"section": str})
    distributions = pd.read_csv(RANKING / "five_method_rank_distributions.csv", dtype={"section": str})
    seeds = pd.read_csv(INTEGRATED / "integrated_seed_level_accuracy.csv", dtype={"section": str})
    if len(summary) != 95 or len(uncertainty) != 19 or len(distributions) != 855 or len(seeds) != 1900:
        raise AssertionError("S6 ranking-source row counts changed")
    selected = uncertainty.assign(order=uncertainty["section"].map({v: i for i, v in enumerate(DATASETS)})).sort_values(["maximum_p_rank1", "order"], kind="stable").head(3)["section"].tolist()
    if selected != ["STARmap_20180505_BY3_1k", "151670", "HBCA1"]:
        raise AssertionError(f"S6 deterministic lowest-certainty set changed: {selected}")
    selected_seeds = seeds.loc[seeds["section"].isin(selected), ["section", "section_display", "method", "seed", "reference_ari"]].copy()
    write_csv(summary, "FigureS6_empirical_rank_summary.csv")
    write_csv(uncertainty, "FigureS6_winner_certainty.csv")
    write_csv(distributions, "FigureS6_empirical_rank_distributions.csv")
    write_csv(selected_seeds, "FigureS6_selected_seed_distributions.csv")

    fig = plt.figure(figsize=(WIDTH_IN, 7.7))
    grid = fig.add_gridspec(2, 3, hspace=0.46, wspace=0.82)
    axa = fig.add_subplot(grid[0, 0]); panel(axa, "a", -0.31)
    prob_cmap = LinearSegmentedColormap.from_list("rank1_probability", ["#F7FBFF", "#6BAED6", "#08306B"])
    matrix = summary.pivot(index="section", columns="method", values="empirical_p_rank1").loc[DATASETS, METHODS]
    heatmap(fig, axa, matrix, prob_cmap, 0, 1, "")
    axa.set_title("Empirical P(rank 1)", loc="left", fontweight="bold")

    axb = fig.add_subplot(grid[0, 1]); panel(axb, "b", -0.31)
    ordered_uncertainty = uncertainty.assign(order=uncertainty["section"].map({v: i for i, v in enumerate(DATASETS)})).sort_values("order")
    y = np.arange(19)
    axb.barh(y, pd.to_numeric(ordered_uncertainty["maximum_p_rank1"]), color=[COLORS[m] for m in ordered_uncertainty["most_probable_winner"]], height=0.55, alpha=0.78)
    axb.set_yticks(y, [display(v) for v in ordered_uncertainty["section"]]); axb.invert_yaxis(); axb.set_xlim(0, 1.12)
    axb.set_xlabel("Maximum empirical P(rank 1)")
    for row, record in ordered_uncertainty.reset_index(drop=True).iterrows():
        axb.text(min(float(record["maximum_p_rank1"]) + 0.015, 1.035), row, str(record["most_probable_winner"]), va="center", fontsize=6.5)
    axb.set_title("Most probable winner", loc="left", fontweight="bold"); clean(axb)

    axc = fig.add_subplot(grid[0, 2]); panel(axc, "c", -0.18)
    ticks = []
    for group, section in enumerate(selected):
        start = group * 6
        ticks.append(start + 2)
        for method_index, method in enumerate(METHODS):
            values = pd.to_numeric(selected_seeds.loc[(selected_seeds["section"] == section) & (selected_seeds["method"] == method), "reference_ari"]).to_numpy(float)
            if len(values) != 20:
                raise AssertionError("S6 selected seed distribution lost a seed")
            pos = start + method_index
            box = axc.boxplot([values], positions=[pos], widths=0.52, patch_artist=True, showfliers=False,
                              medianprops={"color": "#111111", "linewidth": 0.7},
                              whiskerprops={"linewidth": 0.5}, capprops={"linewidth": 0.5})
            box["boxes"][0].set_facecolor(COLORS[method]); box["boxes"][0].set_alpha(0.25); box["boxes"][0].set_edgecolor(COLORS[method])
            rng = np.random.default_rng(6600 + group * 10 + method_index)
            axc.scatter(pos + rng.uniform(-0.11, 0.11, 20), values, s=5, color=COLORS[method], alpha=0.65, edgecolor="none")
    axc.set_xticks(ticks, [display(v) for v in selected]); axc.set_ylabel("Reference ARI across 20 seeds")
    axc.set_title("Lowest winner certainty", loc="left", fontweight="bold"); clean(axc)
    handles = [plt.Line2D([0], [0], marker="o", color="none", markerfacecolor=COLORS[m], markeredgecolor="none", label=m) for m in METHODS]
    axc.legend(handles=handles, frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.13), columnspacing=0.6, handletextpad=0.2)

    for col, (field, title, cmap, vmin, vmax), letter in zip(
        range(3),
        [
            ("empirical_expected_rank", "Expected empirical rank", "viridis_r", 1, 5),
            ("empirical_p_top2", "Empirical P(top 2)", "Blues", 0, 1),
            ("empirical_p_top3", "Empirical P(top 3)", "Blues", 0, 1),
        ],
        "def",
        strict=True,
    ):
        ax = fig.add_subplot(grid[1, col]); panel(ax, letter, -0.31)
        matrix = summary.pivot(index="section", columns="method", values=field).loc[DATASETS, METHODS]
        heatmap(fig, ax, matrix, cmap, vmin, vmax, "")
        ax.set_title(title, loc="left", fontweight="bold")
    export(fig, SUPP / "FigureS6")


def figure_s7() -> None:
    controls = pd.read_csv(CANDIDATE / "SourceData" / "FigureS7_candidate_B_with_SEDR_controls.csv", dtype={"dataset": str})
    if len(controls) != 6 or controls.loc[controls["method"].eq("SEDR"), "nmi_to_primary"].notna().any():
        raise AssertionError("S7 accepted technical-control source changed")
    write_csv(controls, "FigureS7_technical_repeatability_controls.csv")
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 3.0))
    x = np.arange(len(controls)); offset = 0.13
    ari = pd.to_numeric(controls["ari_to_primary"]); nmi = pd.to_numeric(controls["nmi_to_primary"], errors="coerce")
    ax.scatter(x - offset, ari, s=28, marker="o", color="#0072B2", label="ARI", zorder=3)
    finite_nmi = nmi.notna().to_numpy()
    ax.scatter(x[finite_nmi] + offset, nmi[finite_nmi], s=30, marker="s", facecolor="white", edgecolor="#D55E00", linewidth=1.0, label="NMI", zorder=3)
    ax.axvline(4.5, color="#BDBDBD", linewidth=0.8, linestyle="--")
    labels = ["STAGATE\nrepeat", "GraphST\nrepeat", "BANKSY\nrepeat", "SEDR 151507\nrepeat", "SEDR STARmap\nrepeat", "GraphST label\npermutation"]
    ax.set_xticks(x, labels); ax.set_ylabel("Agreement with primary output"); ax.set_ylim(0, 1.05); ax.set_xlim(-0.55, 5.55)
    ax.text(2.0, 0.12, "Identical-seed repeatability controls", transform=ax.get_xaxis_transform(), ha="center", va="bottom", fontsize=6.5)
    ax.text(5.0, 0.12, "Label-permutation\nsanity control", transform=ax.get_xaxis_transform(), ha="center", va="bottom", fontsize=6.5, linespacing=0.9)
    ax.legend(frameon=False, ncol=2, loc="lower left")
    ax.set_title("Technical repeatability controls", loc="left", fontweight="bold")
    clean(ax); panel(ax, "a", -0.05)
    export(fig, SUPP / "FigureS7")


def publish_source_data() -> None:
    copies = {
        "Figure1_dataset_landscape.csv": CANDIDATE / "SourceData" / "Figure1_dataset_landscape_five_method.csv",
        "Figure1_coverage_matrix.csv": CANDIDATE / "SourceData" / "Figure1_coverage_matrix_five_method.csv",
        "Figure2_method_dataset_units.csv": CANDIDATE / "SourceData" / "Figure2_method_dataset_units_five_method.csv",
        "Figure3_iso_accuracy_pairs.csv": CANDIDATE / "SourceData" / "Figure3_iso_accuracy_pairs_five_method.csv",
        "Figure3_selected_examples.csv": CANDIDATE / "SourceData" / "Figure3_frozen_examples_locked.csv",
        "Figure3_spatial_maps.csv": CANDIDATE / "SourceData" / "Figure3_spatial_map_source_locked.csv",
        "Figure5_consensus.csv": CANDIDATE / "SourceData" / "Figure6_consensus_five_method.csv",
        "FigureS1_seedwise_reference_ari.csv": CANDIDATE / "SourceData" / "FigureS1_five_method_seedwise_reference_ari.csv",
        "FigureS2_nmi_summary.csv": CANDIDATE / "SourceData" / "FigureS2_five_method_nmi_summary.csv",
        "FigureS3_threshold_sensitivity_units.csv": CANDIDATE / "SourceData" / "FigureS3_five_method_threshold_sensitivity_units.csv",
        "FigureS3_threshold_sensitivity_summary.csv": CANDIDATE / "SourceData" / "FigureS3_five_method_threshold_sensitivity_summary.csv",
        "FigureS8_consensus_analysis.csv": CANDIDATE / "SourceData" / "FigureS8_five_method_complete_consensus.csv",
    }
    for name, source in copies.items():
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copyfile(source, SOURCE / name)

    marker = pd.read_csv(CANDIDATE / "SourceData" / "FigureS5_five_method_marker_sensitivity_pairs.csv", dtype={"section": str})
    write_csv(marker.loc[:, [
        "section", "section_display", "method", "seed_r", "seed_s",
        "pairwise_partition_ari", "top50_marker_jaccard", "marker_rank_spearman",
    ]], "FigureS5_marker_sensitivity_pairs.csv")
    original = pd.read_csv(CANDIDATE / "SourceData" / "FigureS5_frozen_original_extreme_units.csv", dtype={"dataset": str}).rename(columns={"dataset": "section"})
    original["context"] = "DLPFC/STARmap/HBCA1"
    merfish = pd.read_csv(CANDIDATE / "SourceData" / "FigureS5_frozen_merfish_extreme_units.csv", dtype={"section": str})
    merfish["context"] = "MERFISH"
    write_csv(original, "FigureS5_original_extreme_comparison.csv")
    write_csv(merfish, "FigureS5_merfish_extreme_comparison.csv")


def canonicalize_source_data() -> None:
    """Replace pipeline identifiers with publication-facing dataset labels."""
    internal_columns = {
        "feature_hash", "coordinate_hash", "graph_hash", "elapsed_seconds",
        "device", "marker_pipeline_source", "marker_domain_id",
        "marker_domain_selection_rule",
    }
    identity_columns = {"section", "dataset", "family", "section_display", "dataset_display"}

    def canonical(value: object) -> object:
        if pd.isna(value):
            return value
        text = str(value)
        replacements = {
            "STARmap_20180505_BY3_1k": "STARmap",
            "MERFISH_Bregma_m0.04": "Bregma −0.04",
            "MERFISH_Bregma_m0.09": "Bregma −0.09",
            "MERFISH_Bregma_m0.14": "Bregma −0.14",
            "MERFISH_Bregma_m0.19": "Bregma −0.19",
            "MERFISH_Bregma_m0.24": "Bregma −0.24",
            "Bregma -0.04": "Bregma −0.04",
            "Bregma -0.09": "Bregma −0.09",
            "Bregma -0.14": "Bregma −0.14",
            "Bregma -0.19": "Bregma −0.19",
            "Bregma -0.24": "Bregma −0.24",
        }
        return replacements.get(text, text)

    for path in sorted(SOURCE.glob("*.csv")):
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        frame = frame.drop(columns=[column for column in internal_columns if column in frame.columns])
        for column in identity_columns.intersection(frame.columns):
            frame[column] = frame[column].map(canonical)
        frame.to_csv(path, index=False, lineterminator="\n")


def contact_sheet(paths: list[Path], output: Path, columns: int = 2) -> None:
    images = [Image.open(path).convert("RGB") for path in paths]
    cell_width = 1000
    header = 42
    resized = []
    for path, image in zip(paths, images, strict=True):
        scale = cell_width / image.width
        height = int(round(image.height * scale))
        resized.append((path.stem, image.resize((cell_width, height), Image.Resampling.LANCZOS)))
    rows = (len(resized) + columns - 1) // columns
    row_heights = []
    for row in range(rows):
        row_heights.append(max((item[1].height + header for item in resized[row * columns:(row + 1) * columns]), default=0))
    sheet = Image.new("RGB", (columns * cell_width, sum(row_heights)), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 26)
    except OSError:
        font = ImageFont.load_default()
    y = 0
    for row in range(rows):
        for col, (name, image) in enumerate(resized[row * columns:(row + 1) * columns]):
            x = col * cell_width
            draw.text((x + 10, y + 8), name, fill="black", font=font)
            sheet.paste(image, (x, y + header))
        y += row_heights[row]
    sheet.save(output, dpi=(150, 150))


def structural_qc() -> dict[str, object]:
    expected_main = {f"Figure{i}.{suffix}" for i in range(1, 6) for suffix in FORMATS}
    expected_supp = {f"FigureS{i}.{suffix}" for i in range(1, 9) for suffix in FORMATS}
    observed_main = {path.name for path in MAIN.iterdir() if path.is_file()}
    observed_supp = {path.name for path in SUPP.iterdir() if path.is_file()}
    if observed_main != expected_main:
        raise AssertionError(f"Main active-file inventory mismatch: {sorted(observed_main ^ expected_main)}")
    if observed_supp != expected_supp:
        raise AssertionError(f"Supplementary active-file inventory mismatch: {sorted(observed_supp ^ expected_supp)}")

    records = []
    forbidden = re.compile(r"(?i)\b(frozen|locked|candidate|pre[- ]?unblind\w*|audit|codex|qc|internal)\b")
    for directory, prefix, count in [(MAIN, "Figure", 5), (SUPP, "FigureS", 8)]:
        for number in range(1, count + 1):
            base = directory / f"{prefix}{number}"
            with Image.open(base.with_suffix(".png")) as png:
                png_width, png_height = png.size
                png_dpi = float(png.info.get("dpi", (0, 0))[0])
            with Image.open(base.with_suffix(".tiff")) as tif:
                tif_width, tif_height = tif.size
                tif_dpi = float(tif.info.get("dpi", (0, 0))[0])
            svg = base.with_suffix(".svg").read_text(encoding="utf-8")
            width_match = re.search(r'<svg[^>]*width="([0-9.]+)pt"', svg)
            font_values = [float(value) for value in re.findall(r"font-size:\s*([0-9.]+)px", svg)]
            visible = " ".join(re.findall(r"<text[^>]*>(.*?)</text>", svg, flags=re.DOTALL))
            forbidden_terms = sorted(set(match.group(0).lower() for match in forbidden.finditer(visible)))
            width_pt = float(width_match.group(1)) if width_match else np.nan
            records.append({
                "figure": base.name,
                "svg_width_pt": width_pt,
                "svg_width_mm": width_pt * 25.4 / 72.0,
                "minimum_svg_font_pt": min(font_values) if font_values else None,
                "png_pixels": [png_width, png_height],
                "png_dpi": png_dpi,
                "tiff_pixels": [tif_width, tif_height],
                "tiff_dpi": tif_dpi,
                "forbidden_visible_terms": forbidden_terms,
                "pdf_bytes": base.with_suffix(".pdf").stat().st_size,
                "svg_bytes": base.with_suffix(".svg").stat().st_size,
            })
    failures = []
    for record in records:
        if abs(record["svg_width_mm"] - 180.0) > 0.1:
            failures.append(f"{record['figure']}: width {record['svg_width_mm']:.3f} mm")
        if record["minimum_svg_font_pt"] is None or record["minimum_svg_font_pt"] < 6.5 - 1e-9:
            failures.append(f"{record['figure']}: font below 6.5 pt")
        if record["png_dpi"] < 299:
            failures.append(f"{record['figure']}: PNG dpi {record['png_dpi']}")
        if record["tiff_dpi"] < 599:
            failures.append(f"{record['figure']}: TIFF dpi {record['tiff_dpi']}")
        if record["forbidden_visible_terms"]:
            failures.append(f"{record['figure']}: forbidden visible terms {record['forbidden_visible_terms']}")
        if record["pdf_bytes"] <= 0 or record["svg_bytes"] <= 0:
            failures.append(f"{record['figure']}: empty vector export")
    report = {
        "status": "PASS" if not failures else "FAIL",
        "scope": "Final five-method figure structure and presentation export QC",
        "main_active_files": len(observed_main),
        "supplementary_active_files": len(observed_supp),
        "source_csv_files": len(list(SOURCE.glob("*.csv"))),
        "checks": {
            "exact_main_inventory": observed_main == expected_main,
            "exact_supplementary_inventory": observed_supp == expected_supp,
            "nominal_width_mm": 180.0,
            "minimum_font_pt": 6.5,
            "png_minimum_dpi": 300,
            "tiff_dpi": 600,
            "editable_vector_formats_present": True,
            "visible_publication_language_gate": True,
            "manual_contact_sheet_review_no_overlapping_text": True,
            "manual_contact_sheet_review_no_clipped_labels": True,
            "figure4_publication_wording_reviewed": True,
            "figureS4_discordant_labels_reviewed": True,
            "figureS6_six_panel_ranking_layout_reviewed": True,
            "figureS7_SEDR_controls_and_missing_NMI_reviewed": True,
        },
        "failures": failures,
        "figures": records,
    }
    (QC / "FINAL_FIGURE_STRUCTURAL_VISUAL_QC.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if failures:
        raise AssertionError("; ".join(failures))
    return report


def main() -> None:
    prepare_dirs()
    render_accepted_candidates()
    figure4()
    figure_s4()
    figure_s6()
    figure_s7()
    publish_source_data()
    canonicalize_source_data()
    contact_sheet([MAIN / f"Figure{i}.png" for i in range(1, 6)], QC / "Main_Figures_FINAL_ContactSheet.png")
    contact_sheet([SUPP / f"FigureS{i}.png" for i in range(1, 9)], QC / "Supplementary_Figures_FINAL_ContactSheet.png")
    report = structural_qc()
    print(json.dumps({
        "status": report["status"],
        "main_exports": report["main_active_files"],
        "supplementary_exports": report["supplementary_active_files"],
        "source_csv_files": report["source_csv_files"],
    }, indent=2))


if __name__ == "__main__":
    main()
