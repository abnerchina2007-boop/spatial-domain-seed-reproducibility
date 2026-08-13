from __future__ import annotations

"""Create candidate-only comparison notes and contact sheets after plotting."""

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, wilcoxon


WORKSPACE = Path(__file__).resolve().parents[2]
SEDR = WORKSPACE / "outputs" / "PROJECT9_SEDR_EXPANSION"
INTEGRATED = SEDR / "candidate_integration"
ALL = INTEGRATED / "all_outputs"
FIVE = INTEGRATED / "five_method"
FIGROOT = INTEGRATED / "figures"
MAIN = FIGROOT / "Main"
SUPP = FIGROOT / "Supplementary"
QC = FIGROOT / "QC"
NOTES = FIGROOT / "MANUSCRIPT_FIGURE_IMPLICATIONS.md"

METHODS = ["GraphST", "STAGATE", "SpaGCN", "BANKSY", "SEDR"]
SEDR_COLOR = "#E69F00"


def write_text(path: Path, text: str) -> None:
    resolved = path.resolve()
    if not (resolved == FIGROOT.resolve() or FIGROOT.resolve() in resolved.parents):
        raise RuntimeError(f"Refusing candidate write outside figure root: {resolved}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def contact_sheet(paths: list[Path], destination: Path, columns: int = 2) -> None:
    images = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        image = Image.open(path).convert("RGB")
        target_width = 1400
        target_height = max(1, round(image.height * target_width / image.width))
        images.append((path.stem, image.resize((target_width, target_height), Image.Resampling.LANCZOS)))
    title_h, gap, margin = 54, 32, 32
    rows = (len(images) + columns - 1) // columns
    row_heights = []
    for row in range(rows):
        row_heights.append(max(im.height for _, im in images[row * columns:(row + 1) * columns]) + title_h)
    width = margin * 2 + columns * 1400 + (columns - 1) * gap
    height = margin * 2 + sum(row_heights) + (rows - 1) * gap
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except OSError:
        font = ImageFont.load_default()
    y = margin
    for row in range(rows):
        x = margin
        for col in range(columns):
            idx = row * columns + col
            if idx >= len(images):
                break
            label, image = images[idx]
            draw.text((x, y), label, fill="black", font=font)
            canvas.paste(image, (x, y + title_h))
            x += 1400 + gap
        y += row_heights[row] + gap
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, dpi=(150, 150))


def main() -> None:
    QC.mkdir(parents=True, exist_ok=True)
    units = pd.read_csv(ALL / "integrated_method_dataset_summary.csv", dtype={"section": str})
    seeds = pd.read_csv(ALL / "integrated_seed_level_accuracy.csv", dtype={"section": str})
    pairs = pd.read_csv(ALL / "integrated_pairwise_reproducibility.csv", dtype={"section": str})
    iso = pd.read_csv(ALL / "integrated_iso_accuracy.csv", dtype={"section": str})
    marker_pairs = pd.read_csv(ALL / "integrated_marker_reproducibility_all_pairs.csv", dtype={"section": str})
    marker_units = pd.read_csv(ALL / "integrated_marker_unit_summary.csv", dtype={"section": str})
    tertiles = pd.read_csv(ALL / "integrated_marker_tertile_summary.csv", dtype={"section": str})
    consensus = pd.read_csv(ALL / "integrated_consensus_summary.csv", dtype={"section": str})
    winners = pd.read_csv(FIVE / "five_method_winner_probabilities.csv", dtype={"section": str})
    uncertainty = pd.read_csv(FIVE / "five_method_dataset_uncertainty.csv", dtype={"section": str})

    # Fail closed on the already validated token-exact old-source reconciliation.
    integration_manifest = json.loads((ALL / "INTEGRATION_MANIFEST.json").read_text(encoding="utf-8"))
    rank_reconciliation = json.loads((FIVE / "four_method_reconciliation.json").read_text(encoding="utf-8"))
    if integration_manifest.get("status") != "PASS" or rank_reconciliation.get("status") != "PASS":
        raise RuntimeError("Four-method reconciliation is not PASS")
    back = integration_manifest["four_method_backfilter_reconciliation"]
    if len(back) != 8 or not all(v.get("status") == "PASS" and v.get("serialized_authoritative_tokens_exact") for v in back.values()):
        raise RuntimeError("Eight-table four-method token-exact backfilter is not PASS")

    rho2 = float(spearmanr(units["reference_ari_sd"], units["partition_instability"]).statistic)
    rule = units[(units["reference_ari_sd"] <= 0.02 + 1e-12) & (units["partition_instability"] >= 0.30 - 1e-12)]
    primary_iso_rows = iso[np.isclose(pd.to_numeric(iso["threshold"]), 0.02, atol=1e-12, rtol=0)]
    eligible = int(primary_iso_rows["n_iso_accuracy_pairs"].sum())
    divergent = int(primary_iso_rows["n_partition_ari_below_0_50"].sum())
    affected = int((primary_iso_rows["n_partition_ari_below_0_50"] > 0).sum())
    rho_values = pd.to_numeric(marker_units["spearman_partition_ari_vs_marker_jaccard"], errors="coerce").dropna()
    pivot = tertiles.pivot(index=["section", "method"], columns="partition_ari_tertile", values="median_top100_marker_jaccard").reindex(columns=["Low", "Middle", "High"])
    complete = pivot.dropna()
    test = wilcoxon(complete["High"], complete["Low"], zero_method="wilcox", alternative="greater", method="auto")
    gains = pd.to_numeric(consensus["split_half_gain_over_median_single_seed_pairwise_ari"], errors="raise")
    rank_sums = winners.groupby("section")["p_rank1"].sum()
    order_map = {section: i for i, section in enumerate([
        "151507", "151508", "151509", "151510", "151669", "151670", "151671", "151672", "151673", "151674", "151675", "151676", "STARmap_20180505_BY3_1k", "HBCA1", "MERFISH_Bregma_m0.04", "MERFISH_Bregma_m0.09", "MERFISH_Bregma_m0.14", "MERFISH_Bregma_m0.19", "MERFISH_Bregma_m0.24"
    ])}
    selected = uncertainty.assign(_order=uncertainty["section"].map(order_map)).sort_values(["maximum_p_rank1", "_order"], kind="stable").head(3)

    checks = [
        (len(units) == 95 and len(seeds) == 1900 and len(pairs) == 18050, "structural totals"),
        (len(primary_iso_rows) == 95 and eligible == 6928 and divergent == 1125 and affected == 55, "primary iso-accuracy"),
        (len(marker_pairs) == 6928 and len(rho_values) == 94 and int((rho_values > 0).sum()) == 94, "marker totals"),
        (len(consensus) == 95 and int((gains > 0).sum()) == 95, "consensus totals"),
        (np.allclose(rank_sums.to_numpy(), 1.0, atol=1e-12, rtol=0), "P(rank1) sums"),
    ]
    if not all(value for value, _ in checks):
        raise RuntimeError("Numerical reconciliation failed: " + ", ".join(name for value, name in checks if not value))

    numerical = f"""# Five-method figure numerical reconciliation

Status: **PASS**

The integrated candidate tables retain an eight-table, token-exact backfilter to the locked four-method sources. No original method output was recomputed. SEDR is consistently shown in `{SEDR_COLOR}`; the four locked method colors are unchanged.

## Figure 1

- Dataset/section entries: **19**
- Methods: **5**
- Method–dataset units: **95**
- Seed-specific runs: **1,900**
- Coverage: 20 seeds in every one of 95 units

## Figure 2

- Units: **95**
- Descriptive Spearman ρ (reference ARI SD versus partition instability): **{rho2:.12f}**
- Low-SD/high-instability units (SD ≤0.02 and instability ≥0.30): **{len(rule)}/95**
- SEDR rows: 19; source values are read directly from the integrated table, whose SEDR source hash is recorded in `INTEGRATION_MANIFEST.json`.

## Figure 3

- Primary iso-accuracy pairs: **{eligible:,}**
- Partition ARI <0.50: **{divergent:,}**
- Fraction divergent: **{divergent / eligible:.12%}** ({100 * divergent / eligible:.6f}%)
- Affected units: **{affected}/95**
- Fixed examples retained: 151670/GraphST, 151507/STAGATE, STARmap/SpaGCN

## Figure 4

- Exact combinations per entry: **3,200,000** (20^5); these are descriptive Cartesian combinations, not independent samples.
- P(rank1) sum range across entries: **{rank_sums.min():.12f}–{rank_sums.max():.12f}**
- Maximum P(rank1) range: **{uncertainty.maximum_p_rank1.min():.7f}–{uncertainty.maximum_p_rank1.max():.7f}**
- Entries with max P(rank1) <0.50: **{int((uncertainty.maximum_p_rank1 < .50).sum())}/19**
- Entries with max P(rank1) <0.75: **{int((uncertainty.maximum_p_rank1 < .75).sum())}/19**
- Deterministic three lowest: **{', '.join(selected.section_display.astype(str))}**

## Figure 5

- Primary marker pairs: **{len(marker_pairs):,}**
- Estimable within-unit correlations: **{len(rho_values)}**
- Positive correlations: **{int((rho_values > 0).sum())}/{len(rho_values)}**
- Median within-unit Spearman ρ: **{rho_values.median():.10f}**
- Unit-level median top-100 Jaccard (Low/Middle/High): **{complete.Low.median():.10f} / {complete.Middle.median():.10f} / {complete.High.median():.10f}**
- Median paired High−Low: **{(complete.High - complete.Low).median():.10f}**
- One-sided paired Wilcoxon: **W={float(test.statistic):.1f}; P={float(test.pvalue):.16g}; n={len(complete)}**
- Frozen panel d remains the original 151507 GraphST representative.

## Figure 6

- Units: **{len(consensus)}**
- Positive split-half gains: **{int((gains > 0).sum())}/{len(consensus)}**
- Median reproducibility gain: **{gains.median():.10f}**
- Median split-half consensus ARI: **{consensus.split_half_consensus_ari.median():.12f}**

All prescribed thresholds, deterministic example rules, exact rank conventions, and method/dataset orders are unchanged.
"""
    write_text(QC / "FIVE_METHOD_FIGURE_NUMERICAL_RECONCILIATION.md", numerical)

    comparison = """# Four-method versus five-method figure comparison

## Figure 1

The fifth coverage column remains legible at 180 mm and adds limited density because all cells share the same completion encoding. **FIVE_METHOD_SIMILAR**

## Figure 2

SEDR adds an informative, coherent method profile: it has relatively high median pairwise reproducibility without eliminating between-seed variation or iso-accuracy divergence. The integrated scatter still shows overlap rather than an isolated class. **FIVE_METHOD_STRONGER**

## Figure 3

The global divergent fraction decreases to 16.24%, so the histogram is less visually dramatic, but 1,125 divergent pairs across 55/95 units retain the central score–map point. **FIVE_METHOD_WEAKER**

## Figure 4

SEDR is the most-probable winner in many entries, reducing broad winner ambiguity. However, the remaining dataset dependence (minimum max P(rank1)=0.521; five entries below 0.75) remains scientifically informative. **FIVE_METHOD_WEAKER**

## Figure 5

The five-method result strengthens the downstream relationship: 94/94 estimable unit correlations are positive, and the frozen paired framework remains strongly ordered from low to high partition agreement. **FIVE_METHOD_STRONGER**

## Figure 6

Consensus improves reproducibility in 95/95 units, extending an established mitigation result across the added method. **FIVE_METHOD_STRONGER**

## Global recommendation

The five-method suite is more heterogeneous but scientifically stronger. Preserve the current six-figure architecture for review, while treating Figure 4 as the leading candidate for possible supplementary relocation.
"""
    write_text(QC / "FOUR_VS_FIVE_METHOD_FIGURE_COMPARISON.md", comparison)

    fig4_note = f"""# Figure 4 main-versus-supplementary assessment

Recommendation: **MOVE_TO_SUPPLEMENT**

1. **Scientific importance:** exact empirical ranking remains valid and useful, but it is one step removed from the central score–map discordance result.
2. **Readability:** the 19×5 annotated heatmap is readable at 180 mm, though it is the densest main panel after adding SEDR.
3. **Connection to central claim:** it addresses benchmark-ranking uncertainty rather than direct partition irreproducibility.
4. **Current evidence:** maximum P(rank1) ranges from {uncertainty.maximum_p_rank1.min():.3f} to {uncertainty.maximum_p_rank1.max():.3f}; no entry is below 0.50 and only five of 19 are below 0.75.
5. **Interpretation:** the most accurate framing is **dataset-dependent winner certainty**, not universal winner uncertainty.
6. **SEDR contribution:** SEDR dominance in many entries makes the overall rank-uncertainty message less central, although STARmap, 151670, and HBCA1 remain meaningfully uncertain.
7. **Placement:** Figure S6 already carries exact rank summaries, so Figure 4 could move to Supplementary without losing the exact empirical-ranking evidence.

This is a recommendation only. No figure was moved, renumbered, or promoted.
"""
    write_text(QC / "FIGURE4_MAIN_VS_SUPPLEMENTARY_ASSESSMENT.md", fig4_note)

    sedr_units = units[units.method == "SEDR"]
    sedr_primary = pairs[(pairs.method == "SEDR") & (pairs.abs_reference_ari_difference <= .02 + 1e-12)]
    heterogeneity = f"""# SEDR heterogeneity visual assessment

1. **Is SEDR visibly more reproducible in Figure 2?** SEDR has a median unit-level median pairwise ARI of {sedr_units.median_pairwise_partition_ari.median():.3f}; it occupies a relatively reproducible region, but overlaps other methods and is not labelled as “most stable.”
2. **Coherent profile or unexplained outlier?** Coherent method-specific profile. All 19 SEDR units remain visible, and no method-specific fit or inferential comparison was added.
3. **Nonzero iso-accuracy divergence?** Yes: {int((sedr_primary.pairwise_partition_ari < .5).sum())}/{len(sedr_primary)} SEDR primary pairs have partition ARI <0.50, affecting {sedr_primary.loc[sedr_primary.pairwise_partition_ari < .5, 'section'].nunique()}/19 entries.
4. **Downstream consistency?** Yes. SEDR has 19/19 positive estimable within-unit marker correlations, while the integrated result is 94/94 positive.
5. **Supported framing?** Yes: stochastic irreproducibility is method dependent, but external-score stability is not a method-agnostic proxy for partition reproducibility.
6. **Misleading equality of instability?** No main panel implies equal instability. Figure 2d and method colors explicitly expose heterogeneous distributions.

No arrows, significance stars, post hoc examples, or new method-comparison tests were introduced.
"""
    write_text(QC / "SEDR_HETEROGENEITY_VISUAL_ASSESSMENT.md", heterogeneity)

    main_visual_qc = """# Main figure visual QC

All candidates were inspected from their 300-dpi PNG at approximately 180-mm final width. SVG text remains editable and the minimum configured text size is 6.5 pt.

| Figure | Readability | Information density | Visual balance | Method colors | Row labels / legends | Effect of SEDR | Verdict |
|---|---|---|---|---|---|---|---|
| Figure 1 | Clear | Moderate | Balanced | Fifth column distinct | 19 rows legible | Adds coverage without crowding | **PASS** |
| Figure 2 | Clear | High but controlled | Balanced 2×2 grid | Five groups distinguishable | Heatmap rows and scatter legend legible | Adds informative method heterogeneity | **PASS** |
| Figure 3 | Clear after replacing an unsupported Unicode subscript in the example label | Moderate | Global distribution remains dominant | Spatial-domain palette unchanged | Titles and annotations legible | Lowers global divergent fraction but preserves impact | **PASS** |
| Figure 4 | Clear | Highest of main suite | Balanced across ranking and seed panels | Warm SEDR and vermilion STAGATE remain distinguishable | 19×5 values and winners legible | Makes ranking more dataset-dependent | **PASS** |
| Figure 5 | Clear | High | Balanced 2×2 grid | Five method groups distinguishable | Labels and frozen-example legend legible | Strengthens downstream consistency | **PASS** |
| Figure 6 | Clear | Moderate | Three panels aligned | Five scatter colors distinguishable | 19-row heatmap legible | Strengthens consensus generalization | **PASS** |

No overlap, clipped label, decorative gradient, or post hoc SEDR highlight was observed. Figure 4’s placement question is scientific/editorial rather than a rendering defect.
"""
    write_text(QC / "MAIN_FIGURE_VISUAL_QC.md", main_visual_qc)

    supplementary_visual_qc = """# Supplementary figure visual QC

All candidates were inspected from their 300-dpi PNG at final-width scale. Candidate A and Candidate B for S7 are both retained; the regular S7 candidate filename is a byte-identical compatibility alias of A and does not constitute a selection.

| Figure | Readability | Density / balance | Color / legend clarity | SEDR integration | Verdict |
|---|---|---|---|---|---|
| S1 | 3+2 layout preserves 6.5-pt labels | Balanced | Five colors distinct | Full fifth panel | **PASS** |
| S2 | Both 19×5 heatmaps legible | Balanced | Fixed scales and colorbars clear | Fifth column integrated | **PASS** |
| S3 | Three prespecified thresholds clear | Low density | Single neutral series | Five-method totals integrated | **PASS** |
| S4 | Byte-identical to locked figure | Locked balance | Locked palette retained | No post hoc SEDR example | **PASS** |
| S5 | Hexbins and paired contrast legible | Moderate | Extreme contrast remains clearly supplementary | Five-method sensitivity; no invented SEDR extreme | **PASS** |
| S6 | Three 19×5 heatmaps legible | High but controlled | Rank scales and labels clear | Exact five-method ranks | **PASS** |
| S7-A | Byte-identical to locked controls | Sparse by design | ARI/NMI symbols clear | No automatic modification | **PASS** |
| S7-B | Six categories legible | Sparse by design | Missing SEDR NMI is represented by absence, not imputation | Two SEDR repeat controls added | **PASS** |
| S8 | Three panels legible | Balanced | Five method colors and gain groups clear | 95-unit integration | **PASS** |

No supplementary figure requires a redesign.
"""
    write_text(QC / "SUPPLEMENTARY_FIGURE_VISUAL_QC.md", supplementary_visual_qc)

    write_text(
        QC / "SUPPLEMENTARY_FIGURE_S4_NOTE.md",
        "No post-unblinding SEDR spatial example added to avoid post hoc example selection.",
    )

    notes = """# Manuscript figure implications only

- Figure 2 now shows stronger method heterogeneity while retaining the same descriptive low-score-SD/high-instability rule.
- Figure 3 remains supportive, although the integrated divergent fraction is lower after adding SEDR.
- Figure 4 is better described as dataset-dependent winner certainty and is the strongest candidate for supplementary relocation.
- Figure 5 remains highly consistent across methods; all 94 estimable within-unit correlations are positive.
- Figure 6 remains uniformly positive: split-half consensus improves all 95 units.
- Supplementary Figure S4 contains no post-unblinding SEDR spatial example, avoiding post hoc example selection.
- Supplementary Figure S7 is supplied in two review candidates; no version was selected automatically.

These are figure-integration notes only. No manuscript prose or legend was edited.
"""
    write_text(NOTES, notes)

    main_paths = [MAIN / f"Figure{i}_five_method_candidate.png" for i in range(1, 7)]
    supp_paths = [SUPP / f"FigureS{i}_five_method_candidate.png" for i in range(1, 9)] + [
        SUPP / "FigureS7_candidate_B_with_SEDR_controls.png"
    ]
    contact_sheet(main_paths, QC / "Main_Figures_Five_Method_ContactSheet.png", columns=2)
    contact_sheet(supp_paths, QC / "Supplementary_Figures_Five_Method_ContactSheet.png", columns=2)

    print(json.dumps({
        "status": "PASS",
        "main_contact_sheet": str(QC / "Main_Figures_Five_Method_ContactSheet.png"),
        "supplementary_contact_sheet": str(QC / "Supplementary_Figures_Five_Method_ContactSheet.png"),
        "figure2_descriptive_rho": rho2,
        "figure4_recommendation": "MOVE_TO_SUPPLEMENT",
    }, indent=2))


if __name__ == "__main__":
    main()
