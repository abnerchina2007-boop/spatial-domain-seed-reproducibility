from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "PROJECT9_FIVE_METHOD_FINAL_FIGURE_TABLE_PACKAGE"
SOURCE = OUT / "Tables" / "SourceData"
QC = OUT / "QC"
OLD = OUT.parent / "PROJECT9_FINAL_PUBLICATION_PACKAGE" / "Tables" / "SourceData"
BASE = OUT.parent / "PROJECT9_MERFISH_EXPANSION" / "combined_dataset_manifest.csv"
INTEGRATED = OUT.parent / "PROJECT9_SEDR_EXPANSION" / "candidate_integration"
ALL = INTEGRATED / "all_outputs"
FIVE = INTEGRATED / "five_method"

METHODS = ["GraphST", "STAGATE", "SpaGCN", "BANKSY", "SEDR"]
INTERNAL = [
    "151507", "151508", "151509", "151510", "151669", "151670",
    "151671", "151672", "151673", "151674", "151675", "151676",
    "STARmap_20180505_BY3_1k", "HBCA1", "MERFISH_Bregma_m0.04",
    "MERFISH_Bregma_m0.09", "MERFISH_Bregma_m0.14", "MERFISH_Bregma_m0.19",
    "MERFISH_Bregma_m0.24",
]
DISPLAY = {x: x for x in INTERNAL}
DISPLAY.update({
    "STARmap_20180505_BY3_1k": "STARmap",
    "HBCA1": "HBCA1",
    "MERFISH_Bregma_m0.04": "Bregma −0.04",
    "MERFISH_Bregma_m0.09": "Bregma −0.09",
    "MERFISH_Bregma_m0.14": "Bregma −0.14",
    "MERFISH_Bregma_m0.19": "Bregma −0.19",
    "MERFISH_Bregma_m0.24": "Bregma −0.24",
})


def read(path: Path, **kwargs) -> pd.DataFrame:
    return pd.read_csv(path, **kwargs)


def table1() -> pd.DataFrame:
    frame = read(OLD / "Table1_FINAL.csv", dtype={"Dataset": str})
    frame.loc[frame["Dataset"].eq("Breast cancer (HBCA1)"), "Dataset"] = "HBCA1"
    frame.loc[frame["Dataset"].eq("HBCA1"), "Dataset"] = "HBCA1"
    frame.loc[frame["Platform"].eq("MERFISH"), "Reference annotation"] = "BASS/manual atlas-informed spatial domains"
    return frame


def table_s1() -> pd.DataFrame:
    frame = read(OLD / "Supplementary_Table_S1_FINAL.csv", dtype=str, keep_default_na=False)
    frame.loc[frame["Dataset"].eq("Breast cancer (HBCA1)"), "Dataset"] = "HBCA1"
    hb = frame["Dataset"].eq("HBCA1")
    frame.loc[hb, "Reference annotation source"] = "Manual 20-region pathology reference defined from H&E and pathological features in the original SEDR study"
    frame.loc[hb, "Preprocessing / reference-label note"] = (
        "The reference is a manual pathology annotation, not a SEDR clustering output. "
        "The original SEDR study used this dataset; cross-method reference-accuracy comparisons involving SEDR should be interpreted with awareness of prior developer-dataset exposure."
    )
    for suffix in ("0.04", "0.09", "0.14", "0.19", "0.24"):
        ascii_label = f"Bregma -{suffix}"
        dataset = f"Bregma −{suffix}"
        row = frame["Dataset"].eq(ascii_label) | frame["Dataset"].eq(dataset)
        frame.loc[row, "Dataset"] = dataset
        frame.loc[row, "Sample / section ID"] = dataset
    return frame


def table_s2() -> pd.DataFrame:
    shared_seed = "Integers 1-20; Python, NumPy, PyTorch/CUDA and stochastic final readout controlled where applicable"
    k_rule = "K=7 (DLPFC and STARmap); K=20 (HBCA1); requested K=8 (MERFISH)"
    rows = [
        {
            "Method": "GraphST", "Software version / commit": "1.1.1; commit d62b0b7",
            "Implementation source": "Official GraphST Python implementation",
            "Input modalities": "Expression; spatial coordinates",
            "Expression preprocessing / PCA": "Filtered and normalized expression; 20-PC reduction of the embedding when required; MERFISH used all 155 targeted genes",
            "Spatial graph": "Official spatial graph; MERFISH used datatype=Stereo and the official 3-nearest-neighbor graph",
            "Architecture / training": "Official GraphST representation; 200 epochs; MERFISH learning rate 0.001 and nominal output dimension 64",
            "Final clustering / readout": "Tied-covariance Gaussian mixture; n_init=5; max_iter=500; reg_covar=1e-6",
            "Requested K rule": k_rule, "Seed propagation": shared_seed,
            "Refinement / platform note": "No spatial refinement; original coordinates and fixed requested K were used."
        },
        {
            "Method": "STAGATE", "Software version / commit": "STAGATE_pyG source",
            "Implementation source": "Official STAGATE Python/PyG implementation",
            "Input modalities": "Expression; spatial coordinates",
            "Expression preprocessing / PCA": "Filtered and normalized expression; MERFISH used all 155 targeted genes",
            "Spatial graph": "Radius 150; HBCA1 used the scale-equivalent radius 300; MERFISH used radius 150 without coordinate rescaling",
            "Architecture / training": "Hidden dimensions [512, 30]; 200 epochs; learning rate 0.001; weight decay 0.0001",
            "Final clustering / readout": "Tied-covariance Gaussian mixture; n_init=5; max_iter=500; reg_covar=1e-6",
            "Requested K rule": k_rule, "Seed propagation": shared_seed,
            "Refinement / platform note": "No spatial refinement; original coordinates and fixed requested K were used."
        },
        {
            "Method": "SpaGCN", "Software version / commit": "1.2.7; commit dc7a1c2",
            "Implementation source": "Official SpaGCN Python implementation",
            "Input modalities": "Expression; spatial coordinates; histology not used",
            "Expression preprocessing / PCA": "normalize_total(10,000), log1p and up to 50 PCs; MERFISH used all 155 targeted genes",
            "Spatial graph": "Official coordinate adjacency; MERFISH used section-specific l after label-free search_l with p=0.5",
            "Architecture / training": "Learning rate 0.05; maximum 200 epochs; k-means initialization; tolerance 0.005",
            "Final clustering / readout": "Fixed-K k-means initialization followed by official spatial refinement",
            "Requested K rule": k_rule, "Seed propagation": shared_seed,
            "Refinement / platform note": "Official 6-neighbor hexagonal refinement. Official refinement-induced reductions in observed K were retained as valid end-to-end stochastic outputs."
        },
        {
            "Method": "BANKSY", "Software version / commit": "pybanksy 1.3.5 source",
            "Implementation source": "Official BANKSY Python implementation",
            "Input modalities": "Expression; spatial coordinates",
            "Expression preprocessing / PCA": "Normalized expression; deterministic variance >1e-12 safeguard; 20 PCs; MERFISH used all 155 targeted genes",
            "Spatial graph": "15 spatial neighbors with scaled-Gaussian weights",
            "Architecture / training": "lambda=0.2; max_m=0; no variance balancing",
            "Final clustering / readout": "Tied-covariance Gaussian mixture; n_init=5; max_iter=500; reg_covar=1e-6",
            "Requested K rule": k_rule, "Seed propagation": shared_seed,
            "Refinement / platform note": "No spatial refinement; lambda=0.2 benchmark configuration and fixed requested K."
        },
        {
            "Method": "SEDR", "Software version / commit": "1.0.0; commit ef4836059a4ea49be3bf7c67008a44ffc16a2a0e",
            "Implementation source": "Official JinmiaoChenLab/SEDR implementation",
            "Input modalities": "Expression; spatial coordinates",
            "Expression preprocessing / PCA": "Visium: gene filters min_cells=50 and min_counts=10, normalize_total(1e6), 2,000 seurat_v3 HVGs, scaling and PCA up to 200 components; STARmap/MERFISH: full gene panel, normalize_total(1e6), scaling and PCA up to 200 components; no log transformation; PCA random_state=42",
            "Spatial graph": "Official Euclidean k-nearest-neighbor graph; k=12 for Visium and k=6 for STARmap/MERFISH; undirected union symmetrization with official normalization",
            "Architecture / training": "Official SEDR clustering representation with DEC; expression encoder 64->16, graph hidden 64 with 16+16 outputs, 32-dimensional latent representation; 200 pretraining plus 200 DEC epochs; Adam learning rate 0.01, weight decay 0.01",
            "Final clustering / readout": "One official mclust_R fixed-K call; Mclust model EEE; G=requested K",
            "Requested K rule": k_rule,
            "Seed propagation": "Integers 1-20; Python, NumPy, PyTorch/CUDA and R seed set to the run seed; PCA and internal DEC k-means random_state=42",
            "Refinement / platform note": "No post-clustering spatial refinement; normally completed finite fixed-K readouts were retained."
        },
    ]
    return pd.DataFrame(rows)


def ordered(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["section"] = pd.Categorical(result["section"], INTERNAL, ordered=True)
    result["method"] = pd.Categorical(result["method"], METHODS, ordered=True)
    result = result.sort_values(["section", "method"], kind="stable").reset_index(drop=True)
    result["section"] = result["section"].astype("string")
    result["method"] = result["method"].astype("string")
    return result


def table_s3() -> pd.DataFrame:
    units = read(ALL / "integrated_method_dataset_summary.csv", dtype={"section": str})
    iso = read(ALL / "integrated_iso_accuracy.csv", dtype={"section": str})
    iso = iso[np.isclose(pd.to_numeric(iso["threshold"]), 0.02, atol=1e-12, rtol=0)].copy()
    merged = units.merge(iso[["section", "method", "n_iso_accuracy_pairs", "median_pairwise_partition_ari", "minimum_pairwise_partition_ari", "n_partition_ari_below_0_50", "fraction_partition_ari_below_0_50"]], on=["section", "method"], how="inner", validate="one_to_one", suffixes=("", "_iso"))
    merged = ordered(merged)
    return pd.DataFrame({
        "Dataset": merged["section"].map(DISPLAY), "Method": merged["method"],
        "Median reference ARI": merged["median_reference_ari"], "Reference ARI SD": merged["reference_ari_sd"],
        "Median reference NMI": merged["median_reference_nmi"], "Reference NMI SD": merged["reference_nmi_sd"],
        "Median pairwise partition ARI": merged["median_pairwise_partition_ari"],
        "5th percentile pairwise partition ARI": merged["p05_pairwise_partition_ari"],
        "Minimum pairwise partition ARI": merged["minimum_pairwise_partition_ari"],
        "Iso-accuracy pairs, n": merged["n_iso_accuracy_pairs"].astype(int),
        "Median iso-accuracy partition ARI": merged["median_pairwise_partition_ari_iso"],
        "Minimum iso-accuracy partition ARI": merged["minimum_pairwise_partition_ari_iso"],
        "Divergent iso-accuracy pairs, n": merged["n_partition_ari_below_0_50"].astype(int),
        "Divergent iso-accuracy fraction": merged["fraction_partition_ari_below_0_50"],
    })


def table_s4() -> pd.DataFrame:
    ranks = read(FIVE / "five_method_rank_summary.csv", dtype={"section": str})
    markers = read(ALL / "integrated_marker_unit_summary.csv", dtype={"section": str})
    tertiles = read(ALL / "integrated_marker_tertile_summary.csv", dtype={"section": str})
    consensus = read(ALL / "integrated_consensus_summary.csv", dtype={"section": str})
    wide = tertiles.pivot(index=["section", "method"], columns="partition_ari_tertile", values="median_top100_marker_jaccard").reset_index().rename(columns={"Low": "low", "Middle": "middle", "High": "high"})
    merged = ranks.merge(markers[["section", "method", "spearman_partition_ari_vs_marker_jaccard"]], on=["section", "method"], validate="one_to_one").merge(wide, on=["section", "method"], validate="one_to_one").merge(consensus[["section", "method", "consensus20_reference_ari", "split_half_consensus_ari", "split_half_gain_over_median_single_seed_pairwise_ari"]], on=["section", "method"], validate="one_to_one")
    merged = ordered(merged)
    return pd.DataFrame({
        "Dataset": merged["section"].map(DISPLAY), "Method": merged["method"],
        "Empirical P(rank 1)": merged["empirical_p_rank1"], "Expected empirical rank": merged["empirical_expected_rank"],
        "Median empirical rank": merged["empirical_median_rank"], "P(top 2)": merged["empirical_p_top2"], "P(top 3)": merged["empirical_p_top3"],
        "Within-unit partition-to-marker Spearman rho": merged["spearman_partition_ari_vs_marker_jaccard"],
        "Low-tertile marker Jaccard": merged["low"], "Middle-tertile marker Jaccard": merged["middle"], "High-tertile marker Jaccard": merged["high"],
        "20-seed consensus reference ARI": merged["consensus20_reference_ari"], "Split-half consensus ARI": merged["split_half_consensus_ari"],
        "Consensus reproducibility gain": merged["split_half_gain_over_median_single_seed_pairwise_ari"],
    })


def main() -> None:
    SOURCE.mkdir(parents=True, exist_ok=True)
    QC.mkdir(parents=True, exist_ok=True)
    tables = {"Table1_FINAL.csv": table1(), "Supplementary_Table_S1_FINAL.csv": table_s1(), "Supplementary_Table_S2_FINAL.csv": table_s2(), "Supplementary_Table_S3_FINAL.csv": table_s3(), "Supplementary_Table_S4_FINAL.csv": table_s4()}
    expected = {"Table1_FINAL.csv": 19, "Supplementary_Table_S1_FINAL.csv": 19, "Supplementary_Table_S2_FINAL.csv": 5, "Supplementary_Table_S3_FINAL.csv": 95, "Supplementary_Table_S4_FINAL.csv": 95}
    for name, frame in tables.items():
        if len(frame) != expected[name]: raise AssertionError((name, len(frame)))
        frame.to_csv(SOURCE / name, index=False, encoding="utf-8-sig", na_rep="NA", float_format="%.17g")
    s4 = tables["Supplementary_Table_S4_FINAL.csv"]
    checks = {
        "status": "PASS", "rows": {k: len(v) for k, v in tables.items()},
        "s3_unique_units": not tables["Supplementary_Table_S3_FINAL.csv"].duplicated(["Dataset", "Method"]).any(),
        "s4_unique_units": not s4.duplicated(["Dataset", "Method"]).any(),
        "s4_legitimate_marker_rho_na_count": int(s4["Within-unit partition-to-marker Spearman rho"].isna().sum()),
        "methods": list(tables["Supplementary_Table_S2_FINAL.csv"]["Method"]),
    }
    if not checks["s3_unique_units"] or not checks["s4_unique_units"] or checks["s4_legitimate_marker_rho_na_count"] != 1: raise AssertionError(checks)
    corpus = "\n".join((SOURCE / name).read_text(encoding="utf-8-sig") for name in tables)
    forbidden = ["m0.19", "seed19", "LOCK_ADD_SEDR", "protocol hash", "preflight", "outcome-blind", "wrapper failure", "candidate"]
    found = [x for x in forbidden if x.lower() in corpus.lower()]
    if found: raise AssertionError({"forbidden": found})
    (QC / "TABLE_SOURCE_VALIDATION.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    print(json.dumps(checks, indent=2))


if __name__ == "__main__": main()
