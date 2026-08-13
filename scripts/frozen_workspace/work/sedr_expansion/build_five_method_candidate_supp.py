from __future__ import annotations

"""Build candidate five-method Supplementary Figures S1--S8.

This script is deliberately limited to candidate figure exports and their
figure-ready CSV files.  It reads the locked four-method publication package
and the validated five-method integration, but never writes to either source.
"""

import shutil
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


WORKSPACE = Path(__file__).resolve().parents[2]
SEDR = WORKSPACE / "outputs" / "PROJECT9_SEDR_EXPANSION"
INTEGRATED = SEDR / "candidate_integration"
ALL_OUTPUTS = INTEGRATED / "all_outputs"
FIVE_METHOD = INTEGRATED / "five_method"
LOCKED = WORKSPACE / "outputs" / "PROJECT9_FINAL_PUBLICATION_PACKAGE"
LOCKED_SUPP = LOCKED / "Figures" / "Supplementary"
LOCKED_SOURCE = LOCKED / "Figures" / "SourceData"
PHASE0 = WORKSPACE / "outputs" / "PROJECT9_PHASE0"

FIGURE_ROOT = INTEGRATED / "figures"
SUPPLEMENTARY = FIGURE_ROOT / "Supplementary"
SOURCE_DATA = FIGURE_ROOT / "SourceData"

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
ORDER = DLPFC + ["STARmap_20180505_BY3_1k", "HBCA1"] + MERFISH
DISPLAY = {item: item for item in DLPFC} | {
    "STARmap_20180505_BY3_1k": "STARmap",
    "HBCA1": "HBCA1",
    "MERFISH_Bregma_m0.04": "Bregma \u22120.04",
    "MERFISH_Bregma_m0.09": "Bregma \u22120.09",
    "MERFISH_Bregma_m0.14": "Bregma \u22120.14",
    "MERFISH_Bregma_m0.19": "Bregma \u22120.19",
    "MERFISH_Bregma_m0.24": "Bregma \u22120.24",
}
FORMATS = ("pdf", "svg", "tiff", "png")


mpl.rcParams.update(
    {
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
    }
)


def _require_inputs(paths: list[Path]) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing authoritative source(s):\n" + "\n".join(missing))


def _prepare_output_dirs() -> None:
    SUPPLEMENTARY.mkdir(parents=True, exist_ok=True)
    SOURCE_DATA.mkdir(parents=True, exist_ok=True)


def _assert_output_path(path: Path) -> None:
    resolved = path.resolve()
    allowed = (SUPPLEMENTARY.resolve(), SOURCE_DATA.resolve())
    if not any(resolved == root or root in resolved.parents for root in allowed):
        raise RuntimeError(f"Refusing write outside candidate supplementary outputs: {resolved}")


def _write_csv(data: pd.DataFrame, filename: str) -> Path:
    destination = SOURCE_DATA / filename
    _assert_output_path(destination)
    data.to_csv(destination, index=False, lineterminator="\n")
    return destination


def _copy_file(source: Path, destination: Path) -> None:
    _require_inputs([source])
    _assert_output_path(destination)
    shutil.copyfile(source, destination)
    if source.read_bytes() != destination.read_bytes():
        raise RuntimeError(f"Byte-copy validation failed: {source} -> {destination}")


def _save(fig: mpl.figure.Figure, basename: str) -> None:
    base = SUPPLEMENTARY / basename
    for suffix in FORMATS:
        destination = base.with_suffix(f".{suffix}")
        _assert_output_path(destination)
        kwargs: dict[str, object] = {"bbox_inches": "tight", "pad_inches": 0.04}
        if suffix == "png":
            kwargs["dpi"] = 300
        elif suffix == "tiff":
            kwargs["dpi"] = 600
            kwargs["pil_kwargs"] = {"compression": "tiff_lzw"}
        fig.savefig(destination, **kwargs)
    plt.close(fig)


def _clean(ax: mpl.axes.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _panel(ax: mpl.axes.Axes, letter: str, x: float = -0.14, y: float = 1.03) -> None:
    ax.text(
        x,
        y,
        letter,
        transform=ax.transAxes,
        fontsize=9,
        fontweight="bold",
        ha="left",
        va="bottom",
    )


def _heatmap(
    ax: mpl.axes.Axes,
    matrix: pd.DataFrame,
    cmap: str,
    vmin: float,
    vmax: float,
    colorbar_label: str,
) -> None:
    image = ax.imshow(matrix.to_numpy(dtype=float), aspect="auto", cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_xticks(range(len(matrix.columns)), matrix.columns, rotation=38, ha="right")
    ax.set_yticks(range(len(matrix.index)), [DISPLAY[str(value)] for value in matrix.index])
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    bar = plt.colorbar(image, ax=ax, fraction=0.045, pad=0.025)
    bar.set_label(colorbar_label, fontsize=7.0)
    bar.ax.tick_params(labelsize=6.5, width=0.6)


def _ordered(data: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    result["section"] = result["section"].astype(str)
    result["section"] = pd.Categorical(result["section"], categories=ORDER, ordered=True)
    result["method"] = pd.Categorical(result["method"], categories=METHODS, ordered=True)
    return result.sort_values(["section", "method"], kind="stable").reset_index(drop=True)


def _validate_five_method_units(data: pd.DataFrame) -> None:
    if len(data) != 95:
        raise AssertionError(f"Expected 95 method-dataset units, found {len(data)}")
    observed_sections = set(data["section"].astype(str))
    observed_methods = set(data["method"].astype(str))
    if observed_sections != set(ORDER) or observed_methods != set(METHODS):
        raise AssertionError("Five-method unit coverage differs from the frozen 19 x 5 design")
    counts = data.groupby([data["section"].astype(str), data["method"].astype(str)]).size()
    if len(counts) != 95 or not (counts == 1).all():
        raise AssertionError("Method-dataset unit identities are incomplete or duplicated")


def supplementary1() -> None:
    source = ALL_OUTPUTS / "integrated_seed_level_accuracy.csv"
    _require_inputs([source])
    data = pd.read_csv(source, dtype={"section": str})
    if len(data) != 1900:
        raise AssertionError(f"S1 expected 1,900 seed-level rows, found {len(data)}")
    counts = data.groupby(["section", "method"])["seed"].agg(["size", "nunique"])
    if len(counts) != 95 or not ((counts["size"] == 20) & (counts["nunique"] == 20)).all():
        raise AssertionError("S1 does not contain exactly 20 distinct seeds for every one of 95 units")
    if set(data["section"]) != set(ORDER) or set(data["method"]) != set(METHODS):
        raise AssertionError("S1 coverage does not match frozen dataset/method order")
    data = _ordered(data)
    _write_csv(data, "FigureS1_five_method_seedwise_reference_ari.csv")

    fig = plt.figure(figsize=(7.087, 7.15))
    grid = fig.add_gridspec(2, 6, hspace=0.34, wspace=1.30)
    positions = [(0, slice(0, 2)), (0, slice(2, 4)), (0, slice(4, 6)),
                 (1, slice(1, 3)), (1, slice(3, 5))]
    axes = [fig.add_subplot(grid[row, columns]) for row, columns in positions]
    rng = np.random.default_rng(7101)
    for ax, method, letter in zip(axes, METHODS, "abcde", strict=True):
        subset = data[data["method"].astype(str) == method]
        values = [
            subset[subset["section"].astype(str) == section]["reference_ari"].to_numpy(dtype=float)
            for section in ORDER
        ]
        boxes = ax.boxplot(
            values,
            positions=range(len(ORDER)),
            vert=False,
            widths=0.55,
            patch_artist=True,
            showfliers=False,
            medianprops={"color": "#111111", "linewidth": 0.7},
            whiskerprops={"linewidth": 0.5},
            capprops={"linewidth": 0.5},
        )
        for patch in boxes["boxes"]:
            patch.set_facecolor(COLORS[method])
            patch.set_alpha(0.22)
            patch.set_edgecolor(COLORS[method])
        for y, values_for_section in enumerate(values):
            jitter = rng.uniform(-0.12, 0.12, len(values_for_section))
            ax.scatter(
                values_for_section,
                y + jitter,
                s=5,
                color=COLORS[method],
                alpha=0.60,
                edgecolor="none",
            )
        ax.set_yticks(range(len(ORDER)), [DISPLAY[section] for section in ORDER])
        ax.set_ylim(len(ORDER) - 0.5, -0.5)
        ax.set_xlim(0, 1)
        ax.set_xlabel("Reference ARI")
        ax.set_title(method, loc="left", fontweight="bold")
        _clean(ax)
        _panel(ax, letter, x=-0.34)
    _save(fig, "FigureS1_five_method_candidate")


def supplementary2() -> None:
    source = ALL_OUTPUTS / "integrated_method_dataset_summary.csv"
    _require_inputs([source])
    data = pd.read_csv(source, dtype={"section": str})
    _validate_five_method_units(data)
    data = _ordered(data)
    _write_csv(data, "FigureS2_five_method_nmi_summary.csv")

    nmi_sd = data.pivot(index="section", columns="method", values="reference_nmi_sd").loc[ORDER, METHODS]
    pairwise_nmi = data.pivot(
        index="section", columns="method", values="median_pairwise_partition_nmi"
    ).loc[ORDER, METHODS]
    fig, axes = plt.subplots(1, 2, figsize=(7.087, 4.55))
    _heatmap(axes[0], nmi_sd, "magma_r", 0, 0.12, "Reference NMI SD")
    axes[0].set_title("Reference-score variability", loc="left", fontweight="bold")
    _heatmap(axes[1], pairwise_nmi, "viridis", 0, 1, "Median pairwise partition NMI")
    axes[1].set_title("Partition reproducibility", loc="left", fontweight="bold")
    _panel(axes[0], "a", x=-0.25)
    _panel(axes[1], "b", x=-0.25)
    fig.tight_layout(w_pad=1.1)
    _save(fig, "FigureS2_five_method_candidate")


def supplementary3() -> None:
    iso_source = ALL_OUTPUTS / "integrated_iso_accuracy.csv"
    pair_source = ALL_OUTPUTS / "integrated_pairwise_reproducibility.csv"
    _require_inputs([iso_source, pair_source])
    iso = pd.read_csv(iso_source, dtype={"section": str})
    pairs = pd.read_csv(pair_source, dtype={"section": str})
    if len(iso) != 285 or len(pairs) != 18050:
        raise AssertionError("S3 source row counts do not match the validated five-method totals")

    # Normalize the serialized SEDR 0.0299999999999999 value before grouping.
    iso["threshold"] = pd.to_numeric(iso["threshold"], errors="raise").round(2)
    thresholds = [0.01, 0.02, 0.03]
    per_threshold_counts = iso.groupby("threshold").size().reindex(thresholds)
    if not (per_threshold_counts == 95).all():
        raise AssertionError(f"S3 threshold coverage is not 95 units each: {per_threshold_counts.to_dict()}")

    summaries: list[dict[str, float | int]] = []
    for threshold in thresholds:
        rows = iso[np.isclose(iso["threshold"], threshold, atol=1e-12, rtol=0)]
        eligible_pairs = int(rows["n_iso_accuracy_pairs"].sum())
        divergent_pairs = int(rows["n_partition_ari_below_0_50"].sum())
        eligible = pairs[
            pd.to_numeric(pairs["abs_reference_ari_difference"], errors="raise")
            <= threshold + 1e-12
        ]
        if len(eligible) != eligible_pairs:
            raise AssertionError(
                f"S3 threshold {threshold:.2f}: unit summary has {eligible_pairs} pairs but pair table has {len(eligible)}"
            )
        summaries.append(
            {
                "threshold": threshold,
                "n_units": len(rows),
                "n_iso_accuracy_pairs": eligible_pairs,
                "n_partition_ari_below_0_50": divergent_pairs,
                "fraction_partition_ari_below_0_50": divergent_pairs / eligible_pairs,
                "pooled_median_pairwise_partition_ari": float(
                    pd.to_numeric(eligible["pairwise_partition_ari"], errors="raise").median()
                ),
            }
        )
    summary = pd.DataFrame(summaries)
    expected = {
        0.01: (4135, 535),
        0.02: (6928, 1125),
        0.03: (9070, 1627),
    }
    for row in summary.itertuples(index=False):
        if (int(row.n_iso_accuracy_pairs), int(row.n_partition_ari_below_0_50)) != expected[float(row.threshold)]:
            raise AssertionError(f"S3 reconciliation failed at threshold {row.threshold}")

    iso = _ordered(iso)
    _write_csv(iso, "FigureS3_five_method_threshold_sensitivity_units.csv")
    _write_csv(summary, "FigureS3_five_method_threshold_sensitivity_summary.csv")

    fig, axes = plt.subplots(1, 3, figsize=(7.087, 2.75))
    configurations = [
        ("n_iso_accuracy_pairs", "Eligible pairs, n"),
        ("pooled_median_pairwise_partition_ari", "Median partition ARI"),
        ("fraction_partition_ari_below_0_50", "Fraction below ARI 0.50"),
    ]
    for ax, (column, ylabel), letter in zip(axes, configurations, "abc", strict=True):
        ax.plot(
            summary["threshold"],
            summary[column],
            marker="o",
            color="#0072B2",
            linewidth=1.1,
            markersize=3.5,
        )
        ax.set_xticks(thresholds, ["0.01", "0.02", "0.03"])
        ax.set_xlabel("|\u0394 reference ARI| threshold")
        ax.set_ylabel(ylabel)
        _clean(ax)
        _panel(ax, letter)
    fig.tight_layout(w_pad=1.2)
    _save(fig, "FigureS3_five_method_candidate")


def supplementary4() -> None:
    # The user explicitly froze S4; every visual byte is copied, not redrawn.
    for suffix in FORMATS:
        _copy_file(
            LOCKED_SUPP / f"FigureS4.{suffix}",
            SUPPLEMENTARY / f"FigureS4_five_method_candidate.{suffix}",
        )
    source_names = [
        "FigureS4_original_frozen_examples.csv",
        "FigureS4_original_spatial_maps.csv",
        "FigureS4_merfish_frozen_example.csv",
        "FigureS4_merfish_spatial_map.csv",
    ]
    for filename in source_names:
        _copy_file(LOCKED_SOURCE / filename, SOURCE_DATA / filename)


def supplementary5() -> None:
    pair_source = ALL_OUTPUTS / "integrated_marker_reproducibility_all_pairs.csv"
    original_extreme_source = LOCKED_SOURCE / "FigureS5_original_extreme_units.csv"
    merfish_extreme_source = LOCKED_SOURCE / "FigureS5_merfish_extreme_units.csv"
    _require_inputs([pair_source, original_extreme_source, merfish_extreme_source])
    pairs = pd.read_csv(pair_source, dtype={"section": str})
    original_extreme = pd.read_csv(original_extreme_source, dtype={"dataset": str})
    merfish_extreme = pd.read_csv(merfish_extreme_source, dtype={"section": str})
    if len(pairs) != 6928:
        raise AssertionError(f"S5 expected 6,928 primary pairs, found {len(pairs)}")
    required = ["pairwise_partition_ari", "top50_marker_jaccard", "marker_rank_spearman"]
    if not bool(pairs[required].apply(pd.to_numeric, errors="coerce").notna().all().all()):
        raise AssertionError("S5 contains non-finite required marker-sensitivity values")
    if len(original_extreme) != 56 or len(merfish_extreme) != 20:
        raise AssertionError("Frozen four-method extreme-pair source counts changed")

    pairs = _ordered(pairs)
    _write_csv(pairs, "FigureS5_five_method_marker_sensitivity_pairs.csv")
    _copy_file(original_extreme_source, SOURCE_DATA / "FigureS5_frozen_original_extreme_units.csv")
    _copy_file(merfish_extreme_source, SOURCE_DATA / "FigureS5_frozen_merfish_extreme_units.csv")

    fig, axes = plt.subplots(1, 3, figsize=(7.087, 2.75))
    axes[0].hexbin(
        pd.to_numeric(pairs["pairwise_partition_ari"]),
        pd.to_numeric(pairs["top50_marker_jaccard"]),
        gridsize=30,
        mincnt=1,
        cmap="viridis",
        linewidths=0.1,
        extent=(0, 1, 0, 1),
    )
    axes[0].set_xlabel("Partition ARI")
    axes[0].set_ylabel("Top-50 marker Jaccard")
    _clean(axes[0])

    axes[1].hexbin(
        pd.to_numeric(pairs["pairwise_partition_ari"]),
        pd.to_numeric(pairs["marker_rank_spearman"]),
        gridsize=30,
        mincnt=1,
        cmap="viridis",
        linewidths=0.1,
        extent=(0, 1, -0.2, 1),
    )
    axes[1].set_xlabel("Partition ARI")
    axes[1].set_ylabel("Whole-ranking Spearman \u03c1")
    _clean(axes[1])

    unstable = np.r_[
        pd.to_numeric(original_extreme["unstable_marker_jaccard"]).to_numpy(),
        pd.to_numeric(merfish_extreme["top100_marker_jaccard__iso_accuracy_unstable"]).to_numpy(),
    ]
    stable = np.r_[
        pd.to_numeric(original_extreme["stable_marker_jaccard"]).to_numpy(),
        pd.to_numeric(merfish_extreme["top100_marker_jaccard__stable_control"]).to_numpy(),
    ]
    for unstable_value, stable_value in zip(unstable, stable, strict=True):
        axes[2].plot([0, 1], [unstable_value, stable_value], color="#B8B8B8", linewidth=0.45, alpha=0.65)
    axes[2].scatter(np.zeros(len(unstable)), unstable, s=9, color="#D55E00")
    axes[2].scatter(np.ones(len(stable)), stable, s=9, color="#0072B2")
    axes[2].set_xticks([0, 1], ["Extreme unstable", "Matched stable"], rotation=20, ha="right")
    axes[2].set_ylabel("Top-100 marker Jaccard")
    axes[2].set_ylim(0, 1.02)
    _clean(axes[2])
    for ax, letter in zip(axes, "abc", strict=True):
        _panel(ax, letter)
    fig.tight_layout(w_pad=1.0)
    _save(fig, "FigureS5_five_method_candidate")


def supplementary6() -> None:
    distribution_source = FIVE_METHOD / "five_method_rank_distributions.csv"
    summary_source = FIVE_METHOD / "five_method_rank_summary.csv"
    _require_inputs([distribution_source, summary_source])
    distributions = pd.read_csv(distribution_source, dtype={"section": str})
    summary = pd.read_csv(summary_source, dtype={"section": str})
    _validate_five_method_units(summary)
    if len(distributions) != 855:
        raise AssertionError(f"S6 expected 855 exact half-rank rows, found {len(distributions)}")
    if set(pd.to_numeric(distributions["rank_x2"]).astype(int)) != set(range(2, 11)):
        raise AssertionError("S6 exact empirical rank support is not 1, 1.5, ..., 5")
    combinations = pd.to_numeric(summary["enumerated_combinations"], errors="raise")
    if not (combinations == 3_200_000).all():
        raise AssertionError("S6 is not based on exactly 20^5 combinations per entry")
    rank1_sums = summary.groupby("section")["empirical_p_rank1"].sum()
    if not np.allclose(rank1_sums.to_numpy(dtype=float), 1.0, atol=1e-10, rtol=0):
        raise AssertionError("S6 fractional P(rank 1) does not sum to one within entry")
    distribution_sums = distributions.groupby(["section", "method"])["probability"].sum()
    if not np.allclose(distribution_sums.to_numpy(dtype=float), 1.0, atol=1e-10, rtol=0):
        raise AssertionError("S6 per-method empirical rank distributions do not sum to one")

    distributions = _ordered(distributions)
    summary = _ordered(summary)
    _write_csv(distributions, "FigureS6_five_method_exact_rank_distributions.csv")
    _write_csv(summary, "FigureS6_five_method_exact_rank_summary.csv")

    fig, axes = plt.subplots(1, 3, figsize=(7.087, 4.55))
    configurations = [
        ("empirical_expected_rank", "Expected empirical rank", "viridis_r", 1, 5),
        ("empirical_p_top2", "Empirical P(top 2)", "Blues", 0, 1),
        ("empirical_p_top3", "Empirical P(top 3)", "Blues", 0, 1),
    ]
    for ax, (column, label, cmap, vmin, vmax), letter in zip(
        axes, configurations, "abc", strict=True
    ):
        matrix = summary.pivot(index="section", columns="method", values=column).loc[ORDER, METHODS]
        _heatmap(ax, matrix, cmap, vmin, vmax, label)
        _panel(ax, letter, x=-0.28)
    fig.tight_layout(w_pad=0.8)
    _save(fig, "FigureS6_five_method_candidate")


def supplementary7() -> None:
    # Candidate A is the byte-identical locked control figure.
    for suffix in FORMATS:
        source = LOCKED_SUPP / f"FigureS7.{suffix}"
        _copy_file(
            source,
            SUPPLEMENTARY / f"FigureS7_candidate_A_existing_controls.{suffix}",
        )
        # Compatibility alias required by the ordinary S1--S8 inventory.  It
        # is byte-identical to A only because the locked figure is the neutral
        # pre-existing candidate; this alias does not constitute selection of
        # A over the independently exported Candidate B.
        _copy_file(
            source,
            SUPPLEMENTARY / f"FigureS7_five_method_candidate.{suffix}",
        )
    locked_controls_source = LOCKED_SOURCE / "FigureS7_identical_seed_controls.csv"
    _copy_file(locked_controls_source, SOURCE_DATA / "FigureS7_candidate_A_existing_controls.csv")

    # Candidate B adds the two prespecified SEDR same-seed partition controls.
    phase0_source = PHASE0 / "tables" / "negative_controls.csv"
    sedr_source = SEDR / "identical_seed_controls.csv"
    _require_inputs([phase0_source, sedr_source])
    original = pd.read_csv(phase0_source)
    sedr = pd.read_csv(sedr_source, dtype={"dataset": str})
    expected_original = {
        ("STAGATE", "identical_seed_rerun"),
        ("GraphST", "identical_seed_rerun"),
        ("BANKSY", "identical_seed_rerun"),
        ("GraphST", "cluster_label_permutation_sanity"),
    }
    if set(map(tuple, original[["method", "control"]].to_numpy())) != expected_original:
        raise AssertionError("Locked technical-control identities changed")
    if len(sedr) != 2 or not np.allclose(
        pd.to_numeric(sedr["partition_ari_same_seed"], errors="raise"), 1.0, atol=0, rtol=0
    ):
        raise AssertionError("Expected two passing SEDR same-seed partition controls")

    repeat_order = [
        ("STAGATE", "identical_seed_rerun"),
        ("GraphST", "identical_seed_rerun"),
        ("BANKSY", "identical_seed_rerun"),
    ]
    keyed = original.set_index(["method", "control"])
    rows: list[dict[str, object]] = []
    for method, control in repeat_order:
        row = keyed.loc[(method, control)]
        rows.append(
            {
                "display_order": len(rows) + 1,
                "method": method,
                "dataset": "",
                "control": control,
                "control_type": "identical_seed_rerun",
                "ari_to_primary": float(row["ari_to_primary"]),
                "nmi_to_primary": float(row["nmi_to_primary"]),
            }
        )
    for dataset in ["151507", "STARmap_20180505_BY3_1k"]:
        row = sedr[sedr["dataset"] == dataset]
        if len(row) != 1:
            raise AssertionError(f"Missing unique SEDR repeatability row for {dataset}")
        rows.append(
            {
                "display_order": len(rows) + 1,
                "method": "SEDR",
                "dataset": dataset,
                "control": "identical_seed_rerun",
                "control_type": "identical_seed_rerun",
                "ari_to_primary": float(row["partition_ari_same_seed"].iloc[0]),
                # NMI was not computed in the frozen SEDR technical control.
                "nmi_to_primary": np.nan,
            }
        )
    permutation = keyed.loc[("GraphST", "cluster_label_permutation_sanity")]
    rows.append(
        {
            "display_order": len(rows) + 1,
            "method": "GraphST",
            "dataset": "",
            "control": "cluster_label_permutation_sanity",
            "control_type": "label_permutation_sanity",
            "ari_to_primary": float(permutation["ari_to_primary"]),
            "nmi_to_primary": float(permutation["nmi_to_primary"]),
        }
    )
    controls = pd.DataFrame(rows)
    if not controls.loc[controls["method"] == "SEDR", "nmi_to_primary"].isna().all():
        raise AssertionError("SEDR NMI technical-control values must remain missing")
    _write_csv(controls, "FigureS7_candidate_B_with_SEDR_controls.csv")

    fig, ax = plt.subplots(figsize=(7.087, 3.0))
    x = np.arange(len(controls))
    offset = 0.13
    ari = pd.to_numeric(controls["ari_to_primary"])
    nmi = pd.to_numeric(controls["nmi_to_primary"], errors="coerce")
    ax.scatter(x - offset, ari, s=28, marker="o", color="#0072B2", label="ARI", zorder=3)
    finite_nmi = nmi.notna().to_numpy()
    ax.scatter(
        x[finite_nmi] + offset,
        nmi[finite_nmi],
        s=30,
        marker="s",
        facecolor="white",
        edgecolor="#D55E00",
        linewidth=1.0,
        label="NMI",
        zorder=3,
    )
    ax.axvline(4.5, color="#BDBDBD", linewidth=0.8, linestyle="--")
    labels = [
        "STAGATE\nrepeat",
        "GraphST\nrepeat",
        "BANKSY\nrepeat",
        "SEDR 151507\nrepeat",
        "SEDR STARmap\nrepeat",
        "GraphST label\npermutation",
    ]
    ax.set_xticks(x, labels)
    ax.set_ylabel("Agreement with primary output")
    ax.set_ylim(0, 1.05)
    ax.set_xlim(-0.55, 5.55)
    ax.text(2.0, 0.12, "Identical-seed reruns", transform=ax.get_xaxis_transform(), ha="center", va="bottom", fontsize=6.5)
    ax.text(5.0, 0.12, "Label-permutation\nsanity control", transform=ax.get_xaxis_transform(), ha="center", va="bottom", fontsize=6.5, linespacing=0.9)
    ax.legend(frameon=False, ncol=2, loc="lower left")
    ax.set_title("Technical controls", loc="left", fontweight="bold")
    _clean(ax)
    _panel(ax, "a", x=-0.05)
    _save(fig, "FigureS7_candidate_B_with_SEDR_controls")


def supplementary8() -> None:
    source = ALL_OUTPUTS / "integrated_consensus_summary.csv"
    _require_inputs([source])
    data = pd.read_csv(source, dtype={"section": str})
    _validate_five_method_units(data)
    gains = pd.to_numeric(
        data["split_half_gain_over_median_single_seed_pairwise_ari"], errors="raise"
    )
    if int((gains > 0).sum()) != 95:
        raise AssertionError("S8 expected positive consensus gains in all 95 units")
    if not np.isclose(float(gains.median()), 0.1715913051, atol=1e-10, rtol=0):
        raise AssertionError("S8 integrated median consensus gain changed")
    data = _ordered(data)
    _write_csv(data, "FigureS8_five_method_complete_consensus.csv")

    fig, axes = plt.subplots(1, 3, figsize=(7.087, 2.75))
    for method in METHODS:
        subset = data[data["method"].astype(str) == method]
        axes[0].scatter(
            subset["median_single_seed_pairwise_ari"],
            subset["split_half_consensus_ari"],
            s=14,
            color=COLORS[method],
            label=method,
            alpha=0.75,
            edgecolor="none",
        )
        axes[1].scatter(
            subset["median_single_seed_reference_ari"],
            subset["consensus20_reference_ari"],
            s=14,
            color=COLORS[method],
            alpha=0.75,
            edgecolor="none",
        )
    for ax in axes[:2]:
        ax.plot([0, 1], [0, 1], color="#777777", linestyle="--", linewidth=0.7)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        _clean(ax)
    axes[0].set_xlabel("Median seed-pair ARI")
    axes[0].set_ylabel("Split-half consensus ARI")
    axes[1].set_xlabel("Median single-seed reference ARI")
    axes[1].set_ylabel("20-seed consensus reference ARI")

    gain_values = [
        pd.to_numeric(
            data[data["method"].astype(str) == method][
                "split_half_gain_over_median_single_seed_pairwise_ari"
            ]
        ).to_numpy()
        for method in METHODS
    ]
    boxes = axes[2].boxplot(
        gain_values,
        positions=range(5),
        widths=0.55,
        patch_artist=True,
        showfliers=False,
        medianprops={"color": "#111111", "linewidth": 0.8},
    )
    for patch, method in zip(boxes["boxes"], METHODS, strict=True):
        patch.set_facecolor(COLORS[method])
        patch.set_alpha(0.28)
        patch.set_edgecolor(COLORS[method])
    rng = np.random.default_rng(7808)
    for position, (method, values) in enumerate(zip(METHODS, gain_values, strict=True)):
        axes[2].scatter(
            position + rng.uniform(-0.10, 0.10, len(values)),
            values,
            s=5,
            color=COLORS[method],
            alpha=0.55,
            edgecolor="none",
        )
    axes[2].axhline(0, color="#BDBDBD", linewidth=0.6)
    axes[2].set_xticks(range(5), METHODS, rotation=30, ha="right")
    axes[2].set_ylabel("Consensus reproducibility gain")
    _clean(axes[2])
    for ax, letter in zip(axes, "abc", strict=True):
        _panel(ax, letter)
    fig.tight_layout(w_pad=1.0)
    _save(fig, "FigureS8_five_method_candidate")


def main() -> None:
    _prepare_output_dirs()
    supplementary1()
    supplementary2()
    supplementary3()
    supplementary4()
    supplementary5()
    supplementary6()
    supplementary7()
    supplementary8()
    print(f"Candidate supplementary figures written under: {SUPPLEMENTARY}")
    print(f"Candidate supplementary source CSVs written under: {SOURCE_DATA}")


if __name__ == "__main__":
    main()
