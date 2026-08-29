#!/usr/bin/env python3
"""Create a randomly corrupted copy of a benchmark CSV."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import shutil
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
BENCHMARK = HERE.parent
DEFAULT_DATASETS_ROOT = BENCHMARK / "datasets"
DEFAULT_OUTPUT_ROOT = BENCHMARK / "test-cases"


def predicate(spec: dict[str, Any]) -> Callable[[str], bool]:
    kind = spec.get("type")
    if kind == "list":
        allowed = set(spec["values"])
        return lambda value: value not in ("", "?") and "#" not in value and value in allowed
    if kind == "integer":
        minimum, maximum = int(spec["minimum"]), int(spec["maximum"])

        def accepts_integer(value: str) -> bool:
            try:
                return value not in ("", "?") and "#" not in value and value.strip() == value and minimum <= int(value, 10) <= maximum
            except ValueError:
                return False

        return accepts_integer
    if kind == "real":
        minimum, maximum = float(spec["minimum"]), float(spec["maximum"])

        def accepts_real(value: str) -> bool:
            try:
                parsed = float(value)
                return value not in ("", "?") and "#" not in value and value.strip() == value and math.isfinite(parsed) and minimum <= parsed <= maximum
            except ValueError:
                return False

        return accepts_real
    if kind == "regex":
        expression = re.compile(spec["regex"])
        return lambda value: value not in ("", "?") and "#" not in value and expression.fullmatch(value) is not None
    raise ValueError(
        f"unsupported oracle type for {spec.get('column', '<unknown>')!r}: {kind!r}"
    )


def apply_edit(value: str, rng: random.Random) -> tuple[str, dict[str, Any]]:
    operations = ["insert"]
    if value:
        operations.extend(("substitute", "delete"))
    operation = rng.choice(operations)
    if operation == "insert":
        position = rng.randrange(len(value) + 1)
        result = value[:position] + "#" + value[position:]
    elif operation == "substitute":
        position = rng.randrange(len(value))
        result = value[:position] + "#" + value[position + 1 :]
    else:
        position = rng.randrange(len(value))
        result = value[:position] + value[position + 1 :]
    return result, {"operation": operation, "position": position}


def mutate(
    source: str,
    accepts: Callable[[str], bool],
    rng: random.Random,
    max_errors_per_cell: int,
) -> tuple[str, list[dict[str, Any]]]:
    for _ in range(1000):
        mutant = source
        edits: list[dict[str, Any]] = []
        for _ in range(rng.randint(1, max_errors_per_cell)):
            mutant, edit = apply_edit(mutant, rng)
            edits.append(edit)
        if mutant != source and not accepts(mutant):
            return mutant, edits
    raise RuntimeError(f"could not create an oracle-rejected mutant for {source!r}")


def resolve_dataset(value: str, datasets_root: Path) -> Path:
    supplied = Path(value)
    if supplied.is_dir():
        return supplied.resolve()
    candidate = datasets_root / value
    if candidate.is_dir():
        return candidate.resolve()
    raise ValueError(f"dataset directory does not exist: {value}")


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        columns = list(reader.fieldnames or [])
        if not columns:
            raise ValueError(f"dataset has no columns: {path}")
        return columns, list(reader)


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate(
    dataset: Path,
    output: Path,
    seed: int,
    corruption_rate: float,
    max_errors_per_cell: int,
) -> tuple[int, int, int]:
    if not 0.0 <= corruption_rate <= 1.0:
        raise ValueError("corruption rate must be between zero and one")
    if max_errors_per_cell < 1:
        raise ValueError("max errors per cell must be at least one")

    manifest_path = dataset / "oracles.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise ValueError("oracles.json root must be an object")
    source_path = dataset / str(manifest.get("source") or "clean.csv")
    columns, original_rows = read_rows(source_path)

    oracle_items = manifest.get("oracles")
    if not isinstance(oracle_items, list) or not oracle_items:
        raise ValueError("oracles.json must contain an 'oracles' array")
    if any(not isinstance(item, dict) for item in oracle_items):
        raise ValueError("every oracle must be an object")
    specifications = {item["column"]: item for item in oracle_items}
    if len(specifications) != len(oracle_items):
        raise ValueError("oracles.json contains duplicate column definitions")
    missing = [column for column in columns if column not in specifications]
    extra = [column for column in specifications if column not in columns]
    if missing or extra:
        raise ValueError(
            f"oracle columns do not match CSV columns; missing={missing}, extra={extra}"
        )

    total_cells = len(original_rows) * len(columns)
    corruption_count = round(total_cells * corruption_rate)
    rng = random.Random(seed)
    selected = rng.sample(range(total_cells), corruption_count)
    validators = {column: predicate(specifications[column]) for column in columns}
    corrupted_rows = [dict(row) for row in original_rows]
    corruptions: list[dict[str, Any]] = []

    for flat_index in selected:
        row_index, column_index = divmod(flat_index, len(columns))
        column = columns[column_index]
        source = original_rows[row_index][column]
        mutant, edits = mutate(source, validators[column], rng, max_errors_per_cell)
        corrupted_rows[row_index][column] = mutant
        corruptions.append(
            {
                "row": row_index,
                "column": column,
                "clean_value": source,
                "corrupted_value": mutant,
                "edits": edits,
            }
        )

    corruptions.sort(key=lambda item: (item["row"], columns.index(item["column"])))
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, output / "original.csv")
    write_csv(output / "corrupted.csv", columns, corrupted_rows)
    metadata = {
        "dataset": str(manifest.get("dataset") or dataset.name),
        "source": str(source_path),
        "seed": seed,
        "corruption_rate": corruption_rate,
        "max_errors_per_cell": max_errors_per_cell,
        "row_count": len(original_rows),
        "column_count": len(columns),
        "total_cells": total_cells,
        "corrupted_cell_count": corruption_count,
        "corruptions": corruptions,
    }
    (output / "corruptions.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return len(original_rows), total_cells, corruption_count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a randomly corrupted copy of a benchmark dataset."
    )
    parser.add_argument(
        "dataset",
        nargs="?",
        help=(
            "one dataset name under --datasets-root, or a dataset directory; "
            "omit to generate every dataset under --datasets-root"
        ),
    )
    parser.add_argument("--datasets-root", type=Path, default=DEFAULT_DATASETS_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--corruption-rate",
        type=float,
        default=0.20,
        help="fraction of all data cells to corrupt (default: 0.20)",
    )
    parser.add_argument(
        "--max-errors-per-cell",
        type=int,
        default=5,
        help="maximum character edits applied to a selected cell (default: 5)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        datasets_root = args.datasets_root.resolve()
        if args.dataset:
            datasets = [resolve_dataset(args.dataset, datasets_root)]
        else:
            if args.output:
                raise ValueError("--output requires one explicit dataset")
            names = sorted(path.name for path in datasets_root.iterdir() if path.is_dir())
            if not names:
                raise ValueError(f"no dataset directories found in {datasets_root}")
            datasets = [resolve_dataset(name, datasets_root) for name in names]
        summaries = []
        for dataset in datasets:
            output = (
                args.output if args.output else DEFAULT_OUTPUT_ROOT / dataset.name
            ).resolve()
            row_count, total_cells, corrupted_cells = generate(
                dataset,
                output,
                args.seed,
                args.corruption_rate,
                args.max_errors_per_cell,
            )
            summaries.append((dataset.name, output, row_count, total_cells, corrupted_cells))
    except (
        OSError,
        KeyError,
        RuntimeError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        re.error,
    ) as error:
        parser.error(str(error))
    for name, output, row_count, total_cells, corrupted_cells in summaries:
        print(
            f"{name}: copied {row_count} rows and corrupted "
            f"{corrupted_cells}/{total_cells} cells in {output}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
