from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

from PIL import Image


WORKSPACE = Path(__file__).resolve().parents[2]
FIGURE_ROOT = (
    WORKSPACE
    / "outputs"
    / "PROJECT9_SEDR_EXPANSION"
    / "candidate_integration"
    / "figures"
)
BASELINE = FIGURE_ROOT / "QC" / "CANDIDATE_FIGURE_IMMUTABILITY_BASELINE.json"
MAIN_ROOT = FIGURE_ROOT / "Main"
SUPPLEMENTARY_ROOT = FIGURE_ROOT / "Supplementary"
SOURCE_ROOT = FIGURE_ROOT / "SourceData"
INTEGRATED_ROOT = (
    WORKSPACE
    / "outputs"
    / "PROJECT9_SEDR_EXPANSION"
    / "candidate_integration"
    / "all_outputs"
)
FIVE_METHOD_ROOT = (
    WORKSPACE
    / "outputs"
    / "PROJECT9_SEDR_EXPANSION"
    / "candidate_integration"
    / "five_method"
)

METHOD_ORDER = ("GraphST", "STAGATE", "SpaGCN", "BANKSY", "SEDR")
DATASET_ORDER = (
    "151507",
    "151508",
    "151509",
    "151510",
    "151669",
    "151670",
    "151671",
    "151672",
    "151673",
    "151674",
    "151675",
    "151676",
    "STARmap",
    "HBCA1",
    "Bregma -0.04",
    "Bregma -0.09",
    "Bregma -0.14",
    "Bregma -0.19",
    "Bregma -0.24",
)
FORMATS = ("pdf", "svg", "tiff", "png")
EXPECTED_MAIN = tuple(f"Figure{index}_five_method_candidate" for index in range(1, 7))
EXPECTED_SUPPLEMENTARY = tuple(
    f"FigureS{index}_five_method_candidate" for index in range(1, 9)
) + (
    "FigureS7_candidate_A_existing_controls",
    "FigureS7_candidate_B_with_SEDR_controls",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def as_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Non-finite numeric value: {value!r}")
    return result


def verify_baseline(failures: list[str]) -> dict[str, Any]:
    require(BASELINE.is_file(), f"Missing baseline: {BASELINE}", failures)
    if not BASELINE.is_file():
        return {}
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    groups = (
        baseline.get("protected_locked_four_method_publication_package", {}),
        baseline.get("authoritative_five_method_scientific_inputs", {}),
    )
    records = [record for group in groups for record in group.get("files", [])]
    require(
        len(records) == 233,
        f"Protected baseline must contain 233 records, found {len(records)}",
        failures,
    )
    require(
        baseline.get("combined_protected_file_count") == 233,
        "Baseline combined_protected_file_count is not 233",
        failures,
    )
    seen: set[str] = set()
    for record in records:
        relative = str(record["path"])
        require(relative not in seen, f"Duplicate protected path: {relative}", failures)
        seen.add(relative)
        path = WORKSPACE / relative
        if not path.is_file():
            failures.append(f"Missing protected file: {relative}")
            continue
        observed_bytes = path.stat().st_size
        observed_hash = sha256(path)
        require(
            observed_bytes == int(record["bytes"]),
            f"Protected byte-count drift: {relative}",
            failures,
        )
        require(
            observed_hash == str(record["sha256"]),
            f"Protected SHA-256 drift: {relative}",
            failures,
        )
    publication_root = WORKSPACE / baseline[
        "protected_locked_four_method_publication_package"
    ]["root"]
    current_publication = {
        path.relative_to(WORKSPACE).as_posix()
        for path in publication_root.rglob("*")
        if path.is_file()
    }
    expected_publication = {
        str(row["path"])
        for row in baseline["protected_locked_four_method_publication_package"]["files"]
    }
    require(
        current_publication == expected_publication,
        "Locked publication-package file set changed",
        failures,
    )
    return baseline


def expected_exports() -> list[Path]:
    paths: list[Path] = []
    for stem in EXPECTED_MAIN:
        paths.extend(MAIN_ROOT / f"{stem}.{suffix}" for suffix in FORMATS)
    for stem in EXPECTED_SUPPLEMENTARY:
        paths.extend(SUPPLEMENTARY_ROOT / f"{stem}.{suffix}" for suffix in FORMATS)
    return paths


def verify_names_and_formats(failures: list[str]) -> list[Path]:
    expected = expected_exports()
    for path in expected:
        require(path.is_file(), f"Missing required candidate export: {path}", failures)
        if path.is_file():
            require(path.stat().st_size > 0, f"Empty candidate export: {path}", failures)
    candidate_files = [path for path in FIGURE_ROOT.rglob("*") if path.is_file()]
    for path in candidate_files:
        require(
            "final" not in path.name.casefold(),
            f"Forbidden FINAL token in candidate filename: {path}",
            failures,
        )
    return [path for path in expected if path.is_file()]


def verify_source_data(failures: list[str]) -> None:
    require(SOURCE_ROOT.is_dir(), f"Missing SourceData directory: {SOURCE_ROOT}", failures)
    if not SOURCE_ROOT.is_dir():
        return
    source_files = [path for path in SOURCE_ROOT.rglob("*") if path.is_file()]
    require(bool(source_files), "SourceData directory contains no files", failures)
    for path in source_files:
        require(
            path.suffix.casefold() == ".csv",
            f"SourceData must contain CSV files only: {path}",
            failures,
        )


def dpi_value(value: Any) -> float:
    if isinstance(value, tuple):
        return float(value[0])
    return float(value)


def verify_raster(path: Path, expected_dpi: float, failures: list[str]) -> None:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            dpi = image.info.get("dpi")
            require(dpi is not None, f"Missing DPI metadata: {path}", failures)
            if dpi is not None:
                x_dpi = dpi_value(dpi)
                y_dpi = float(dpi[1]) if isinstance(dpi, tuple) else x_dpi
                require(
                    abs(x_dpi - expected_dpi) <= 2 and abs(y_dpi - expected_dpi) <= 2,
                    f"Incorrect DPI for {path}: observed {dpi}, expected {expected_dpi}",
                    failures,
                )
            require(image.width > 0 and image.height > 0, f"Invalid raster size: {path}", failures)
    except Exception as error:  # Pillow provides the format-specific validation.
        failures.append(f"Unreadable raster {path}: {error}")


FONT_RE = re.compile(r"font-size\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*(px|pt)?", re.I)
FONT_ATTR_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*(px|pt)?$", re.I)


def svg_font_points(value: str) -> float | None:
    match = FONT_ATTR_RE.match(value.strip())
    if not match:
        return None
    number = float(match.group(1))
    # Matplotlib SVG uses px numerically equal to its configured point size.
    return number


def verify_svg(path: Path, failures: list[str]) -> None:
    try:
        tree = ET.parse(path)
    except Exception as error:
        failures.append(f"Invalid SVG XML {path}: {error}")
        return
    root = tree.getroot()
    text_nodes = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "text"]
    require(bool(text_nodes), f"SVG has no editable <text> nodes: {path}", failures)
    sizes: list[float] = []
    unresolved = 0
    for node in text_nodes:
        raw_size = node.attrib.get("font-size")
        if raw_size:
            parsed = svg_font_points(raw_size)
            if parsed is not None:
                sizes.append(parsed)
                continue
        style = node.attrib.get("style", "")
        match = FONT_RE.search(style)
        if match:
            sizes.append(float(match.group(1)))
        else:
            unresolved += 1
    require(bool(sizes), f"SVG text has no explicit font-size metadata: {path}", failures)
    if sizes:
        require(
            min(sizes) >= 6.5 - 1e-9,
            f"SVG contains font below 6.5 pt ({min(sizes):.3f}): {path}",
            failures,
        )
    require(
        unresolved == 0,
        f"SVG has {unresolved} text nodes without locally resolvable font size: {path}",
        failures,
    )


def verify_export_metadata(exports: Iterable[Path], failures: list[str]) -> None:
    for path in exports:
        suffix = path.suffix.casefold()
        if suffix == ".png":
            verify_raster(path, 300.0, failures)
        elif suffix in {".tif", ".tiff"}:
            verify_raster(path, 600.0, failures)
        elif suffix == ".svg":
            verify_svg(path, failures)
        elif suffix == ".pdf":
            try:
                header = path.read_bytes()[:5]
                require(header == b"%PDF-", f"Invalid PDF signature: {path}", failures)
            except OSError as error:
                failures.append(f"Unreadable PDF {path}: {error}")


def unique(rows: list[dict[str, str]], column: str) -> set[str]:
    return {row[column] for row in rows}


def verify_structural_numerics(failures: list[str]) -> None:
    seed_path = INTEGRATED_ROOT / "integrated_seed_level_accuracy.csv"
    pair_path = INTEGRATED_ROOT / "integrated_pairwise_reproducibility.csv"
    unit_path = INTEGRATED_ROOT / "integrated_method_dataset_summary.csv"
    iso_path = INTEGRATED_ROOT / "integrated_iso_accuracy.csv"
    marker_pair_path = INTEGRATED_ROOT / "integrated_marker_reproducibility_all_pairs.csv"
    marker_unit_path = INTEGRATED_ROOT / "integrated_marker_unit_summary.csv"
    consensus_path = INTEGRATED_ROOT / "integrated_consensus_summary.csv"
    winner_path = FIVE_METHOD_ROOT / "five_method_winner_probabilities.csv"
    headline_path = INTEGRATED_ROOT / "integrated_headline_summary.json"
    required = (
        seed_path,
        pair_path,
        unit_path,
        iso_path,
        marker_pair_path,
        marker_unit_path,
        consensus_path,
        winner_path,
        headline_path,
    )
    for path in required:
        require(path.is_file(), f"Missing structural source: {path}", failures)
    if any(not path.is_file() for path in required):
        return

    seed = load_csv(seed_path)
    pair = load_csv(pair_path)
    units = load_csv(unit_path)
    iso = load_csv(iso_path)
    marker_pairs = load_csv(marker_pair_path)
    marker_units = load_csv(marker_unit_path)
    consensus = load_csv(consensus_path)
    winners = load_csv(winner_path)
    headline = json.loads(headline_path.read_text(encoding="utf-8"))

    require(len(seed) == 1900, f"Expected 1,900 seed rows, found {len(seed)}", failures)
    require(len(pair) == 18050, f"Expected 18,050 seed-pair rows, found {len(pair)}", failures)
    require(len(units) == 95, f"Expected 95 unit rows, found {len(units)}", failures)
    require(len(consensus) == 95, f"Expected 95 consensus rows, found {len(consensus)}", failures)
    require(unique(seed, "method") == set(METHOD_ORDER), "Method set/order domain mismatch", failures)
    require(unique(seed, "section_display") == set(DATASET_ORDER), "Dataset domain mismatch", failures)
    require(
        all(sum(1 for row in seed if row["section_display"] == dataset and row["method"] == method) == 20
            for dataset in DATASET_ORDER for method in METHOD_ORDER),
        "Not every method-dataset unit has exactly 20 seeds",
        failures,
    )

    primary_iso = [row for row in iso if abs(as_float(row["threshold"]) - 0.02) <= 1e-12]
    eligible = sum(int(row["n_iso_accuracy_pairs"]) for row in primary_iso)
    divergent = sum(int(row["n_partition_ari_below_0_50"]) for row in primary_iso)
    affected = sum(int(row["n_partition_ari_below_0_50"]) > 0 for row in primary_iso)
    require(len(primary_iso) == 95, f"Expected 95 primary iso rows, found {len(primary_iso)}", failures)
    require(eligible == 6928, f"Expected 6,928 primary iso pairs, found {eligible}", failures)
    require(divergent == 1125, f"Expected 1,125 divergent pairs, found {divergent}", failures)
    require(affected == 55, f"Expected 55 affected units, found {affected}", failures)
    require(len(marker_pairs) == 6928, f"Expected 6,928 marker-pair rows, found {len(marker_pairs)}", failures)
    marker_rhos = [
        as_float(row["spearman_partition_ari_vs_marker_jaccard"])
        for row in marker_units
        if row["spearman_partition_ari_vs_marker_jaccard"].strip()
    ]
    require(len(marker_rhos) == 94, f"Expected 94 estimable marker units, found {len(marker_rhos)}", failures)
    require(sum(value > 0 for value in marker_rhos) == 94, "Expected 94/94 positive marker correlations", failures)
    gains = [as_float(row["split_half_gain_over_median_single_seed_pairwise_ari"]) for row in consensus]
    require(sum(value > 0 for value in gains) == 95, "Expected 95/95 positive consensus gains", failures)

    require(len(winners) == 95, f"Expected 95 winner-probability rows, found {len(winners)}", failures)
    for dataset in DATASET_ORDER:
        values = [as_float(row["p_rank1"]) for row in winners if row["section_display"] == dataset]
        require(len(values) == 5, f"Expected five P(rank1) values for {dataset}", failures)
        if len(values) == 5:
            require(
                abs(sum(values) - 1.0) <= 1e-12,
                f"P(rank1) does not sum to 1 for {dataset}: {sum(values):.17g}",
                failures,
            )
    structural = headline.get("structural_totals", {})
    expected_structural = {
        "dataset_entries": 19,
        "methods": 5,
        "method_dataset_units": 95,
        "seed_specific_runs": 1900,
        "pairwise_seed_comparisons": 18050,
    }
    require(structural == expected_structural, f"Headline structural totals mismatch: {structural}", failures)
    require(
        headline.get("primary_iso_accuracy", {}).get("eligible_pairs") == 6928
        and headline.get("primary_iso_accuracy", {}).get("divergent_partition_ari_lt_0_50") == 1125
        and headline.get("primary_iso_accuracy", {}).get("affected_units") == 55,
        "Headline iso-accuracy totals mismatch",
        failures,
    )
    require(
        headline.get("within_unit_partition_to_marker", {}).get("n_estimable") == 94
        and headline.get("within_unit_partition_to_marker", {}).get("positive_units") == 94,
        "Headline marker totals mismatch",
        failures,
    )
    require(
        headline.get("consensus", {}).get("improved_units") == 95
        and headline.get("consensus", {}).get("denominator_units") == 95,
        "Headline consensus totals mismatch",
        failures,
    )


def main() -> int:
    failures: list[str] = []
    baseline = verify_baseline(failures)
    exports = verify_names_and_formats(failures)
    verify_source_data(failures)
    verify_export_metadata(exports, failures)
    verify_structural_numerics(failures)
    result = {
        "status": "PASS" if not failures else "FAIL",
        "baseline": str(BASELINE),
        "protected_records_expected": 233,
        "protected_records_observed": baseline.get("combined_protected_file_count"),
        "required_candidate_exports": len(expected_exports()),
        "required_candidate_exports_present": len(exports),
        "checks": {
            "protected_hashes": "PASS" if not any("Protected" in item or "publication-package" in item for item in failures) else "FAIL",
            "candidate_exports": "PASS" if len(exports) == len(expected_exports()) else "FAIL",
            "png_dpi": 300,
            "tiff_dpi": 600,
            "svg_editable_text": True,
            "minimum_svg_font_pt": 6.5,
            "source_data_csv_only": True,
            "structural_numeric_checks": True,
        },
        "failure_count": len(failures),
        "failures": failures,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
