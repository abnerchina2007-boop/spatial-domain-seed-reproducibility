# Publication repository manifest

This file describes what is included, what it represents, and what was changed
for publication. A machine-readable SHA-256 list for released outputs is in
`results/provenance/RELEASE_FILE_HASHES.sha256`.

## Included top-level material

| Path | Purpose |
|---|---|
| `config/` | Frozen dataset and method settings transcribed from authoritative code and Table S2 |
| `data/` | Public acquisition and annotation metadata; no raw matrices |
| `envs/`, `environment.yml`, `requirements.txt` | Recorded, non-upgraded environments |
| `scripts/` | Project-authored frozen code snapshots and safe reviewer entry points |
| `results/source_data/analysis/` | Complete compact integrated scientific tables |
| `results/source_data/figures/` | 27 figure source CSVs |
| `results/source_data/tables/` | Five table CSVs plus editable workbook |
| `results/figures/` | Final PDF/PNG comparison targets |
| `results/provenance/` | Protocol and final validation evidence |
| `docs/` | Dataset/method/workflow/output/security documentation |

## Scientific immutability

The public assembly made no change to seeds, requested K, preprocessing,
method hyperparameters, graph construction, thresholds, statistics, marker
definitions, ranking tie handling, co-association consensus, or locked values.
Source tables were copied, not recalculated. The only deliberate source-code
edit to a frozen method runner is a path-only SEDR portability change that uses
`R_HOME` instead of one workstation-specific R path.

## Public path conventions

- Project root: detected from the script location or supplied through a CLI.
- Data root: configured by `PROJECT9_DATA_ROOT` or documented command arguments.
- R installation: supplied through `R_HOME` for SEDR.
- Generated outputs: `reproduced_outputs/`, ignored by Git.

## Excluded material

Raw/frozen data, predictions, embeddings, checkpoints, caches, logs, process
state, local environments, render scratch, private Office artifacts,
third-party source snapshots, web/literature downloads, and superseded drafts
are excluded. See `REPOSITORY_AUDIT.md` for details.

## Release content counts

- Five methods × 19 entries × 20 seeds = 1,900 run summaries.
- 95 method–entry units and 18,050 within-unit seed pairs.
- 48 released source-data files: 14 integrated analysis/ranking files,
  27 figure CSVs, five table CSVs, one workbook, and one source-data README.
- Five main and eight supplementary figures in PDF and PNG.
- No raw dataset, seed prediction, or model checkpoint.

The script-level source map and hashes are recorded in
`docs/CODE_PROVENANCE.md` and `docs/CODE_HASHES.tsv`.
