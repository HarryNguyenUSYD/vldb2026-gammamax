"""Run and summarize the Adult column-batch benchmark."""

from __future__ import annotations

import csv
import io
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
CASES = ROOT / "shared-suite" / "test-cases" / "test-cases.json"
CONFIG = ROOT / "suite-config.json"
RESULTS = ROOT / "results"
EXE_SUFFIX = ".exe" if os.name == "nt" else ""
GAMMAMAX = BUILD / f"gammamax{EXE_SUFFIX}"


class OverallTimer:
    """Render elapsed benchmark time and completed column cases once per second."""

    def __init__(self, total_cases: int, total_cells: int) -> None:
        self.total_cases = total_cases
        self.total_cells = total_cells
        self.completed_cases = 0
        self.fixed_cells = 0
        self.started = time.monotonic()
        self._line_width = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _text(self) -> str:
        elapsed = int(time.monotonic() - self.started)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        return (
            f"[{hours:02d}:{minutes:02d}:{seconds:02d}] overall: "
            f"completed {self.completed_cases}/{self.total_cases} column cases; "
            f"cells fixed {self.fixed_cells}/{self.total_cells}"
        )

    def _write(self, permanent: bool = False) -> None:
        text = self._text()
        padding = " " * max(0, self._line_width - len(text))
        sys.stdout.write("\r" + text + padding + ("\n" if permanent else ""))
        sys.stdout.flush()
        self._line_width = 0 if permanent else len(text)

    def _run(self) -> None:
        while not self._stop.wait(1.0):
            with self._lock:
                self._write()

    def start(self) -> None:
        with self._lock:
            self._write()
        self._thread.start()

    def complete_case(self, column: str, fixed: int, total: int) -> None:
        with self._lock:
            self.completed_cases += 1
            self.fixed_cells += fixed
            self._write(permanent=True)
            print(f"    {column}: {fixed}/{total} cells fixed", flush=True)

    def close(self) -> None:
        self._stop.set()
        self._thread.join()
        with self._lock:
            if self._line_width:
                self._write(permanent=True)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def worker_count() -> int:
    configured = int(load_json(CONFIG)["workers"])
    if configured != -1:
        if configured < 1:
            raise ValueError("workers must be -1 or positive")
        return configured
    try:
        affinity = os.sched_getaffinity(0)
        if affinity:
            return len(affinity)
    except (AttributeError, OSError):
        pass
    return os.cpu_count() or 1


def oracle_path(column: str) -> Path:
    return BUILD / f"oracle_{column}{EXE_SUFFIX}"


def algorithm_config(config: dict[str, Any], column: str) -> dict[str, Any]:
    settings = config["gammamax"]
    return {
        "seed": int(config["seed"]),
        "cell_timeout_seconds": int(config["cell_timeout_seconds"]),
        "oracle": {"executable": str(oracle_path(column).resolve())},
        "state_merging": {"k": int(settings["k_values"][0])},
        "repair": {
            "n": int(settings["n_values"][0]),
            "rsr_batch_size": int(settings["rsr_batch_size"]),
            "ngrams_batch_size": int(settings["ngrams_batch_size"]),
            "max_candidate_length": int(settings["max_candidate_length"]),
        },
        "limits": {
            "max_iterations": int(settings["max_iterations"]),
            "max_total_oracle_calls": int(settings["max_total_oracle_calls"]),
            "max_positive_examples": int(settings["max_positive_examples"]),
            "max_states": int(settings["max_states"]),
            "max_queue_size": int(settings["max_queue_size"]),
        },
    }


def oracle_accepts(executable: Path, value: str) -> bool:
    completed = subprocess.run([str(executable.resolve())], input=value.encode(),
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if completed.returncode not in (0, 1):
        raise RuntimeError(f"oracle exited with {completed.returncode}")
    return completed.returncode == 0


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for row, left_character in enumerate(left, 1):
        current = [row]
        for column, right_character in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + (left_character != right_character)))
        previous = current
    return previous[-1]


def execute_case(index: int, case: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    fatal_error = ""
    parsed: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix=f"adult-{case['column']}-") as directory:
        working = Path(directory)
        (working / "input.json").write_text(json.dumps({
            "positive_examples": case["positive_examples"],
            "negative_examples": case["negative_examples"],
            "corrupt_strings": case["corrupt_cells"],
        }, indent=2) + "\n", encoding="utf-8")
        (working / "config.json").write_text(
            json.dumps(algorithm_config(config, case["column"]), indent=2) + "\n",
            encoding="utf-8")
        completed = subprocess.run([str(GAMMAMAX.resolve())], cwd=working,
                                   capture_output=True, text=True)
        if completed.returncode:
            fatal_error = completed.stderr.strip() or f"process exited {completed.returncode}"
        else:
            try:
                parsed = json.loads(completed.stdout)
            except (json.JSONDecodeError, TypeError) as error:
                fatal_error = f"invalid GammaMax output: {error}"

    cells: list[dict[str, Any]] = []
    raw_results = parsed.get("results", []) if not fatal_error else []
    if not fatal_error and len(raw_results) != len(case["corrupt_cells"]):
        fatal_error = "GammaMax returned the wrong number of cell results"
    validator = oracle_path(case["column"])
    for cell_index, (corrupt, source) in enumerate(zip(case["corrupt_cells"], case["clean_sources"])):
        raw = raw_results[cell_index] if cell_index < len(raw_results) else {}
        output = raw.get("output_string")
        error = raw.get("error") or fatal_error
        timed_out = bool(raw.get("timed_out", False))
        fixed = False
        if not error and isinstance(output, str):
            try:
                fixed = oracle_accepts(validator, output)
            except RuntimeError as exception:
                error = str(exception)
        cells.append({
            "cell_index": cell_index,
            "corrupt_cell": corrupt,
            "clean_source": source,
            "output_cell": output,
            "fixed": fixed,
            "exact_restoration": fixed and output == source,
            "observed_edit_distance": edit_distance(corrupt, output) if isinstance(output, str) else None,
            "timed_out": timed_out,
            "error": error,
            "repair_time_ns": raw.get("repair_time_ns"),
            "measurements": raw.get("measurements", {}),
        })

    fixed = sum(cell["fixed"] for cell in cells)
    exact = sum(cell["exact_restoration"] for cell in cells)
    measurement_fields = {
        key for cell in cells for key, value in cell["measurements"].items()
        if isinstance(value, int) and not isinstance(value, bool)
    }
    measurement_totals = {
        key: sum(int(cell["measurements"].get(key, 0)) for cell in cells)
        for key in sorted(measurement_fields)
    }
    return {
        "case_index": index,
        "case_id": case["case_id"],
        "column": case["column"],
        "cells_fixed": fixed,
        "total_cells": len(cells),
        "accuracy": fixed / len(cells),
        "exact_restorations": exact,
        "exact_restoration_rate": exact / len(cells),
        "timeouts": sum(cell["timed_out"] for cell in cells),
        "errors": sum(bool(cell["error"]) and not cell["timed_out"] for cell in cells),
        "wall_time_seconds": time.perf_counter() - started,
        "peak_memory_bytes": parsed.get("peak_memory_bytes"),
        "total_execution_time_ns": parsed.get("total_execution_time_ns"),
        "shared_preprocessing": parsed.get("shared_preprocessing", {}),
        "measurement_totals": measurement_totals,
        "cell_results": cells,
        "fatal_error": fatal_error,
    }


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def write_results(
    rows: list[dict[str, Any]], stem: str, planned_cases: int,
    announce: bool = False,
) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    csv_path = RESULTS / f"{stem}.csv"
    fields = ["case_index", "case_id", "column", "cells_fixed", "total_cells",
              "accuracy", "exact_restorations", "exact_restoration_rate", "timeouts",
              "errors", "wall_time_seconds", "peak_memory_bytes",
              "total_execution_time_ns", "shared_preprocessing", "cell_results", "fatal_error"]
    fields.insert(-2, "measurement_totals")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        serialized = dict(row)
        serialized["shared_preprocessing"] = json.dumps(row["shared_preprocessing"], sort_keys=True)
        serialized["measurement_totals"] = json.dumps(row["measurement_totals"], sort_keys=True)
        serialized["cell_results"] = json.dumps(row["cell_results"], sort_keys=True)
        writer.writerow(serialized)
    atomic_write(csv_path, stream.getvalue())

    total_fixed = sum(row["cells_fixed"] for row in rows)
    total_cells = sum(row["total_cells"] for row in rows)
    summary = {
        "test_cases": len(rows),
        "planned_test_cases": planned_cases,
        "completed_test_cases": len(rows),
        "run_complete": len(rows) == planned_cases,
        "total_cells": total_cells,
        "cells_fixed": total_fixed,
        "overall_accuracy": total_fixed / total_cells if total_cells else None,
        "macro_average_accuracy": (
            statistics.fmean(row["accuracy"] for row in rows) if rows else None
        ),
        "exact_restorations": sum(row["exact_restorations"] for row in rows),
        "timeouts": sum(row["timeouts"] for row in rows),
        "errors": sum(row["errors"] for row in rows),
        "algorithm_measurement_totals": {
            key: sum(row["measurement_totals"].get(key, 0) for row in rows)
            for key in sorted({key for row in rows for key in row["measurement_totals"]})
        },
        "results": rows,
    }
    atomic_write(
        RESULTS / f"{stem}-summary.json", json.dumps(summary, indent=2) + "\n"
    )
    if announce:
        print(
            f"wrote {csv_path} and {stem}-summary.json: "
            f"{total_fixed}/{total_cells} cells fixed"
        )


def run_benchmark(workers: int, case_limit: int | None = None,
                  result_stem: str = "benchmark") -> None:
    cases = load_json(CASES)
    config = load_json(CONFIG)
    if case_limit is not None:
        cases = cases[:case_limit]
    required = [GAMMAMAX, *(oracle_path(case["column"]) for case in cases)]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("run make first; missing:\n  " + "\n  ".join(missing))
    rows: list[dict[str, Any]] = []
    write_results(rows, result_stem, len(cases))
    timer = OverallTimer(
        len(cases), sum(len(case["corrupt_cells"]) for case in cases)
    )
    timer.start()
    try:
        with ProcessPoolExecutor(max_workers=min(workers, len(cases))) as pool:
            futures = {pool.submit(execute_case, index, case, config): case["column"]
                       for index, case in enumerate(cases)}
            for future in as_completed(futures):
                row = future.result()
                rows.append(row)
                rows.sort(key=lambda result: result["case_index"])
                write_results(rows, result_stem, len(cases))
                timer.complete_case(
                    row["column"], row["cells_fixed"], row["total_cells"]
                )
    finally:
        timer.close()
    write_results(rows, result_stem, len(cases), announce=True)
