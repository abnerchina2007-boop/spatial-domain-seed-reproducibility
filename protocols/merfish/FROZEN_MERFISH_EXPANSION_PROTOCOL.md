# Frozen MERFISH expansion protocol

**Status:** frozen before Stage B  
**Authorization:** `LOCK_MERFISH_5SECTIONS`  
**Rule:** this file and its recorded SHA-256 must not change after any Stage B scientific result is computed or inspected.

## 1. Scientific scope

This is a frozen external-validation experiment in one independent context: MERFISH measurements from the Moffitt mouse hypothalamus/preoptic region, represented by five consecutive sections from BASS Animal1. All five sections remain in the analysis regardless of outcome.

## 2. Exact inputs

Stage B uses bit-identical copies of these frozen files:

| Section ID | Bregma, mm | Cells | Genes | SHA-256 |
|---|---:|---:|---:|---|
| `MERFISH_Bregma_m0.04` | −0.04 | 5,488 | 155 | `1369641CFABB62572C67AE2DB454F7E2FA65702B81E44365C2E772AFE2CA3F12` |
| `MERFISH_Bregma_m0.09` | −0.09 | 5,557 | 155 | `91E912D7F53E8C7A985B6F152BFB3982F975F3BF82ED135601D1D54C61522D48` |
| `MERFISH_Bregma_m0.14` | −0.14 | 5,926 | 155 | `F46C60973AE99E223A612B148DD068B8A9568E46702245703F6A0C8975D8200F` |
| `MERFISH_Bregma_m0.19` | −0.19 | 5,803 | 155 | `DE986E9212813224BF60F936D08C890EDBD915A1004B99EBA57F176470BACDB3` |
| `MERFISH_Bregma_m0.24` | −0.24 | 5,543 | 155 | `13C3ED6478D3396F152B6016096AA7C13D0761D984061F395930E29B6C641A8E` |

The frozen ordered gene universe is `FROZEN_GENE_UNIVERSE.tsv`, SHA-256 `61FC7CD61DB7AAA720977E4CAB2C4DA5C2642B984FE540A671F3481836312759`. Cell IDs, order, coordinates, expression values, gene order and labels are immutable.

## 3. Reference annotation

The reference is the cell-level BASS/manual spatial-domain annotation in `obs["manual_layer"]`, derived using spatial marker patterns and Allen Mouse Brain Atlas information. K is fixed at 8 for every section. The exact shared ontology is `BST`, `fx`, `MPA`, `MPN`, `PV`, `PVH`, `PVT`, `V3`. All retained cells have valid labels. Reference labels are used only after all 400 prediction runs have completed and passed technical validation.

## 4. Gene and preprocessing rule

Use all 155 measured genes in all five sections. The label-free `min_cells=3` rule retains all 155 genes. The shared prepared object uses total-count normalization to 10,000, `log1p`, all 155 genes marked highly variable, and scaling with `zero_center=False`, `max_value=10`. No 3,000-HVG universe, gene substitution, cell subsampling or result-guided filtering is permitted.

SpaGCN and the downstream marker analysis start from the frozen `layers["counts"]` processed-expression layer and independently apply `normalize_total(10000)` and `log1p` as specified below. This layer is the authoritative BASS/Moffitt processed MERFISH expression, not a uniform raw integer-count matrix.

## 5. Complete run panel and execution controls

- Methods: GraphST, STAGATE, SpaGCN, BANKSY.
- Seeds: integers 1–20 for every method–section unit.
- Required panel: 5 sections × 4 methods × 20 seeds = 400 runs.
- Training epochs: 200 wherever the method trains.
- Each section–method–seed is an atomic resumable checkpoint.
- At most two independent seed runs execute concurrently.
- Each run is capped at four CPU threads; existing GPU selection is preserved.
- If free memory falls below 5 GiB, do not fill the second slot; continue one run at a time.
- Never reduce epochs, sections, methods or seeds to address resource pressure.
- Do not compute or inspect ARI, NMI, seed-pair stability, map quality, marker, ranking or consensus results until all 400 predictions pass technical validation.

## 6. Frozen methods

### GraphST

Use the exact Project 9 Phase 1 GraphST runner: prepared 155-gene matrix, original x/y coordinates, `datatype="Stereo"`, official three-nearest-neighbor graph, 200 epochs, learning rate 0.001, nominal output dimension 64, and seed-controlled training. If the returned embedding has more than 20 columns, reduce to 20 PCs using PCA `svd_solver="arpack"`, `random_state=0`. Apply the common fixed-K readout below.

### STAGATE

Use original x/y coordinates and one radius graph with `rad_cutoff=150.0` in every section. Train the exact Phase 1 model with hidden dimensions `[512, 30]`, 200 epochs, learning rate 0.001, weight decay 0.0001 and the primary seed. Apply the common fixed-K readout. The radius is not tuned or rescaled after results.

### SpaGCN

Use coordinate-only SpaGCN 1.2.7 with no histology. On all 155 genes, apply `normalize_total(10000)` and `log1p`. Construct the official coordinate adjacency once per section. Determine `l` label-free with `search_l(p=0.5, start=0.01, end=1000, tol=0.01, max_run=100)` and cache it. Train with 50 PCs, learning rate 0.05, 200 maximum epochs, `init_spa=True`, `init="kmeans"`, `n_clusters=8`, and `tol=5e-3`. Apply official six-neighbor `shape="hexagon"` refinement. No histology or outcome-guided tuning is allowed.

### BANKSY

Use pybanksy 1.3.5 with 15 spatial neighbors, scaled-Gaussian weights, `lambda=0.2`, `max_m=0`, and no variance balancing. Retain only columns with variance greater than `1e-12` in both own and neighborhood expression; this deterministic label-free safeguard is fixed across seeds. Use 20 PCs with `svd_solver="arpack"`, `random_state=0`. The BANKSY representation is deterministic; the varied primary seed enters the common fixed-K readout. Do not substitute BANKSY's default lambda=0.8 domain mode.

### Common fixed-K readout

Use scikit-learn `GaussianMixture` with `n_components=8`, tied covariance, `n_init=5`, `max_iter=500`, `reg_covar=1e-6`, and `random_state=primary_seed`. Every accepted prediction must contain one finite label for each frozen cell and exactly eight observed clusters.

## 7. Primary accuracy and partition reproducibility

Only after the 400-run panel is technically complete:

- Compute adjusted Rand index (ARI) and normalized mutual information (NMI) between each seed partition and the complete BASS reference labels.
- Per method–section unit report median, minimum, maximum, range and sample SD (`ddof=1`) of reference ARI; median and sample SD of NMI.
- Enumerate all unordered seed pairs: `choose(20,2)=190` per unit.
- Compute partition ARI and NMI for each pair.
- Per unit report median partition ARI, fifth percentile partition ARI and `partition instability = 1 − median pairwise partition ARI`.

## 8. Iso-accuracy analysis

Primary iso-accuracy pairs satisfy absolute reference-ARI difference ≤0.02. Retain the already frozen sensitivity thresholds 0.01 and 0.03. For each method–section unit and threshold report pair count, median pairwise partition ARI, minimum partition ARI and the fraction with partition ARI <0.50. No additional thresholds are permitted.

## 9. Distribution-based winner uncertainty

For each section independently, take the 20 observed reference ARIs for each of the four methods and exhaustively enumerate `20^4=160,000` combinations, selecting one observed run per method. Report each method's rank distribution, empirical `P(rank 1)`, maximum winner probability, winner entropy in bits and normalized entropy, plus all six pairwise superiority/tie probabilities.

The 160,000 combinations are an exact empirical enumeration and are not independent experiments. Exact cross-method ties use average midranks; methods tied for the maximum divide rank-1 credit equally. Pairwise exact ties are reported as tie probability. No regression or inferential P value is added.

## 10. Consensus

For each method–section unit construct an unweighted cell × cell co-association matrix, `C_ij = fraction of included seeds assigning i and j to the same domain`. Set `D=1−C` and apply average-linkage agglomerative clustering with precomputed distance and K=8. Construct a full seeds 1–20 consensus, an independent seeds 1–10 consensus A, and a seeds 11–20 consensus B.

Report full-consensus reference ARI/NMI, split-half `ARI(A,B)`, the unit median single-seed pairwise ARI, and `split-half gain = ARI(A,B) − median single-seed pairwise ARI`.

## 11. Frozen marker-ranking pipeline

Use the full 155-gene targeted panel. Starting from the frozen processed-expression layer, apply `normalize_total(10000)` and `log1p`. Align each seed partition to its corresponding full 20-seed consensus by Hungarian maximum-overlap assignment. For each aligned domain versus all other cells, run Scanpy `rank_genes_groups(method="wilcoxon", use_raw=False, tie_correct=False)` over all 155 genes. If Scanpy rejects a singleton domain, use the already frozen mathematically equivalent untied Wilcoxon rank-sum fallback; do not merge or drop the domain.

The primary marker set size is `min(100, valid measured genes)=100`. For every primary iso-accuracy pair, calculate the median across mutually present aligned domains of top-100 Jaccard, top-50 Jaccard and full-rank Spearman correlation.

## 12. Continuous partition-to-marker analysis

For every primary iso-accuracy pair use `x = pairwise partition ARI` and `y = top-100 marker-set Jaccard`. Pairs are not treated as independent global observations. For each of the 20 method–section units:

1. calculate within-unit Spearman correlation between x and y;
2. sort pairs by partition ARI, breaking ties by seed IDs, and divide them into deterministic equal-count low/middle/high tertiles;
3. report median marker Jaccard per tertile;
4. report high-minus-low marker-Jaccard difference.

If a unit has no primary iso-accuracy pair, retain it with zero pairs and missing correlation/tertile estimates; do not alter the threshold.

## 13. External-generalization classification

Freeze four descriptive components:

1. **Score–map decoupling:** at least two method–section units spanning at least two methods have reference-ARI SD ≤0.02 and partition instability ≥0.30, matching the existing Project 9 low-SD/high-instability definition.
2. **Iso-accuracy divergence:** primary iso-accuracy partition ARI <0.50 occurs in at least two methods.
3. **Positive partition-to-marker relationship:** the median of the 20 within-unit Spearman correlations is positive and more than half of estimable units are positive.
4. **Consensus improvement:** split-half gain is positive in more than half of the 20 units.

Classify `STRONG_GENERALIZATION` if all four components are present, `PARTIAL_GENERALIZATION` if one to three are present, and `WEAK_OR_ABSENT_GENERALIZATION` if none are present. Retain all results regardless of classification.

## 14. Outputs and integration

Preserve all 400 seed predictions, per-run metadata/logs, source/input/protocol hashes, primary tables, figure-ready CSVs and publication-style diagnostic previews for integration with Figures 1–6. Do not overwrite locked manuscript figures. Create a manuscript-integration report that treats the five sections as one new MERFISH context.

## 15. Prohibited changes

No post-result change to inputs, cells, genes, labels, K, graph rules, method parameters, seeds, thresholds, marker pipeline, consensus, classification rule or example-selection rule is permitted. No section or unfavorable result may be removed. No pathway enrichment, additional method, additional section, exploratory figure, extra sensitivity analysis or nonrequired robustness check is authorized.
