# Frozen computational methods

The benchmark evaluated GraphST, STAGATE, SpaGCN, BANKSY, and SEDR across the 19 entries. Seeds were the integers 1 through 20 exactly once per method-entry unit. Requested K was 7 for DLPFC and STARmap, 20 for HBCA1, and 8 for MERFISH. Machine-readable settings are under `config/methods/`; this document summarizes those locked settings without changing them.

## GraphST

GraphST 1.1.1 was pinned to commit `d62b0b7b6cd38ee285f3ac8cd67b7341a10bcc74`. The pipeline used the official spatial graph and trained the official representation for 200 epochs. MERFISH used all 155 genes, original coordinates, `datatype="Stereo"`, the official three-nearest-neighbor graph, learning rate 0.001, and nominal output dimension 64. If an embedding had more than 20 columns, it was reduced to 20 PCs with ARPACK PCA and `random_state=0`. Final labels used the common tied-covariance Gaussian-mixture readout with requested K, `n_init=5`, `max_iter=500`, `reg_covar=1e-6`, and the run seed.

## STAGATE

The analysis used the official STAGATE PyG implementation. Installed package metadata reported version 1.0.0, but the exact Git commit of the branch-based installation is **TO VERIFY**. The model used hidden dimensions `[512, 30]`, 200 epochs, learning rate 0.001, and weight decay 0.0001. The radius graph used radius 150 by default and for MERFISH; HBCA1 used the scale-equivalent radius 300. MERFISH coordinates were not rescaled. The final readout was the common tied-covariance Gaussian mixture at requested K. No post-clustering spatial refinement was applied.

## SpaGCN

SpaGCN 1.2.7 was pinned to commit `dc7a1c26ea0fdf4dfe7064adc7699be141b4871f`. Histology was not used. The coordinate-only pipeline applied total-count normalization to 10,000, `log1p`, and up to 50 PCs. For MERFISH, the official coordinate adjacency was constructed per section and `l` was obtained label-free using `search_l(p=0.5, start=0.01, end=1000, tol=0.01, max_run=100)` and cached. Training used learning rate 0.05, at most 200 epochs, `init_spa=True`, k-means initialization at requested K, and tolerance 0.005. Official six-neighbor hexagonal refinement was then applied.

Requested K was fixed before refinement. Under the blinded protocol amendment, a normally completed, finite refined output remained valid when official refinement reduced the observed cluster count. No reconstruction, manual split/merge, tuning, or result selection was allowed. This matches the original Project 9 SpaGCN estimand and is documented in `results/provenance/MERFISH_SPAGCN_REFINEMENT_AMENDMENT.md`.

## BANKSY

The analysis used pybanksy 1.3.5; its exact source commit is **TO VERIFY**. The frozen configuration used 15 spatial neighbors with scaled-Gaussian weights, `lambda=0.2`, `max_m=0`, and no variance balancing. A label-free safeguard retained columns having variance greater than `1e-12` in both own and neighborhood expression. The representation was reduced to 20 PCs with ARPACK PCA and `random_state=0`. The BANKSY representation was deterministic; the varied run seed entered the common tied-covariance Gaussian-mixture readout at requested K. No spatial refinement was applied.

## SEDR

SEDR 1.0.0 was pinned to commit `ef4836059a4ea49be3bf7c67008a44ffc16a2a0e`. For Visium, preprocessing applied gene filters `min_cells=50` then `min_counts=10`, total-count normalization to 1,000,000, no log transform, 2,000 `seurat_v3` highly variable genes, Scanpy scaling defaults, and up to 200 PCs with `random_state=42`. STARmap and MERFISH retained their full gene panels, used total-count normalization to 1,000,000 without log transformation, Scanpy scaling defaults, and up to 200 PCs.

The official Euclidean KNN graph used 12 neighbors for Visium and 6 for STARmap/MERFISH, excluding self and using undirected-union symmetrization with official normalization. The representation used an expression encoder 64 to 16, graph hidden dimension 64 with 16+16 outputs, and a 32-dimensional latent vector. Official defaults were retained: dropout 0.2, SCE alpha 3, internal DEC K=10, mask rate 0.8, loss weights 10/0.1/1/1, Adam learning rate 0.01, and weight decay 0.01. Each run performed 200 pretraining plus 200 DEC epochs. The internal DEC initialization used K=10, `n_init=20`, and `random_state=42`; this internal K is not the final requested spatial-domain K.

Final SEDR labels came from one R `mclust::Mclust` call with model EEE, `G=requested K`, and R seed equal to the run seed. A normally completed finite readout remained valid if its observed K differed from requested K. No post-clustering spatial refinement was applied.

## Accuracy, reproducibility, markers, ranking, and consensus

Reference performance comprised ARI and NMI for each seed partition. Direct partition reproducibility enumerated all 190 unordered seed pairs per unit and used median seed-pair ARI as the primary summary; partition instability was one minus that median. Primary iso-accuracy pairs had absolute reference-ARI difference at most 0.02, with only 0.01 and 0.03 as frozen sensitivities. Pairs with partition ARI below 0.50 were termed divergent.

Marker rankings were aligned to the full 20-seed consensus by Hungarian maximum-overlap assignment. For each aligned domain versus all other observations, Scanpy Wilcoxon rankings used `use_raw=False` and `tie_correct=False`. Top-100 Jaccard was primary, with top-50 Jaccard and full-rank Spearman as sensitivities. The continuous partition-to-marker analysis used a within-unit Spearman correlation and deterministic equal-count low/middle/high tertiles, breaking ties by seed IDs. The paired high-versus-low comparison used a one-sided Wilcoxon signed-rank test across estimable units.

Ranking uncertainty was computed by exact streaming enumeration of all `20^5=3,200,000` observed-score combinations per entry. Cross-method ties used average midranks, and methods tied for the maximum divided rank-1 credit equally. The combinations were not treated as independent experiments and were not used for inferential P values.

Consensus used an unweighted observation-by-observation co-association matrix, distance `1-C`, average linkage, and the same requested K. Full consensus used seeds 1-20. Split-half reproducibility compared consensus A from seeds 1-10 with consensus B from seeds 11-20 by ARI. Gain was split-half consensus ARI minus the unit median single-seed pairwise ARI.

