# Scientific discrepancy register

No unresolved numerical discrepancy was found between the accepted five-method integrated outputs, final figure/table source data, and the locked manuscript headline values. The existing final numerical gate and reconciliation report both record PASS. No scientific result, threshold, example-selection rule, or parameter was changed while creating this repository.

## SpaGCN post-refinement cluster count

The frozen MERFISH wrapper initially required SpaGCN to contain exactly requested K after official spatial refinement. A blinded technical audit found that this extra validator requirement was inconsistent with the original Project 9 SpaGCN handling, which retained normally completed finite outputs when official refinement collapsed a cluster. The formal amendment removed only the exact post-refinement observed-K acceptance condition. Requested K=8, initialization, preprocessing, adjacency, `p`, `l`, training, epochs, seed, and official refinement were unchanged. The first normally completed finite refined output is retained without tuning or selection. This is a resolved, provenance-documented protocol inconsistency rather than an unresolved result discrepancy.

## SEDR internal DEC K versus final requested K

SEDR's official representation uses internal DEC K=10 for every entry, while the single final mclust EEE readout uses the dataset-specific requested K. These quantities serve different roles and must not be conflated. The locked code and public configuration agree on this distinction; no discrepancy requires correction.

## Metadata uncertainties that do not change scientific results

The exact STAGATE Git commit is unavailable because the recorded installation pinned the `main` branch rather than an immutable revision. BANKSY is recorded as pybanksy 1.3.5, but its exact source commit is unavailable. Exact stable source-file identifiers remain to be verified for the DLPFC archive, BenchmarkST STARmap snapshot, and HBCA1 direct download/annotation files. The complete MERFISH four-method environment freeze and an end-to-end runtime for all 1,900 runs were not retained. These are marked **TO VERIFY** throughout the repository and were not guessed.

## Third-party license metadata conflict

The locked GraphST package metadata reports MIT, while its included `LICENSE.md` contains AGPL-3.0 text. This is a software-distribution issue, not a scientific discrepancy. The public repository does not vendor GraphST source and conservatively flags the conflict in `THIRD_PARTY_NOTICES.md` pending upstream clarification.

