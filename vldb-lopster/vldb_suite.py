#!/usr/bin/env python3
"""Run and evaluate LoPSTER on pre-generated shared cases."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
from evaluator import evaluate as evaluate_shared
DEFAULT_CONFIG = HERE / "config.json"
DATASET_NAMES = (
    "adult_20", "bank_marketing_222", "census_income_kdd_117", "support2_880"
)
IGNORED_VALUES = {"", "?"}


def is_ignored(value: str) -> bool:
    return value in IGNORED_VALUES


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        columns = list(reader.fieldnames or [])
        if not columns or len(columns) != len(set(columns)):
            raise ValueError(f"{path}: CSV requires unique, non-empty headers")
        rows = list(reader)
    return columns, rows


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_config(path: Path) -> dict[str, Any]:
    root = read_json(path)
    if not isinstance(root, dict) or set(root) != {"algorithm"}:
        raise ValueError("config must contain only an algorithm object")
    if not isinstance(root["algorithm"], dict):
        raise ValueError("algorithm must be an object")
    algorithm = root["algorithm"]
    for field in ("seed", "training_max_rows", "epochs", "latent_dimension", "operators", "batch_size"):
        if type(algorithm.get(field)) is not int or algorithm[field] < (0 if field == "seed" else 1):
            raise ValueError(f"algorithm.{field} must be a non-negative seed or positive integer")
    for field in ("learning_rate", "validation_fraction", "missing_value_replacement"):
        if type(algorithm.get(field)) not in (int, float):
            raise ValueError(f"algorithm.{field} must be numeric")
    if algorithm["learning_rate"] <= 0:
        raise ValueError("algorithm.learning_rate must be positive")
    if not 0 < algorithm["validation_fraction"] < 1:
        raise ValueError("algorithm.validation_fraction must be between zero and one")
    if algorithm["latent_dimension"] % algorithm["operators"]:
        raise ValueError("algorithm.latent_dimension must be divisible by algorithm.operators")
    if type(algorithm.get("reuse_model")) is not bool:
        raise ValueError("algorithm.reuse_model must be boolean")
    if not isinstance(algorithm.get("model_cache"), str) or not algorithm["model_cache"]:
        raise ValueError("algorithm.model_cache must be a non-empty string")
    return root



def resolved_roots(config_path: Path, config: dict[str, Any]) -> tuple[Path, Path]:
    datasets = (HERE.parent / "vldb_shared" / "datasets").resolve()
    default_root = "generated-90" if config_path.stem.endswith("-90") else "generated-50"
    output = (HERE / os.getenv("VLDB_CASES_ROOT", default_root)).resolve()
    return datasets, output


def run_algorithm(config_path: Path, names: list[str]) -> None:
    config = load_config(config_path)
    datasets, output = resolved_roots(config_path, config)
    algorithm_config = config["algorithm"]
    from lopster_runner import check_environment, run as run_lopster
    check_environment()
    schemas = read_json(HERE / "schemas.json")
    cache_root = require_suite_path(
        HERE / algorithm_config["model_cache"], "model cache")
    timer = RunProgress(len(names))
    timer.start()
    try:
        for name in names:
            case = output / name
            timer.begin_case(name)
            run_dir = case / "run"
            repaired = run_dir / "repaired.csv"
            telemetry = run_dir / "telemetry.json"
            if run_dir.exists():
                raise FileExistsError(f"refusing to overwrite output for {name}")
            case_data = read_json(case / "case.json")
            run_lopster(
                case, datasets / name / "clean.csv", run_dir, algorithm_config,
                schemas[name], set(case_data["source_row_indices"]), cache_root,
            )
            evaluate(case, repaired, run_dir / "benchmark.json", telemetry,
                     read_json(run_dir / "algorithm-config.json"))
            timer.complete_case()
            print(f"{name}: wrote repaired.csv, telemetry.json, and benchmark.json")
    finally:
        timer.close()


def require_suite_path(path: Path, label: str) -> Path:
    resolved = path.resolve()
    suite = HERE.resolve()
    if resolved == suite or suite not in resolved.parents:
        raise ValueError(f"{label} must be a child of {suite}")
    return resolved



def clean_outputs(config_path: Path, builds: bool) -> None:
    config = load_config(config_path)
    _, output = resolved_roots(config_path, config)
    if output.exists():
        for dataset in DATASET_NAMES:
            run_dir = output / dataset / "run"
            if run_dir.exists():
                shutil.rmtree(run_dir)
                print(f"removed {run_dir}")
    targets = []
    if builds:
        targets.append(require_suite_path(HERE / "build", "build directory"))
        targets.append(require_suite_path(
            HERE / str(config["algorithm"]["model_cache"]), "model cache"))
    for target in targets:
        if target.exists():
            shutil.rmtree(target)
            print(f"removed {target}")



def evaluate(case_dir: Path, repaired_path: Path, output_path: Path,
             telemetry_path: Path | None, algorithm_config: dict[str, Any]) -> dict[str, Any]:
    result = evaluate_shared(case_dir, repaired_path, telemetry_path, algorithm_config)
    write_json(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("run",):
        child = sub.add_parser(command)
        # Do not combine nargs="*" with choices here. Some Python/argparse
        # versions validate the empty default list itself as a choice.
        child.add_argument("datasets", nargs="*", metavar="DATASET")
        child.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    for command in ("clean", "clean-results", "clean-models"):
        cleaner = sub.add_parser(command)
        cleaner.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    scoring = sub.add_parser("evaluate")
    scoring.add_argument("case_dir", type=Path)
    scoring.add_argument("repaired_csv", type=Path)
    scoring.add_argument("--telemetry", type=Path)
    scoring.add_argument("--output", type=Path)
    scoring.add_argument("--algorithm-config", type=Path, required=True)
    args = parser.parse_args()
    if hasattr(args, "datasets"):
        invalid = [name for name in args.datasets if name not in DATASET_NAMES]
        if invalid:
            parser.error(
                f"unknown dataset {invalid[0]!r}; choose from "
                + ", ".join(DATASET_NAMES)
            )
    if args.command == "evaluate":
        result = evaluate(args.case_dir.resolve(), args.repaired_csv.resolve(),
                          (args.output or args.case_dir / "benchmark.json").resolve(),
                          args.telemetry.resolve() if args.telemetry else None,
                          read_json(args.algorithm_config.resolve()))
        print(json.dumps(result["table"], indent=2))
        return 0
    if args.command in ("clean", "clean-results"):
        clean_outputs(args.config, builds=args.command == "clean")
        return 0
    if args.command == "clean-models":
        target = require_suite_path(
            HERE / str(load_config(args.config)["algorithm"]["model_cache"]), "model cache")
        if target.exists():
            shutil.rmtree(target)
            print(f"removed {target}")
        return 0
    config = load_config(args.config)
    _, output = resolved_roots(args.config, config)
    names = args.datasets or list(DATASET_NAMES)
    output.mkdir(parents=True, exist_ok=True)
    run_algorithm(args.config, names)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError, re.error,
    ) as error:
        raise SystemExit(f"error: {error}") from error
