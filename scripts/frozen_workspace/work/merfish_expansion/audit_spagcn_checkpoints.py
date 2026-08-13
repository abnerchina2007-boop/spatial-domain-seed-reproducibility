from __future__ import annotations

import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd


WORKSPACE = Path(__file__).resolve().parents[2]
ROOT = WORKSPACE / "outputs" / "PROJECT9_MERFISH_EXPANSION"
SECTIONS = [
    "MERFISH_Bregma_m0.04", "MERFISH_Bregma_m0.09", "MERFISH_Bregma_m0.14",
    "MERFISH_Bregma_m0.19", "MERFISH_Bregma_m0.24",
]


def main() -> None:
    rows = []
    for section in SECTIONS:
        input_path = ROOT / "data" / section / f"{section}_frozen.h5ad"
        base = ad.read_h5ad(input_path, backed="r")
        names = np.asarray(base.obs_names.astype(str))
        base.file.close()
        for seed in range(1, 21):
            stem = ROOT / "predictions" / section / f"SpaGCN__seed{seed}__primary"
            csv_path, json_path = stem.with_suffix(".csv"), stem.with_suffix(".json")
            record = {
                "section": section,
                "method": "SpaGCN",
                "seed": seed,
                "artifact_present": csv_path.exists() and json_path.exists(),
                "requested_K": 8,
                "pre_refinement_observed_K": pd.NA,
                "post_refinement_observed_K": pd.NA,
                "refinement_cluster_count_reduced": pd.NA,
                "one_label_per_expected_cell": False,
                "cell_order_matches": False,
                "all_labels_finite": False,
                "metadata_readable": False,
                "technically_valid_amended_rule": False,
            }
            if record["artifact_present"]:
                try:
                    metadata = json.loads(json_path.read_text(encoding="utf-8"))
                    prediction = pd.read_csv(csv_path, dtype={"barcode": str})
                    labels = pd.to_numeric(prediction["cluster"], errors="coerce").to_numpy()
                    observed = int(np.unique(labels).size) if np.isfinite(labels).all() else pd.NA
                    record.update({
                        "pre_refinement_observed_K": metadata.get("pre_refinement_observed_K", pd.NA),
                        "post_refinement_observed_K": observed,
                        "refinement_cluster_count_reduced": observed < 8 if observed is not pd.NA else pd.NA,
                        "one_label_per_expected_cell": len(prediction) == len(names),
                        "cell_order_matches": np.array_equal(prediction["barcode"].to_numpy(str), names),
                        "all_labels_finite": bool(np.isfinite(labels).all()),
                        "metadata_readable": True,
                    })
                    record["technically_valid_amended_rule"] = bool(
                        metadata.get("status") == "PASS"
                        and record["one_label_per_expected_cell"]
                        and record["cell_order_matches"]
                        and record["all_labels_finite"]
                        and metadata.get("n_clusters_observed") == observed
                    )
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    pass
            rows.append(record)

    audit = pd.DataFrame(rows)
    audit.to_csv(ROOT / "SPAGCN_RETROSPECTIVE_TECHNICAL_AUDIT.csv", index=False)
    present = audit[audit["artifact_present"]]
    summary = {
        "status": "PASS" if bool(present["technically_valid_amended_rule"].all()) else "FAIL",
        "completed_spagcn_artifacts": int(len(present)),
        "retained_valid_spagcn_checkpoints": int(present["technically_valid_amended_rule"].sum()),
        "invalid_completed_spagcn_checkpoints": int((~present["technically_valid_amended_rule"]).sum()),
        "observed_post_refinement_collapses_in_persisted_merfish_artifacts": int(
            (present["post_refinement_observed_K"] < 8).sum()
        ),
        "completed_checkpoints_with_historical_pre_refinement_K": int(
            present["pre_refinement_observed_K"].notna().sum()
        ),
        "missing_spagcn_artifacts": int((~audit["artifact_present"]).sum()),
        "scientific_metrics_computed": False,
    }
    (ROOT / "SPAGCN_RETROSPECTIVE_TECHNICAL_AUDIT.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
