# PROJECT 9 MERFISH Expansion — SpaGCN Refinement Amendment

## Amendment record

- Amendment date/time: 2026-08-12 16:22:16 +08:00 (Asia/Singapore)
- Scope: technical acceptance of MERFISH SpaGCN outputs after official spatial refinement only
- Scientific-outcome status at amendment: blinded. No ARI, NMI, reference-score variation, pairwise partition reproducibility, iso-accuracy result, winner uncertainty, marker reproducibility, consensus result, spatial-map quality, or biological interpretation was computed or inspected.
- Original protocol status: preserved unchanged. This amendment supplements the original frozen protocol and does not overwrite it or its locked SHA-256.

## Original MERFISH rule

The requested SpaGCN clustering resolution was fixed at K=8 before official refinement, and every accepted prediction was additionally required to contain exactly eight observed clusters after refinement. The execution wrapper therefore rejected any otherwise complete, finite SpaGCN output whose official refinement reduced the observed cluster count below eight.

## Technical audit finding

The historical execution `MERFISH_Bregma_m0.19 / SpaGCN / seed19` used the frozen input, seed, preprocessing, coordinate adjacency, p rule, initialization, 200 epochs, requested K=8, and official six-neighbor hexagonal refinement. Training completed normally. Refinement returned one finite label per expected cell, convertible to `int16`, but the post-refinement observed cluster count was below eight. The prior wrapper rejected the run solely at the exact-post-refinement-K gate and discarded the labels before persistence. The exact historical pre-refinement and post-refinement observed counts are therefore unavailable without a reconstruction rerun.

The original Project 9 SpaGCN pipeline did not require post-refinement observed K to equal requested K. Its primary SpaGCN outputs retained normally completed refinement-induced cluster-count reductions as valid stochastic end-to-end outputs. The MERFISH-only exact-post-refinement-K gate was therefore inconsistent with that original pipeline.

## Amended SpaGCN technical-validity rule

Requested K remains fixed at 8 before official SpaGCN refinement. The frozen SpaGCN version, seed, input, preprocessing, graph construction, p rule, training parameters, initialization, epoch count, and official refinement remain unchanged.

A SpaGCN checkpoint is technically valid when all of the following hold:

1. The intended frozen section, input, seed, preprocessing, and graph rules were used.
2. Training and clustering completed normally.
3. Official SpaGCN refinement completed.
4. The final artifact contains exactly one refined label for every expected frozen cell in frozen cell order.
5. All final labels are finite and the prediction and metadata artifacts are complete and readable.

Post-refinement observed K is not required to equal requested K=8. If official refinement reduces the observed cluster count, the first normally completed finite output is retained without reconstruction of missing clusters, manual merging or splitting, parameter tuning, result selection, or rerunning merely to restore K=8. The refinement-induced reduction is part of the stochastic end-to-end pipeline estimand.

Where technically available for future SpaGCN checkpoints, metadata records `requested_K`, `pre_refinement_observed_K`, `post_refinement_observed_K`, and `refinement_cluster_count_reduced`. Missing historical pre-refinement metadata remains explicitly unavailable and is not reconstructed by rerunning an otherwise valid completed checkpoint.

## Affected checkpoint and recovery

The sole known prior exact-K-only rejection is `MERFISH_Bregma_m0.19 / SpaGCN / seed19`. Because its first historical labels were discarded, it is authorized for one reconstruction rerun using the exact frozen input, seed, environment, preprocessing, graph, p, 200 epochs, requested K=8, initialization, and official refinement. The first normally completed finite reconstruction output is accepted regardless of its post-refinement observed K and is labeled `reconstruction rerun after prior wrapper discard`. The original failure log and historical audit finding remain preserved.

## Unchanged protocol elements

All other frozen elements remain unchanged, including the five sections, cells, 155-gene panel, annotations, requested K, GraphST, STAGATE, BANKSY, all SpaGCN scientific parameters, seeds 1–20, epochs, graph construction, preprocessing, normalization, initialization, official refinement, scientific metrics, iso-accuracy rule, ranking analysis, marker pipeline, consensus algorithm, figure rules, and the 400-run scientific-analysis gate.

Scientific analysis remains prohibited until all 400 technical checkpoints satisfy their method-specific frozen validity rules.
