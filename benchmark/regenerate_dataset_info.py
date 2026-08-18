#!/usr/bin/env python3
"""Infer column information and strict oracles from benchmark clean CSVs."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATASETS = ROOT / "datasets"
ORACLES = ROOT / "oracles"
MAX_LIST_VALUES = 2048


def numeric(text: str) -> tuple[bool, int | float]:
    try:
        if re.fullmatch(r"[-+]?\d+", text):
            return True, int(text)
        value = float(text)
        return math.isfinite(value), value
    except ValueError:
        return False, 0


def regex_class(characters: set[str]) -> str:
    escaped = []
    for character in sorted(characters):
        if character in r"\-]^":
            escaped.append("\\" + character)
        elif character == "\t":
            escaped.append(r"\t")
        elif ord(character) < 32 or ord(character) > 126:
            # Non-ASCII values are better represented by an exact list.
            raise ValueError("cannot build portable character class")
        else:
            escaped.append(character)
    return "".join(escaped)


def infer(dataset: str, column: str, values: list[str], display_name: str) -> dict:
    nonempty = [value for value in values if value != ""]
    has_empty = len(nonempty) != len(values)
    parsed = [numeric(value) for value in nonempty]
    all_numeric = bool(nonempty) and all(ok for ok, _ in parsed)
    all_integer = all_numeric and all(isinstance(value, int) for _, value in parsed)
    description = f"{display_name} column {column}"

    if all_integer and not has_empty:
        numbers = [value for _, value in parsed]
        return {
            "column": column, "description": description, "type": "integer",
            "minimum": min(numbers), "maximum": max(numbers), "output": f"{column}.cpp",
        }
    if all_numeric and not has_empty:
        numbers = [float(value) for _, value in parsed]
        return {
            "column": column, "description": description, "type": "real",
            "minimum": min(numbers), "maximum": max(numbers), "output": f"{column}.cpp",
        }

    unique = sorted(set(values))
    if len(unique) <= MAX_LIST_VALUES:
        return {
            "column": column, "description": description, "type": "list",
            "values": unique, "output": f"{column}.cpp",
        }

    if all_numeric:
        expression = (
            r"^(|[-+]?\d+)$" if all_integer else
            r"^(|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)$"
        )
    else:
        lengths = [len(value) for value in nonempty]
        characters = set("".join(nonempty))
        try:
            character_class = regex_class(characters)
            body = f"[{character_class}]{{{min(lengths)},{max(lengths)}}}"
        except ValueError:
            body = f"[^#\\r\\n]{{{min(lengths)},{max(lengths)}}}"
        expression = f"^(?:|{body})$" if has_empty else f"^{body}$"
    return {
        "column": column, "description": description, "type": "regex",
        "regex": expression, "observed_distinct_values": len(unique),
        "output": f"{column}.cpp",
    }


def read_identity(metadata: Path, fallback: str) -> tuple[str, str]:
    text = metadata.read_text(encoding="utf-8-sig") if metadata.exists() else ""
    uci = next((line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("UCI ID:")), "unknown")
    name = next((line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("Name:")), fallback)
    return uci, name


def process(dataset_dir: Path) -> tuple[int, int, list[str]]:
    csv_path = dataset_dir / "clean.csv"
    uci_id, display_name = read_identity(dataset_dir / "metadata.txt", dataset_dir.name)
    with csv_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream)
        columns = next(reader)
        values = [[] for _ in columns]
        row_count = 0
        for row_count, row in enumerate(reader, 1):
            if len(row) != len(columns):
                raise ValueError(f"{csv_path}: row {row_count + 1} has {len(row)} fields; expected {len(columns)}")
            for index, value in enumerate(row):
                values[index].append(value)

    oracles = [
        infer(dataset_dir.name, column, column_values, display_name)
        for column, column_values in zip(columns, values)
    ]
    manifest = {
        "dataset": dataset_dir.name,
        "source": "clean.csv",
        "domain_reference": "../COLUMN_VALUES.md",
        "oracles": oracles,
    }
    (dataset_dir / "oracles.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    metadata_lines = [
        f"UCI ID: {uci_id}", f"Name: {display_name}", f"Rows: {row_count}",
        f"Columns: {len(columns)}", "", "Column information:",
    ]
    summaries = []
    for oracle, column_values in zip(oracles, values):
        missing = sum(value == "" for value in column_values)
        distinct = len(set(column_values))
        kind = oracle["type"]
        if kind == "list":
            domain = f"closed list with {len(oracle['values'])} values"
        elif kind in ("integer", "real"):
            domain = f"{kind} range {oracle['minimum']} to {oracle['maximum']}"
        else:
            domain = f"regex {oracle['regex']}"
        metadata_lines.append(
            f"{oracle['column']}: {oracle['description']}; {domain}; "
            f"distinct={distinct}; missing={missing}"
        )
        if kind == "list":
            shown = oracle["values"][:100]
            suffix = "" if len(shown) == len(oracle["values"]) else f"; ... ({len(oracle['values'])} total)"
            details = "; ".join("<empty>" if value == "" else value for value in shown) + suffix
        elif kind in ("integer", "real"):
            details = f"range {oracle['minimum']} to {oracle['maximum']}"
        else:
            details = f"regex `{oracle['regex']}`"
        summaries.append(
            f"- **{oracle['column']}** — {oracle['description']}; {kind}: {details}; "
            f"distinct={distinct}; missing={missing}."
        )
    (dataset_dir / "metadata.txt").write_text("\n".join(metadata_lines) + "\n", encoding="utf-8")

    destination = ORACLES / dataset_dir.name
    subprocess.run(
        [sys.executable, str(ORACLES / "oracle-gen.py"), str(dataset_dir / "oracles.json"), "--output-dir", str(destination)],
        check=True,
    )
    return row_count, len(columns), summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("datasets", nargs="*", help="dataset directory names; default: every directory")
    args = parser.parse_args()
    names = args.datasets or sorted(path.name for path in DATASETS.iterdir() if path.is_dir())
    domain_lines = [
        "# Benchmark dataset columns", "",
        "Domains are inferred from current clean CSV files. Closed lists contain all observed categorical values; numeric ranges contain observed extrema. No generated regex accepts every string.", "",
    ]
    for name in names:
        directory = DATASETS / name
        if not directory.is_dir():
            parser.error(f"dataset does not exist: {name}")
        rows, columns, summaries = process(directory)
        domain_lines.extend([f"## {name}", "", f"{rows} rows; {columns} columns.", "", *summaries, ""])
        print(f"{name}: {rows} rows, {columns} columns")
    (DATASETS / "COLUMN_VALUES.md").write_text("\n".join(domain_lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
