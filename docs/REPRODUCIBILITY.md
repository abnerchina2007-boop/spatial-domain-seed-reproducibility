# Reproducibility workflow

This release supports two distinct levels of reproduction. The compact route revalidates the reported statistics and regenerates figures from released source-data tables without training spatial models. The full route reconstructs all 1,900 stochastic runs and is computationally expensive, requires the third-party datasets and method environments, and must preserve every frozen setting.

## Compact source-data route

The accepted integrated tables are under `results/source_data/analysis/`, figure-specific inputs are under `results/source_data/figures/`, and final table sources are under `results/source_data/tables/`. The final numerical gate and reconciliation report are under `results/provenance/`. This route is appropriate for reviewers checking row counts, headline values, table assembly, and figure rendering. It must not alter or regenerate the underlying stochastic partitions.

The final figure entry point is `scripts/frozen_workspace/work/final_five_method_package/build_final_figures.py`. Final table source and validation entry points are under `scripts/frozen_workspace/work/five_method_final_tables/`. These programs preserve the historical relative workspace layout; consult the script-area READMEs and run them from the mirrored workspace root.

## Full model route

The full sequence is data acquisition and preparation, input-hash verification, method execution, checkpoint validation, scientific gate opening, downstream analysis, five-method integration, numerical reconciliation, and figure/table generation. DLPFC, STARmap, and HBCA1 preparation and four-method execution are preserved under `scripts/frozen_workspace/outputs/PROJECT9_PHASE1/code/`. MERFISH preparation and execution are under `scripts/frozen_workspace/work/merfish_preflight/` and `scripts/frozen_workspace/work/merfish_expansion/`. SEDR's outcome-blind preflight, technical views, checkpoint runner, validator, gate, scientific analysis, integration, and final validation are under `scripts/frozen_workspace/work/sedr_expansion/`.

Every valid run is an atomic method-entry-seed checkpoint. Existing valid checkpoints are skipped, invalid or incomplete checkpoints are rerun with identical parameters, and valid results are never rerun to select a preferred output. Predictions, embeddings, checkpoints, and execution logs are intentionally absent from the public repository because they are large intermediate artifacts. The released derived tables are the public audit surface.

## Frozen controls

Seeds are integers 1-20. Requested K values and dataset identities are in `config/datasets/datasets.yml`, method parameters are under `config/methods/`, and downstream definitions are in `config/analysis.yml`. The frozen MERFISH protocol SHA-256 was `BF5106AF34143753A244EFD50038EF3F4AFF40580AEADD276547512076D17ED4`. The frozen SEDR protocol SHA-256 was `8DC7B571D832C15895741597E77BDFADD22268F9CD2856CF4D5DA9490D7A8544`. The corresponding human-readable protocol copies and SpaGCN amendment are under `results/provenance/`.

The SEDR worker set `PYTHONHASHSEED` to the run seed before interpreter initialization and used `CUBLAS_WORKSPACE_CONFIG=:4096:8`. Python random, NumPy, SEDR, PyTorch CPU/CUDA, and R seeds were propagated. Deterministic PyTorch algorithms were enabled, cuDNN benchmarking and TF32 were disabled, and PCA/DEC-initialization random states remained fixed as specified in `config/methods/sedr.yml`.

## Validation expectations

Before a full reproduction, the 19 prepared H5AD hashes must match `data/metadata/frozen_input_hashes.csv`. Technical validation must check input and protocol hashes, observation order, expected output length, finite labels, completed epochs, and readable atomic artifacts without consulting reference metrics. Scientific analysis begins only after the complete technical panel is validated. For SEDR this means 380/380 checkpoints; the MERFISH four-method gate means 400/400 predictions. The integrated release must then contain exactly 1,900 seed-level rows and 95 method-entry units.

Reproducing on a different GPU, CUDA stack, operating system, or unpinned upstream branch may not be bit-identical. Such runs should be described as independent reproductions, not as the original locked execution. STAGATE's exact commit and BANKSY's exact source commit remain **TO VERIFY**.

