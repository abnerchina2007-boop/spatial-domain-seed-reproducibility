# Frozen SEDR stochastic-method coverage-expansion protocol

**Decision:** `LOCK_ADD_SEDR`  
**State at lock:** all scientific SEDR outcomes blinded  
**Target:** 19 entries × 20 seeds = 380 technically valid SEDR checkpoints

## 1. Authoritative implementation

- Repository: `https://github.com/JinmiaoChenLab/SEDR`
- Package version: `1.0.0`
- Commit: `ef4836059a4ea49be3bf7c67008a44ffc16a2a0e`
- Official repository has no Git tags or GitHub releases; the commit above is the immutable pin of the current peer-reviewed-generation official workflow.
- Primary representation path: official `SEDR.Sedr(..., mode="clustering")` with DEC.
- Final readout: one official-equivalent R `mclust::Mclust` call, `modelNames="EEE"`, `G=project K`.

## 2. Environment and compatibility lock

- Python 3.11.9; NumPy 1.26.4; SciPy 1.13.1; pandas 2.2.3; scikit-learn 1.5.2; scikit-misc 0.5.2; Scanpy 1.10.4; AnnData 0.10.9.
- PyTorch 2.11.0+cu128; CUDA runtime 12.8; NVIDIA RTX 5060 Laptop GPU.
- R 4.3.1; mclust 6.1.3; rpy2 3.5.17.
- The official developer-local Linux `R_HOME` assignment is externalized to `D:\R\R4.3.1`; its `bin\x64` directory is prepended to `PATH`.
- The official rpy2 array handoff is implemented by an explicit numeric R matrix and a named R wrapper solely for Windows/rpy2 compatibility. The called method, EEE model, requested K, and single-call rule are unchanged.
- The current PyTorch compatibility patch changes the official float index dtype to `torch.long` and `torch.range` to `torch.arange`; the exact sampled integer values/order used by the official code are preserved.
- PyTorch deterministic algorithms are enforced and TF32 is disabled to implement the official deterministic-backend intent on this host. This changes no architecture, graph, loss, epoch, seed, or clustering parameter.

## 3. Frozen inputs and identity firewall

The 19 frozen source hashes, observation-order hashes, dimensions, platform classes, and technical-view hashes are those in `SEDR_INPUT_STRUCTURAL_AUDIT.manifest.json` and `technical_inputs/TECHNICAL_INPUT_MANIFEST.json`. Both manifests passed 19/19 before lock.

Technical training reads only the label-blind technical H5ADs. Each contains:

- frozen `layers/counts` values as `X`;
- the exact ordered observation index;
- the exact ordered gene index;
- frozen `obsm/spatial`;
- no observation annotation columns and no reference labels.

No observation filtering is permitted. Source hashes and observation-order hashes must be revalidated at every run.

## 4. Entries, K, and seeds

- DLPFC `151507`, `151508`, `151509`, `151510`, `151669`, `151670`, `151671`, `151672`, `151673`, `151674`, `151675`, `151676`: K=7.
- `STARmap_20180505_BY3_1k`: K=7.
- `HBCA1`: K=20.
- `MERFISH_Bregma_m0.04`, `m0.09`, `m0.14`, `m0.19`, `m0.24`: K=8.
- Seeds: integers 1–20 exactly once per entry.

## 5. Representation preprocessing

### Visium (12 DLPFC entries and HBCA1)

Starting from frozen counts, preserve all observations. Apply official gene-only filters `min_cells=50`, then `min_counts=10`; normalize total to 1,000,000; do not log-transform; select 2,000 HVGs with `flavor="seurat_v3"` on the count layer; subset to those HVGs; apply Scanpy scaling defaults; run sklearn PCA with `n_components=min(200, retained_genes−1, observations−1)` and `random_state=42`.

### STARmap and MERFISH

Preserve the complete frozen valid gene panel (1,020 for STARmap and 155 for each MERFISH section); normalize total to 1,000,000; do not log-transform; use no fabricated HVG selection; apply Scanpy scaling defaults; run sklearn PCA with `n_components=min(200, retained_genes−1, observations−1)` and `random_state=42`.

PCA randomness is fixed and is not the experimental perturbation.

## 6. Spatial graph

Use the official Euclidean KNN graph: full pairwise coordinate distances, nearest neighbors excluding self, undirected union symmetrization, and official normalized adjacency/self-loop handling.

- Visium: 12 nearest spatial neighbors.
- STARmap/MERFISH: 6 nearest spatial neighbors.

No graph search or sensitivity analysis is allowed. Record edge count, isolates, connected components, and graph hash.

## 7. Training

Use official clustering mode with DEC enabled. Preserve official defaults:

- feature encoder 64→16; GCN hidden 64; GCN outputs 16+16; concatenated latent dimension 32;
- dropout 0.2; SCE alpha 3; internal DEC K=10; mask rate 0.8;
- reconstruction weight 10; GCN weight 0.1; self-construction weight 1; DEC-KL weight 1;
- Adam, learning rate 0.01, weight decay 0.01;
- internal DEC-init KMeans K=10, `n_init=20`, `random_state=42`;
- DEC interval 20 and tolerance 0.00.

The canonical official path runs 200 pretraining optimizer epochs and 200 DEC optimizer epochs (400 total), because `train_with_dec(epochs=200)` first calls the default 200-epoch `train_without_dec()` and then runs 200 DEC epochs. Do not reinterpret this as 200 total or alter internal DEC K to the final project K.

## 8. RNG propagation

Before interpreter/CUDA initialization set `PYTHONHASHSEED=run_seed` and `CUBLAS_WORKSPACE_CONFIG=:4096:8`. Set Python random and NumPy seeds; call official `SEDR.fix_seed(run_seed)`; set PyTorch CPU, CUDA, and CUDA-all seeds; use deterministic backends. Immediately before the single mclust call set R `set.seed(run_seed)`. The same seed controls the full run.

## 9. Final readout and technical validity

Call mclust exactly once on the finite 32-dimensional SEDR embedding with `G=project K` and fixed model `EEE`. Do not search K or model family, refit, or select among valid results. A normally completed finite output remains valid even if observed K differs from requested K.

A checkpoint is valid only when it has:

- exact input/protocol/observation-order hashes;
- all 200+200 epochs completed;
- one finite 32-dimensional embedding row per frozen observation;
- exactly one normally returned finite label per frozen observation;
- exactly one mclust call;
- atomic `labels.csv` and `checkpoint.json` with hashes and technical metadata.

Final-run embeddings are optional; labels and metadata are mandatory.

## 10. Retry, checkpoint, and scheduler policy

Use atomic temporary writes. Never overwrite a valid checkpoint. Skip only a checkpoint that passes the strict outcome-blind validator under this exact protocol and input hash. On a process/system crash, preserve logs and allow one bounded identical retry; accept the first normally completed finite result. Do not retry a valid run to obtain preferred labels or K.

Run one GPU training process at a time with four CPU threads. The technical smoke median was approximately 32 seconds/run and peak measured use was about 2.55 GiB RAM and 0.35 GiB allocated GPU memory. No two-worker throughput gate was requested after one-worker feasibility was established; the frozen scheduler remains one worker.

## 11. Scientific firewall and 380/380 gate

Until an independent strict scan validates all 380 expected entry/seed checkpoints:

- do not load reference annotations;
- do not compute, inspect, print, plot, serialize, or summarize reference ARI/NMI, different-seed partition agreement, instability, iso-accuracy, maps, ranks, markers, consensus, or biological interpretation;
- do not visually inspect cluster labels or embeddings.

Only after 380/380 may an atomic `SCIENTIFIC_GATE_OPEN.json` be written with this protocol hash and the complete checkpoint-manifest hash. Scientific scripts must independently revalidate both before loading references.

## 12. Prespecified post-gate analyses

After the gate only, inherit the existing Project 9 definitions unchanged:

- reference ARI/NMI; 190 unordered seed pairs per SEDR entry; partition instability `1−median pairwise ARI`;
- low-SD/high-instability rule: reference ARI SD ≤0.02 and instability ≥0.30;
- iso-accuracy primary absolute ARI difference ≤0.02, with only 0.01/0.03 frozen sensitivities;
- marker universe independent of SEDR representation genes; normalize total 10,000, log1p, Scanpy Wilcoxon versus rest, `use_raw=False`, `tie_correct=False`; domains aligned to the 20-seed SEDR consensus by maximum-overlap Hungarian assignment; top-100 primary, top-50 and full-rank Spearman sensitivity;
- within-entry Spearman and deterministic equal-count low/middle/high tertiles; one-sided paired high>low Wilcoxon if estimable;
- unweighted 20-seed co-association consensus, `D=1−C`, average-linkage agglomeration at project K; full 20 seeds and split halves 1–10 versus 11–20;
- exact five-method empirical ranking by streaming all `20^5=3,200,000` combinations per entry; average midranks for ties; tied maxima divide rank-1 credit equally; combinations are not inferential observations.

Filtering integrated outputs back to GraphST/STAGATE/SpaGCN/BANKSY must reproduce locked four-method sources within exact/floating tolerance. Existing files are never overwritten.

## 13. HBCA1 provenance

HBCA1's 20-region reference was manually defined in the original SEDR study from H&E/pathological features; it is not SEDR clustering output and is not a circular clustering reference. Record prior developer–dataset exposure when interpreting cross-method reference accuracy. Do not exclude, downweight, retune, or remove HBCA1.

## 14. Outcome-independent commitment

Technical smoke passed 4/4 regimes and identical-seed partitions passed 2/2 with ARI=1.0. No SEDR scientific outcome was inspected before this lock. SEDR is therefore committed regardless of later stability, accuracy, ranking, marker, or consensus results. No scientific threshold may change and no valid seed may be removed because of its result.
