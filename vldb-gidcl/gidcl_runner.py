#!/usr/bin/env python3
"""Portable GIDCL graph-retrieval adapter for prepared suite cases."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import vldb_suite as suite


def check_environment() -> None:
    try:
        import openai  # noqa: F401
    except ImportError as error:
        raise RuntimeError("GIDCL requires the openai package") from error
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("GIDCL requires OPENAI_API_KEY")


def retrieve(rows: list[dict[str, str]], row_index: int, targets: list[str],
             checks: dict[str, Callable[[str], bool]], limit: int) -> list[dict[str, str]]:
    query = rows[row_index]
    candidates = []
    for index, row in enumerate(rows):
        if index == row_index or any(not checks[column](row[column]) for column in targets):
            continue
        score = sum(row[column] == query[column] for column in query if column not in targets)
        candidates.append((score, index, row))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [dict(row) for _, _, row in candidates[:limit]]


def openai_request(prompt: str, model: str, timeout: int) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError("GIDCL requires the openai package") from error
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("GIDCL requires OPENAI_API_KEY")
    client = OpenAI(
        api_key=key,
        base_url=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        timeout=timeout,
    )
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "Repair tabular data. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
    )
    value = json.loads(response.choices[0].message.content or "{}")
    if not isinstance(value, dict):
        raise ValueError("GIDCL response must be a JSON object")
    return value


def is_timeout(error: Exception) -> bool:
    if isinstance(error, TimeoutError):
        return True
    try:
        from openai import APITimeoutError
        return isinstance(error, APITimeoutError)
    except ImportError:
        return False


def run(case_dir: Path, output_dir: Path, config: dict[str, Any],
        request: Callable[[str, str, int], dict[str, Any]] = openai_request) -> None:
    columns, corrupted = suite.read_csv(case_dir / "corrupted.csv")
    original_columns, original = suite.read_csv(case_dir / "original.csv")
    if original_columns != columns or len(original) != len(corrupted):
        raise ValueError("original and corrupted CSV files do not align")
    manifest = suite.read_json(case_dir / "oracles.json")
    specs = {item["column"]: item for item in manifest["oracles"]}
    if list(specs) != columns:
        raise ValueError("oracle manifest columns do not match corrupted.csv")
    checks = {column: suite.predicate(spec) for column, spec in specs.items()}
    by_row: dict[int, list[str]] = {}
    for row_index, row in enumerate(corrupted):
        for column in columns:
            if not checks[column](row[column]):
                by_row.setdefault(row_index, []).append(column)

    repaired = [dict(row) for row in corrupted]
    cell_data = {
        (row_index, column): {"timed_out": False, "execution_time_seconds": 0.0}
        for row_index, row in enumerate(original) for column in columns
    }
    column_data = {
        column: {"execution_time_seconds": 0.0, "detected_cells": 0,
                 "requested_rows": 0, "returned_corrections": 0,
                 "missing_corrections": 0, "timeouts": 0}
        for column in columns
    }
    model = os.getenv("GIDCL_MODEL", config["model"])
    started = time.monotonic()
    for row_index, targets in by_row.items():
        neighbors = retrieve(corrupted, row_index, targets, checks, config["retrieval_limit"])
        prompt = (
            "This is GIDCL graph-enhanced correction. Related rows were retrieved by "
            "agreement on non-target attributes. Infer repairs from row relationships and "
            "column constraints. Change only listed columns.\n"
            f"Dirty row: {json.dumps(corrupted[row_index], ensure_ascii=False)}\n"
            f"Columns to repair: {json.dumps(targets)}\n"
            f"Column constraints: {json.dumps({c: specs[c] for c in targets})}\n"
            f"Retrieved related rows: {json.dumps(neighbors, ensure_ascii=False)}\n"
            'Return {"corrections": {"column": "correct value"}}.'
        )
        request_started = time.monotonic()
        timed_out = False
        try:
            response = request(prompt, model, config["request_timeout_seconds"])
        except Exception as error:
            if not is_timeout(error):
                raise
            response = {}
            timed_out = True
        elapsed = time.monotonic() - request_started
        if not isinstance(response, dict):
            raise ValueError("GIDCL response must be a JSON object")
        corrections = response.get("corrections", response)
        if not isinstance(corrections, dict):
            raise ValueError("GIDCL corrections must be a JSON object")
        for column in targets:
            stats = column_data[column]
            stats["detected_cells"] += 1
            stats["requested_rows"] += 1
            stats["execution_time_seconds"] += elapsed
            record = cell_data[(row_index, column)]
            record["execution_time_seconds"] = elapsed
            record["timed_out"] = timed_out
            if timed_out:
                stats["timeouts"] += 1
                stats["missing_corrections"] += 1
            elif column in corrections:
                repaired[row_index][column] = str(corrections[column])
                stats["returned_corrections"] += 1
            else:
                stats["missing_corrections"] += 1

    output_dir.mkdir(parents=True, exist_ok=True)
    effective = dict(config)
    effective["model"] = model
    suite.write_json(output_dir / "algorithm-config.json", effective)
    suite.write_csv(output_dir / "repaired.csv", columns, repaired)
    cells = [
        {"row": row, "column": column, **cell_data[(row, column)]}
        for row, source in enumerate(original) for column in columns
    ]
    suite.write_json(output_dir / "telemetry.json", {
        "schema_version": 2,
        "total_execution_time_seconds": time.monotonic() - started,
        "columns": column_data,
        "cells": cells,
    })
