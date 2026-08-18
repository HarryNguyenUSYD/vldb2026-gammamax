#!/usr/bin/env python3
"""Shared dataset, detection, sampling, API, and evaluation helpers."""

from __future__ import annotations

import csv
import json
import math
import os
import random
import re
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validator(spec: dict[str, Any]) -> Callable[[str], bool]:
    kind = spec["type"]
    if kind == "list":
        values = set(map(str, spec["values"]))
        return lambda value: "#" not in value and value in values
    if kind == "regex":
        expression = re.compile(spec["regex"])
        return lambda value: "#" not in value and expression.fullmatch(value) is not None
    if kind == "integer":
        low, high = int(spec["minimum"]), int(spec["maximum"])

        def valid_integer(value: str) -> bool:
            try:
                return "#" not in value and value.strip() == value and low <= int(value) <= high
            except ValueError:
                return False

        return valid_integer
    if kind == "real":
        low, high = float(spec["minimum"]), float(spec["maximum"])

        def valid_real(value: str) -> bool:
            try:
                number = float(value)
                return "#" not in value and value.strip() == value and math.isfinite(number) and low <= number <= high
            except ValueError:
                return False

        return valid_real
    raise ValueError(f"unsupported oracle type: {kind}")


def load_case(dataset: str) -> tuple[list[str], list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    case_dir = ROOT / "test-cases" / dataset
    columns, original = read_csv(case_dir / "original.csv")
    dirty_columns, corrupted = read_csv(case_dir / "corrupted.csv")
    if columns != dirty_columns or len(original) != len(corrupted):
        raise ValueError("original and corrupted tables do not align")
    manifest = json.loads((ROOT / "datasets" / dataset / "oracles.json").read_text(encoding="utf-8-sig"))
    return columns, original, corrupted, manifest


def detected_cells(rows: list[dict[str, str]], manifest: dict[str, Any]) -> list[tuple[int, str]]:
    checks = {item["column"]: validator(item) for item in manifest["oracles"]}
    return [
        (row_index, column)
        for row_index, row in enumerate(rows)
        for column, check in checks.items()
        if not check(row[column])
    ]


def sample_rows(
    original: list[dict[str, str]],
    corrupted: list[dict[str, str]],
    smoke: bool,
    seed: int,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[int]]:
    if not smoke:
        indices = list(range(len(original)))
    else:
        count = min(math.ceil(len(original) * 0.05), 100)
        count = max(1, count)
        rng = random.Random(seed)
        indices = rng.sample(range(len(original)), count)
        corrupt_rows = [
            index for index, (clean, dirty) in enumerate(zip(original, corrupted))
            if clean != dirty
        ]
        if not corrupt_rows:
            raise ValueError("smoke test requires at least one corrupted row")
        if not any(index in set(corrupt_rows) for index in indices):
            indices[-1] = rng.choice(corrupt_rows)
        indices = sorted(set(indices))
    return ([dict(original[i]) for i in indices], [dict(corrupted[i]) for i in indices], indices)


def openai_json(prompt: str, model_env: str) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError("install the openai package") from error
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required")
    client = OpenAI(api_key=key, base_url=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"))
    response = client.chat.completions.create(
        model=os.getenv("BENCHMARK_MODEL", os.getenv(model_env, "gpt-4o-mini")),
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "Repair tabular data. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
    )
    text = response.choices[0].message.content or "{}"
    return json.loads(text)


def metrics(
    original: list[dict[str, str]],
    corrupted: list[dict[str, str]],
    repaired: list[dict[str, str]],
) -> dict[str, Any]:
    errors = changed = correct = 0
    for clean, dirty, output in zip(original, corrupted, repaired):
        for column in clean:
            was_error = clean[column] != dirty[column]
            was_changed = output[column] != dirty[column]
            errors += was_error
            changed += was_changed
            correct += was_error and output[column] == clean[column]
    precision = correct / changed if changed else 0.0
    recall = correct / errors if errors else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "error_cells": errors,
        "changed_cells": changed,
        "correct_repairs": correct,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def save_result(
    output_dir: Path,
    columns: list[str],
    repaired: list[dict[str, str]],
    report: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "repaired.csv", columns, repaired)
    (output_dir / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
