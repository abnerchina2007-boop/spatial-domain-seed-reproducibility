# Repository audit

Audit date: 2026-08-13  
Scope: original Project 9 working directory and the isolated public repository  
Scientific execution: none

## Executive assessment

The original directory was a complete private analysis workspace, not a safe
GitHub repository. It contained 41,720 files totaling about 15.9 GB, including
raw/frozen public datasets, local environments, downloaded method source trees,
per-seed predictions, checkpoints, logs, caches, render scratch files, and
superseded publication artifacts. Nothing was deleted from that workspace.

The public repository was assembled separately from reviewed project-authored
scripts, frozen configurations/protocols, final derived source-data tables, and
PDF/PNG comparison figures. Large datasets, operational state, private paths,
and third-party source trees were excluded.

## Original directory classes

| Class | Examples | Public treatment |
|---|---|---|
| Project source code | Phase 1 runners/analyzers; final MERFISH and SEDR scripts; final figure/table builders | Included as reviewed snapshots, organized by workflow |
| Configurations/protocols | frozen MERFISH/SEDR protocols; method settings | Included or summarized |
| Raw/frozen data | H5AD/H5/RData inputs | Excluded; public acquisition documented |
| Seed outputs | predictions, labels, embeddings | Excluded because large and unnecessary for source-data review |
| Scientific intermediate outputs | pair matrices, marker caches, queue checkpoints | Excluded; compact validated summaries included |
| Final source data | 27 figure CSVs, 5 table CSVs, integrated tables | Included |
| Final figures | PDF/SVG/TIFF/PNG | PDF and PNG included; SVG/TIFF omitted to limit duplication |
| Logs/state | scheduler logs, PIDs, lock/state files, crash attempts | Excluded as operational/private provenance |
| Environments | `.venv`, copied packages, `node_modules` | Excluded; version manifests converted to environment files |
| Third-party sources | GraphST/STAGATE/SpaGCN/BANKSY/SEDR checkouts; BenchmarkST | Excluded; install from upstream and observe their licenses |
| Draft/superseded code | old Figure 4/5/6 rebuild scripts and pre-MERFISH archives | Excluded; listed below, not deleted |

## Authoritative code lineage

- Original four-method benchmark: `prepare_dlpfc.py`, `prepare_external.py`,
  `run_seed_panel.py`, `analyze_core.py`, `analyze_markers.py`, and validators
  from the locked Phase 1 code snapshot.
- MERFISH extension: the post-amendment scripts in the private
  `work/merfish_expansion` lineage. Earlier copies under the expansion output
  directory were superseded because they rejected valid SpaGCN
  refinement-induced reductions in observed K.
- SEDR extension: the frozen protocol, one-checkpoint runner, technical
  validator, guarded queue/gate, scientific analyzer, marker analyzer,
  five-method ranking, and final integration scripts.
- Final presentation: the five-method final figure wrapper plus its candidate
  main/supplementary builders, and the final table-source builder.

`MANIFEST.md` maps every public code snapshot to its private source path and
records any portability-only change.

## Main result generators

- Reference ARI/NMI, 190 within-unit seed pairs, iso-accuracy thresholds, and
  consensus summaries: platform-specific core analyzers.
- Marker top-100 Jaccard, top-50 sensitivity, full-rank Spearman, and tertiles:
  platform-specific marker analyzers.
- Exact empirical ranks: five-method ranking analyzer using the full
  `20^5` Cartesian distribution per dataset and frozen tie rules.
- Figures 1–5 and S1–S8: final figure builder and two source builders, mapped
  exactly in `docs/OUTPUTS.md`.
- Tables 1 and S1–S4: final table-source builder.

## Absolute paths and machine dependence

The private workspace contained a personal Windows path in 2,649 files, mostly
logs and checkpoint/provenance records. Those files were not copied. Selected
publication scripts were checked again after copying. The SEDR runner's fixed
workstation R path was replaced in the public copy by the standard `R_HOME`
environment variable; its R version, mclust model, seed, requested K, and
scientific behavior were unchanged.

GPU method execution remains environment-dependent. The exact recorded
hardware/software combination is documented, while portable installation uses
separate environments. STAGATE and BANKSY exact upstream Git commits were not
recoverable from the locked environment and are marked `TO VERIFY`.

## Credentials and private information

No private-key header, recognized API/GitHub/OpenAI token, JWT, or password
assignment was found in the original pattern scan. That negative finding did
not make the original tree publishable: it still contained personal paths,
Office author metadata, operational logs, and downloaded materials. The final
repository was subjected to a separate fail-closed scan before staging.

## Large files

The original tree had 143 files over 10 MiB and 73 over 50 MiB. The major
classes were raw/technical data, environment binaries, caches/intermediates,
and archives. No file over 10 MiB is intentionally included in the publication
repository.

## Superseded or uncertain files retained privately

Examples include `analysis_fig4_upgrade.py`, `analysis_fig5_upgrade.py`, old
Figure 6 redesign scripts, pre-MERFISH archives, candidate render directories,
queue recovery utilities, and document-render scratch code. Their purposes were
audited where possible. They were not deleted merely because they were old or
uncertain; they were omitted because the locked five-method workflow supersedes
them or because they are internal operational provenance.

## Licensing review

No third-party source is vendored. GraphST's reviewed checkout had an AGPL-3.0
license file while package metadata claimed MIT; BANKSY/pybanksy is GPL-3.0;
STAGATE and SEDR were MIT in reviewed sources; SpaGCN package metadata stated
MIT but its complete upstream license artifact was not retained. These issues
are disclosed in `THIRD_PARTY_NOTICES.md`. The repository-level MIT license
applies only to project-authored material, not external dependencies or data.

## Validation conclusion

The public snapshot preserves the frozen settings and matches the validated
submission results. Repository preparation found no scientific discrepancy.
Unresolved metadata and portability limitations are documented rather than
guessed.
