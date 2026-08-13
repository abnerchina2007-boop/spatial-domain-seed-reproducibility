# Datasets and reference annotations

The benchmark contains 19 entries spanning four biological/technology contexts. Twelve entries are 10x Visium sections from human dorsolateral prefrontal cortex (DLPFC), one is a mouse visual-cortex STARmap sample, one is a human breast-cancer 10x Visium sample, and five are consecutive sections from one mouse hypothalamus/preoptic MERFISH Animal1 context. Each entry was evaluated with five methods and 20 seeds, producing 95 method-entry units and 1,900 runs.

The machine-readable entry list, dimensions, and requested K values are in `config/datasets/datasets.yml`. Public-source metadata are in `data/metadata/dataset_sources.csv`, and the 19 prepared-object hashes are in `data/metadata/frozen_input_hashes.csv`. The repository does not distribute raw or prepared third-party data.

## DLPFC

The DLPFC entries are `151507`, `151508`, `151509`, `151510`, `151669`, `151670`, `151671`, `151672`, `151673`, `151674`, `151675`, and `151676`. They are human 10x Visium sections from Maynard et al. (2021), DOI `10.1038/s41593-020-00787-0`, distributed through spatialLIBD/HumanPilot at <https://spatial.libd.org/spatialLIBD/>. The reference labels are manually annotated cortical layers L1-L6 and white matter, with requested K=7. The frozen objects contain 3,460-4,789 spots and 18,067-19,878 retained genes. A stable archived accession or exact release identifier for the downloaded files is **TO VERIFY**.

## STARmap

`STARmap_20180505_BY3_1k`, displayed as STARmap, is a mouse visual-cortex sample associated with Wang et al. (2018), DOI `10.1126/science.aat5691`. It was obtained through the BenchmarkST-curated source at <https://github.com/maiziezhoulab/BenchmarkST>. The frozen object contains 1,207 cells and 1,020 genes. The seven-domain BenchmarkST anatomical reference includes CC, HPC, and cortical layers L1-L6 with L2/3 combined. The exact BenchmarkST source commit or release is **TO VERIFY**.

## HBCA1

HBCA1 is the public 10x Genomics Human Breast Cancer Block A Section 1 Visium sample. The BenchmarkST data-availability page is <https://benchmarkst-reproducibility.readthedocs.io/en/latest/Data%20availability.html>, and BenchmarkST is described by Hu et al. (2024), DOI `10.1186/s13059-024-03361-0`. The frozen object contains 3,798 spots and 22,240 genes, with requested K=20. The reference is a manual 20-region pathology annotation defined from H&E and pathological features in the original SEDR study, not a SEDR clustering output. Because the SEDR developers previously used this dataset, cross-method reference-accuracy comparisons involving SEDR require awareness of developer-dataset exposure. The exact direct 10x download URL and exact annotation-file URL are **TO VERIFY**.

## MERFISH

The MERFISH entries correspond to Bregma -0.04, -0.09, -0.14, -0.19, and -0.24 mm from one Animal1 context. They derive from the Moffitt et al. (2018) mouse hypothalamus/preoptic dataset, DOI `10.1126/science.aau5324`, available through Dryad DOI `10.5061/dryad.8t8s248`. Preparation used the official BASS analysis repository at <https://github.com/zhengli09/BASS-Analysis> and the `MERFISH_Animal1.RData` asset at Git blob `212b0a2a388fd4b97899fcff754d6ffde3aa847b`. Each section contains 5,488-5,926 cells and the complete 155-gene targeted panel, with requested K=8. The BASS/manual atlas-informed reference ontology is BST, fx, MPA, MPN, PV, PVH, PVT, and V3.

The MERFISH `layers/counts` representation is the authoritative frozen BASS/Moffitt processed-expression layer and is not a uniform raw integer-count matrix. The exact Dryad subfile mapping is **TO VERIFY**.

## Preparation and identity checks

The historical preparation entry points are preserved below `scripts/frozen_workspace/outputs/PROJECT9_PHASE1/code/` and `scripts/frozen_workspace/work/merfish_preflight/`. An independent user should prepare each entry without altering observation order, gene order, coordinates, expression, or reference labels, then compare the resulting SHA-256 with `data/metadata/frozen_input_hashes.csv`. A mismatched hash means the object is not bit-identical to the locked benchmark input and must not be represented as an exact reproduction.

