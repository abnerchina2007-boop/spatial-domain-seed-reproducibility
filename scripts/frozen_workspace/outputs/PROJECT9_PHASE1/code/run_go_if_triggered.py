from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "tables"; CACHE = ROOT / "environment" / "marker_cache"
trigger_info = json.loads((TABLES / "marker_stable_vs_unstable_test.json").read_text())
if not trigger_info["go_enrichment_triggered_across_multiple_families"]:
    print("GO enrichment not triggered; go_enrichment.csv remains absent")
    raise SystemExit(0)

repro = pd.read_csv(ROOT / "marker_reproducibility.csv", dtype={"dataset": str})
domains = repro[(repro.record_type == "aligned_domain") &
                (repro.pair_type == "iso_accuracy_unstable") &
                (repro.dataset.str.fullmatch(r"151\d+"))]
representative = domains.sort_values(["top100_marker_jaccard", "dataset", "method", "aligned_consensus_domain"]).iloc[0]
dataset, method, domain = representative.dataset, representative.method, int(representative.aligned_consensus_domain)
selections = pd.read_csv(TABLES / "deterministic_pair_selection.csv", dtype={"dataset": str})
sel = selections[(selections.dataset == dataset) & (selections.method == method)]
queries = {}
for _, row in sel.iterrows():
    for side in ("r", "s"):
        seed = int(row[f"seed_{side}"])
        z = np.load(CACHE / f"{dataset}__{method}__seed{seed}__wilcoxon.npz", allow_pickle=True)
        q = int(np.flatnonzero(z["domains"] == domain)[0])
        genes = z["genes"].astype(str)[z["orders"][q, :100]].tolist()
        queries[f"{row.pair_type}__seed{seed}"] = genes

payload = {"organism": "hsapiens", "query": queries, "sources": ["GO:BP"],
           "user_threshold": 0.05, "significance_threshold_method": "fdr",
           "no_evidences": True}
response = requests.post("https://biit.cs.ut.ee/gprofiler/api/gost/profile/", json=payload, timeout=120)
response.raise_for_status()
items = response.json().get("result", [])
rows = []
for x in items:
    rows.append({"dataset": dataset, "method": method, "aligned_consensus_domain": domain,
                 "query": x.get("query"), "source": x.get("source"), "term_id": x.get("native"),
                 "term_name": x.get("name"), "adjusted_p_value": x.get("p_value"),
                 "intersection_size": x.get("intersection_size"), "term_size": x.get("term_size"),
                 "query_size": x.get("query_size"), "effective_domain_size": x.get("effective_domain_size"),
                 "resource": "GO Biological Process only", "service": "g:Profiler API"})
out = pd.DataFrame(rows)
out.to_csv(ROOT / "go_enrichment.csv", index=False)
sig_sets = {q: set(out.loc[out["query"] == q, "term_id"]) for q in queries}
overlap_rows = []
for pair_type in ("iso_accuracy_unstable", "stable_control"):
    names = [q for q in queries if q.startswith(pair_type)]
    a, b = sig_sets[names[0]], sig_sets[names[1]]
    overlap_rows.append({"pair_type": pair_type, "query_a": names[0], "query_b": names[1],
                         "n_significant_a": len(a), "n_significant_b": len(b),
                         "significant_term_jaccard": len(a & b) / max(len(a | b), 1)})
pd.DataFrame(overlap_rows).to_csv(TABLES / "supplementary_table_S6_go_term_overlap.csv", index=False)
print(json.dumps({"status": "complete", "representative": {"dataset": dataset, "method": method, "domain": domain},
                  "n_results": len(out), "term_overlap": overlap_rows}, indent=2))
