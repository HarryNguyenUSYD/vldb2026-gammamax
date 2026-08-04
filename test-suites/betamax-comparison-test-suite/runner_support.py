"""Run the same generated cases against current and legacy betaMax."""

from __future__ import annotations

import csv
import json
import os
import re
import signal
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
SHARED_SUITE = ROOT / "shared-suite"
BUILD = ROOT / "build"
CASES = SHARED_SUITE / "test-cases" / "test-cases.json"
CONFIG = SHARED_SUITE / "suite-config.json"
RESULTS = ROOT / "results"
FORMATS = ("date", "time", "url", "isbn", "ipv4", "ipv6")
EXE_SUFFIX = ".exe" if os.name == "nt" else ""
EXECUTABLES = {
    "betamax": BUILD / f"betamax{EXE_SUFFIX}",
    "betamax-old": BUILD / f"betamax-old{EXE_SUFFIX}",
}
STDIN_VALIDATORS = {
    name: BUILD / f"validate_{name}{EXE_SUFFIX}" for name in FORMATS
}
FILE_VALIDATORS = {
    name: BUILD / f"validate_old_{name}{EXE_SUFFIX}" for name in FORMATS
}
RESULT_FIELDS = (
    "implementation",
    "case_index",
    "case_id",
    "format",
    "category",
    "positive_examples",
    "negative_examples",
    "regex",
    "corrupt_string",
    "valid_source",
    "true_edit_distance",
    "output_string",
    "accuracy",
    "output_in_positive_examples",
    "observed_edit_distance",
    "total_execution_time_ns",
    "wall_time_seconds",
    "peak_memory_bytes",
    "timed_out",
    "error",
    "return_code",
    "stdout_tail",
    "stderr_tail",
)
COMPARISON_FIELDS = (
    "case_index",
    "case_id",
    "format",
    "category",
    "corrupt_string",
    "valid_source",
    "true_edit_distance",
    "outputs_equal",
    "accuracy_winner",
    "speed_winner",
    "betamax_output_string",
    "betamax_accuracy",
    "betamax_output_in_positive_examples",
    "betamax_observed_edit_distance",
    "betamax_total_execution_time_ns",
    "betamax_wall_time_seconds",
    "betamax_peak_memory_bytes",
    "betamax_timed_out",
    "betamax_error",
    "betamax_old_output_string",
    "betamax_old_accuracy",
    "betamax_old_output_in_positive_examples",
    "betamax_old_observed_edit_distance",
    "betamax_old_total_execution_time_ns",
    "betamax_old_wall_time_seconds",
    "betamax_old_peak_memory_bytes",
    "betamax_old_timed_out",
    "betamax_old_error",
)


class ProgressReporter:
    """Print algorithm and overall counters plus a once-per-second timer."""

    def __init__(
        self,
        label: str,
        algorithm_total: int,
        total_executions: int,
        total_offset: int,
        started: float,
    ) -> None:
        self.label = label
        self.algorithm_total = algorithm_total
        self.total_executions = total_executions
        self.total_offset = total_offset
        self.algorithm_completed = 0
        self.started = started
        self._line_width = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._timer, daemon=True)

    def _text(self) -> str:
        elapsed = int(time.monotonic() - self.started)
        overall_completed = self.total_offset + self.algorithm_completed
        return (
            f"[{elapsed:4d}s] {self.label}: completed "
            f"{self.algorithm_completed}/{self.algorithm_total} "
            f"(total {overall_completed}/{self.total_executions})"
        )

    def _write(self, permanent: bool) -> None:
        text = self._text()
        padding = " " * max(0, self._line_width - len(text))
        sys.stdout.write("\r" + text + padding + ("\n" if permanent else ""))
        sys.stdout.flush()
        self._line_width = 0 if permanent else len(text)

    def _timer(self) -> None:
        while not self._stop.wait(1.0):
            with self._lock:
                self._write(permanent=False)

    def start(self) -> None:
        with self._lock:
            self._write(permanent=False)
        self._thread.start()

    def advance(self) -> None:
        with self._lock:
            self.algorithm_completed += 1
            self._write(permanent=True)

    def close(self) -> None:
        self._stop.set()
        self._thread.join()
        with self._lock:
            if self._line_width:
                self._write(permanent=True)


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


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def load_cases() -> list[dict[str, Any]]:
    if not CASES.exists():
        raise FileNotFoundError(f"{CASES} does not exist; run make generate first")
    value = json.loads(CASES.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{CASES} must contain a JSON array")
    return value


def worker_count() -> int:
    try:
        affinity = os.sched_getaffinity(0)
        if affinity:
            return len(affinity)
    except (AttributeError, NotImplementedError, OSError):
        pass
    return os.cpu_count() or 1


def _ensure_binaries() -> None:
    paths = (
        *EXECUTABLES.values(),
        *STDIN_VALIDATORS.values(),
        *FILE_VALIDATORS.values(),
    )
    missing = [path for path in paths if not path.is_file()]
    if missing:
        listing = "\n".join(f"  {path}" for path in missing)
        raise FileNotFoundError("Run make first; missing executables:\n" + listing)


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
    process.kill()


def _tail(text: str, lines: int = 10) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def _current_config(
    suite_config: dict[str, Any], validator: Path, case_index: int
) -> dict[str, Any]:
    settings = suite_config["betamax"]
    return {
        "seed": (int(suite_config["seed"]) + case_index) % (1 << 64),
        "oracle": {"executable": str(validator.resolve())},
        "neighborhood_exploration": {
            "target_negative_examples": int(
                settings["neighborhood_target_negative_examples"]
            ),
            "max_oracle_calls": int(settings["neighborhood_max_oracle_calls"]),
        },
        "state_merging": {
            "cross_merge_samples": int(settings["cross_merge_samples"]),
        },
        "repair": {
            "candidate_count": int(settings["candidate_count"]),
            "match_cost": 0,
            "insertion_cost": 1,
            "deletion_cost": 1,
            "substitution_cost": 1,
            "max_candidate_length": int(settings["max_candidate_length"]),
        },
        "limits": {
            "max_iterations": int(settings["max_iterations"]),
            "max_total_oracle_calls": int(settings["max_total_oracle_calls"]),
            "max_states": int(settings["max_states"]),
            "max_queue_size": int(settings["max_queue_size"]),
        },
    }


def _write_lines(path: Path, values: list[str]) -> None:
    path.write_text("".join(value + "\n" for value in values), encoding="ascii")


def _legacy_validator_command(validator: Path) -> str:
    if os.name == "nt":
        # Preserve literal quotes through the old shlex-like parser and use
        # forward slashes so it cannot consume path separators as escapes.
        return f'\\"{validator.resolve().as_posix()}\\"'
    return f'"{validator.resolve()}"'


def _legacy_arguments(
    case_index: int,
    case: dict[str, Any],
    suite_config: dict[str, Any],
    positives: Path,
    negatives: Path,
    broken: Path,
) -> list[str]:
    settings = suite_config["betamax"]
    seed = (int(suite_config["seed"]) + case_index) % (1 << 64)
    return [
        str(EXECUTABLES["betamax-old"].resolve()),
        "--positives", str(positives),
        "--negatives", str(negatives),
        "--category", str(case["category"]),
        "--broken-file", str(broken),
        "--oracle-validator",
        _legacy_validator_command(FILE_VALIDATORS[case["format"]]),
        "--mutations", str(settings["neighborhood_target_negative_examples"]),
        "--mutations-seed", str(seed),
        "--xover-pairs", str(settings["cross_merge_samples"]),
        "--max-attempts", str(settings["max_iterations"]),
        "--attempt-candidates", str(settings["candidate_count"]),
        "--max-cost", "-1",
        "--max-candidates", str(settings["candidate_count"]),
        "--seed", str(seed),
    ]


def _launch(
    arguments: list[str], working_directory: Path, timeout: float
) -> tuple[str, str, int, bool]:
    process = subprocess.Popen(
        arguments,
        cwd=working_directory,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=(os.name == "posix"),
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(process)
        stdout, stderr = process.communicate()
    return stdout, stderr, process.returncode, timed_out


def execute_case(
    implementation: str,
    case_index: int,
    case: dict[str, Any],
    suite_config: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    timeout = float(suite_config["case_timeout_seconds"])
    timed_out = False
    stdout = ""
    stderr = ""
    return_code: int | None = None
    output = ""
    execution_time: int | str = ""
    peak_memory: int | str = ""
    error = ""

    try:
        with tempfile.TemporaryDirectory(prefix=f"{implementation}-") as directory:
            working_directory = Path(directory)
            if implementation == "betamax":
                input_json = {
                    "positive_examples": case["positive_examples"],
                    "negative_examples": case["negative_examples"],
                    "corrupt_string": case["corrupt_string"],
                }
                config_json = _current_config(
                    suite_config, STDIN_VALIDATORS[case["format"]], case_index
                )
                (working_directory / "input.json").write_text(
                    json.dumps(input_json, indent=2) + "\n", encoding="utf-8"
                )
                (working_directory / "config.json").write_text(
                    json.dumps(config_json, indent=2) + "\n", encoding="utf-8"
                )
                arguments = [str(EXECUTABLES["betamax"].resolve())]
            elif implementation == "betamax-old":
                positives = working_directory / "positives.txt"
                negatives = working_directory / "negatives.txt"
                broken = working_directory / "broken.txt"
                _write_lines(positives, case["positive_examples"])
                _write_lines(negatives, case["negative_examples"])
                with broken.open("w", encoding="ascii", newline="") as stream:
                    stream.write(case["corrupt_string"])
                arguments = _legacy_arguments(
                    case_index, case, suite_config, positives, negatives, broken
                )
            else:
                raise ValueError(f"unknown implementation: {implementation}")

            stdout, stderr, return_code, timed_out = _launch(
                arguments, working_directory, timeout
            )

        if timed_out:
            error = f"Algorithm exceeded {timeout:g} seconds."
        elif return_code != 0:
            error = f"Process exited with code {return_code}."
        elif implementation == "betamax":
            parsed = json.loads(stdout)
            required = {
                "output_string", "peak_memory_bytes", "total_execution_time_ns"
            }
            if not isinstance(parsed, dict) or set(parsed) != required:
                raise ValueError("betaMax stdout has an unexpected JSON shape")
            if not isinstance(parsed["output_string"], str):
                raise ValueError("betaMax output_string is not a string")
            if not isinstance(parsed["peak_memory_bytes"], int):
                raise ValueError("betaMax peak_memory_bytes is not an integer")
            if not isinstance(parsed["total_execution_time_ns"], int):
                raise ValueError("betaMax total_execution_time_ns is not an integer")
            output = parsed["output_string"]
            execution_time = parsed["total_execution_time_ns"]
            peak_memory = parsed["peak_memory_bytes"]
        else:
            output = stdout[:-1] if stdout.endswith("\n") else stdout
            if output.endswith("\r"):
                output = output[:-1]
            if "\n" in output or "\r" in output:
                raise ValueError("betamax-old emitted more than one stdout line")
    except Exception as exception:
        error = f"{type(exception).__name__}: {exception}"

    elapsed = time.perf_counter() - started
    accepted = not error and re.fullmatch(case["regex"], output) is not None
    if not error and not accepted:
        error = "Repair was rejected by the format validator."

    return {
        "implementation": implementation,
        "case_index": case_index,
        "case_id": case["case_id"],
        "format": case["format"],
        "category": case["category"],
        "positive_examples": json.dumps(case["positive_examples"], separators=(",", ":")),
        "negative_examples": json.dumps(case["negative_examples"], separators=(",", ":")),
        "regex": case["regex"],
        "corrupt_string": case["corrupt_string"],
        "valid_source": case["valid_source"],
        "true_edit_distance": case["true_edit_distance"],
        "output_string": output,
        "accuracy": int(accepted),
        "output_in_positive_examples": int(output in case["positive_examples"]),
        "observed_edit_distance": edit_distance(case["corrupt_string"], output),
        "total_execution_time_ns": execution_time,
        "wall_time_seconds": elapsed,
        "peak_memory_bytes": peak_memory,
        "timed_out": int(timed_out),
        "error": error,
        "return_code": "" if return_code is None else return_code,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
    }


def _run_phase(
    implementation: str,
    cases: list[dict[str, Any]],
    config: dict[str, Any],
    workers: int,
    total_offset: int,
    total_executions: int,
    timer_started: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any] | None] = [None] * len(cases)
    print(f"{implementation}: {len(cases)} cases, {workers} workers", flush=True)
    progress = ProgressReporter(
        implementation, len(cases), total_executions, total_offset, timer_started
    )
    progress.start()
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(execute_case, implementation, index, case, config): index
                for index, case in enumerate(cases)
            }
            for future in as_completed(futures):
                index = futures[future]
                rows[index] = future.result()
                progress.advance()
    finally:
        progress.close()
    return [row for row in rows if row is not None]


def _comparison_rows(
    current: list[dict[str, Any]], legacy: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if len(current) != len(legacy):
        raise ValueError("implementation result counts differ")
    rows: list[dict[str, Any]] = []
    for new, old in zip(current, legacy):
        if new["case_id"] != old["case_id"]:
            raise ValueError("implementation results are not case-aligned")
        if new["accuracy"] == old["accuracy"]:
            accuracy_winner = "tie"
        elif new["accuracy"]:
            accuracy_winner = "betamax"
        else:
            accuracy_winner = "betamax-old"

        comparable_speed = (
            new["accuracy"] and old["accuracy"] and
            not new["timed_out"] and not old["timed_out"]
        )
        if not comparable_speed:
            speed_winner = ""
        elif new["wall_time_seconds"] == old["wall_time_seconds"]:
            speed_winner = "tie"
        elif new["wall_time_seconds"] < old["wall_time_seconds"]:
            speed_winner = "betamax"
        else:
            speed_winner = "betamax-old"

        row = {
            "case_index": new["case_index"],
            "case_id": new["case_id"],
            "format": new["format"],
            "category": new["category"],
            "corrupt_string": new["corrupt_string"],
            "valid_source": new["valid_source"],
            "true_edit_distance": new["true_edit_distance"],
            "outputs_equal": int(new["output_string"] == old["output_string"]),
            "accuracy_winner": accuracy_winner,
            "speed_winner": speed_winner,
        }
        for prefix, result in (("betamax", new), ("betamax_old", old)):
            for field in (
                "output_string", "accuracy", "output_in_positive_examples",
                "observed_edit_distance", "total_execution_time_ns",
                "wall_time_seconds", "peak_memory_bytes", "timed_out", "error",
            ):
                row[f"{prefix}_{field}"] = result[field]
        rows.append(row)
    return rows


def _write_csv(
    path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wall_times = [float(row["wall_time_seconds"]) for row in rows]
    return {
        "cases": len(rows),
        "accepted_repairs": sum(int(row["accuracy"]) for row in rows),
        "timeouts": sum(int(row["timed_out"]) for row in rows),
        "errors": sum(bool(row["error"]) for row in rows),
        "outputs_in_positive_examples": sum(
            int(row["output_in_positive_examples"]) for row in rows
        ),
        "mean_wall_time_seconds": statistics.fmean(wall_times) if wall_times else 0,
        "median_wall_time_seconds": statistics.median(wall_times) if wall_times else 0,
    }


def run_benchmark(
    workers: int,
    case_limit: int | None = None,
    result_stem: str = "benchmark",
) -> None:
    if workers < 1:
        raise ValueError("workers must be at least 1")
    _ensure_binaries()
    cases = load_cases()
    if case_limit is not None:
        if case_limit < 1:
            raise ValueError("case_limit must be at least 1")
        cases = cases[:case_limit]
    config = load_config()
    started = time.perf_counter()
    timer_started = time.monotonic()

    # Separate phases prevent one implementation from competing with the other
    # for CPU while preserving maximum parallelism within each implementation.
    total_executions = len(cases) * 2
    current = _run_phase(
        "betamax", cases, config, workers,
        total_offset=0, total_executions=total_executions,
        timer_started=timer_started,
    )
    legacy = _run_phase(
        "betamax-old", cases, config, workers,
        total_offset=len(cases), total_executions=total_executions,
        timer_started=timer_started,
    )
    combined = current + legacy
    comparisons = _comparison_rows(current, legacy)

    results_path = RESULTS / f"{result_stem}.csv"
    comparison_path = RESULTS / f"{result_stem}-comparison.csv"
    summary_path = RESULTS / f"{result_stem}-summary.json"
    _write_csv(results_path, RESULT_FIELDS, combined)
    _write_csv(comparison_path, COMPARISON_FIELDS, comparisons)
    summary = {
        "workers": workers,
        "case_timeout_seconds": config["case_timeout_seconds"],
        "elapsed_wall_time_seconds": time.perf_counter() - started,
        "implementations": {
            "betamax": _summary(current),
            "betamax-old": _summary(legacy),
        },
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {results_path}", flush=True)
    print(f"wrote {comparison_path}", flush=True)
    print(f"wrote {summary_path}", flush=True)
