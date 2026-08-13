# Security, privacy, path, and size audit draft

Status: pre-publication draft based on a read-only audit of the original working
directory. This document contains no secret values. It is not a final attestation
for the assembled public repository; the repository-only scanner must still pass
immediately before staging and again in CI.

## Scope and method

The original Project 9 working directory was inspected recursively without
modifying files and without running scientific analyses. The audit covered:

- common API-key, access-token, JWT, password, and private-key patterns;
- credential-like filenames and nested Git metadata;
- Windows, macOS, and Linux personal absolute paths;
- Office Open XML content and document core properties;
- files larger than 10 MiB and 50 MiB;
- raw data, predictions, checkpoints, logs, caches, environments, temporary
  files, downloaded third-party code, and superseded artifacts.

The original directory contained 41,720 files totaling approximately 15.9 GB.
There were 143 files larger than 10 MiB (approximately 12.78 GB) and 73 files
larger than 50 MiB (approximately 11.43 GB).

## Credential and privacy findings

No private-key header, recognized cloud/GitHub/OpenAI-style token, JWT, or
quoted password/secret assignment was found by the pattern scans. No credential
configuration file such as `.npmrc`, `.pypirc`, `.netrc`, private-key file, or
cookie database was found outside dependency-package filename collisions.
Nested Git remotes did not contain embedded user information or tokens.

This negative result is not permission to publish the original directory. A
personal Windows absolute path appeared in 2,649 files. One classification pass
grouped these as approximately 2,202 log files, 395 checkpoint files, 27
provenance/state files, 17 code or notebook files, and 8 other files. (Some
artifacts fit more than one semantic category; the total file count is the
authoritative quantity.) These files reveal a local username and directory
layout and must not be copied verbatim into the public repository.

Seventeen files contained email-shaped strings. Sixteen were downloaded
publication or literature metadata and one was reference-audit code. They were
not identified as credentials, but downloaded full text and literature scraping
artifacts are excluded because they are unnecessary and may have licensing or
privacy implications.

Forty-four Office files were inspected internally. No secret pattern, personal
absolute path, or email address was found in their XML. Thirty-one contained
creator or last-modifier core properties; fifteen used non-default values.
Original Office deliverables should therefore not be published unless their
metadata is deliberately reviewed and sanitized. The public code-and-source-data
repository does not require those Office files.

## High-risk material excluded from the public repository

The following original paths or path classes are excluded. They remain preserved
in the private working directory.

| Risk | Original path or class | Reason for exclusion |
| --- | --- | --- |
| Critical | `work/sedr_expansion/.venv/` | Local environment, compiled binaries, machine-specific paths; approximately 4.66 GB. |
| Critical | `work/*/node_modules/` | Generated dependencies; three copies of approximately 303 MB each. |
| Critical | `outputs/PROJECT9_PHASE0/data/` | Raw/frozen and processed third-party data; approximately 1.09 GB. |
| Critical | `outputs/PROJECT9_PHASE1/data/` | Raw/frozen and processed third-party data; approximately 1.56 GB. |
| Critical | `outputs/PROJECT9_MERFISH_EXPANSION/data/` and `outputs/PROJECT9_MERFISH_PREFLIGHT/source_data/` | Third-party MERFISH inputs. |
| Critical | `outputs/PROJECT9_SEDR_EXPANSION/technical_inputs/` | Large derived technical inputs; approximately 240 MB. |
| Critical | `work/candidate_A/` and `work/candidate_B/` | Downloaded candidate datasets, partial transfers, and raw imagery; candidate A alone is approximately 3.14 GB. |
| High | `outputs/**/predictions/` and `outputs/**/checkpoints/` | Per-seed predictions/checkpoints; unnecessary for the lightweight public source-data release and contain local paths. |
| High | `outputs/**/logs/`, `work/**/smoke_logs/`, queue-state, PID, and lock files | Operational history, failures, process state, and local paths. |
| High | `outputs/**/environment/*cache*/`, analysis checkpoints, marker caches, and `__pycache__/` | Reconstructable intermediate/cache data, including multi-hundred-MB arrays. |
| High | `outputs/PROJECT9_PHASE*/environment/sources/` | Downloaded third-party source trees and nested `.git` histories; not owned publication code. |
| High | `outputs/PROJECT9_PHASE*/environment/python_packages/` | Vendored package copies with independent licenses. |
| High | `work/benchmark_st_repo/` and `work/sedr_audit/` | Downloaded third-party repositories; one lacks a verified top-level license and both are unnecessary to vendor. |
| High | `outputs/PROJECT9_FINAL_PUBLICATION_PACKAGE/archive_preMERFISH/` and other `old`, `draft`, `candidate`, or `superseded` files | Obsolete submission artifacts and possible author metadata. |
| High | `work/mendeley_page.html`, `work/mendeley_bundle.js`, downloaded full-text XML/TXT, and literature-scraping packets | Downloaded web/application content; unnecessary, potentially copyrighted, and not provenance-ready. |
| Medium | ZIP, TAR, partial-download, render-scratch, LibreOffice-profile, crash-dump, and temporary files | Bundled or transient material that is not source code or manuscript source data. |

Large-file categories in the original directory were dominated by approximately
5.9 GB of raw/technical data, 4.1 GB of environment binaries, 2.1 GB of cache or
intermediate arrays, and 0.46 GB of archives among files larger than 10 MiB.

## Files requiring safe path parameterization

Only a reviewed copy of any needed script may enter the public repository. At a
minimum, the following original scripts contain local or system-specific paths
and require CLI arguments, configuration entries, relative paths, or environment
variables without changing any scientific setting:

- `work/analysis_fig4_upgrade.py:21`
- `work/analysis_fig5_upgrade.py:20`
- `work/build_docx.py:16`
- `work/build_manuscript.py:25-27`
- `work/capture_manuscript_hashes.py:10-11`
- `work/capture_project9_model_tree_hashes.py:10`
- `work/edit_docx_tables_qc.py:6`
- `work/final_five_method_package_qc.py:23`
- `work/final_publication_package/build_workbook.mjs:3,5`
- `work/final_publication_package/convert_docx_lo.ps1:2,18-19`
- `work/final_publication_package/corrections_baseline/create_baseline.py:13`
- `work/final_publication_package/render_word.ps1:2`
- `work/final_publication_package/table_qc_final/create_contact_sheets.py:15-16`
- `work/final_publication_package/table_qc_final/render_tables.ps1:6-7,18`
- `work/five_method_final_tables/build_final_workbook.mjs:5`
- `work/merfish_expansion/build_tables.mjs:5`
- `work/spreadsheet/build_tables.mjs:8`
- `work/spreadsheet/edit_tables_qc.mjs:4`
- `work/sedr_expansion/run_sedr_checkpoint.py:275-277` (hard-coded R home and binary directories)

Most scripts in the authoritative Phase 0, Phase 1, MERFISH, and SEDR execution
chains did not contain the personal user path. That does not eliminate their need
for dependency, input/output, and license review before copying.

## Candidate material that was safe in the original audit

The final five-method package contained 27 figure source-data files totaling
approximately 4.8 MB and six table source-data files totaling approximately
0.08 MB. Those directories had no secret-pattern or personal-path hit and no
file larger than 10 MiB. They are suitable candidates for publication after
the assembled repository passes the final scanner. This statement applies only
to those reviewed source-data files, not to the surrounding publication archive.

## Public-repository scanner

Run this command only against the assembled public repository:

```bash
python scripts/validation/security_scan.py
```

The scanner fails with a nonzero exit status for suspected secrets, private-key
headers, credential-like filenames, personal absolute paths, files over 10 MiB,
raw-data/checkpoint binary extensions, logs, caches, temporary files, nested
`.git` directories, dependency/vendor trees, or unreadable files. It reports
only rule names and paths; it never prints matched content.

Before publication, also review the exact staged set (`git diff --cached --name-only`)
and run an independent history-aware secret scanner after Git initialization.
No statement that the repository is secret-free or publicly visible should be
made until both the repository-only scan and the staged/history checks pass.
