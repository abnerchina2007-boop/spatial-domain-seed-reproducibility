# Third-party software and data notices

This repository contains project-authored orchestration, validation, analysis, and figure-generation code. It does not vendor the source code of GraphST, STAGATE, SpaGCN, BANKSY, SEDR, Scanpy, PyTorch, scikit-learn, R, mclust, or the public datasets. Install those dependencies from their upstream distributions and consult the upstream license text corresponding to the exact version used.

## Method software

| Dependency | Locked version or revision | Upstream | Recorded license status |
|---|---|---|---|
| GraphST | 1.1.1; `d62b0b7b6cd38ee285f3ac8cd67b7341a10bcc74` | <https://github.com/JinmiaoChenLab/GraphST> | **TO VERIFY:** package metadata says MIT, while the locked source snapshot's `LICENSE.md` contains AGPL-3.0 text. Treat AGPL-3.0 as the conservative assumption unless upstream clarifies. |
| STAGATE_pyG | package metadata 1.0.0; exact commit **TO VERIFY** | <https://github.com/zhanglabtools/STAGATE_pyG> | MIT in the locked source snapshot. |
| SpaGCN | 1.2.7; `dc7a1c26ea0fdf4dfe7064adc7699be141b4871f` | <https://github.com/jianhuupenn/SpaGCN> | MIT in package metadata and the locked source snapshot. |
| pybanksy / BANKSY | 1.3.5; exact source commit **TO VERIFY** | <https://github.com/prabhakarlab/Banksy_py> | GPL-3.0 in installed package metadata. |
| SEDR | 1.0.0; `ef4836059a4ea49be3bf7c67008a44ffc16a2a0e` | <https://github.com/JinmiaoChenLab/SEDR> | MIT in the locked source snapshot. |

The repository's own license does not replace, supersede, or relicense these dependencies. In particular, users installing or modifying GPL/AGPL components remain responsible for the corresponding upstream obligations. No third-party method source is included here.

## Other software

The environments also depend on Python, NumPy, SciPy, pandas, AnnData, Scanpy, scikit-learn, statsmodels, matplotlib, PyTorch, PyTorch Geometric, igraph, leidenalg, R, mclust, and rpy2. Each remains subject to its upstream license. Exact versions used by the locked environments are recorded in `environment.yml`, `requirements.txt`, and `envs/`.

## Public datasets

DLPFC, STARmap, HBCA1, and MERFISH data are third-party public datasets and are not redistributed. Their publications, repositories, annotations, and remaining provenance TODOs are listed in `data/README.md` and `docs/DATASETS.md`. Users must follow the original repositories' access terms, licenses, and citation requirements.
