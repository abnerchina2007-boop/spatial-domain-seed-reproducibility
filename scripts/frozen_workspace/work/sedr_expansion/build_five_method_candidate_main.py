from __future__ import annotations

"""Build the six five-method Project 9 candidate main figures.

This is a figure-only, deterministic renderer.  It reads the already validated
five-method integration, rechecks the frozen four-method backfilter, and writes
only candidate main-figure exports and their figure-ready CSV files.  It never
touches the locked publication package and it never runs a spatial-domain model.
"""

import hashlib
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, wilcoxon


WORKSPACE = Path(__file__).resolve().parents[2]
SEDR_ROOT = WORKSPACE / "outputs" / "PROJECT9_SEDR_EXPANSION"
INTEGRATION = SEDR_ROOT / "candidate_integration"
ALL_OUTPUTS = INTEGRATION / "all_outputs"
RANKING = INTEGRATION / "five_method"
FOUR_METHOD_ROOT = WORKSPACE / "outputs" / "PROJECT9_MERFISH_EXPANSION"
LOCKED_FIGURE_SOURCE = (
    WORKSPACE / "outputs" / "PROJECT9_FINAL_PUBLICATION_PACKAGE" /
    "Figures" / "SourceData"
)

# The renderer is deliberately confined to this candidate subtree.
CANDIDATE_ROOT = INTEGRATION / "figures"
MAIN_OUT = CANDIDATE_ROOT / "Main"
SOURCE_OUT = CANDIDATE_ROOT / "SourceData"

METHODS = ["GraphST", "STAGATE", "SpaGCN", "BANKSY", "SEDR"]
ORIGINAL_METHODS = METHODS[:4]
METHOD_COLORS = {
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
    "MERFISH_Bregma_m0.04",
    "MERFISH_Bregma_m0.09",
    "MERFISH_Bregma_m0.14",
    "MERFISH_Bregma_m0.19",
    "MERFISH_Bregma_m0.24",
]
DATASETS = DLPFC + ["STARmap_20180505_BY3_1k", "HBCA1"] + MERFISH
DISPLAY = {dataset: dataset for dataset in DLPFC} | {
    "STARmap_20180505_BY3_1k": "STARmap",
    "HBCA1": "HBCA1",
    "MERFISH_Bregma_m0.04": "Bregma −0.04",
    "MERFISH_Bregma_m0.09": "Bregma −0.09",
    "MERFISH_Bregma_m0.14": "Bregma −0.14",
    "MERFISH_Bregma_m0.19": "Bregma −0.19",
    "MERFISH_Bregma_m0.24": "Bregma −0.24",
}
DATASET_INDEX = {dataset: index for index, dataset in enumerate(DATASETS)}
METHOD_INDEX = {method: index for index, method in enumerate(METHODS)}

CONTEXT_COLORS = {
    "DLPFC": "#6A6A6A",
    "STARmap": "#E69F00",
    "HBCA1": "#56B4E9",
    "MERFISH": "#009E73",
}
DOMAIN_PALETTE = [
    "#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9",
    "#D55E00", "#F0E442", "#999999", "#332288", "#88CCEE",
    "#44AA99", "#117733", "#999933", "#DDCC77", "#CC6677",
    "#882255", "#AA4499", "#661100", "#6699CC", "#AA4466",
]

LOCKED_SOURCE_HASHES = {
    "Figure1_dataset_landscape.csv":
        "41F60A487F605BE13475140BE478CCF7107A42C0A16E131089F2A69AAA556973",
    "Figure3_frozen_examples.csv":
        "B838986148DB2E46BB8B3D823A808F216E8066BFBC02D481FD585F1F3303F9AE",
    "Figure3_spatial_map_source.csv":
        "F1B39497E2671985298C2BEC6524350C8B63701A9A5CD596F5BB957971E0676A",
    "Figure5_frozen_representative_overlap.csv":
        "70C09A8533B8591C8729BD03BE9F2901E8A1CEEB407F097444DE202030DF117D",
}

ALL_OUTPUT_FILES = {
    "seed": "integrated_seed_level_accuracy.csv",
    "pairwise": "integrated_pairwise_reproducibility.csv",
    "iso": "integrated_iso_accuracy.csv",
    "unit": "integrated_method_dataset_summary.csv",
    "consensus": "integrated_consensus_summary.csv",
    "marker_unit": "integrated_marker_unit_summary.csv",
    "marker_tertile": "integrated_marker_tertile_summary.csv",
    "marker_pairs": "integrated_marker_reproducibility_all_pairs.csv",
}
FOUR_METHOD_FILES = {
    "seed": "combined_seed_level_accuracy.csv",
    "pairwise": "combined_pairwise_partition_reproducibility.csv",
    "iso": "combined_iso_accuracy_results.csv",
    "unit": "combined_method_dataset_summary.csv",
    "consensus": "combined_consensus_results.csv",
    "marker_unit": "combined_within_unit_marker_correlations.csv",
    "marker_tertile": "combined_marker_tertile_summary.csv",
    "marker_pairs": "combined_marker_reproducibility_all_pairs.csv",
}
BACKFILTER_KEYS = {
    "seed": ["section", "method", "seed"],
    "pairwise": ["section", "method", "seed_r", "seed_s"],
    "iso": ["section", "method", "threshold"],
    "unit": ["section", "method"],
    "consensus": ["section", "method"],
    "marker_unit": ["section", "method"],
    "marker_tertile": ["section", "method", "partition_ari_tertile"],
    "marker_pairs": ["section", "method", "seed_r", "seed_s"],
}

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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def assert_hash(path: Path, expected: str) -> None:
    observed = sha256(path)
    assert observed == expected.upper(), (
        f"SHA-256 mismatch for {path}: expected {expected}, observed {observed}"
    )


def context(section: str) -> str:
    if section in DLPFC:
        return "DLPFC"
    if section.startswith("STARmap"):
        return "STARmap"
    if section == "HBCA1":
        return "HBCA1"
    return "MERFISH"


def display(section: str) -> str:
    return DISPLAY.get(str(section), str(section))


def clean(ax: mpl.axes.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def panel(ax: mpl.axes.Axes, letter: str, x: float = -0.13,
          y: float = 1.03) -> None:
    ax.text(
        x, y, letter, transform=ax.transAxes, fontsize=9,
        fontweight="bold", ha="left", va="bottom",
    )


def save_four_formats(fig: mpl.figure.Figure, basename: str) -> None:
    target = MAIN_OUT / basename
    fig.savefig(target.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.04)
    fig.savefig(target.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.04)
    fig.savefig(
        target.with_suffix(".png"), dpi=300, bbox_inches="tight",
        pad_inches=0.04,
    )
    fig.savefig(
        target.with_suffix(".tiff"), dpi=600, bbox_inches="tight",
        pad_inches=0.04, pil_kwargs={"compression": "tiff_lzw"},
    )
    plt.close(fig)


def save_png_only(fig: mpl.figure.Figure, path: Path, dpi: int = 300) -> None:
    """Save a QC-only raster alternative inside the candidate subtree."""
    resolved = path.resolve()
    assert CANDIDATE_ROOT.resolve() in resolved.parents
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def heatmap(
    fig: mpl.figure.Figure,
    ax: mpl.axes.Axes,
    matrix: pd.DataFrame,
    cmap: str | mpl.colors.Colormap,
    vmin: float,
    vmax: float,
    colorbar_label: str,
    *,
    annotate: bool = False,
    percent: bool = False,
    colorbar_orientation: str = "vertical",
) -> None:
    image = ax.imshow(
        matrix.to_numpy(float), aspect="auto", cmap=cmap, vmin=vmin, vmax=vmax,
    )
    ax.set_xticks(range(len(matrix.columns)), matrix.columns, rotation=38, ha="right")
    ax.set_yticks(
        range(len(matrix.index)), [display(value) for value in matrix.index],
    )
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    if annotate:
        for row in range(matrix.shape[0]):
            for column in range(matrix.shape[1]):
                value = float(matrix.iloc[row, column])
                rgba = image.cmap(image.norm(value))
                luminance = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
                label = f"{value:.0%}" if percent else f"{value:.2f}"
                ax.text(
                    column, row, label, ha="center", va="center", fontsize=6.5,
                    color="white" if luminance < 0.48 else "#111111",
                )
    if colorbar_orientation == "horizontal":
        bar = fig.colorbar(
            image, ax=ax, orientation="horizontal", fraction=0.035,
            pad=0.075, aspect=35,
        )
    else:
        bar = fig.colorbar(image, ax=ax, fraction=0.045, pad=0.025)
    bar.set_label(colorbar_label, fontsize=7)
    bar.ax.tick_params(labelsize=6.5)


def _manifest_output_hashes(manifest: dict) -> dict[str, str]:
    return {
        str(item["path"]): str(item["sha256"]).upper()
        for item in manifest.get("outputs", [])
    }


def _verify_four_method_backfilter(integration_manifest: dict) -> None:
    reconciliation = integration_manifest["four_method_backfilter_reconciliation"]
    assert set(reconciliation) == set(ALL_OUTPUT_FILES)
    for key in ALL_OUTPUT_FILES:
        record = reconciliation[key]
        assert record["status"] == "PASS", f"Backfilter manifest failed for {key}"
        assert record["serialized_authoritative_tokens_exact"] is True
        assert record["numeric_tolerance_used_for_old_rows"] is False
        assert int(record["rows"]) in {76, 228, 1520, 14440, 5810}

        authoritative = WORKSPACE / record["authoritative_source"]
        assert authoritative.resolve() == (FOUR_METHOD_ROOT / FOUR_METHOD_FILES[key]).resolve()
        assert_hash(authoritative, record["authoritative_source_sha256"])

        fields = list(record["authoritative_fields_exact"])
        old = pd.read_csv(authoritative, dtype=str, keep_default_na=False)
        integrated = pd.read_csv(
            ALL_OUTPUTS / ALL_OUTPUT_FILES[key], dtype=str, keep_default_na=False,
        )
        assert set(fields).issubset(integrated.columns)
        filtered = integrated.loc[integrated["method"].isin(ORIGINAL_METHODS), fields]
        old = old.loc[:, fields]
        keys = BACKFILTER_KEYS[key]
        assert not old.duplicated(keys).any()
        assert not filtered.duplicated(keys).any()
        old = old.sort_values(keys, kind="stable").reset_index(drop=True)
        filtered = filtered.sort_values(keys, kind="stable").reset_index(drop=True)
        pd.testing.assert_frame_equal(
            filtered, old, check_dtype=False, check_exact=True,
            obj=f"fresh four-method backfilter: {key}",
        )


def _verify_integration_manifests() -> tuple[dict, dict]:
    integration_manifest_path = ALL_OUTPUTS / "INTEGRATION_MANIFEST.json"
    ranking_manifest_path = RANKING / "analysis_manifest.json"
    integration_manifest = json.loads(integration_manifest_path.read_text(encoding="utf-8"))
    ranking_manifest = json.loads(ranking_manifest_path.read_text(encoding="utf-8"))

    assert integration_manifest["status"] == "PASS"
    assert integration_manifest["methods"] == METHODS
    assert integration_manifest["datasets"] == DATASETS
    assert integration_manifest["four_method_sources_modified"] is False
    assert integration_manifest["row_counts"] == {
        "seed": 1900,
        "pairwise": 18050,
        "iso": 285,
        "unit": 95,
        "consensus": 95,
        "marker_unit": 95,
        "marker_tertile": 285,
        "marker_pairs": 6928,
    }
    integration_hashes = _manifest_output_hashes(integration_manifest)
    for filename in list(ALL_OUTPUT_FILES.values()) + ["integrated_headline_summary.json"]:
        assert filename in integration_hashes, f"Missing integration hash: {filename}"
        assert_hash(ALL_OUTPUTS / filename, integration_hashes[filename])

    assert ranking_manifest["status"] == "PASS"
    assert ranking_manifest["methods"] == METHODS
    assert int(ranking_manifest["dataset_count"]) == 19
    assert int(ranking_manifest["seeds_per_method_dataset"]) == 20
    assert int(ranking_manifest["combinations_per_dataset"]) == 3_200_000
    assert int(ranking_manifest["total_enumerated_combinations"]) == 60_800_000
    assert ranking_manifest["combinations_are_independent_experiments"] is False
    assert ranking_manifest["rank_rule"] == "average midrank for exact ties"
    assert ranking_manifest["rank1_rule"] == "tied maxima split rank-1 credit equally"
    ranking_reconciliation = ranking_manifest["four_method_reconciliation"]
    assert ranking_reconciliation["status"] == "PASS"
    assert ranking_reconciliation["existing_source_modified"] is False
    assert ranking_reconciliation["serialized_authoritative_tokens_exact"] is True
    assert int(ranking_reconciliation["original_method_rows_observed_after_filter"]) == 1520
    ranking_hashes = _manifest_output_hashes(ranking_manifest)
    required_ranking = [
        "integrated_seed_level_accuracy.csv",
        "five_method_rank_distributions.csv",
        "five_method_rank_summary.csv",
        "five_method_winner_probabilities.csv",
        "five_method_pairwise_superiority.csv",
        "five_method_dataset_uncertainty.csv",
        "four_method_reconciliation.json",
    ]
    for filename in required_ranking:
        assert filename in ranking_hashes, f"Missing ranking hash: {filename}"
        assert_hash(RANKING / filename, ranking_hashes[filename])

    _verify_four_method_backfilter(integration_manifest)
    return integration_manifest, ranking_manifest


def _verify_locked_sources() -> None:
    for filename, expected_hash in LOCKED_SOURCE_HASHES.items():
        assert_hash(LOCKED_FIGURE_SOURCE / filename, expected_hash)


def _assert_method_dataset_grid(frame: pd.DataFrame, label: str) -> None:
    assert len(frame) == 95, f"{label}: expected 95 rows"
    assert not frame.duplicated(["section", "method"]).any()
    observed = set(map(tuple, frame[["section", "method"]].astype(str).to_numpy()))
    expected = {(dataset, method) for dataset in DATASETS for method in METHODS}
    assert observed == expected, f"{label}: method–dataset grid changed"


def _load_and_validate() -> dict[str, pd.DataFrame | dict]:
    integration_manifest, ranking_manifest = _verify_integration_manifests()
    _verify_locked_sources()

    frames: dict[str, pd.DataFrame | dict] = {
        key: pd.read_csv(ALL_OUTPUTS / filename, dtype={"section": str})
        for key, filename in ALL_OUTPUT_FILES.items()
    }
    frames["winner"] = pd.read_csv(
        RANKING / "five_method_winner_probabilities.csv", dtype={"section": str},
    )
    frames["uncertainty"] = pd.read_csv(
        RANKING / "five_method_dataset_uncertainty.csv", dtype={"section": str},
    )
    frames["rank_summary"] = pd.read_csv(
        RANKING / "five_method_rank_summary.csv", dtype={"section": str},
    )
    frames["landscape"] = pd.read_csv(
        LOCKED_FIGURE_SOURCE / "Figure1_dataset_landscape.csv", dtype={"dataset": str},
    )
    frames["frozen_examples"] = pd.read_csv(
        LOCKED_FIGURE_SOURCE / "Figure3_frozen_examples.csv", dtype={"dataset": str},
    )
    frames["frozen_maps"] = pd.read_csv(
        LOCKED_FIGURE_SOURCE / "Figure3_spatial_map_source.csv", dtype={"dataset": str},
    )
    frames["frozen_marker"] = pd.read_csv(
        LOCKED_FIGURE_SOURCE / "Figure5_frozen_representative_overlap.csv",
        dtype={"dataset": str},
    )
    frames["headline"] = json.loads(
        (ALL_OUTPUTS / "integrated_headline_summary.json").read_text(encoding="utf-8")
    )
    frames["integration_manifest"] = integration_manifest
    frames["ranking_manifest"] = ranking_manifest

    unit = frames["unit"]
    seed = frames["seed"]
    pairwise = frames["pairwise"]
    iso = frames["iso"]
    consensus = frames["consensus"]
    marker_unit = frames["marker_unit"]
    marker_tertile = frames["marker_tertile"]
    marker_pairs = frames["marker_pairs"]
    winner = frames["winner"]
    uncertainty = frames["uncertainty"]
    rank_summary = frames["rank_summary"]

    assert isinstance(unit, pd.DataFrame)
    assert isinstance(seed, pd.DataFrame)
    assert isinstance(pairwise, pd.DataFrame)
    assert isinstance(iso, pd.DataFrame)
    assert isinstance(consensus, pd.DataFrame)
    assert isinstance(marker_unit, pd.DataFrame)
    assert isinstance(marker_tertile, pd.DataFrame)
    assert isinstance(marker_pairs, pd.DataFrame)
    assert isinstance(winner, pd.DataFrame)
    assert isinstance(uncertainty, pd.DataFrame)
    assert isinstance(rank_summary, pd.DataFrame)

    _assert_method_dataset_grid(unit, "method summary")
    _assert_method_dataset_grid(consensus, "consensus")
    _assert_method_dataset_grid(marker_unit, "marker unit")
    _assert_method_dataset_grid(winner, "winner probability")
    _assert_method_dataset_grid(rank_summary, "rank summary")

    assert len(seed) == 1900
    assert not seed.duplicated(["section", "method", "seed"]).any()
    seed_counts = seed.groupby(["section", "method"], observed=True).size()
    assert len(seed_counts) == 95 and seed_counts.eq(20).all()
    assert set(pd.to_numeric(seed["seed"]).astype(int)) == set(range(1, 21))

    assert len(pairwise) == 18050
    assert not pairwise.duplicated(["section", "method", "seed_r", "seed_s"]).any()
    pair_counts = pairwise.groupby(["section", "method"], observed=True).size()
    assert len(pair_counts) == 95 and pair_counts.eq(190).all()
    assert (pd.to_numeric(pairwise["seed_r"]) < pd.to_numeric(pairwise["seed_s"])).all()

    assert len(iso) == 285
    assert not iso.duplicated(["section", "method", "threshold"]).any()
    assert set(np.round(pd.to_numeric(iso["threshold"]), 8)) == {0.01, 0.02, 0.03}
    assert iso.groupby(["section", "method"], observed=True).size().eq(3).all()

    assert len(marker_pairs) == 6928
    assert not marker_pairs.duplicated(["section", "method", "seed_r", "seed_s"]).any()
    assert marker_pairs[[
        "pairwise_partition_ari", "top50_marker_jaccard",
        "top100_marker_jaccard", "marker_rank_spearman",
    ]].notna().all().all()
    assert len(marker_tertile) == 285
    assert not marker_tertile.duplicated(
        ["section", "method", "partition_ari_tertile"]
    ).any()
    assert set(marker_tertile["partition_ari_tertile"]) == {"Low", "Middle", "High"}
    assert marker_tertile.groupby(["section", "method"], observed=True).size().eq(3).all()

    primary_pairs = pairwise.loc[
        pd.to_numeric(pairwise["abs_reference_ari_difference"]) <= 0.02 + 1e-12
    ].copy()
    assert len(primary_pairs) == 6928
    primary_keys = set(map(tuple, primary_pairs[[
        "section", "method", "seed_r", "seed_s"
    ]].astype(str).to_numpy()))
    marker_keys = set(map(tuple, marker_pairs[[
        "section", "method", "seed_r", "seed_s"
    ]].astype(str).to_numpy()))
    assert primary_keys == marker_keys
    divergent = primary_pairs.loc[
        pd.to_numeric(primary_pairs["pairwise_partition_ari"]) < 0.50
    ]
    assert len(divergent) == 1125
    affected = divergent[["section", "method"]].drop_duplicates()
    assert len(affected) == 55

    assert len(uncertainty) == 19
    assert set(uncertainty["section"].astype(str)) == set(DATASETS)
    probability_sums = winner.groupby("section", observed=True)["p_rank1"].sum()
    assert np.allclose(probability_sums.to_numpy(float), 1.0, rtol=0, atol=1e-12)
    maxima = pd.to_numeric(uncertainty["maximum_p_rank1"])
    assert np.isclose(maxima.min(), 0.5211875, rtol=0, atol=1e-12)
    assert np.isclose(maxima.max(), 1.0, rtol=0, atol=1e-12)
    assert int((maxima < 0.50).sum()) == 0
    assert int((maxima < 0.75).sum()) == 5

    finite_rho = pd.to_numeric(
        marker_unit["spearman_partition_ari_vs_marker_jaccard"], errors="coerce"
    ).dropna()
    assert len(finite_rho) == 94
    assert int((finite_rho > 0).sum()) == 94
    assert np.isclose(finite_rho.median(), 0.6945763796, rtol=0, atol=1e-10)

    tertile_pivot = marker_tertile.pivot(
        index=["section", "method"], columns="partition_ari_tertile",
        values="median_top100_marker_jaccard",
    ).reindex(columns=["Low", "Middle", "High"])
    assert tertile_pivot.shape == (95, 3) and tertile_pivot.notna().all().all()
    assert np.allclose(
        tertile_pivot.median(axis=0).to_numpy(float),
        [0.72413793, 0.7699115, 0.8181818182], rtol=0, atol=1e-10,
    )
    assert np.isclose(
        (tertile_pivot["High"] - tertile_pivot["Low"]).median(),
        0.082808648, rtol=0, atol=1e-10,
    )

    gain = pd.to_numeric(
        consensus["split_half_gain_over_median_single_seed_pairwise_ari"]
    )
    assert int((gain > 0).sum()) == 95
    assert np.isclose(gain.median(), 0.1715913051, rtol=0, atol=1e-10)

    rule = (
        (pd.to_numeric(unit["reference_ari_sd"]) <= 0.02) &
        (pd.to_numeric(unit["partition_instability"]) >= 0.30)
    )
    assert int(rule.sum()) == 12

    headline = frames["headline"]
    assert isinstance(headline, dict)
    assert headline["structural_totals"] == {
        "dataset_entries": 19,
        "methods": 5,
        "method_dataset_units": 95,
        "seed_specific_runs": 1900,
        "pairwise_seed_comparisons": 18050,
    }
    assert int(headline["primary_iso_accuracy"]["eligible_pairs"]) == 6928
    assert int(headline["primary_iso_accuracy"]["divergent_partition_ari_lt_0_50"]) == 1125
    assert int(headline["consensus"]["improved_units"]) == 95

    landscape = frames["landscape"]
    frozen_examples = frames["frozen_examples"]
    frozen_maps = frames["frozen_maps"]
    frozen_marker = frames["frozen_marker"]
    assert isinstance(landscape, pd.DataFrame)
    assert isinstance(frozen_examples, pd.DataFrame)
    assert isinstance(frozen_maps, pd.DataFrame)
    assert isinstance(frozen_marker, pd.DataFrame)
    assert landscape["dataset"].astype(str).tolist() == DATASETS
    expected_examples = [
        ("151670", "GraphST", 9, 14),
        ("151507", "STAGATE", 2, 4),
        ("STARmap_20180505_BY3_1k", "SpaGCN", 2, 17),
    ]
    observed_examples = [
        (str(row.dataset), str(row.method), int(row.seed_r), int(row.seed_s))
        for row in frozen_examples.itertuples()
    ]
    assert observed_examples == expected_examples
    assert len(frozen_maps) > 0
    assert set(frozen_maps["dataset"].astype(str)) == {item[0] for item in expected_examples}
    assert set(frozen_marker["partition_ari_tertile"]) == {"Low", "High"}
    assert frozen_marker["dataset"].astype(str).eq("151507").all()
    assert frozen_marker["method"].eq("GraphST").all()

    frames["primary_pairs"] = primary_pairs
    frames["tertile_pivot"] = tertile_pivot
    return frames


def _write_source(frame: pd.DataFrame, filename: str) -> None:
    frame.to_csv(SOURCE_OUT / filename, index=False, float_format="%.12g")


def _ordered(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.copy()
    ordered["_dataset_order"] = ordered["section"].map(DATASET_INDEX)
    ordered["_method_order"] = ordered["method"].map(METHOD_INDEX)
    assert ordered[["_dataset_order", "_method_order"]].notna().all().all()
    return ordered.sort_values(
        ["_dataset_order", "_method_order"], kind="stable",
    ).drop(columns=["_dataset_order", "_method_order"])


def _plot_spatial_example(
    fig: mpl.figure.Figure,
    container,
    map_data: pd.DataFrame,
    title: str,
    letter: str,
) -> None:
    assert len(map_data) > 0
    inner = container.subgridspec(1, 4, wspace=0.22)
    columns = ["reference", "seed_a_aligned_domain", "seed_b_aligned_domain"]
    categories = sorted(
        set(map_data[columns[0]].astype(str)) |
        set(map_data[columns[1]].astype(str)) |
        set(map_data[columns[2]].astype(str))
    )
    palette = {
        name: DOMAIN_PALETTE[index % len(DOMAIN_PALETTE)]
        for index, name in enumerate(categories)
    } | {"Unmatched": "#D9D9D9"}
    axes: list[mpl.axes.Axes] = []
    for index, column in enumerate(columns):
        ax = fig.add_subplot(inner[0, index])
        axes.append(ax)
        values = map_data[column].astype(str)
        ax.scatter(
            map_data["x"], map_data["y"],
            c=[palette.get(value, "#D9D9D9") for value in values],
            s=1.1, linewidth=0,
        )
        ax.invert_yaxis()
        ax.set_axis_off()
        ax.set_title(
            [
                "Reference",
                f"Seed {int(map_data['seed_a'].iloc[0])}",
                f"Seed {int(map_data['seed_b'].iloc[0])}",
            ][index],
            pad=2.0, fontsize=6.5,
        )
    ax = fig.add_subplot(inner[0, 3])
    axes.append(ax)
    changed = (
        map_data["seed_a_aligned_domain"].astype(str) !=
        map_data["seed_b_aligned_domain"].astype(str)
    )
    ax.scatter(
        map_data["x"], map_data["y"],
        c=np.where(changed, "#222222", "#D9D9D9"),
        s=1.1, linewidth=0,
    )
    ax.invert_yaxis()
    ax.set_axis_off()
    ax.set_title("Discordant", pad=2.0, fontsize=6.5)
    axes[0].text(
        -0.10, 1.08, letter, transform=axes[0].transAxes, fontsize=9,
        fontweight="bold", ha="left", va="bottom",
    )
    axes[1].text(
        1.0, -0.10, title, transform=axes[1].transAxes,
        ha="center", va="top", fontsize=6.5,
    )


def figure1(frames: dict[str, pd.DataFrame | dict]) -> None:
    unit = _ordered(frames["unit"])
    landscape = frames["landscape"].copy()
    assert isinstance(unit, pd.DataFrame)
    assert isinstance(landscape, pd.DataFrame)
    coverage = unit.pivot(index="section", columns="method", values="n_seeds").loc[
        DATASETS, METHODS
    ]
    assert coverage.shape == (19, 5)
    assert np.allclose(coverage.to_numpy(float), 20, rtol=0, atol=0)

    landscape["methods"] = ";".join(METHODS)
    landscape["valid_runs"] = 100
    landscape["dataset_display"] = landscape["dataset"].map(DISPLAY)
    _write_source(landscape, "Figure1_dataset_landscape_five_method.csv")
    _write_source(
        coverage.rename_axis("section").reset_index(),
        "Figure1_coverage_matrix_five_method.csv",
    )

    fig = plt.figure(figsize=(7.087, 4.45))
    grid = fig.add_gridspec(
        1, 3, width_ratios=[0.27, 0.32, 0.41], wspace=0.58,
    )

    axa = fig.add_subplot(grid[0, 0])
    panel(axa, "a", -0.18)
    axa.set_axis_off()
    axa.text(
        0.0, 1.0, "Fixed analysis inputs", transform=axa.transAxes,
        fontweight="bold", va="top",
    )
    fixed = [
        "Same dataset", "Same preprocessing", "Same requested K",
        "Same method settings", "Different random seed",
    ]
    for y, label in zip(np.linspace(0.87, 0.47, len(fixed)), fixed):
        axa.text(0.0, y, label, transform=axa.transAxes, fontsize=7.0, va="center")
    axa.annotate(
        "", xy=(0.50, 0.31), xytext=(0.50, 0.41), xycoords=axa.transAxes,
        arrowprops={"arrowstyle": "->", "lw": 0.8, "color": "#444444"},
    )
    axa.text(
        0.0, 0.27, "Evaluated separately", transform=axa.transAxes,
        fontweight="bold", va="top",
    )
    outcomes = [
        "Reference accuracy", "Partition reproducibility",
        "Iso-accuracy divergence", "Marker reproducibility",
    ]
    for y, label in zip(np.linspace(0.16, -0.08, len(outcomes)), outcomes):
        axa.text(0.04, y, label, transform=axa.transAxes, fontsize=6.8, va="center")

    axb = fig.add_subplot(grid[0, 1])
    panel(axb, "b", -0.20)
    axb.set_xlim(0, 1)
    axb.set_ylim(-0.8, len(DATASETS) - 0.2)
    axb.invert_yaxis()
    axb.set_axis_off()
    groupings = [
        (0, 11, "DLPFC", CONTEXT_COLORS["DLPFC"]),
        (12, 12, "STARmap", CONTEXT_COLORS["STARmap"]),
        (13, 13, "HBCA1", CONTEXT_COLORS["HBCA1"]),
        (14, 18, "MERFISH", CONTEXT_COLORS["MERFISH"]),
    ]
    for start, end, label, color in groupings:
        axb.fill_betweenx([start - 0.45, end + 0.45], 0.0, 0.055, color=color)
        axb.text(
            0.08, (start + end) / 2, label, va="center", fontweight="bold",
            fontsize=6.5, color=color,
        )
    for row, section in enumerate(DATASETS):
        axb.text(0.54, row, display(section), va="center", ha="left", fontsize=6.5)
    axb.set_title("Benchmark landscape", loc="left", fontweight="bold", pad=4)

    axc = fig.add_subplot(grid[0, 2])
    panel(axc, "c", -0.25)
    uniform = LinearSegmentedColormap.from_list(
        "completed_coverage", ["#3D5A73", "#3D5A73"],
    )
    axc.imshow(np.ones((19, 5)), aspect="auto", cmap=uniform, vmin=0, vmax=1)
    axc.set_xticks(range(5), METHODS, rotation=38, ha="right")
    axc.set_yticks(range(19), [display(value) for value in DATASETS])
    axc.tick_params(length=0)
    for spine in axc.spines.values():
        spine.set_visible(False)
    for row in range(19):
        for column in range(5):
            axc.text(column, row, "20", ha="center", va="center", fontsize=6.5,
                     color="white")
    axc.set_title("Complete 20-seed coverage", loc="left", fontweight="bold")
    axc.text(
        0.5, -0.16,
        "20 seeds per method–dataset unit\n95 units; 1,900 runs",
        transform=axc.transAxes, ha="center", va="top", fontsize=6.5,
        linespacing=1.05,
    )
    save_four_formats(fig, "Figure1_five_method_candidate")


def figure2(frames: dict[str, pd.DataFrame | dict]) -> None:
    unit = _ordered(frames["unit"])
    assert isinstance(unit, pd.DataFrame)
    _write_source(unit, "Figure2_method_dataset_units_five_method.csv")

    score_sd = unit.pivot(
        index="section", columns="method", values="reference_ari_sd"
    ).loc[DATASETS, METHODS]
    partition = unit.pivot(
        index="section", columns="method", values="median_pairwise_partition_ari"
    ).loc[DATASETS, METHODS]
    rho = float(spearmanr(
        pd.to_numeric(unit["reference_ari_sd"]),
        pd.to_numeric(unit["partition_instability"]),
    ).statistic)
    threshold_positive = unit.loc[
        (pd.to_numeric(unit["reference_ari_sd"]) <= 0.02) &
        (pd.to_numeric(unit["partition_instability"]) >= 0.30)
    ]
    assert np.isclose(rho, 0.24809630459126542, rtol=0, atol=1e-12)
    assert len(threshold_positive) == 12

    fig = plt.figure(figsize=(7.087, 7.0))
    grid = fig.add_gridspec(
        2, 2, height_ratios=[1.45, 1.0], wspace=0.55, hspace=0.38,
    )
    axa = fig.add_subplot(grid[0, 0])
    panel(axa, "a", -0.25)
    heatmap(fig, axa, score_sd, "magma_r", 0, 0.14, "Reference ARI SD")
    axa.set_title("Reference-score variability", loc="left", fontweight="bold")

    axb = fig.add_subplot(grid[0, 1])
    panel(axb, "b", -0.25)
    heatmap(
        fig, axb, partition, "viridis", 0, 1,
        "Median pairwise partition ARI",
    )
    axb.set_title("Partition reproducibility", loc="left", fontweight="bold")

    axc = fig.add_subplot(grid[1, 0])
    panel(axc, "c")
    for method in METHODS:
        subset = unit.loc[unit["method"].eq(method)]
        axc.scatter(
            subset["reference_ari_sd"], subset["partition_instability"],
            s=19, color=METHOD_COLORS[method], label=method, alpha=0.82,
            edgecolor="white", linewidth=0.3,
        )
    axc.scatter(
        threshold_positive["reference_ari_sd"],
        threshold_positive["partition_instability"],
        s=44, facecolor="none", edgecolor="#111111", linewidth=0.8, zorder=5,
    )
    axc.axvline(0.02, color="#777777", linestyle="--", linewidth=0.7)
    axc.axhline(0.30, color="#777777", linestyle="--", linewidth=0.7)
    axc.set_xlabel("Reference ARI SD")
    axc.set_ylabel("Partition instability\n(1 − median pairwise ARI)")
    axc.text(
        0.97, 0.96,
        f"Descriptive Spearman ρ = {rho:.3f}\n"
        f"{len(threshold_positive)} threshold-positive units",
        transform=axc.transAxes, ha="right", va="top", fontsize=6.5,
    )
    axc.legend(frameon=False, ncol=3, loc="lower right", columnspacing=0.8,
               handletextpad=0.3)
    clean(axc)

    axd = fig.add_subplot(grid[1, 1])
    panel(axd, "d")
    rng = np.random.default_rng(2402)
    values = [
        pd.to_numeric(
            unit.loc[unit["method"].eq(method), "median_pairwise_partition_ari"]
        ).to_numpy(float)
        for method in METHODS
    ]
    boxplot = axd.boxplot(
        values, positions=np.arange(5), widths=0.55, patch_artist=True,
        showfliers=False,
        medianprops={"color": "#111111", "linewidth": 1.0},
        whiskerprops={"linewidth": 0.7}, capprops={"linewidth": 0.7},
    )
    for patch, method in zip(boxplot["boxes"], METHODS):
        patch.set_facecolor(METHOD_COLORS[method])
        patch.set_alpha(0.28)
        patch.set_edgecolor(METHOD_COLORS[method])
    for index, (method, method_values) in enumerate(zip(METHODS, values)):
        assert len(method_values) == 19
        axd.scatter(
            index + rng.uniform(-0.13, 0.13, len(method_values)), method_values,
            s=11, color=METHOD_COLORS[method], alpha=0.72,
            edgecolor="white", linewidth=0.2,
        )
    axd.set_xticks(range(5), METHODS, rotation=25, ha="right")
    axd.set_ylabel("Median pairwise partition ARI")
    axd.set_ylim(0, 1.02)
    clean(axd)
    save_four_formats(fig, "Figure2_five_method_candidate")


def figure3(frames: dict[str, pd.DataFrame | dict]) -> None:
    primary_pairs = frames["primary_pairs"].copy()
    frozen_examples = frames["frozen_examples"].copy()
    frozen_maps = frames["frozen_maps"].copy()
    assert isinstance(primary_pairs, pd.DataFrame)
    assert isinstance(frozen_examples, pd.DataFrame)
    assert isinstance(frozen_maps, pd.DataFrame)
    primary_pairs = _ordered(primary_pairs)
    _write_source(primary_pairs, "Figure3_iso_accuracy_pairs_five_method.csv")
    _write_source(frozen_examples, "Figure3_frozen_examples_locked.csv")
    _write_source(frozen_maps, "Figure3_spatial_map_source_locked.csv")

    divergent = primary_pairs.loc[
        pd.to_numeric(primary_pairs["pairwise_partition_ari"]) < 0.50
    ]
    affected = divergent[["section", "method"]].drop_duplicates()
    assert len(primary_pairs) == 6928 and len(divergent) == 1125 and len(affected) == 55

    fig = plt.figure(figsize=(7.087, 6.2))
    grid = fig.add_gridspec(
        2, 3, height_ratios=[0.72, 1.35], hspace=0.34, wspace=0.20,
    )
    axa = fig.add_subplot(grid[0, :])
    panel(axa, "a", -0.035)
    axa.hist(
        pd.to_numeric(primary_pairs["pairwise_partition_ari"]),
        bins=np.linspace(0, 1, 41), color="#9ECAE1", edgecolor="white",
        linewidth=0.35,
    )
    axa.axvline(0.50, color="#D55E00", linestyle="--", linewidth=0.9)
    axa.text(
        0.98, 0.94,
        f"{len(primary_pairs):,} iso-accuracy pairs\n"
        f"{len(divergent):,} ({len(divergent) / len(primary_pairs):.2%}) below 0.50\n"
        f"{len(affected)}/95 affected units",
        transform=axa.transAxes, ha="right", va="top", fontsize=7,
    )
    axa.set_xlabel("Pairwise partition ARI (|Δ reference ARI| ≤ 0.02)")
    axa.set_ylabel("Pair count")
    clean(axa)

    for index, row in frozen_examples.iterrows():
        subset = frozen_maps.loc[
            frozen_maps["dataset"].astype(str).eq(str(row["dataset"])) &
            frozen_maps["method"].eq(row["method"]) &
            pd.to_numeric(frozen_maps["seed_a"]).eq(int(row["seed_r"])) &
            pd.to_numeric(frozen_maps["seed_b"]).eq(int(row["seed_s"]))
        ]
        title = (
            f"{display(str(row['dataset']))} · {row['method']}\n"
            f"|Δ reference ARI|={float(row['abs_reference_ari_difference']):.3f}; "
            f"partition ARI={float(row['pairwise_partition_ari']):.3f}"
        )
        _plot_spatial_example(
            fig, grid[1, index], subset, title, chr(ord("b") + index),
        )
    save_four_formats(fig, "Figure3_five_method_candidate")

    # Optional QC-only method stratification requested by the brief. It is not
    # a main-figure candidate and uses the same frozen primary pair universe.
    qc = CANDIDATE_ROOT / "QC"
    fig_alt, ax_alt = plt.subplots(figsize=(7.087, 2.8))
    bins = np.linspace(0, 1, 41)
    for method in METHODS:
        values = pd.to_numeric(
            primary_pairs.loc[primary_pairs["method"].eq(method), "pairwise_partition_ari"]
        ).to_numpy(float)
        ax_alt.hist(
            values, bins=bins, histtype="step", density=True,
            color=METHOD_COLORS[method], linewidth=1.0, label=method,
        )
    ax_alt.axvline(0.50, color="#777777", linestyle="--", linewidth=0.8)
    ax_alt.set_xlabel("Pairwise partition ARI (|Δ reference ARI| ≤ 0.02)")
    ax_alt.set_ylabel("Density")
    ax_alt.set_title("QC alternative: method-stratified primary iso-accuracy distributions", loc="left")
    ax_alt.legend(frameon=False, ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.18))
    clean(ax_alt)
    save_png_only(fig_alt, qc / "Figure3a_method_stratified_alternative.png")


def figure4(frames: dict[str, pd.DataFrame | dict]) -> None:
    winner = _ordered(frames["winner"])
    uncertainty = frames["uncertainty"].copy()
    seed = frames["seed"].copy()
    assert isinstance(winner, pd.DataFrame)
    assert isinstance(uncertainty, pd.DataFrame)
    assert isinstance(seed, pd.DataFrame)

    uncertainty["_dataset_order"] = uncertainty["section"].map(DATASET_INDEX)
    assert uncertainty["_dataset_order"].notna().all()
    uncertainty = uncertainty.sort_values("_dataset_order", kind="stable").drop(
        columns="_dataset_order"
    )
    selection = uncertainty.assign(
        _dataset_order=uncertainty["section"].map(DATASET_INDEX)
    ).sort_values(
        ["maximum_p_rank1", "_dataset_order"], kind="stable"
    ).head(3).copy()
    selection["selection_rank"] = np.arange(1, 4)
    selected = selection["section"].astype(str).tolist()
    assert selected == ["STARmap_20180505_BY3_1k", "151670", "HBCA1"]

    matrix = winner.pivot(
        index="section", columns="method", values="p_rank1"
    ).loc[DATASETS, METHODS]
    selected_seeds = seed.loc[seed["section"].isin(selected)].merge(
        selection[["section", "selection_rank"]], on="section", how="left",
        validate="many_to_one",
    ).sort_values(["selection_rank", "method", "seed"], kind="stable")
    assert len(selected_seeds) == 300

    _write_source(winner, "Figure4_winner_probabilities_five_method.csv")
    _write_source(
        uncertainty, "Figure4_dataset_uncertainty_five_method.csv",
    )
    _write_source(
        selected_seeds, "Figure4_selected_seed_distributions_five_method.csv",
    )

    fig = plt.figure(figsize=(7.087, 7.2))
    grid = fig.add_gridspec(
        2, 2, height_ratios=[1.28, 0.90], width_ratios=[0.59, 0.41],
        hspace=0.38, wspace=0.54,
    )
    axa = fig.add_subplot(grid[0, 0])
    panel(axa, "a", -0.25)
    probability_cmap = LinearSegmentedColormap.from_list(
        "winner_probability", ["#F7FBFF", "#6BAED6", "#08306B"],
    )
    heatmap(
        fig, axa, matrix, probability_cmap, 0, 1, "Empirical P(rank 1)",
        annotate=True, percent=True,
    )
    axa.set_title("Winner probability", loc="left", fontweight="bold")

    axb = fig.add_subplot(grid[0, 1])
    panel(axb, "b", -0.30)
    y = np.arange(len(uncertainty))
    colors = [METHOD_COLORS[value] for value in uncertainty["most_probable_winner"]]
    axb.barh(
        y, pd.to_numeric(uncertainty["maximum_p_rank1"]),
        color=colors, height=0.55, alpha=0.78,
    )
    axb.set_yticks(y, [display(value) for value in uncertainty["section"]])
    axb.invert_yaxis()
    axb.set_xlim(0, 1.10)
    axb.set_xlabel("Maximum empirical P(rank 1)")
    for row, record in uncertainty.reset_index(drop=True).iterrows():
        probability = float(record["maximum_p_rank1"])
        axb.text(
            min(probability + 0.015, 1.025), row,
            str(record["most_probable_winner"]), va="center", fontsize=6.5,
        )
    clean(axb)

    axc = fig.add_subplot(grid[1, :])
    panel(axc, "c", -0.035)
    tick_positions: list[float] = []
    tick_labels: list[str] = []
    for group, section in enumerate(selected):
        group_start = group * 7
        tick_positions.append(group_start + 2)
        tick_labels.append(display(section))
        for method_index, method in enumerate(METHODS):
            position = group_start + method_index
            values = pd.to_numeric(seed.loc[
                seed["section"].eq(section) & seed["method"].eq(method),
                "reference_ari",
            ]).to_numpy(float)
            assert len(values) == 20
            boxplot = axc.boxplot(
                [values], positions=[position], widths=0.55, patch_artist=True,
                showfliers=False,
                medianprops={"color": "#111111", "linewidth": 0.8},
                whiskerprops={"linewidth": 0.6}, capprops={"linewidth": 0.6},
            )
            boxplot["boxes"][0].set_facecolor(METHOD_COLORS[method])
            boxplot["boxes"][0].set_alpha(0.28)
            boxplot["boxes"][0].set_edgecolor(METHOD_COLORS[method])
            rng = np.random.default_rng(4400 + group * 10 + method_index)
            axc.scatter(
                position + rng.uniform(-0.13, 0.13, len(values)), values,
                s=8, color=METHOD_COLORS[method], alpha=0.72,
                edgecolor="white", linewidth=0.15,
            )
    axc.set_xticks(tick_positions, tick_labels)
    axc.set_ylabel("Reference ARI across 20 seeds")
    handles = [
        plt.Line2D(
            [0], [0], marker="o", color="none",
            markerfacecolor=METHOD_COLORS[method], markeredgecolor="none",
            label=method,
        )
        for method in METHODS
    ]
    axc.legend(
        handles=handles, frameon=False, ncol=5, loc="upper center",
        bbox_to_anchor=(0.5, -0.12), columnspacing=1.0, handletextpad=0.3,
    )
    clean(axc)
    save_four_formats(fig, "Figure4_five_method_candidate")


def figure5(frames: dict[str, pd.DataFrame | dict]) -> None:
    marker_pairs = frames["marker_pairs"].copy()
    marker_unit = _ordered(frames["marker_unit"])
    marker_tertile = frames["marker_tertile"].copy()
    frozen_marker = frames["frozen_marker"].copy()
    tertile_pivot = frames["tertile_pivot"].copy()
    assert isinstance(marker_pairs, pd.DataFrame)
    assert isinstance(marker_unit, pd.DataFrame)
    assert isinstance(marker_tertile, pd.DataFrame)
    assert isinstance(frozen_marker, pd.DataFrame)
    assert isinstance(tertile_pivot, pd.DataFrame)

    marker_pairs = _ordered(marker_pairs)
    marker_tertile = _ordered(marker_tertile)
    finite = marker_unit.loc[pd.to_numeric(
        marker_unit["spearman_partition_ari_vs_marker_jaccard"], errors="coerce"
    ).notna()].copy()
    rho_values = pd.to_numeric(finite["spearman_partition_ari_vs_marker_jaccard"])

    paired = tertile_pivot.dropna(subset=["Low", "High"])
    test = wilcoxon(
        paired["High"], paired["Low"], alternative="greater",
        zero_method="wilcox", method="auto",
    )
    differences = paired["High"] - paired["Low"]
    test_frame = pd.DataFrame([{
        "analysis": "paired one-sided Wilcoxon: high versus low unit-level tertile medians",
        "n_complete_units": len(paired),
        "n_positive_differences": int((differences > 0).sum()),
        "n_zero_differences": int((differences == 0).sum()),
        "n_negative_differences": int((differences < 0).sum()),
        "median_low": float(tertile_pivot["Low"].median()),
        "median_middle": float(tertile_pivot["Middle"].median()),
        "median_high": float(tertile_pivot["High"].median()),
        "median_paired_high_minus_low": float(differences.median()),
        "wilcoxon_statistic": float(test.statistic),
        "wilcoxon_p_value_one_sided": float(test.pvalue),
    }])
    assert int(test_frame.iloc[0]["n_complete_units"]) == 95
    assert np.isclose(float(test.statistic), 4459.0, rtol=0, atol=0)
    assert np.isclose(float(test.pvalue), 2.3097164857133306e-17, rtol=1e-12)

    _write_source(marker_pairs, "Figure5_marker_pairs_five_method.csv")
    _write_source(marker_unit, "Figure5_unit_correlations_five_method.csv")
    _write_source(marker_tertile, "Figure5_tertiles_five_method.csv")
    _write_source(frozen_marker, "Figure5_frozen_representative_overlap_locked.csv")
    _write_source(test_frame, "Figure5_paired_tertile_test_five_method.csv")

    fig = plt.figure(figsize=(7.087, 6.5))
    grid = fig.add_gridspec(2, 2, hspace=0.48, wspace=0.40)

    axa = fig.add_subplot(grid[0, 0])
    panel(axa, "a")
    density = axa.hexbin(
        pd.to_numeric(marker_pairs["pairwise_partition_ari"]),
        pd.to_numeric(marker_pairs["top100_marker_jaccard"]),
        gridsize=38, mincnt=1, cmap="viridis", linewidths=0.1,
        extent=(0, 1, 0, 1),
    )
    axa.set_xlim(0, 1)
    axa.set_ylim(0, 1)
    axa.set_xlabel("Partition ARI")
    axa.set_ylabel("Top-100 marker Jaccard")
    axa.text(
        0.03, 0.97,
        f"n = {len(marker_pairs):,} pairs\nDescriptive; pairs share seeds",
        transform=axa.transAxes, va="top", fontsize=6.5,
    )
    bar = fig.colorbar(density, ax=axa, fraction=0.045, pad=0.025)
    bar.set_label("Pair count", fontsize=7)
    bar.ax.tick_params(labelsize=6.5)
    clean(axa)

    axb = fig.add_subplot(grid[0, 1])
    panel(axb, "b")
    rng = np.random.default_rng(5005)
    for index, method in enumerate(METHODS):
        values = pd.to_numeric(finite.loc[
            finite["method"].eq(method),
            "spearman_partition_ari_vs_marker_jaccard",
        ]).to_numpy(float)
        boxplot = axb.boxplot(
            [values], positions=[index], widths=0.55, patch_artist=True,
            showfliers=False,
            medianprops={"color": "#111111", "linewidth": 0.8},
            whiskerprops={"linewidth": 0.6}, capprops={"linewidth": 0.6},
        )
        boxplot["boxes"][0].set_facecolor(METHOD_COLORS[method])
        boxplot["boxes"][0].set_alpha(0.28)
        boxplot["boxes"][0].set_edgecolor(METHOD_COLORS[method])
        axb.scatter(
            index + rng.uniform(-0.12, 0.12, len(values)), values,
            s=11, color=METHOD_COLORS[method], alpha=0.75,
            edgecolor="white", linewidth=0.2,
        )
    axb.axhline(0, color="#777777", linestyle="--", linewidth=0.7)
    axb.set_ylim(-0.08, 1.04)
    axb.set_xticks(range(5), METHODS, rotation=25, ha="right")
    axb.set_ylabel("Within-unit Spearman ρ")
    axb.text(
        0.03, 0.97,
        f"Median ρ = {rho_values.median():.3f}\n"
        f"Positive in {(rho_values > 0).sum()}/{len(rho_values)} estimable units",
        transform=axb.transAxes, va="top", fontsize=6.5,
    )
    clean(axb)

    axc = fig.add_subplot(grid[1, 0])
    panel(axc, "c")
    for (section, method), row in tertile_pivot.iterrows():
        axc.plot(
            range(3), row.to_numpy(float), color=METHOD_COLORS[method],
            alpha=0.18, linewidth=0.55,
        )
    medians = tertile_pivot.median(axis=0).to_numpy(float)
    axc.plot(
        range(3), medians, color="#111111", marker="D", markersize=4,
        linewidth=1.3, zorder=4,
    )
    axc.set_xticks(range(3), ["Low", "Middle", "High"])
    axc.set_xlabel("Within-unit partition-ARI tertile")
    axc.set_ylabel("Unit median top-100 marker Jaccard")
    axc.set_ylim(0, 1.02)
    axc.text(
        0.03, 0.97,
        f"Medians: {medians[0]:.3f}, {medians[1]:.3f}, {medians[2]:.3f}\n"
        f"Median high − low = {differences.median():.3f}\n"
        f"W = {float(test.statistic):.0f}; P = {float(test.pvalue):.2e}",
        transform=axc.transAxes, va="top", fontsize=6.5,
    )
    clean(axc)

    axd = fig.add_subplot(grid[1, 1])
    panel(axd, "d")
    representative = frozen_marker.set_index("partition_ari_tertile").loc[
        ["Low", "High"]
    ]
    left = pd.to_numeric(representative["unique_to_seed_r"]).to_numpy(float)
    shared = pd.to_numeric(representative["shared_top100"]).to_numpy(float)
    right = pd.to_numeric(representative["unique_to_seed_s"]).to_numpy(float)
    y_labels = ["Lower agreement", "Higher agreement"]
    axd.barh(y_labels, left, color="#D55E00", label="Unique to seed A")
    axd.barh(y_labels, shared, left=left, color="#BDBDBD", label="Shared")
    axd.barh(
        y_labels, right, left=left + shared, color="#0072B2",
        label="Unique to seed B",
    )
    axd.invert_yaxis()
    axd.set_xlabel("Marker count")
    axd.set_title("Union of two top-100 marker sets", loc="left", fontsize=7, pad=4)
    axd.legend(
        frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.14),
        columnspacing=0.9, handletextpad=0.4,
    )
    axd.text(
        0.02, -0.34,
        "Frozen representative: 151507 · GraphST · largest consensus domain",
        transform=axd.transAxes, fontsize=6.5, va="top",
    )
    clean(axd)
    save_four_formats(fig, "Figure5_five_method_candidate")


def figure6(frames: dict[str, pd.DataFrame | dict]) -> None:
    consensus = _ordered(frames["consensus"])
    assert isinstance(consensus, pd.DataFrame)
    _write_source(consensus, "Figure6_consensus_five_method.csv")

    gain = pd.to_numeric(
        consensus["split_half_gain_over_median_single_seed_pairwise_ari"]
    )
    improved = int((gain > 0).sum())
    assert improved == len(consensus) == 95

    fig = plt.figure(figsize=(7.087, 3.75))
    grid = fig.add_gridspec(
        1, 3, width_ratios=[0.40, 0.27, 0.33], wspace=0.55,
    )
    axa, axb, axc = [fig.add_subplot(grid[0, index]) for index in range(3)]

    rng = np.random.default_rng(6006)
    x_single = rng.normal(0, 0.016, len(consensus))
    x_consensus = rng.normal(1, 0.016, len(consensus))
    for index, row in enumerate(consensus.itertuples()):
        axa.plot(
            [x_single[index], x_consensus[index]],
            [row.median_single_seed_pairwise_ari, row.split_half_consensus_ari],
            color="#B8B8B8", linewidth=0.45, alpha=0.75,
        )
    axa.scatter(
        x_single, consensus["median_single_seed_pairwise_ari"],
        s=11, color="#777777", edgecolor="white", linewidth=0.25,
    )
    axa.scatter(
        x_consensus, consensus["split_half_consensus_ari"],
        s=11, color="#0072B2", edgecolor="white", linewidth=0.25,
    )
    axa.set_xticks(
        [0, 1], ["Median seed-pair\nARI", "Split-half consensus\nARI"],
    )
    axa.set_ylabel("Partition reproducibility (ARI)")
    axa.set_ylim(0, 1.02)
    axa.set_xlim(-0.28, 1.28)
    axa.text(
        0.5, 0.035,
        f"Improved in {improved}/{len(consensus)} units\n"
        f"Median gain = {gain.median():.3f}",
        transform=axa.transAxes, ha="center", va="bottom", fontsize=6.5,
    )
    clean(axa)

    for method in METHODS:
        subset = consensus.loc[consensus["method"].eq(method)]
        axb.scatter(
            subset["median_single_seed_reference_ari"],
            subset["consensus20_reference_ari"],
            s=18, color=METHOD_COLORS[method], label=method, alpha=0.78,
            edgecolor="white", linewidth=0.25,
        )
    axb.plot([0, 1], [0, 1], color="#777777", linestyle="--", linewidth=0.7)
    axb.set_xlim(0, 1)
    axb.set_ylim(0, 1)
    axb.set_xlabel("Median single-seed reference ARI")
    axb.set_ylabel("20-seed consensus reference ARI")
    axb.legend(
        frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.22),
        columnspacing=0.7, handletextpad=0.25,
    )
    clean(axb)

    matrix = consensus.pivot(
        index="section", columns="method", values="split_half_consensus_ari"
    ).loc[DATASETS, METHODS]
    heatmap(fig, axc, matrix, "viridis", 0, 1, "Split-half consensus ARI")
    for letter, ax in zip("abc", [axa, axb, axc]):
        panel(ax, letter, -0.16, 1.03)
    save_four_formats(fig, "Figure6_five_method_candidate")


def main() -> None:
    # Validate every immutable input before creating output directories.
    frames = _load_and_validate()
    MAIN_OUT.mkdir(parents=True, exist_ok=True)
    SOURCE_OUT.mkdir(parents=True, exist_ok=True)
    figure1(frames)
    figure2(frames)
    figure3(frames)
    figure4(frames)
    figure5(frames)
    figure6(frames)
    print(
        json.dumps(
            {
                "status": "CANDIDATE_MAIN_FIGURES_RENDERED",
                "main_directory": str(MAIN_OUT),
                "source_data_directory": str(SOURCE_OUT),
                "figures": [f"Figure{index}_five_method_candidate" for index in range(1, 7)],
                "formats": ["pdf", "svg", "tiff", "png"],
                "locked_publication_package_modified": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
