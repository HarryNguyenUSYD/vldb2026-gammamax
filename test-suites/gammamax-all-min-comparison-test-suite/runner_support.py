"""Compare gammaMax with the all-minimum-candidates variant."""

from __future__ import annotations

import csv
import json
import os
import platform
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
    "gammamax": BUILD / f"gammamax{EXE_SUFFIX}",
    "gammamax-all-min": BUILD / f"gammamax-all-min{EXE_SUFFIX}",
}
STDIN_VALIDATORS = {
    name: BUILD / f"validate_{name}{EXE_SUFFIX}" for name in FORMATS
}
RESULT_FIELDS = (
    "implementation",
    "rsr_batch_size",
    "max_rsr_candidates",
    "ngrams_batch_size",
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
    "effective_seed",
    "total_execution_time_ns",
    "rsr_execution_time_ns",
    "ktails_execution_time_ns",
    "edsm_execution_time_ns",
    "ngrams_execution_time_ns",
    "initial_state_merge_ns",
    "merge_replay_ns",
    "resumed_state_merge_ns",
    "candidate_copy_or_rollback_ns",
    "negative_validation_ns",
    "total_iterations",
    "rsr_total_calls",
    "rsr_candidates_generated",
    "rsr_max_candidates_in_call",
    "rsr_calls_with_multiple_candidates",
    "rsr_enumeration_truncated",
    "rsr_iterations",
    "wall_time_seconds",
    "peak_memory_bytes",
    "timed_out",
    "error",
    "return_code",
    "stdout_tail",
    "stderr_tail",
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
    value = json.loads(CONFIG.read_text(encoding="utf-8"))
    return value


def load_cases() -> list[dict[str, Any]]:
    if not CASES.exists():
        raise FileNotFoundError(f"{CASES} does not exist; run make generate first")
    value = json.loads(CASES.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{CASES} must contain a JSON array")
    return value


def worker_count() -> int:
    configured = int(load_config()["workers"])
    if configured != -1:
        if configured < 1:
            raise ValueError("configured workers must be -1 or at least 1")
        return configured
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
    suite_config: dict[str, Any], validator: Path, implementation: str
) -> dict[str, Any]:
    settings_key = "gammamax" if implementation == "gammamax" else "gammamax_all_min"
    settings = suite_config[settings_key]
    repair = {
        "n": int(settings["n"]),
        "ngrams_batch_size": int(settings["ngrams_batch_size"]),
        "max_candidate_length": int(settings["max_candidate_length"]),
    }
    limits = {
        "max_iterations": int(settings["max_iterations"]),
        "max_total_oracle_calls": int(settings["max_total_oracle_calls"]),
        "max_states": int(settings["max_states"]),
        "max_queue_size": int(settings["max_queue_size"]),
    }
    if implementation == "gammamax":
        repair["rsr_batch_size"] = int(settings["rsr_batch_size"])
    else:
        limits["max_rsr_candidates"] = int(settings["max_rsr_candidates"])
    return {
        "seed": int(suite_config["seed"]),
        "oracle": {"executable": str(validator.resolve())},
        "state_merging": {"k": int(settings["k"])},
        "repair": repair,
        "limits": limits,
    }


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
    effective_seed: int | str = ""
    rsr_execution_time: int | str = ""
    ktails_execution_time: int | str = ""
    edsm_execution_time: int | str = ""
    ngrams_execution_time: int | str = ""
    initial_state_merge_time: int | str = ""
    merge_replay_time: int | str = ""
    resumed_state_merge_time: int | str = ""
    candidate_copy_or_rollback_time: int | str = ""
    negative_validation_time: int | str = ""
    total_iterations: int | str = ""
    rsr_total_calls: int | str = ""
    rsr_candidates_generated: int | str = ""
    rsr_max_candidates_in_call: int | str = ""
    rsr_calls_with_multiple_candidates: int | str = ""
    rsr_enumeration_truncated: bool | str = ""
    rsr_iterations = ""
    error = ""
    try:
        with tempfile.TemporaryDirectory(prefix=f"{implementation}-") as directory:
            working_directory = Path(directory)
            if implementation not in EXECUTABLES:
                raise ValueError(f"unknown implementation: {implementation}")
            input_json = {
                "positive_examples": case["positive_examples"],
                "negative_examples": case["negative_examples"],
                "corrupt_string": case["corrupt_string"],
            }
            config_json = _current_config(
                suite_config, STDIN_VALIDATORS[case["format"]], implementation
            )
            (working_directory / "input.json").write_text(
                json.dumps(input_json, indent=2) + "\n", encoding="utf-8"
            )
            (working_directory / "config.json").write_text(
                json.dumps(config_json, indent=2) + "\n", encoding="utf-8"
            )
            arguments = [str(EXECUTABLES[implementation].resolve())]

            stdout, stderr, return_code, timed_out = _launch(
                arguments, working_directory, timeout
            )

        if timed_out:
            error = f"Algorithm exceeded {timeout:g} seconds."
        elif return_code != 0:
            error = f"Process exited with code {return_code}."
        else:
            parsed = json.loads(stdout)
            required = {
                "output_string", "effective_seed", "peak_memory_bytes",
                "total_execution_time_ns", "rsr_execution_time_ns",
                "ktails_execution_time_ns", "edsm_execution_time_ns",
                "ngrams_execution_time_ns", "initial_state_merge_ns",
                "merge_replay_ns", "resumed_state_merge_ns",
                "candidate_copy_or_rollback_ns", "negative_validation_ns",
                "total_iterations"
            }
            if implementation == "gammamax-all-min":
                required.update({
                    "rsr_total_calls", "rsr_candidates_generated",
                    "rsr_max_candidates_in_call",
                    "rsr_calls_with_multiple_candidates",
                    "rsr_enumeration_truncated", "rsr_iterations",
                })
            if not isinstance(parsed, dict) or set(parsed) != required:
                raise ValueError("gammaMax stdout has an unexpected JSON shape")
            if not isinstance(parsed["output_string"], str):
                raise ValueError("gammaMax output_string is not a string")
            if not isinstance(parsed["peak_memory_bytes"], int):
                raise ValueError("gammaMax peak_memory_bytes is not an integer")
            if not isinstance(parsed["total_execution_time_ns"], int):
                raise ValueError("gammaMax total_execution_time_ns is not an integer")
            if not isinstance(parsed["effective_seed"], int):
                raise ValueError("gammaMax effective_seed is not an integer")
            for field in (
                "rsr_execution_time_ns", "ktails_execution_time_ns",
                "edsm_execution_time_ns", "ngrams_execution_time_ns",
                "initial_state_merge_ns", "merge_replay_ns",
                "resumed_state_merge_ns", "candidate_copy_or_rollback_ns",
                "negative_validation_ns",
                "total_iterations",
            ):
                if not isinstance(parsed[field], int):
                    raise ValueError(f"gammaMax {field} is not an integer")
            output = parsed["output_string"]
            effective_seed = parsed["effective_seed"]
            execution_time = parsed["total_execution_time_ns"]
            peak_memory = parsed["peak_memory_bytes"]
            rsr_execution_time = parsed["rsr_execution_time_ns"]
            ktails_execution_time = parsed["ktails_execution_time_ns"]
            edsm_execution_time = parsed["edsm_execution_time_ns"]
            ngrams_execution_time = parsed["ngrams_execution_time_ns"]
            initial_state_merge_time = parsed["initial_state_merge_ns"]
            merge_replay_time = parsed["merge_replay_ns"]
            resumed_state_merge_time = parsed["resumed_state_merge_ns"]
            candidate_copy_or_rollback_time = parsed["candidate_copy_or_rollback_ns"]
            negative_validation_time = parsed["negative_validation_ns"]
            total_iterations = parsed["total_iterations"]
            if implementation == "gammamax-all-min":
                for field in (
                    "rsr_total_calls", "rsr_candidates_generated",
                    "rsr_max_candidates_in_call",
                    "rsr_calls_with_multiple_candidates",
                ):
                    if not isinstance(parsed[field], int):
                        raise ValueError(f"gammaMax {field} is not an integer")
                if not isinstance(parsed["rsr_enumeration_truncated"], bool):
                    raise ValueError("gammaMax rsr_enumeration_truncated is not boolean")
                if not isinstance(parsed["rsr_iterations"], list):
                    raise ValueError("gammaMax rsr_iterations is not an array")
                expected_iteration_fields = {
                    "minimum_edit_cost", "unique_candidates",
                    "candidates_after_ngrams", "enumeration_complete",
                }
                for iteration in parsed["rsr_iterations"]:
                    if not isinstance(iteration, dict) or set(iteration) != expected_iteration_fields:
                        raise ValueError("gammaMax RSR iteration has an unexpected JSON shape")
                    if not all(isinstance(iteration[field], int) for field in (
                        "minimum_edit_cost", "unique_candidates", "candidates_after_ngrams"
                    )) or not isinstance(iteration["enumeration_complete"], bool):
                        raise ValueError("gammaMax RSR iteration has invalid field types")
                if len(parsed["rsr_iterations"]) != parsed["rsr_total_calls"]:
                    raise ValueError("gammaMax RSR call count does not match iteration details")
                rsr_total_calls = parsed["rsr_total_calls"]
                rsr_candidates_generated = parsed["rsr_candidates_generated"]
                rsr_max_candidates_in_call = parsed["rsr_max_candidates_in_call"]
                rsr_calls_with_multiple_candidates = parsed["rsr_calls_with_multiple_candidates"]
                rsr_enumeration_truncated = parsed["rsr_enumeration_truncated"]
                rsr_iterations = json.dumps(parsed["rsr_iterations"], separators=(",", ":"))
    except Exception as exception:
        error = f"{type(exception).__name__}: {exception}"

    elapsed = time.perf_counter() - started
    accepted = not error and re.fullmatch(case["regex"], output) is not None
    if not error and not accepted:
        error = "Repair was rejected by the format validator."


    return {
        "implementation": implementation,
        "rsr_batch_size": (
            suite_config["gammamax"]["rsr_batch_size"]
            if implementation == "gammamax" else ""
        ),
        "max_rsr_candidates": (
            suite_config["gammamax_all_min"]["max_rsr_candidates"]
            if implementation == "gammamax-all-min" else ""
        ),
        "ngrams_batch_size": (
            suite_config["gammamax" if implementation == "gammamax" else "gammamax_all_min"]["ngrams_batch_size"]
        ),
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
        "effective_seed": effective_seed,
        "total_execution_time_ns": execution_time,
        "rsr_execution_time_ns": rsr_execution_time,
        "ktails_execution_time_ns": ktails_execution_time,
        "edsm_execution_time_ns": edsm_execution_time,
        "ngrams_execution_time_ns": ngrams_execution_time,
        "initial_state_merge_ns": initial_state_merge_time,
        "merge_replay_ns": merge_replay_time,
        "resumed_state_merge_ns": resumed_state_merge_time,
        "candidate_copy_or_rollback_ns": candidate_copy_or_rollback_time,
        "negative_validation_ns": negative_validation_time,
        "total_iterations": total_iterations,
        "rsr_total_calls": rsr_total_calls,
        "rsr_candidates_generated": rsr_candidates_generated,
        "rsr_max_candidates_in_call": rsr_max_candidates_in_call,
        "rsr_calls_with_multiple_candidates": rsr_calls_with_multiple_candidates,
        "rsr_enumeration_truncated": rsr_enumeration_truncated,
        "rsr_iterations": rsr_iterations,
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
    observed = [row for row in rows if not row["timed_out"] and not row["error"]]
    wall_times = [float(row["wall_time_seconds"]) for row in observed]
    edit_distances = [
        float("inf") if row["timed_out"] else int(row["observed_edit_distance"])
        for row in rows
    ]
    measurement_fields = (
        "rsr_execution_time_ns", "ktails_execution_time_ns",
        "edsm_execution_time_ns", "ngrams_execution_time_ns",
        "initial_state_merge_ns", "merge_replay_ns",
        "resumed_state_merge_ns", "candidate_copy_or_rollback_ns",
        "negative_validation_ns",
    )
    measurement_totals = {
        field: sum(int(row[field]) for row in observed) for field in measurement_fields
    }
    measurement_means = {
        field: (statistics.fmean(int(row[field]) for row in observed) if observed else None)
        for field in measurement_fields
    }
    summary = {
        "cases": len(rows),
        "observed_runtime_samples": len(wall_times),
        "censored_timeout_samples": sum(int(row["timed_out"]) for row in rows),
        "accepted_repairs": sum(int(row["accuracy"]) for row in rows),
        "timeouts": sum(int(row["timed_out"]) for row in rows),
        "errors": sum(bool(row["error"]) for row in rows),
        "total_iterations": sum(int(row["total_iterations"]) for row in observed),
        "subalgorithm_total_time_ns": measurement_totals,
        "subalgorithm_mean_time_ns": measurement_means,
        "outputs_in_positive_examples": sum(
            int(row["output_in_positive_examples"]) for row in rows
        ),
        "median_observed_edit_distance": (
            statistics.median(edit_distances) if edit_distances else None
        ),
        "mean_wall_time_seconds": statistics.fmean(wall_times) if wall_times else None,
        "median_wall_time_seconds": statistics.median(wall_times) if wall_times else None,
    }
    if rows and rows[0]["implementation"] == "gammamax-all-min":
        summary["rsr_candidate_diagnostics"] = {
            "total_calls": sum(int(row["rsr_total_calls"]) for row in observed),
            "unique_candidates_generated": sum(
                int(row["rsr_candidates_generated"]) for row in observed
            ),
            "max_candidates_in_one_call": max(
                (int(row["rsr_max_candidates_in_call"]) for row in observed),
                default=0,
            ),
            "calls_with_multiple_candidates": sum(
                int(row["rsr_calls_with_multiple_candidates"]) for row in observed
            ),
            "completed_cases_with_truncation": sum(
                row["rsr_enumeration_truncated"] is True for row in observed
            ),
            "completed_cases_fully_enumerated": sum(
                row["rsr_enumeration_truncated"] is False for row in observed
            ),
        }
    return summary


def _paired_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_case: dict[int, dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_case.setdefault(int(row["case_index"]), {})[str(row["implementation"])] = row
    metrics = {
        "accuracy": (lambda row: int(row["accuracy"]), True),
        "observed_edit_distance": (lambda row: int(row["observed_edit_distance"]), False),
        "wall_time_seconds": (lambda row: float(row["wall_time_seconds"]), False),
        "peak_memory_bytes": (lambda row: int(row["peak_memory_bytes"]), False),
    }
    result: dict[str, Any] = {"paired_cases": 0, "metrics": {}}
    pairs = []
    for pair in by_case.values():
        old = pair.get("gammamax")
        new = pair.get("gammamax-all-min")
        if old and new:
            pairs.append((old, new))
    result["paired_cases"] = len(pairs)
    for name, (extract, higher_is_better) in metrics.items():
        wins = losses = ties = 0
        comparable = pairs if name == "accuracy" else [
            pair for pair in pairs if not pair[0]["error"] and not pair[1]["error"]
        ]
        for old, new in comparable:
            old_value, new_value = extract(old), extract(new)
            if new_value == old_value:
                ties += 1
            elif (new_value > old_value) == higher_is_better:
                wins += 1
            else:
                losses += 1
        result["metrics"][name] = {
            "gammamax_all_min_wins": wins,
            "gammamax_all_min_losses": losses,
            "ties": ties,
            "comparable_cases": len(comparable),
        }
    return result


def _environment_metadata() -> dict[str, Any]:
    compiler = os.environ.get("CXX", "c++")
    flags = os.environ.get(
        "CXXFLAGS", "-O2 -DNDEBUG -std=c++20 -Wall -Wextra -Wpedantic"
    )
    try:
        completed = subprocess.run(
            [compiler, "--version"], capture_output=True, text=True, timeout=10,
            check=False,
        )
        compiler_version = _tail(completed.stdout or completed.stderr, lines=1)
    except (OSError, subprocess.SubprocessError) as exception:
        compiler_version = f"unavailable: {type(exception).__name__}: {exception}"
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "compiler_command": compiler,
        "compiler_version": compiler_version,
        "compiler_flags": flags,
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

    total_executions = len(cases) * 2
    old_rows = _run_phase(
        "gammamax", cases, config, workers,
        total_offset=0, total_executions=total_executions,
        timer_started=timer_started,
    )
    new_rows = _run_phase(
        "gammamax-all-min", cases, config, workers,
        total_offset=len(cases), total_executions=total_executions,
        timer_started=timer_started,
    )
    current = old_rows + new_rows

    results_path = RESULTS / f"{result_stem}.csv"
    summary_path = RESULTS / f"{result_stem}-summary.json"
    _write_csv(results_path, RESULT_FIELDS, current)
    summary = {
        "workers": workers,
        "seed": config["seed"],
        "case_timeout_seconds": config["case_timeout_seconds"],
        "environment": _environment_metadata(),
        "suite_config": config,
        "elapsed_wall_time_seconds": time.perf_counter() - started,
        "implementations": {
            "gammamax": _summary(old_rows),
            "gammamax-all-min": _summary(new_rows),
        },
        "paired_comparison": _paired_summary(current),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {results_path}", flush=True)
    print(f"wrote {summary_path}", flush=True)
