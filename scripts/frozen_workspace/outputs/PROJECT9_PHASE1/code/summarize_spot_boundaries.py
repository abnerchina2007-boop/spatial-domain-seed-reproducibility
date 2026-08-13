from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors

ROOT = Path(__file__).resolve().parents[1]
DLPFC = ["151507", "151508", "151509", "151510", "151669", "151670",
          "151671", "151672", "151673", "151674", "151675", "151676"]
spots = pd.read_csv(ROOT / "spot_stability.csv", dtype={"dataset": str, "barcode": str}, low_memory=False)
rows = []
for dataset in DLPFC:
    a = ad.read_h5ad(ROOT / "data" / dataset / f"{dataset}_frozen.h5ad")
    ref = a.obs.manual_layer.astype(str).to_numpy(); valid = a.obs.manual_layer.notna().to_numpy()
    ind = NearestNeighbors(n_neighbors=7).fit(a.obsm["spatial"]).kneighbors(return_distance=False)
    boundary = np.array([valid[i] and any(valid[j] and ref[j] != ref[i] for j in ind[i, 1:]) for i in range(a.n_obs)])
    for method in spots[spots.dataset == dataset].method.unique():
        g = spots[(spots.dataset == dataset) & (spots.method == method)]
        support = g.consensus_support.to_numpy()
        rows.append({"dataset": dataset, "method": method,
                     "manual_boundary_n": int(boundary.sum()), "interior_n": int((valid & ~boundary).sum()),
                     "median_support_manual_boundary": float(np.median(support[boundary])),
                     "median_support_interior": float(np.median(support[valid & ~boundary])),
                     "low_support_le_0.5_at_boundary_n": int(((support <= .5) & boundary).sum()),
                     "low_support_le_0.5_interior_n": int(((support <= .5) & valid & ~boundary).sum()),
                     "interpretation": "descriptive nearest-neighbor manual-layer boundary overlay; no formal test"})
pd.DataFrame(rows).to_csv(ROOT / "tables" / "spot_boundary_descriptive_summary.csv", index=False)
print(pd.DataFrame(rows)[["median_support_manual_boundary", "median_support_interior"]].median().to_string())
