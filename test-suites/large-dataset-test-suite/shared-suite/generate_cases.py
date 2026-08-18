#!/usr/bin/env python3
"""Generate the deterministic Adult column-repair benchmark corpus."""

from __future__ import annotations

import csv
import json
import math
import random
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent
SUITE = ROOT.parent
CONFIG_PATH = SUITE / "suite-config.json"
DATASET = SUITE / "datasets" / "adult_20"
OUTPUT = ROOT / "test-cases"
MISSING = {"", "?", "NA", "NaN", "nan", "null", "None"}


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for row, left_character in enumerate(left, 1):
        current = [row]
        for column, right_character in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (left_character != right_character),
            ))
        previous = current
    return previous[-1]


def predicate(spec: dict[str, Any]) -> Callable[[str], bool]:
    kind = spec["type"]
    if kind == "list":
        allowed = set(spec["values"])
        return lambda value: value in allowed
    if kind == "integer":
        minimum, maximum = int(spec["minimum"]), int(spec["maximum"])

        def accepts_integer(value: str) -> bool:
            try:
                return value.strip() == value and minimum <= int(value, 10) <= maximum
            except ValueError:
                return False

        return accepts_integer
    if kind == "real":
        minimum, maximum = float(spec["minimum"]), float(spec["maximum"])

        def accepts_real(value: str) -> bool:
            try:
                parsed = float(value)
                return value.strip() == value and math.isfinite(parsed) and minimum <= parsed <= maximum
            except ValueError:
                return False

        return accepts_real
    raise ValueError(f"unsupported Adult oracle type: {kind}")


def mutate(source: str, accepts: Callable[[str], bool], rng: random.Random) -> tuple[str, str, int]:
    operations = ["insert", "substitute"]
    if source:
        operations.append("delete")
    for _ in range(1000):
        operation = rng.choice(operations)
        if operation == "insert":
            position = rng.randrange(len(source) + 1)
            mutant = source[:position] + "#" + source[position:]
        elif operation == "substitute":
            position = rng.randrange(len(source))
            mutant = source[:position] + "#" + source[position + 1:]
        else:
            position = rng.randrange(len(source))
            mutant = source[:position] + source[position + 1:]
        if mutant != source and edit_distance(source, mutant) == 1 and not accepts(mutant):
            return mutant, operation, position
    raise RuntimeError(f"could not create an invalid one-edit mutant for {source!r}")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    generation = config["generation"]
    rng = random.Random(int(config["seed"]))
    with (DATASET / "clean.csv").open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        columns = list(reader.fieldnames or [])
        complete = [row for row in reader if all(row[column] not in MISSING for column in columns)]

    training_fraction = float(generation["training_fraction"])
    if not 0.0 < training_fraction < 1.0:
        raise ValueError("generation.training_fraction must be between zero and one")
    sampled = list(complete)
    rng.shuffle(sampled)
    training_count = int(len(sampled) * training_fraction)
    training = sampled[:training_count]
    clean_sources = sampled[training_count:]
    corrupt_count = len(clean_sources)

    manifest = json.loads((DATASET / "oracles.json").read_text(encoding="utf-8-sig"))
    specifications = {item["column"]: item for item in manifest["oracles"]}
    corrupted = [dict(row) for row in clean_sources]
    mutations: dict[str, list[dict[str, Any]]] = {column: [] for column in columns}
    for row_index, row in enumerate(clean_sources):
        for column in columns:
            mutant, operation, position = mutate(row[column], predicate(specifications[column]), rng)
            corrupted[row_index][column] = mutant
            mutations[column].append({"operation": operation, "position": position})

    cases = []
    for column in columns:
        cases.append({
            "case_id": f"adult_20-{column}",
            "column": column,
            "positive_examples": [row[column] for row in training],
            "negative_examples": [],
            "corrupt_cells": [row[column] for row in corrupted],
            "clean_sources": [row[column] for row in clean_sources],
            "mutations": mutations[column],
            "oracle": f"{column}.cpp",
        })

    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT / "training.csv", columns, training)
    write_csv(OUTPUT / "clean-sources.csv", columns, clean_sources)
    write_csv(OUTPUT / "corrupted.csv", columns, corrupted)
    (OUTPUT / "test-cases.json").write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    print(
        f"generated 15 column cases from {training_count} training rows "
        f"and {corrupt_count} corrupted-source rows"
    )


if __name__ == "__main__":
    generate()
