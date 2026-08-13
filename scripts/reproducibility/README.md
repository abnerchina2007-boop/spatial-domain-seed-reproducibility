# Reproducibility and iso-accuracy

Core analyzers:

- Phase 1 `analyze_core.py`
- MERFISH `work/merfish_expansion/analyze_core.py`
- SEDR `work/sedr_expansion/analyze_scientific.py`

They implement direct within-unit seed-pair ARI/NMI, primary median pairwise
ARI, partition instability, the 0.01/0.02/0.03 iso-accuracy thresholds, and
co-association consensus. Final merging is performed by
`work/sedr_expansion/integrate_all_outputs.py`.

