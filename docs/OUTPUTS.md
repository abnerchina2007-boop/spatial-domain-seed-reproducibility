# Output provenance

This map answers which code and frozen input support each publication object.
Paths are relative to the repository root. Final source-data CSVs were copied
from the validated submission package and were not recomputed during public
repository assembly.

## Main figures

| Output | Authoritative renderer | Released input files | Released output |
|---|---|---|---|
| Figure 1 | `scripts/frozen_workspace/work/sedr_expansion/build_five_method_candidate_main.py::figure1` | `Figure1_dataset_landscape.csv`, `Figure1_coverage_matrix.csv` | `results/figures/main/Figure1.{pdf,png}` |
| Figure 2 | same builder, `figure2` | `Figure2_method_dataset_units.csv` | `results/figures/main/Figure2.{pdf,png}` |
| Figure 3 | same builder, `figure3` | `Figure3_iso_accuracy_pairs.csv`, `Figure3_selected_examples.csv`, `Figure3_spatial_maps.csv` | `results/figures/main/Figure3.{pdf,png}` |
| Figure 4 | `scripts/frozen_workspace/work/final_five_method_package/build_final_figures.py::figure4` | five `Figure4_*.csv` files | `results/figures/main/Figure4.{pdf,png}` |
| Figure 5 | candidate-main `figure6` followed by final renaming | `Figure5_consensus.csv` | `results/figures/main/Figure5.{pdf,png}` |

The final article architecture contains five main figures. Historical
candidate numbering called the consensus figure “Figure 6”; the final wrapper
renamed it to Figure 5 without changing its data.

## Supplementary figures

| Output | Authoritative renderer | Released input files |
|---|---|---|
| S1 | candidate-supp builder `supplementary1` | `FigureS1_seedwise_reference_ari.csv` |
| S2 | candidate-supp builder `supplementary2` | `FigureS2_nmi_summary.csv` |
| S3 | candidate-supp builder `supplementary3` | `FigureS3_threshold_sensitivity_*.csv` |
| S4 | final builder `figure_s4` | `FigureS4_selected_examples.csv`, `FigureS4_spatial_maps.csv` |
| S5 | candidate-supp builder `supplementary5` | three `FigureS5_*.csv` files |
| S6 | final builder `figure_s6` | four `FigureS6_*.csv` files |
| S7 | final builder `figure_s7` | `FigureS7_technical_repeatability_controls.csv` |
| S8 | candidate-supp builder `supplementary8` | `FigureS8_consensus_analysis.csv` |

Final files are `results/figures/supplementary/FigureS1` through `FigureS8`
in PDF and PNG.

## Tables

`scripts/frozen_workspace/work/five_method_final_tables/build_final_table_sources.py`
assembled the following final
CSVs; Word/XLSX renderers are included only as presentation utilities.

| Output | Released source |
|---|---|
| Table 1 | `results/source_data/tables/Table1_FINAL.csv` |
| Supplementary Table S1 | `Supplementary_Table_S1_FINAL.csv` |
| Supplementary Table S2 | `Supplementary_Table_S2_FINAL.csv` |
| Supplementary Table S3 | `Supplementary_Table_S3_FINAL.csv` |
| Supplementary Table S4 | `Supplementary_Table_S4_FINAL.csv` |

## Scientific analysis lineage

- Seed-level ARI/NMI and direct partition ARI: the three platform-specific
  core analyzers in `scripts/reproducibility/`.
- Primary and sensitivity iso-accuracy summaries: the same core analyzers,
  frozen at 0.02 primary and 0.01/0.03 sensitivity thresholds.
- Marker Jaccard and rank correlation: `scripts/marker_analysis/`.
- Five-method exact rankings: `scripts/ranking/analyze_five_method_rankings.py`.
- Co-association and split-half consensus: the core analyzers and
  `scripts/consensus/` documentation.
- Final cross-method merge: `scripts/reproducibility/integrate_all_outputs.py`.
