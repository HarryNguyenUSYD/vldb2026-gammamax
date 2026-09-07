#!/usr/bin/env python3
"""Build, run, and evaluate GammaMax with shallow decision tree imputation on pre-generated shared cases."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
from evaluator import evaluate as evaluate_shared, write_example_summary
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
    for section in ("state_merging", "repair", "batching", "limits", "imputation"):
        if not isinstance(algorithm.get(section), dict):
            raise ValueError(f"algorithm.{section} must be an object")
    required_positive = {
        "state_merging": ("k",),
        "repair": ("n", "ngrams_batch_size"),
        "batching": ("cell_timeout_seconds",),
    }
    for section, fields in required_positive.items():
        for field in fields:
            value = algorithm[section].get(field)
            if type(value) is not int or value < 1:
                raise ValueError(f"algorithm.{section}.{field} must be a positive integer")
    for section, fields in {
        "repair": ("max_candidate_length",),
        "batching": ("negative_capacity", "max_positive_examples"),
        "limits": ("max_iterations", "max_total_oracle_calls", "max_states",
                   "max_queue_size", "max_rsr_candidates"),
    }.items():
        for field in fields:
            value = algorithm[section].get(field)
            if type(value) is not int or (value != -1 and value < 1):
                raise ValueError(f"algorithm.{section}.{field} must be positive or -1")
    if type(algorithm.get("seed")) is not int or algorithm["seed"] < 0:
        raise ValueError("algorithm.seed must be non-negative")
    bounds = {"max_depth": (0, 5), "min_samples_leaf": (1, 2**64 - 1),
              "max_thresholds": (1, 32), "max_decimal_places": (0, 15)}
    if set(algorithm["imputation"]) != set(bounds):
        raise ValueError("algorithm.imputation contains missing or unsupported fields")
    for field, (low, high) in bounds.items():
        value = algorithm["imputation"][field]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"algorithm.imputation.{field} must be an integer in [{low}, {high}]")
    return root



def resolved_roots(config_path: Path, config: dict[str, Any]) -> tuple[Path, Path]:
    default_root = "generated-90" if config_path.stem.endswith("-90") else "generated-50"
    output = (HERE / os.getenv("VLDB_CASES_ROOT", default_root)).resolve()
    return HERE, output


def cmake_build(source: Path, build: Path, target: str) -> Path:
    cmake = os.getenv("CMAKE", "cmake")
    suffix = ".exe" if os.name == "nt" else ""
    if shutil.which(cmake):
        subprocess.run([cmake, "-S", str(source), "-B", str(build), "-DBUILD_TESTING=ON"], check=True)
        subprocess.run([cmake, "--build", str(build), "--config", "Release", "--target", target], check=True)
        matches = list(build.rglob(target + suffix))
        if not matches:
            raise FileNotFoundError(f"build did not produce {target}{suffix}")
        return matches[0]
    return direct_build(source, build, target)


def cxx_compiler() -> str:
    configured = os.getenv("CXX")
    candidates = [configured] if configured else []
    candidates.extend(["c++", "clang++", "g++"])
    for candidate in candidates:
        if candidate and shutil.which(candidate):
            return candidate
    raise RuntimeError(
        "neither CMake nor a C++20 compiler was found; on macOS run "
        "'xcode-select --install', or set CXX to a compiler path"
    )


def direct_build(source: Path, build: Path, target: str) -> Path:
    compiler = cxx_compiler()
    build.mkdir(parents=True, exist_ok=True)
    output = build / (target + (".exe" if os.name == "nt" else ""))
    if target == "vldb_theory_oracle":
        source_file = source / "main.cpp"
        includes = [HERE / "algorithm" / "vendor"]
    elif target == "vldb_theory_algorithm":
        source_file = source / "src" / "main.cpp"
        includes = [source / "include", source / "vendor"]
    elif target == "vldb_theory_algorithm_tests":
        source_file = source / "tests" / "tests.cpp"
        includes = [source / "include", source / "vendor"]
    else:
        raise ValueError(f"direct build does not know target {target!r}")
    command = [compiler, "-std=c++20", "-O2", str(source_file), "-o", str(output)]
    for include in includes:
        command.extend(["-I", str(include)])
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True)
    if completed.returncode:
        raise RuntimeError(
            f"C++ build failed for {target} (exit {completed.returncode}):\n"
            f"{completed.stdout.strip()}"
        )
    if completed.stdout:
        print(completed.stdout, end="")
    return output


def build_algorithm() -> Path:
    return cmake_build(HERE / "algorithm", HERE / "build" / "algorithm", "vldb_theory_algorithm")


def test_algorithm() -> None:
    source = HERE / "algorithm"
    build = HERE / "build" / "algorithm"
    binary = cmake_build(source, build, "vldb_theory_algorithm_tests")
    subprocess.run([str(binary)], check=True)


def oracle_case(output: Path, name: str) -> Path:
    if output.name in {"generated-50", "generated-90"}:
        return HERE / "shared-generation" / name
    return output / name


def build_oracles(output: Path, names: list[str]) -> None:
    binary = cmake_build(HERE / "oracle", HERE / "build" / "oracle", "vldb_theory_oracle")
    suffix = binary.suffix
    for name in names:
        case = oracle_case(output, name)
        manifest = read_json(case / "oracles.json")
        destination = case / "compiled-oracles"
        destination.mkdir(parents=True, exist_ok=True)
        for index, spec in enumerate(manifest["oracles"]):
            stem = f"oracle_{index:03d}"
            shutil.copy2(binary, destination / (stem + suffix))
            write_json(destination / f"{stem}.json", spec)
        print(f"{name}: built {len(manifest['oracles'])} external oracles")


class RunProgress:
    def __init__(self, total_cases: int) -> None:
        self.total_cases = total_cases
        self.completed_cases = 0
        self.case_name = "preparing"
        self.completed_cells = 0
        self.total_cells = 0
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.line_width = 0

    def _text(self) -> str:
        elapsed = int(time.monotonic() - self.started)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        return (
            f"[{hours:02d}:{minutes:02d}:{seconds:02d}] {self.case_name}: cells "
            f"{self.completed_cells}/{self.total_cells}; test cases "
            f"{self.completed_cases}/{self.total_cases}"
        )

    def _write(self, permanent: bool = False) -> None:
        message = self._text()
        padding = " " * max(0, self.line_width - len(message))
        sys.stdout.write("\r" + message + padding + ("\n" if permanent else ""))
        sys.stdout.flush()
        self.line_width = 0 if permanent else len(message)

    def _run(self) -> None:
        while not self.stop.wait(1.0):
            with self.lock:
                self._write()

    def start(self) -> None:
        with self.lock:
            self._write()
        self.thread.start()

    def begin_case(self, name: str, total_cells: int) -> None:
        with self.lock:
            self.case_name = name
            self.completed_cells = 0
            self.total_cells = total_cells
            self._write()

    def update_cells(self, completed: int, total: int) -> None:
        with self.lock:
            self.completed_cells = completed
            self.total_cells = total

    def complete_case(self) -> None:
        with self.lock:
            self.completed_cells = self.total_cells
            self.completed_cases += 1
            self._write(permanent=True)

    def close(self) -> None:
        self.stop.set()
        self.thread.join()
        with self.lock:
            if self.line_width:
                self._write(permanent=True)


def run_algorithm(config_path: Path, names: list[str]) -> None:
    config = load_config(config_path)
    _, output = resolved_roots(config_path, config)
    binary = build_algorithm()
    timer = RunProgress(len(names))
    timer.start()
    try:
        for name in names:
            case = output / name
            case_data = read_json(case / "case.json")
            timer.begin_case(name, int(case_data["row_count"]) * int(case_data["column_count"]))
            repaired = case / "repaired.csv"
            telemetry = case / "telemetry.json"
            if repaired.exists() or telemetry.exists():
                raise FileExistsError(f"refusing to overwrite algorithm output for {name}")
            process = subprocess.Popen([
                str(binary), "--input", str(case / "corrupted.csv"),
                "--config", str(output / "algorithm-config.json"),
                "--oracles-dir", str(oracle_case(output, name) / "compiled-oracles"),
                "--output", str(repaired), "--telemetry", str(telemetry),
            ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1)
            diagnostics = []
            assert process.stderr is not None
            for line in process.stderr:
                stripped = line.rstrip("\r\n")
                match = re.fullmatch(r"VLDB_PROGRESS (\d+) (\d+)", stripped)
                if match:
                    timer.update_cells(int(match.group(1)), int(match.group(2)))
                elif stripped:
                    diagnostics.append(stripped)
            stdout = process.stdout.read() if process.stdout is not None else ""
            return_code = process.wait()
            if return_code:
                detail = "\n".join(diagnostics) or stdout.strip() or f"exit status {return_code}"
                raise RuntimeError(f"algorithm failed for {name}: {detail}")
            evaluate(case, repaired, case / "benchmark.json", telemetry)
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
    for dataset in DATASET_NAMES:
        case = output / dataset
        for filename in ("repaired.csv", "telemetry.json", "benchmark.json"):
            target = case / filename
            if target.exists():
                target.unlink()
                print(f"removed {target}")
        compiled = oracle_case(output, dataset) / "compiled-oracles"
        if builds and compiled.exists():
            shutil.rmtree(compiled)
            print(f"removed {compiled}")
    targets = []
    if builds:
        targets.append(require_suite_path(HERE / "build", "build directory"))
    for target in targets:
        if target.exists():
            shutil.rmtree(target)
            print(f"removed {target}")



def evaluate(case_dir: Path, repaired_path: Path, output_path: Path,
             telemetry_path: Path | None) -> dict[str, Any]:
    result = evaluate_shared(
        case_dir, repaired_path, telemetry_path,
        read_json(case_dir.parent / "algorithm-config.json"),
    )
    write_json(output_path, result)
    write_example_summary(HERE)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("build-oracles", "run"):
        child = sub.add_parser(command)
        # Do not combine nargs="*" with choices here. Some Python/argparse
        # versions validate the empty default list itself as a choice.
        child.add_argument("datasets", nargs="*", metavar="DATASET")
        child.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub.add_parser("build-algorithm")
    sub.add_parser("test-algorithm")
    for command in ("clean", "clean-results"):
        cleaner = sub.add_parser(command)
        cleaner.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    scoring = sub.add_parser("evaluate")
    scoring.add_argument("case_dir", type=Path)
    scoring.add_argument("repaired_csv", type=Path)
    scoring.add_argument("--telemetry", type=Path)
    scoring.add_argument("--output", type=Path)
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
                          args.telemetry.resolve() if args.telemetry else None)
        print(json.dumps(result["table"], indent=2))
        return 0
    if args.command == "build-algorithm":
        print(build_algorithm())
        return 0
    if args.command == "test-algorithm":
        test_algorithm()
        print("C++ algorithm tests passed")
        return 0
    if args.command in ("clean", "clean-results"):
        clean_outputs(args.config, builds=args.command == "clean")
        return 0
    config = load_config(args.config)
    _, output = resolved_roots(args.config, config)
    names = args.datasets or list(DATASET_NAMES)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "algorithm-config.json", config["algorithm"])
    if args.command == "build-oracles":
        build_oracles(output, names)
    else:
        run_algorithm(args.config, names)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError, ValueError, KeyError, RuntimeError, subprocess.CalledProcessError,
        json.JSONDecodeError, re.error,
    ) as error:
        raise SystemExit(f"error: {error}") from error
