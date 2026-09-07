"""CSV benchmark evaluator for GammaMax with decision tree imputation."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Callable

IGNORED_VALUES = {"", "?"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"invalid CSV header: {path}")
        return list(reader.fieldnames), [dict(row) for row in reader]


def is_ignored(value: str) -> bool:
    return value in IGNORED_VALUES


def predicate(spec: dict[str, Any]) -> Callable[[str], bool]:
    if spec.get("type") == "enum":
        allowed = set(spec["values"])
        return lambda value: not is_ignored(value) and value in allowed
    if spec.get("type") == "regex":
        expression = re.compile(spec["regex"])
        return lambda value: not is_ignored(value) and expression.fullmatch(value) is not None
    raise ValueError(f"unsupported oracle type: {spec.get('type')!r}")


def reference_dir(case_dir: Path) -> Path:
    if case_dir.parent.name not in {"generated-50", "generated-90"}:
        return case_dir
    shared = case_dir.parents[1] / "shared-generation" / case_dir.name
    if (shared / "original.csv").is_file() and (shared / "oracles.json").is_file():
        return shared
    return case_dir



EXAMPLE_PEAKS = ("max_positive_examples_stored", "max_negative_examples_stored")


def example_peaks(columns: dict[str, Any]) -> dict[str, Any]:
    """Maxima across columns; absent legacy measurements remain unknown."""
    return {key: max(values) if values and all(v is not None for v in values) else None
            for key in EXAMPLE_PEAKS
            for values in [[column.get(key) for column in columns.values()]]}


def write_example_summary(suite: Path) -> None:
    datasets = {}
    for path in sorted(suite.glob("generated-*/**/benchmark.json")):
        result = read_json(path)
        datasets[str(path.relative_to(suite))] = {
            key: result["table"].get(key) for key in EXAMPLE_PEAKS}
    summary = {"schema_version": 1, **example_peaks(datasets), "datasets": datasets}
    (suite / "example-storage-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def evaluate(case_dir: Path, repaired_path: Path, telemetry_path: Path | None,
             algorithm_config: dict[str, Any]) -> dict[str, Any]:
    references = reference_dir(case_dir)
    columns, original = read_csv(references / "original.csv")
    repaired_columns, repaired = read_csv(repaired_path)
    if repaired_columns != columns:
        raise ValueError("repaired CSV headers or column order do not match original.csv")
    if len(repaired) != len(original):
        raise ValueError("repaired CSV row count does not match original.csv")
    specs = {item["column"]: item for item in read_json(references / "oracles.json")["oracles"]}
    telemetry = read_json(telemetry_path) if telemetry_path and telemetry_path.is_file() else None
    timed = {}
    if telemetry:
        records = telemetry.get("cells")
        if not isinstance(records, list):
            raise ValueError("telemetry.cells must be an array")
        expected = {
            (row, column) for row in range(len(original)) for column in columns
            if telemetry.get("schema_version") in (2, 3) or not is_ignored(original[row][column])
        }
        for item in records:
            key = (item.get("row"), item.get("column"))
            if key not in expected or key in timed:
                raise ValueError(f"invalid, duplicate, or unexpected telemetry cell: {key}")
            timed[key] = item
        if set(timed) != expected:
            raise ValueError(f"telemetry is incomplete: expected {len(expected)}, received {len(timed)} cells")
    totals = {key: 0 for key in (
        "cells", "eligible_cells", "oracle_eligible_cells", "exact_eligible_cells",
        "originally_missing_cells", "oracle_correct", "exact_correct", "timeouts",
        "dt_imputed", "dt_fallback_predictions", "dt_rounded_repairs", "dt_unresolved", "final_missing", "final_invalid",
    )}
    totals["execution_time_seconds"] = 0.0
    per_column = {}
    for column in columns:
        metric = {key: (0.0 if key == "execution_time_seconds" else 0) for key in totals}
        accepts = predicate(specs[column])
        for row, clean in enumerate(original):
            output = repaired[row][column]
            missing = is_ignored(clean[column])
            accepted = accepts(output)
            record = timed.get((row, column), {})
            metric["cells"] += 1
            metric["oracle_eligible_cells"] += 1
            metric["originally_missing_cells"] += int(missing)
            metric["oracle_correct"] += int(accepted)
            metric["final_missing"] += int(is_ignored(output))
            metric["final_invalid"] += int(not is_ignored(output) and not accepted)
            metric["timeouts"] += int(record.get("timed_out", False))
            metric["dt_imputed"] += int(record.get("dt_imputed", False))
            metric["dt_fallback_predictions"] += int(record.get("prediction_source") == "global_fallback")
            metric["dt_rounded_repairs"] += int(record.get("rounded", False))
            metric["dt_unresolved"] += int(bool(record.get("unresolved_reason")))
            if not missing:
                metric["eligible_cells"] += 1
                metric["exact_eligible_cells"] += 1
                metric["exact_correct"] += int(output == clean[column])
        metric["oracle_accuracy"] = metric["oracle_correct"] / metric["oracle_eligible_cells"] if metric["oracle_eligible_cells"] else None
        metric["exact_accuracy"] = metric["exact_correct"] / metric["exact_eligible_cells"] if metric["exact_eligible_cells"] else None
        metric["timeout_rate"] = metric["timeouts"] / metric["exact_eligible_cells"] if telemetry and metric["exact_eligible_cells"] else None
        if telemetry:
            column_data = telemetry.get("columns", {}).get(column, {})
            metric["execution_time_seconds"] = float(column_data.get("execution_time_seconds", 0.0))
            metric["algorithm_counts"] = {key: value for key, value in column_data.items() if key != "execution_time_seconds"}
        per_column[column] = metric
        for key in totals:
            totals[key] += metric[key]
    totals["oracle_accuracy"] = totals["oracle_correct"] / totals["oracle_eligible_cells"] if totals["oracle_eligible_cells"] else None
    totals["exact_accuracy"] = totals["exact_correct"] / totals["exact_eligible_cells"] if totals["exact_eligible_cells"] else None
    totals["timeout_rate"] = totals["timeouts"] / totals["exact_eligible_cells"] if telemetry and totals["exact_eligible_cells"] else None
    if telemetry:
        totals["total_execution_time_seconds"] = float(telemetry["total_execution_time_seconds"])
    for column, metric in per_column.items():
        column_data = telemetry.get("columns", {}).get(column, {}) if telemetry else {}
        for key in EXAMPLE_PEAKS:
            metric[key] = column_data.get(key)
    totals.update(example_peaks(per_column))
    case = read_json(case_dir / "case.json")
    return {
        "schema_version": 2, "dataset": case["dataset"], "generation": case["generation"],
        "algorithm": algorithm_config, "run_metadata": case.get("run_metadata", {}),
        "columns": per_column, "table": totals, "telemetry_supplied": telemetry is not None,
        "validation_failures": [],
    }
