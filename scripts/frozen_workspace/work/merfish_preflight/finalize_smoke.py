from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


WORKSPACE = Path(__file__).resolve().parents[2]
LOG_ROOT = WORKSPACE / "work" / "merfish_preflight" / "smoke_logs"
OUTPUT = WORKSPACE / "outputs" / "PROJECT9_MERFISH_PREFLIGHT"
SECTIONS = [
    "MERFISH_Bregma_m0.04", "MERFISH_Bregma_m0.09", "MERFISH_Bregma_m0.14",
    "MERFISH_Bregma_m0.19", "MERFISH_Bregma_m0.24",
]
METHODS = ["GraphST", "STAGATE", "SpaGCN", "BANKSY"]
PROHIBITED_SCIENTIFIC_KEYS = {
    "reference_ari", "reference_nmi", "pairwise_partition_ari", "pairwise_partition_nmi",
    "instability", "marker_jaccard", "rank", "consensus_reference_ari",
}


def main() -> None:
    records = []
    failures = []
    for section in SECTIONS:
        for method in METHODS:
            path = LOG_ROOT / f"{section}__{method}__seed1.json"
            if not path.exists():
                failures.append(f"missing {path.name}")
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            actual_keys = set(record)
            prohibited = sorted(actual_keys & PROHIBITED_SCIENTIFIC_KEYS)
            checks = (
                record.get("status") == "PASS"
                and record.get("seed") == 1
                and record.get("epochs") == 200
                and record.get("n_clusters_observed") == 8
                and record.get("required_K") == 8
                and record.get("cluster_count_matches_K") is True
                and record.get("labels_finite") is True
                and record.get("label_length_matches_cells") is True
                and record.get("scientific_reference_metrics_computed") is False
                and record.get("scientific_reference_metrics_inspected") is False
                and record.get("prediction_map_saved") is False
                and not prohibited
            )
            if not checks:
                failures.append(f"invalid {path.name}; prohibited_keys={prohibited}")
            records.append(record)
    if failures or len(records) != 20:
        raise RuntimeError(f"Smoke panel is not a valid 20-run outcome-blind panel: {failures}")

    frame = pd.DataFrame(records)
    rows = []
    for method in METHODS:
        group = frame[frame.method == method]
        serial_seconds = float(group.elapsed_seconds.sum() * 20)
        estimated_prediction_bytes = int(np.sum(group.n_cells.to_numpy() * 90 * 20))
        rows.append({
            "method": method,
            "sections": 5,
            "seeds_per_section": 20,
            "full_runs": 100,
            "smoke_median_seconds_per_run": float(group.elapsed_seconds.median()),
            "smoke_min_seconds_per_run": float(group.elapsed_seconds.min()),
            "smoke_max_seconds_per_run": float(group.elapsed_seconds.max()),
            "projected_serial_compute_hours": serial_seconds / 3600,
            "projected_two_slot_wall_hours_if_balanced": serial_seconds / 7200,
            "observed_peak_rss_gib": float(group.peak_rss_gib.max()),
            "observed_peak_vram_gib": float(group.peak_cuda_allocated_gib.max()),
            "observed_devices": ";".join(sorted(set(group.device.astype(str)))),
            "cpu_threads_per_run": 4,
            "max_concurrent_runs": 2,
            "projected_prediction_csv_gib": estimated_prediction_bytes / (1024 ** 3),
        })
    estimate = pd.DataFrame(rows)
    total_serial = float(estimate.projected_serial_compute_hours.sum())
    estimate.loc[len(estimate)] = {
        "method": "TOTAL_400_RUN_PANEL",
        "sections": 5,
        "seeds_per_section": 20,
        "full_runs": 400,
        "smoke_median_seconds_per_run": np.nan,
        "smoke_min_seconds_per_run": np.nan,
        "smoke_max_seconds_per_run": np.nan,
        "projected_serial_compute_hours": total_serial,
        "projected_two_slot_wall_hours_if_balanced": total_serial / 2,
        "observed_peak_rss_gib": float(frame.peak_rss_gib.max()),
        "observed_peak_vram_gib": float(frame.peak_cuda_allocated_gib.max()),
        "observed_devices": ";".join(sorted(set(frame.device.astype(str)))),
        "cpu_threads_per_run": 4,
        "max_concurrent_runs": 2,
        "projected_prediction_csv_gib": float(estimate.projected_prediction_csv_gib.sum()),
    }
    estimate.to_csv(OUTPUT / "COMPUTE_ESTIMATE.csv", index=False)
    frame[[
        "section", "method", "seed", "epochs", "device", "status", "n_cells", "n_genes",
        "n_clusters_observed", "required_K", "cluster_count_matches_K", "labels_finite",
        "graph_edges", "graph_hash", "elapsed_seconds", "peak_rss_gib", "peak_cuda_allocated_gib",
        "scientific_reference_metrics_computed", "scientific_reference_metrics_inspected",
        "prediction_map_saved",
    ]].to_csv(OUTPUT / "SMOKE_TECHNICAL_SUMMARY.csv", index=False)
    (OUTPUT / "SMOKE_VALIDATION.json").write_text(json.dumps({
        "status": "PASS", "technical_smoke_runs": 20, "expected": 20,
        "seed": 1, "epochs": 200, "sections": 5, "methods": 4,
        "all_completed": True, "all_K_equal_8": True, "all_outputs_finite": True,
        "scientific_reference_metrics_computed": False,
        "scientific_reference_metrics_inspected": False,
        "prediction_maps_saved": False,
        "concurrency_cap": 2, "cpu_threads_per_run": 4,
        "memory_pressure_fallback_rule": "one concurrent run if free memory <5 GiB",
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
