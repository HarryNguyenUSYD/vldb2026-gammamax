"""Self-contained CSV benchmark evaluator shared verbatim by every suite."""

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
            if telemetry.get("schema_version") == 2 or not is_ignored(original[row][column])
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
        "knn_imputed", "final_missing", "final_invalid",
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
            metric["knn_imputed"] += int(record.get("knn_imputed", False))
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
    case = read_json(case_dir / "case.json")
    return {
        "schema_version": 2, "dataset": case["dataset"], "generation": case["generation"],
        "algorithm": algorithm_config, "run_metadata": case.get("run_metadata", {}),
        "columns": per_column, "table": totals, "telemetry_supplied": telemetry is not None,
        "validation_failures": [],
    }
