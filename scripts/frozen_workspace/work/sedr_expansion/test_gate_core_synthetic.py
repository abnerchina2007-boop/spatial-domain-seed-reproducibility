"""Synthetic-only fault and formula tests for the SEDR gate/core workflow.

No Project 9 reference file, checkpoint label, or scientific output is opened.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load_module("synthetic_gate_module", "open_scientific_gate.py")
core = load_module("synthetic_core_module", "analyze_scientific.py")


class TinyFrame:
    def __init__(self, value: str):
        self.value = value

    def to_csv(self, path: Path, **_: object) -> None:
        path.write_text(f"field\n{self.value}\n", encoding="utf-8", newline="\n")


def configure_gate(root: Path) -> list[tuple[Path, bytes]]:
    gate.CHECKPOINT_MANIFEST = root / "manifest.csv"
    gate.TECHNICAL_METADATA = root / "technical.csv"
    gate.PREFLIGHT_TECHNICAL_METADATA = root / "preflight.csv"
    gate.TECHNICAL_VALIDATION_REPORT = root / "validation.json"
    gate.GATE_FILE = root / "gate.json"
    gate.GATE_TRANSACTION_DIR = root / ".gate_transaction"
    gate.TECHNICAL_METADATA.write_bytes(b"preflight-original\n")
    return [
        (gate.CHECKPOINT_MANIFEST, b"manifest\n"),
        (gate.PREFLIGHT_TECHNICAL_METADATA, b"preflight-original\n"),
        (gate.TECHNICAL_METADATA, b"technical-final\n"),
        (gate.TECHNICAL_VALIDATION_REPORT, b"validation\n"),
        (gate.GATE_FILE, b"gate-last\n"),
    ]


def test_gate_transactions() -> None:
    with tempfile.TemporaryDirectory(prefix="sedr_gate_normal_") as raw:
        root = Path(raw)
        payloads = configure_gate(root)
        payloads[-1] = (
            gate.GATE_FILE,
            b'{"opened_utc":"2099-01-01T00:00:00+00:00"}\n',
        )
        gate.publish_gate_bundle(payloads)
        assert [path.read_bytes() for path, _ in payloads] == [value for _, value in payloads]
        assert not gate.GATE_TRANSACTION_DIR.exists()

    with tempfile.TemporaryDirectory(prefix="sedr_gate_partial_") as raw:
        root = Path(raw)
        payloads = configure_gate(root)
        payloads[-1] = (
            gate.GATE_FILE,
            b'{"opened_utc":"2099-01-01T00:00:00+00:00"}\n',
        )
        real_rename = os.rename

        def interrupt_after_validation(source, target):
            real_rename(source, target)
            if Path(target).resolve() == gate.TECHNICAL_VALIDATION_REPORT.resolve():
                raise KeyboardInterrupt("synthetic crash")

        os.rename = interrupt_after_validation
        try:
            try:
                gate.publish_gate_bundle(payloads)
            except KeyboardInterrupt:
                pass
        finally:
            os.rename = real_rename
        assert gate.GATE_TRANSACTION_DIR.is_dir()
        assert gate.recover_gate_transaction() is False
        assert gate.TECHNICAL_METADATA.read_bytes() == b"preflight-original\n"
        assert not gate.CHECKPOINT_MANIFEST.exists()
        assert not gate.PREFLIGHT_TECHNICAL_METADATA.exists()
        assert not gate.TECHNICAL_VALIDATION_REPORT.exists()
        assert not gate.GATE_FILE.exists()
        assert not gate.GATE_TRANSACTION_DIR.exists()

    with tempfile.TemporaryDirectory(prefix="sedr_gate_complete_") as raw:
        root = Path(raw)
        payloads = configure_gate(root)
        payloads[-1] = (
            gate.GATE_FILE,
            b'{"opened_utc":"2099-01-01T00:00:00+00:00"}\n',
        )
        real_rename = os.rename

        def interrupt_after_gate(source, target):
            real_rename(source, target)
            if Path(target).resolve() == gate.GATE_FILE.resolve():
                raise KeyboardInterrupt("synthetic crash after commit marker")

        os.rename = interrupt_after_gate
        try:
            try:
                gate.publish_gate_bundle(payloads)
            except KeyboardInterrupt:
                pass
        finally:
            os.rename = real_rename
        assert gate.recover_gate_transaction() is True
        assert [path.read_bytes() for path, _ in payloads] == [value for _, value in payloads]
        assert not gate.GATE_TRANSACTION_DIR.exists()


def configure_core(root: Path):
    core.CORE_TRANSACTION_DIR = root / ".core_transaction"
    core.CORE_RECEIPT = root / ".core_receipt.json"
    paths = [root / f"output_{index}.csv" for index in range(5)]
    return {path: TinyFrame(str(index)) for index, path in enumerate(paths)}


def test_core_transactions() -> None:
    with tempfile.TemporaryDirectory(prefix="sedr_core_normal_") as raw:
        root = Path(raw)
        frames = configure_core(root)
        core.atomic_dataframes(frames)
        assert all(path.is_file() for path in frames)
        assert core.CORE_RECEIPT.is_file()
        assert not core.CORE_TRANSACTION_DIR.exists()

    with tempfile.TemporaryDirectory(prefix="sedr_core_partial_") as raw:
        root = Path(raw)
        frames = configure_core(root)
        crash_target = list(frames)[1].resolve()
        real_rename = os.rename

        def interrupt_after_second(source, target):
            real_rename(source, target)
            if Path(target).resolve() == crash_target:
                raise KeyboardInterrupt("synthetic crash")

        os.rename = interrupt_after_second
        try:
            try:
                core.atomic_dataframes(frames)
            except KeyboardInterrupt:
                pass
        finally:
            os.rename = real_rename
        assert core.CORE_TRANSACTION_DIR.is_dir()
        assert core.recover_core_transaction(frames) is False
        assert not any(path.exists() for path in frames)
        assert not core.CORE_RECEIPT.exists()
        assert not core.CORE_TRANSACTION_DIR.exists()

    with tempfile.TemporaryDirectory(prefix="sedr_core_complete_") as raw:
        root = Path(raw)
        frames = configure_core(root)
        crash_target = list(frames)[-1].resolve()
        real_rename = os.rename

        def interrupt_after_fifth(source, target):
            real_rename(source, target)
            if Path(target).resolve() == crash_target:
                raise KeyboardInterrupt("synthetic crash after five CSVs")

        os.rename = interrupt_after_fifth
        try:
            try:
                core.atomic_dataframes(frames)
            except KeyboardInterrupt:
                pass
        finally:
            os.rename = real_rename
        assert core.recover_core_transaction(frames) is True
        assert all(path.is_file() for path in frames)
        assert core.CORE_RECEIPT.is_file()
        assert not core.CORE_TRANSACTION_DIR.exists()

    with tempfile.TemporaryDirectory(prefix="sedr_core_ambiguous_") as raw:
        root = Path(raw)
        frames = configure_core(root)
        first = list(frames)[0].resolve()
        real_rename = os.rename

        def interrupt_after_first(source, target):
            real_rename(source, target)
            if Path(target).resolve() == first:
                raise KeyboardInterrupt("synthetic crash")

        os.rename = interrupt_after_first
        try:
            try:
                core.atomic_dataframes(frames)
            except KeyboardInterrupt:
                pass
        finally:
            os.rename = real_rename
        first.write_bytes(b"foreign bytes\n")
        try:
            core.recover_core_transaction(frames)
        except RuntimeError as error:
            assert "Ambiguous scientific artifact" in str(error)
        else:
            raise AssertionError("Ambiguous core artifact was not rejected")
        assert first.read_bytes() == b"foreign bytes\n"


def test_full_core_on_synthetic_panel() -> None:
    import numpy as np
    import pandas as pd
    import sklearn.metrics as metrics

    with tempfile.TemporaryDirectory(prefix="sedr_core_formula_") as raw:
        root = Path(raw)
        sources = root / "sources"
        labels_root = root / "labels"
        output_root = root / "outputs"
        sources.mkdir()
        labels_root.mkdir()
        output_root.mkdir()

        core.OUTPUTS = {
            "seed": output_root / "seed_level_accuracy.csv",
            "pairwise": output_root / "pairwise_partition_reproducibility.csv",
            "iso": output_root / "iso_accuracy_results.csv",
            "consensus": output_root / "consensus_results.csv",
            "unit": output_root / "sedr_unit_summary.csv",
        }
        core.CORE_TRANSACTION_DIR = output_root / ".core_transaction"
        core.CORE_RECEIPT = output_root / ".core_receipt.json"

        fake_bases: dict[Path, object] = {}
        score_map: dict[tuple[int, tuple[int, ...]], float] = {}
        checkpoints: list[dict[str, object]] = []
        input_entries: dict[str, dict[str, object]] = {}

        class Closer:
            def close(self):
                return None

        for dataset_index, dataset in enumerate(core.DATASETS):
            n = 12
            observation_ids = np.asarray(
                [f"synthetic_{dataset_index:02d}_{index:02d}" for index in range(n)]
            )
            reference = [
                f"R{dataset_index:02d}_{index % 3}" for index in range(n)
            ]
            source = sources / f"source_{dataset_index:02d}.bin"
            source.write_bytes(f"synthetic source {dataset}\n".encode("utf-8"))
            base = types.SimpleNamespace(
                obs_names=pd.Index(observation_ids),
                obs=pd.DataFrame({"manual_layer": reference}, index=observation_ids),
                n_vars=25,
                file=Closer(),
            )
            fake_bases[source.resolve()] = base
            source_hash = core.sha256_file(source)
            input_entries[dataset] = {
                "source_path": str(source.resolve()),
                "source_sha256": source_hash,
                "locked_source_sha256": source_hash,
                "source_bytes": source.stat().st_size,
                "obs_count": n,
                "obs_order_sha256_newline_utf8": core.ordered_string_hash(
                    observation_ids.tolist()
                ),
            }

            if dataset_index == 0:
                scores = [0.04 * index for index in range(20)]
            elif dataset_index == 1:
                scores = [0.10, 0.12] + [0.20 + 0.04 * index for index in range(18)]
            else:
                scores = [0.15 + 0.02 * index for index in range(20)]

            for seed in core.SEEDS:
                rng = np.random.default_rng(1000 * dataset_index + seed)
                labels = rng.integers(0, 3, size=n, dtype=np.int32)
                labels[:3] = np.asarray([0, 1, 2], dtype=np.int32)
                if dataset_index == 0 and seed == 20:
                    labels = np.arange(n, dtype=np.int32) % 2
                observed_k = int(np.unique(labels).size)
                score_map[(dataset_index, tuple(int(value) for value in labels))] = scores[seed - 1]
                label_dir = labels_root / f"d{dataset_index:02d}_s{seed:02d}"
                label_dir.mkdir()
                label_path = label_dir / "labels.csv"
                pd.DataFrame(
                    {
                        "observation_id": observation_ids,
                        "cluster_label": labels,
                    }
                ).to_csv(label_path, index=False)
                checkpoints.append(
                    {
                        "dataset": dataset,
                        "seed": seed,
                        "labels_path": label_path.resolve(),
                        "requested_k": 3,
                        "observed_k": observed_k,
                        "checkpoint_sha256": "A" * 64,
                        "labels_sha256": core.sha256_file(label_path),
                    }
                )

        audit = {
            "gate_sha256": "B" * 64,
            "protocol_hash": "C" * 64,
            "checkpoint_manifest_hash": "D" * 64,
            "checkpoints": checkpoints,
            "input_entries": input_entries,
        }

        fake_anndata = types.SimpleNamespace(
            read_h5ad=lambda path, backed="r": fake_bases[Path(path).resolve()]
        )
        old_anndata = sys.modules.get("anndata")
        real_ari = metrics.adjusted_rand_score
        real_nmi = metrics.normalized_mutual_info_score

        def synthetic_reference_score(first, second, nmi=False):
            first_array = np.asarray(first)
            if first_array.dtype.kind in {"O", "U", "S"} and len(first_array):
                dataset_index = int(str(first_array[0])[1:3])
                value = score_map.get(
                    (dataset_index, tuple(int(item) for item in np.asarray(second)))
                )
                if value is None:
                    value = 0.30
                return 0.50 + value / 2.0 if nmi else value
            return real_nmi(first, second) if nmi else real_ari(first, second)

        sys.modules["anndata"] = fake_anndata
        metrics.adjusted_rand_score = lambda first, second: synthetic_reference_score(
            first, second, nmi=False
        )
        metrics.normalized_mutual_info_score = lambda first, second: synthetic_reference_score(
            first, second, nmi=True
        )
        original_verify = core.verify_gate_and_fresh_scan
        core.verify_gate_and_fresh_scan = lambda: audit
        try:
            result = core.run_scientific_analysis(audit)
        finally:
            core.verify_gate_and_fresh_scan = original_verify
            metrics.adjusted_rand_score = real_ari
            metrics.normalized_mutual_info_score = real_nmi
            if old_anndata is None:
                sys.modules.pop("anndata", None)
            else:
                sys.modules["anndata"] = old_anndata

        assert result["status"] == "COMPLETE"
        seed = pd.read_csv(core.OUTPUTS["seed"])
        pair = pd.read_csv(core.OUTPUTS["pairwise"])
        iso = pd.read_csv(core.OUTPUTS["iso"])
        consensus = pd.read_csv(core.OUTPUTS["consensus"])
        unit = pd.read_csv(core.OUTPUTS["unit"])
        assert (len(seed), len(pair), len(iso), len(consensus), len(unit)) == (
            380,
            3610,
            57,
            19,
            19,
        )
        first_seed = seed[seed.dataset.astype(str) == core.DATASETS[0]].sort_values("seed")
        first_unit = unit[unit.dataset.astype(str) == core.DATASETS[0]].iloc[0]
        assert np.isclose(
            first_unit.reference_ari_sd,
            np.std(first_seed.reference_ari.to_numpy(float), ddof=1),
        )
        first_iso = iso[iso.dataset.astype(str) == core.DATASETS[0]]
        assert first_iso.n_iso_accuracy_pairs.tolist() == [0, 0, 0]
        assert first_iso.median_pairwise_partition_ari.isna().all()
        assert int(first_unit.n_primary_iso_accuracy_pairs) == 0
        assert np.isnan(first_unit.percentage_primary_iso_divergent_lt_0_50)
        assert (int(first_unit.observed_k_min), int(first_unit.observed_k_max)) == (2, 3)

        boundary = pair[
            (pair.dataset.astype(str) == core.DATASETS[1])
            & (pair.seed_r == 1)
            & (pair.seed_s == 2)
        ].iloc[0]
        assert np.isclose(boundary.abs_reference_ari_difference, 0.02)
        assert bool(boundary.iso_accuracy_0_02)
        assert not bool(boundary.iso_accuracy_0_01)
        assert core.CORE_RECEIPT.is_file()


def main() -> int:
    test_gate_transactions()
    test_core_transactions()
    test_full_core_on_synthetic_panel()
    print(
        json.dumps(
            {
                "status": "PASS",
                "real_scientific_inputs_opened": False,
                "tests": [
                    "gate normal/partial/complete-crash transaction recovery",
                    "core normal/partial/complete-crash/ambiguous recovery",
                    "synthetic 19x20 -> 380/3610/57/19/19 schemas",
                    "ddof=1, inclusive 0.02, zero-iso retention, observed-K collapse",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
