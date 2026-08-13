# Source-data dictionary

All values here were copied byte-for-byte from the validated five-method
publication package; they were not recomputed during repository preparation.

## Analysis tables

| File | Principal content | Used by |
|---|---|---|
| `integrated_seed_level_accuracy.csv` | Reference ARI/NMI for 1,900 seed runs | S1, rankings |
| `integrated_pairwise_reproducibility.csv` | 18,050 within-unit seed-pair comparisons | Figures 2–3, S3 |
| `integrated_iso_accuracy.csv` | Unit summaries at 0.01/0.02/0.03 thresholds | Figure 3, S3, Table S3 |
| `integrated_method_dataset_summary.csv` | 95 method–entry summaries | Figure 2, Tables S3–S4 |
| `integrated_marker_reproducibility_all_pairs.csv` | Marker agreement for primary iso-accuracy pairs | Figure 4, S5 |
| `integrated_marker_unit_summary.csv` | Within-unit marker correlations | Figure 4, Table S4 |
| `integrated_marker_tertile_summary.csv` | Low/middle/high partition-similarity strata | Figure 4, Table S4 |
| `integrated_consensus_summary.csv` | Single-seed and consensus reproducibility | Figure 5, S8, Table S4 |
| `five_method_rank_*.csv`, `five_method_winner_probabilities.csv`, `five_method_pairwise_superiority.csv`, `five_method_dataset_uncertainty.csv` | Exact empirical ranking summaries | S6, Table S4 |

## Figure and table tables

File names identify their target figure or table. `docs/OUTPUTS.md` gives the
complete script → input → output map. Missing values are retained where a
quantity was not estimable; they are not zeroes.

