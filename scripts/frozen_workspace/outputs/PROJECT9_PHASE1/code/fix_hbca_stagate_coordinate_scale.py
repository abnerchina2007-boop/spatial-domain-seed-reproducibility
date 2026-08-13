from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
from sklearn.neighbors import NearestNeighbors

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "data" / "HBCA1" / "HBCA1_frozen.h5ad"
a = ad.read_h5ad(p)
xy = np.asarray(a.obsm["spatial_original"])
hbca_nn = float(np.median(NearestNeighbors(n_neighbors=2).fit(xy).kneighbors(xy)[0][:, 1]))
dlpfc = ad.read_h5ad(ROOT / "data" / "151507" / "151507_frozen.h5ad", backed="r")
dxy = np.asarray(dlpfc.obsm["spatial_original"])
dlpfc_nn = float(np.median(NearestNeighbors(n_neighbors=2).fit(dxy).kneighbors(dxy)[0][:, 1]))
dlpfc.file.close()
equivalent_radius = float(round(150.0 * hbca_nn / dlpfc_nn))
if equivalent_radius != 299.0:
    raise RuntimeError(f"Unexpected coordinate scaling result: {equivalent_radius}")
# Round to the nearest transparent benchmark-equivalent value. This produces
# the same radius/nearest-neighbor ratio as radius 150 in the DLPFC pixel grid.
config = dict(a.uns["phase1_dataset"])
config["stagate_radius"] = 300.0
config["stagate_radius_rationale"] = (
    "Benchmark radius 150 rescaled to the HBCA1 full-resolution coordinate grid: "
    "median nearest-neighbor distance 273 vs 137 in DLPFC; equivalent radius 299, rounded to 300."
)
a.uns["phase1_dataset"] = config
a.write_h5ad(p)
h = hashlib.sha256()
with p.open("rb") as f:
    for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
audit_path = ROOT / "data" / "HBCA1" / "mapping_audit.json"
audit = json.loads(audit_path.read_text())
audit["stagate_coordinate_scale_fix"] = {
    "reason": "radius 150 on full-resolution HBCA1 coordinates generated zero non-self edges",
    "dlpfc_median_nearest_neighbor": dlpfc_nn,
    "hbca1_median_nearest_neighbor": hbca_nn,
    "benchmark_equivalent_radius_unrounded": 150.0 * hbca_nn / dlpfc_nn,
    "frozen_radius_used": 300.0,
    "status": "documented implementation-error correction before evidence analysis"
}
audit["frozen_h5ad_sha256"] = h.hexdigest()
audit_path.write_text(json.dumps(audit, indent=2))
print(json.dumps(audit["stagate_coordinate_scale_fix"], indent=2))
