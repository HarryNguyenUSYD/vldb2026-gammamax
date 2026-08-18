#!/usr/bin/env python3
"""Run ZeroEC-style zero-shot row correction on generated benchmark data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BENCHMARK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCHMARK))
from benchmark_common import (  # noqa: E402
    detected_cells, load_case, metrics, openai_json, sample_rows, save_result
)


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
    targets = detected_cells(corrupted, manifest)
    by_row: dict[int, list[str]] = {}
    for row_index, column in targets:
        by_row.setdefault(row_index, []).append(column)
    specifications = {item["column"]: item for item in manifest["oracles"]}
    repaired = [dict(row) for row in corrupted]

    for row_index, target_columns in by_row.items():
        prompt = (
            "This is ZeroEC zero-shot correction. Inspect the complete dirty row and repair "
            "only the listed columns. Preserve every other value.\n"
            f"Columns: {json.dumps(columns)}\n"
            f"Dirty row: {json.dumps(corrupted[row_index], ensure_ascii=False)}\n"
            f"Columns to repair: {json.dumps(target_columns)}\n"
            f"Column constraints: {json.dumps({c: specifications[c] for c in target_columns})}\n"
            'Return {"corrections": {"column": "correct value"}}.'
        )
        response = openai_json(prompt, "ZEROEC_MODEL")
        corrections = response.get("corrections", response)
        if isinstance(corrections, dict):
            for column in target_columns:
                if column in corrections:
                    repaired[row_index][column] = str(corrections[column])

    report = metrics(original, corrupted, repaired)
    report.update({
        "algorithm": "ZeroEC",
        "dataset": args.dataset,
        "smoke": args.smoke,
        "row_count": len(corrupted),
        "source_rows": source_indices if args.smoke else "all",
        "detected_cells": len(targets),
    })
    output = Path(args.output) if args.output else BENCHMARK / "results" / "zeroec" / args.dataset / ("smoke" if args.smoke else "full")
    save_result(output, columns, repaired, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
