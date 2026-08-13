# Computational requirements

The recorded execution host ran Windows 10 build 10.0.26200 with Python 3.11.9. It had 16 physical and 32 logical AMD64 CPU cores, 31.3 GiB RAM, and one NVIDIA GeForce RTX 5060 Laptop GPU with 8,151 MiB memory, driver 582.05, and compute capability 12.0. The SEDR environment reported CUDA runtime 12.8. The CPU was recorded only as `AMD64 Family 25 Model 97 Stepping 2, AuthenticAMD`; a marketing model name is **TO VERIFY**.

These specifications describe the machine used, not a validated minimum. The frozen schedulers limited each process to four CPU threads. SEDR used one GPU worker. The MERFISH scheduler used one or two STAGATE jobs and later up to three lightweight jobs only after a throughput/memory test; the lowest observed free physical memory under that scheduler was 11.647 GiB. A preflight observed a maximum single-process peak RSS of approximately 7.89 GiB. A practical full-run system should therefore provide at least 16 GiB RAM, while approximately 32 GiB matches the tested host. This 16-GiB statement is a planning recommendation, not a formally benchmarked minimum.

The 380 SEDR checkpoints recorded 15,980.31 summed run-seconds, or 4.439 compute-hours, with a median of 40.295 seconds per checkpoint. Maximum measured SEDR peak memory was 2.591 GiB RAM and 349.2 MiB allocated GPU memory. Because one worker was used, summed compute time approximates the SEDR execution duration but excludes data preparation, validation, downstream analysis, and queue overhead.

The 400 MERFISH four-method checkpoints recorded approximately 93,827.25 summed run-seconds, or 26.063 compute-hours. This is not wall-clock time because jobs overlapped. Summed run time by method was approximately 63.10 seconds for BANKSY, 6,070.39 seconds for GraphST, 2,449.09 seconds for SpaGCN, and 85,244.67 seconds for STAGATE. The complete standalone MERFISH environment freeze and exact end-to-end wall-clock time are **TO VERIFY**.

A clean, duplication-free wall-clock summary for the original DLPFC/STARmap/HBCA1 four-method panel was not retained. Its end-to-end runtime is therefore **TO VERIFY** and must not be inferred by summing logs that include retries, quarantine runs, or duplicated panels. The full 1,900-run benchmark should be expected to require substantial time, and the compact source-data route is recommended for routine review and figure/statistical reproduction.

Disk requirements depend mainly on third-party inputs and optional predictions/checkpoints, none of which are included. The public source-data CSVs are small. GPU use is most relevant to GraphST and SEDR; BANKSY and SpaGCN were CPU-bound in the frozen four-method runner. Device behavior for STAGATE varied with the execution panel. Consult `envs/README.md` before installation.

