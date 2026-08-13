# Code provenance and layout

The authoritative scripts are preserved below `scripts/frozen_workspace/` in
the relative layout used by the completed project. Keeping this layout avoids
rewriting path-sensitive analysis code merely to make the repository look
flatter. Category-level guides point reviewers to the relevant scripts.

## Frozen workspace map

| Public path | Private authoritative lineage | Purpose |
|---|---|---|
| `outputs/PROJECT9_PHASE1/code/` | locked Phase 1 code snapshot | DLPFC/STARmap/HBCA1 preparation; GraphST, STAGATE, SpaGCN, BANKSY seed execution; original core/marker analysis |
| `work/merfish_preflight/` | final MERFISH preflight utilities | BASS section export and frozen H5AD preparation |
| `work/merfish_expansion/` | post-amendment final work scripts | MERFISH execution, queue, analysis, marker, validation, reporting |
| `work/sedr_expansion/` | final SEDR locked pipeline | technical views, checkpoint runner, queue/gate, SEDR science, markers, exact five-method rankings, integration, QC |
| `work/final_five_method_package/` | final publication figure builder | final Figures 1–5 and S1–S8 |
| `work/five_method_final_tables/` | final table pipeline | final table CSV/Word generation and QC |
| `work/five_method_final_package/` | final legends/supplement pipeline | presentation assembly and validation |

Earlier output-directory copies of the MERFISH runner/analyzers were not used:
they predated the formal SpaGCN refinement amendment. The public snapshot uses
the final `work/merfish_expansion` versions.

## Portability-only modification

The public copy of
`work/sedr_expansion/run_sedr_checkpoint.py` obtains the R installation from
the standard `R_HOME` environment variable instead of embedding one
workstation-specific drive path. R 4.3.1, mclust 6.1.3, the single EEE call,
requested K, seeds, preprocessing, graph, architecture, epochs, and output
validation are unchanged. No other scientific logic was intentionally edited.

## Hashes

`docs/CODE_HASHES.tsv` contains SHA-256 hashes for every published Python/R
source file after the portability edit. The upstream/original SHA and the exact
publication-edit statement for the SEDR runner are retained in the private
audit; the release hash is the public integrity authority.

## Navigation by scientific task

- Preprocessing: Phase 1 `prepare_*.py`, MERFISH preflight, SEDR
  `prepare_technical_views.py`.
- Method execution: Phase 1 `run_seed_panel.py`, MERFISH `run_seed.py`, SEDR
  `run_sedr_checkpoint.py`.
- Direct reproducibility/iso-accuracy/consensus: the three `analyze_core.py` or
  `analyze_scientific.py` scripts.
- Markers: the three marker analyzers.
- Rankings: SEDR expansion `analyze_five_method.py`.
- Five-method integration: `integrate_all_outputs.py`.
- Figures/tables: final package/table directories above.

Operational resume scripts are included because they encode checkpoint and
scientific-gate provenance. They are not the recommended reviewer entry point;
use `scripts/run_full_analysis.py` for safe planning and validation.

