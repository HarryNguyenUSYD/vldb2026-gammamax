#!/usr/bin/env python3
"""Run graph-retrieval GIDCL correction on generated benchmark data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BENCHMARK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCHMARK))
from benchmark_common import (  # noqa: E402
    detected_cells, load_case, metrics, openai_json, sample_rows, save_result,
    validator,
)


def retrieve(rows, row_index, targets, checks, limit=5):
    query = rows[row_index]
    candidates = []
    for index, row in enumerate(rows):
        if index == row_index or any(not checks[column](row[column]) for column in targets):
            continue
        score = sum(
            row[column] == query[column]
            for column in query
            if column not in targets
        )
        candidates.append((score, index, row))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [row for _, _, row in candidates[:limit]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output")
    args = parser.parse_args()

    columns, original, corrupted, manifest = load_case(args.dataset)
    original, corrupted, source_indices = sample_rows(
        original, corrupted, args.smoke, args.seed
    )
    specifications = {item["column"]: item for item in manifest["oracles"]}
    checks = {column: validator(spec) for column, spec in specifications.items()}
    targets = detected_cells(corrupted, manifest)
    by_row: dict[int, list[str]] = {}
    for row_index, column in targets:
        by_row.setdefault(row_index, []).append(column)
    repaired = [dict(row) for row in corrupted]

    for row_index, target_columns in by_row.items():
        neighbors = retrieve(corrupted, row_index, target_columns, checks)
        prompt = (
            "This is GIDCL graph-enhanced correction. Related rows were retrieved by "
            "agreement on non-target attributes. Infer repairs from row relationships and "
            "column constraints. Change only listed columns.\n"
            f"Dirty row: {json.dumps(corrupted[row_index], ensure_ascii=False)}\n"
            f"Columns to repair: {json.dumps(target_columns)}\n"
            f"Column constraints: {json.dumps({c: specifications[c] for c in target_columns})}\n"
            f"Retrieved related rows: {json.dumps(neighbors, ensure_ascii=False)}\n"
            'Return {"corrections": {"column": "correct value"}}.'
        )
        response = openai_json(prompt, "GIDCL_MODEL")
        corrections = response.get("corrections", response)
        if isinstance(corrections, dict):
            for column in target_columns:
                if column in corrections:
                    repaired[row_index][column] = str(corrections[column])

    report = metrics(original, corrupted, repaired)
    report.update({
        "algorithm": "GIDCL",
        "dataset": args.dataset,
        "smoke": args.smoke,
        "row_count": len(corrupted),
        "source_rows": source_indices if args.smoke else "all",
        "detected_cells": len(targets),
    })
    output = Path(args.output) if args.output else BENCHMARK / "results" / "gidcl" / args.dataset / ("smoke" if args.smoke else "full")
    save_result(output, columns, repaired, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
