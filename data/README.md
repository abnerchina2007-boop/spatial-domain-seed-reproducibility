# Data acquisition and local layout

This repository does not redistribute the third-party raw or prepared spatial-transcriptomics datasets. Download each dataset from its cited public source, comply with the source's terms, and place it below `data/raw/` using the identifiers in `config/datasets/datasets.yml`. The public release includes only compact derived source-data tables under `results/source_data/`.

The frozen analysis used 19 entries: twelve human dorsolateral prefrontal cortex (DLPFC) 10x Visium sections, one mouse visual-cortex STARmap sample, one human breast-cancer 10x Visium sample, and five consecutive mouse hypothalamus/preoptic MERFISH sections from Animal1. Each method-entry unit used seeds 1 through 20. The dataset-level dimensions and requested cluster counts are recorded in `metadata/dataset_sources.csv`; frozen prepared-file hashes are recorded in `metadata/frozen_input_hashes.csv` for identity checking after local preparation.

## Expected layout

```text
data/
  raw/
    dlpfc/
      151507/
      ...
      151676/
    starmap/STARmap_20180505_BY3_1k/
    hbca1/HBCA1/
    merfish/Animal1/
  prepared/
    <entry-id>/<entry-id>_frozen.h5ad
```

`data/raw/` and `data/prepared/` are intentionally excluded from version control. The historical preparation programs are preserved under `scripts/frozen_workspace/outputs/PROJECT9_PHASE1/code/` for DLPFC, STARmap, and HBCA1 and under `scripts/frozen_workspace/work/merfish_preflight/` for MERFISH. They are a provenance-preserving mirror of the locked workflow, not a promise that every upstream provider permits unattended downloading. No unverified download URL has been invented.

## Public sources and annotations

The DLPFC sections are from Maynard et al. (2021), DOI `10.1038/s41593-020-00787-0`, distributed through spatialLIBD/HumanPilot at <https://spatial.libd.org/spatialLIBD/>. The reference comprises manually annotated cortical layers L1-L6 and white matter. A stable archived accession or release identifier for the exact files used is **TO VERIFY**.

The STARmap sample `STARmap_20180505_BY3_1k` is associated with Wang et al. (2018), DOI `10.1126/science.aat5691`, and was obtained through the BenchmarkST-curated source at <https://github.com/maiziezhoulab/BenchmarkST>. The analysis used the curated seven-domain anatomical annotation. The exact BenchmarkST commit or release containing the downloaded files is **TO VERIFY**.

HBCA1 is the 10x Genomics Human Breast Cancer Block A Section 1 sample, with the BenchmarkST/SEDR annotation source documented at <https://benchmarkst-reproducibility.readthedocs.io/en/latest/Data%20availability.html>. BenchmarkST is described by Hu et al. (2024), DOI `10.1186/s13059-024-03361-0`. The 20-region reference is a manual pathology annotation defined from H&E and pathological features in the original SEDR study; it is not a SEDR clustering output. The exact direct 10x download URL and exact annotation-file URL are **TO VERIFY**.

The MERFISH entries are five consecutive sections from the Moffitt et al. (2018) mouse hypothalamus/preoptic dataset, DOI `10.1126/science.aau5324`. The public data source is Dryad DOI `10.5061/dryad.8t8s248`, and the preparation used the official BASS analysis repository at <https://github.com/zhengli09/BASS-Analysis>. The source asset was `MERFISH_Animal1.RData` at Git blob `212b0a2a388fd4b97899fcff754d6ffde3aa847b`. The reference is the BASS/manual atlas-informed cell-level Animal1 annotation with eight domains: BST, fx, MPA, MPN, PV, PVH, PVT, and V3. The exact Dryad subfile-to-local-file mapping is **TO VERIFY**.

MERFISH `layers/counts` is the authoritative frozen BASS/Moffitt processed-expression layer; it is nonnegative but is not a uniform raw integer-count matrix. Do not silently substitute another expression representation.

## Integrity and privacy

Prepared objects must retain observation order, gene order, expression values, spatial coordinates, and reference labels. Compare their SHA-256 values with `metadata/frozen_input_hashes.csv` before model execution. The repository contains no raw data, model predictions, embeddings, or checkpoints.

