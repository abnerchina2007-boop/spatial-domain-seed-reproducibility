# Stable benchmark scores can conceal stochastic irreproducibility in spatial transcriptomics domain detection

[![release](https://img.shields.io/badge/release-v1.0.0-blue)](https://github.com/abnerchina2007-boop/spatial-domain-seed-reproducibility/releases/tag/v1.0.0)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Overview

This repository is the public code and source-data snapshot for a benchmark of
random-seed reproducibility in spatial transcriptomics domain detection. The
study distinguishes stability of external reference scores from direct
reproducibility of the inferred spatial partition, then traces seed dependence
through domain maps, marker rankings, method rankings, and an established
multi-seed co-association consensus.

The frozen benchmark comprises GraphST, STAGATE, SpaGCN, BANKSY, and SEDR on
19 dataset entries, with 20 seeds per method–entry unit: 95 units and 1,900
model runs. The primary iso-accuracy definition is
`|Δ reference ARI| ≤ 0.02`; sensitivity thresholds are 0.01 and 0.03.

No model was rerun and no scientific value was regenerated while preparing
this public repository. Released tables are byte-for-byte copies of the
validated submission package.

## Repository structure

```text
.
├── config/                  # frozen dataset and method settings
├── data/                    # download/provenance guidance; no raw datasets
├── docs/                    # methods, workflow, outputs, and limitations
├── envs/                    # split environments for incompatible stacks
├── notebooks/               # explains why notebooks are not authoritative
├── results/
│   ├── figures/             # final PDF/PNG renderings
│   ├── provenance/          # frozen protocols and final validation records
│   └── source_data/         # analysis, figure, and table source files
├── scripts/
│   ├── preprocessing/       # frozen-input preparation
│   ├── run_methods/         # seed-level method execution
│   ├── reproducibility/     # ARI/NMI and partition comparisons
│   ├── iso_accuracy/        # iso-accuracy summaries
│   ├── marker_analysis/     # marker agreement
│   ├── ranking/             # exact empirical rank distributions
│   ├── consensus/           # co-association/split-half workflows
│   ├── figures/             # final figure renderers
│   ├── tables/              # publication table builders
│   ├── pipeline/            # guarded long-running orchestration
│   └── validation/          # static, numerical, and security checks
├── REPOSITORY_AUDIT.md
├── MANIFEST.md
└── SCIENTIFIC_DISCREPANCIES.md
```

## Datasets

The benchmark includes 12 human dorsolateral prefrontal cortex sections,
STARmap visual cortex, one human breast-cancer Visium sample (HBCA1), and five
MERFISH hypothalamus sections. Public raw data are intentionally not mirrored
on GitHub. Sources, reference-annotation provenance, expected local paths, and
preprocessing entry points are listed in [data/README.md](data/README.md) and
[docs/DATASETS.md](docs/DATASETS.md). Metadata that could not be verified from
the locked project is explicitly marked `TO VERIFY`.

## Installation

The five methods do not share one perfectly portable dependency stack. For
downstream validation and plotting:

```bash
conda env create -f environment.yml
conda activate spatial-seed-repro
python scripts/validation/validate_release.py
```

Method execution should use the environment file for that method in `envs/`.
GPU-enabled PyTorch must be installed for the local CUDA driver as documented
in [docs/COMPUTATIONAL_REQUIREMENTS.md](docs/COMPUTATIONAL_REQUIREMENTS.md).
Third-party methods are installed as dependencies and are not vendored here;
see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Reproducing analyses

The high-level entry point is deliberately safe by default:

```bash
python scripts/run_full_analysis.py --help
python scripts/run_full_analysis.py validate
python scripts/run_full_analysis.py plan
```

`plan` prints the frozen stages without launching any model. Training requires
an explicit `--execute` flag and prepared local data. The workflow is split as:

1. prepare public datasets locally;
2. execute one method × entry × seed checkpoint;
3. collect the 20 seed outputs per unit;
4. calculate direct partition reproducibility;
5. identify iso-accuracy comparisons;
6. calculate marker reproducibility;
7. enumerate empirical method-rank distributions;
8. construct full and split-half co-association consensus partitions;
9. generate figures and publication tables.

The 1,900-run training panel is expensive and is not the default reviewer
action. Fast verification starts from the released source data:

```bash
python scripts/validation/validate_release.py
```

Exact method parameters and gate behavior are documented in
[docs/METHODS.md](docs/METHODS.md) and
[docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md).

## Reproducing figures

Final PDF/PNG figures and all 27 corresponding CSV source tables are included.
The authoritative rendering code is indexed under `scripts/figures/` and
preserved in `scripts/frozen_workspace/work/`; table builders are indexed under
`scripts/tables/`. The complete figure/table provenance map is in
[docs/OUTPUTS.md](docs/OUTPUTS.md). The released renderings provide a direct
comparison target without requiring model training.

## Computational requirements

The recorded workstation used Windows, 16 physical CPU cores (32 logical),
31.3 GiB RAM, and an NVIDIA RTX 5060 Laptop GPU with 8 GiB VRAM. Processes
were limited to four CPU threads. SEDR used one GPU worker; its 380 checkpoints
totaled 4.44 compute-hours (median 40.3 s/run; maximum observed RAM 2.59 GiB
and GPU memory 349 MiB). The MERFISH four-method panel totaled 26.06
compute-hours summed across runs; this is not wall-clock time. A reliable total
wall-clock value for the original 14-entry panel was not retained and is marked
`TO VERIFY` rather than estimated.

## Code availability

This repository contains the project-authored preprocessing, execution,
scientific-analysis, integration, figure, table, and validation scripts used
for the submission snapshot. It also contains frozen configurations and the
small derived/source-data tables underlying the reported results. Raw public
datasets, seed-level partition predictions, checkpoints, logs, and third-party
source trees are excluded. Original method implementations must be obtained
from their upstream projects.

## Data availability

All benchmark inputs are based on public datasets. This repository does not
redistribute those large inputs. Dataset-specific publication, repository, and
annotation information is provided in [data/README.md](data/README.md). The
small derived tables necessary to inspect manuscript statistics and figures
are in `results/source_data/`.

## Validation and integrity

Repository preparation included Python syntax checks, path/reference checks,
source-table shape and manuscript-number reconciliation, a secret/private-path
scan, large-file checks, and a staged-content audit. The original working tree
was not deleted or reorganized. Details are in [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md),
[MANIFEST.md](MANIFEST.md), and `results/provenance/`.

## Citation

Citation metadata are provided in [CITATION.cff](CITATION.cff). The final
manuscript author list was not reliably present in the locked project, so the
author field is visibly marked `TO VERIFY` and must be replaced before journal
publication metadata are finalized.
