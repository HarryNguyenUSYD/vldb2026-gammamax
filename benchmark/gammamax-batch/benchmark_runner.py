#!/usr/bin/env python3
"""Run one GammaMax oracle/session per benchmark column."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BENCHMARK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCHMARK))
from benchmark_common import (  # noqa: E402
    load_case, metrics, run_with_elapsed_timer, sample_rows, save_result,
)


def oracle_path(root: Path, column: str) -> Path:
    plain = root / column
    windows = root / f"{column}.exe"
    if plain.is_file():
        return plain.resolve()
    if windows.is_file():
        return windows.resolve()
    raise FileNotFoundError(f"compiled oracle not found for column {column!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset")
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--oracle-dir", required=True, type=Path)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output")
    args = parser.parse_args()

    columns, original, corrupted, _ = load_case(args.dataset)
    original, corrupted, source_indices = sample_rows(
        original, corrupted, args.smoke, args.seed
    )
    repaired = [dict(row) for row in corrupted]
    scans = {}
    failures = []

    for column in columns:
        executable = oracle_path(args.oracle_dir.resolve(), column)
        config = {
            "seed": args.seed,
            "oracle": {"executable": str(executable)},
            "state_merging": {"k": 3},
            "repair": {
                "n": 3,
                "rsr_batch_size": 8,
                "ngrams_batch_size": 1,
                "max_candidate_length": -1,
            },
            "limits": {
                "max_iterations": -1,
                "max_total_oracle_calls": -1,
                "max_positive_examples": 500,
                "max_states": -1,
                "max_queue_size": -1,
            },
            "cell_timeout_seconds": 60,
        }
        with tempfile.TemporaryDirectory(prefix="gammamax-benchmark-") as directory:
            work = Path(directory)
            (work / "input.json").write_text(
                json.dumps({"cells": [row[column] for row in corrupted]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (work / "config.json").write_text(json.dumps(config), encoding="utf-8")
            process = subprocess.run(
                [str(args.binary.resolve())], cwd=work, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        if process.returncode != 0:
            raise RuntimeError(f"GammaMax failed for {column}: {process.stderr.strip()}")
        result = json.loads(process.stdout)
        scans[column] = result["oracle_scan"]
        for repair in result["results"]:
            row_index = int(repair["cell_index"])
            if repair.get("output_string") is not None:
                repaired[row_index][column] = str(repair["output_string"])
            if repair.get("error"):
                failures.append({"row": row_index, "column": column, "error": repair["error"]})

    report = metrics(original, corrupted, repaired)
    report.update({
        "algorithm": "GammaMax",
        "dataset": args.dataset,
        "smoke": args.smoke,
        "row_count": len(corrupted),
        "source_rows": source_indices if args.smoke else "all",
        "oracle_scans": scans,
        "repair_failures": failures,
    })
    output = Path(args.output) if args.output else BENCHMARK / "results" / "gammamax" / args.dataset / ("smoke" if args.smoke else "full")
    save_result(output, columns, repaired, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_with_elapsed_timer(main))
