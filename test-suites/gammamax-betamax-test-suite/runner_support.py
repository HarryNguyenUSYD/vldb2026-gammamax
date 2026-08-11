"""Run generated repair cases against gammaMax."""

from __future__ import annotations

import csv
import json
import math
import os
import platform
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
    "k",
    "n",
    "rsr_batch_size",
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
    timeout = float(value["case_timeout_seconds"])
    if timeout != -1 and timeout <= 0:
        raise ValueError("case_timeout_seconds must be -1 or positive")
    return value


def load_cases() -> list[dict[str, Any]]:
    if not CASES.exists():
        raise FileNotFoundError(f"{CASES} does not exist; run make generate first")
    value = json.loads(CASES.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{CASES} must contain a JSON array")
    return value


def k_n_combinations(config: dict[str, Any]) -> list[tuple[int, int]]:
    settings = config["gammamax"]
    k_values = [int(value) for value in settings["k_values"]]
    n_values = [int(value) for value in settings["n_values"]]
    if any(value < 0 for value in (*k_values, *n_values)):
        raise ValueError("k and n values must be non-negative")
    if len(set(k_values)) != len(k_values) or len(set(n_values)) != len(n_values):
        raise ValueError("k and n lists must not contain duplicates")
    combinations = [(k, n) for k in k_values for n in n_values]
    if not combinations:
        raise ValueError("no gammaMax k/n combinations configured")
    return combinations


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


def _validator_accepts(format_name: str, output: str) -> bool:
    completed = subprocess.run(
        [str(STDIN_VALIDATORS[format_name].resolve())],
        input=output,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode not in (0, 1):
        detail = _tail(completed.stderr or completed.stdout, lines=3)
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(
            f"scoring validator exited with code {completed.returncode}{suffix}"
        )
    return completed.returncode == 0


def _current_config(
    suite_config: dict[str, Any], validator: Path, k: int, n: int
) -> dict[str, Any]:
    settings = suite_config["gammamax"]
    return {
        "seed": int(suite_config["seed"]),
        "oracle": {"executable": str(validator.resolve())},
        "state_merging": {"k": k},
        "repair": {
            "n": n,
            "rsr_batch_size": int(settings["rsr_batch_size"]),
            "ngrams_batch_size": int(settings["ngrams_batch_size"]),
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
        return f'\\"{validator.resolve().as_posix()}\\"'
    return f'"{validator.resolve()}"'


def _betamax_old_arguments(
    case: dict[str, Any], suite_config: dict[str, Any],
    positives: Path, negatives: Path, broken: Path,
) -> list[str]:
    settings = suite_config["betamax_old"]
    seed = int(suite_config["seed"])
    return [
        str(EXECUTABLES["betamax-old"].resolve()),
        "--positives", str(positives),
        "--negatives", str(negatives),
        "--category", str(case["category"]),
        "--broken-file", str(broken),
        "--oracle-validator",
        _legacy_validator_command(FILE_VALIDATORS[case["format"]]),
        "--mutations", "0",
        "--mutations-seed", str(seed),
        "--xover-pairs", str(settings["cross_merge_samples"]),
        "--max-attempts", str(settings["max_iterations"]),
        "--attempt-candidates", str(settings["batch_size"]),
        "--max-cost", str(settings["max_cost"]),
        "--max-candidates", str(settings["batch_size"]),
        "--oracle-timeout-ms", str(settings["oracle_timeout_ms"]),
        "--eq-disable-sampling",
        "--seed", str(seed),
    ]


def _launch(
    arguments: list[str], working_directory: Path, timeout: float | None
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
    k: int | None,
    n: int | None,
    case_index: int,
    case: dict[str, Any],
    suite_config: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    configured_timeout = float(suite_config["case_timeout_seconds"])
    timeout = None if configured_timeout == -1 else configured_timeout
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
    error = ""
    try:
        with tempfile.TemporaryDirectory(prefix=f"{implementation}-") as directory:
            working_directory = Path(directory)
            if implementation == "gammamax":
                if k is None or n is None:
                    raise ValueError("gammaMax requires k and n")
                input_json = {
                    "positive_examples": case["positive_examples"],
                    "negative_examples": case["negative_examples"],
                    "corrupt_string": case["corrupt_string"],
                }
                config_json = _current_config(
                    suite_config, STDIN_VALIDATORS[case["format"]], k, n
                )
                (working_directory / "input.json").write_text(
                    json.dumps(input_json, indent=2) + "\n", encoding="utf-8"
                )
                (working_directory / "config.json").write_text(
                    json.dumps(config_json, indent=2) + "\n", encoding="utf-8"
                )
                arguments = [str(EXECUTABLES["gammamax"].resolve())]
            elif implementation == "betamax-old":
                positives = working_directory / "positives.txt"
                negatives = working_directory / "negatives.txt"
                broken = working_directory / "broken.txt"
                _write_lines(positives, case["positive_examples"])
                _write_lines(negatives, case["negative_examples"])
                with broken.open("w", encoding="ascii", newline="") as stream:
                    stream.write(case["corrupt_string"])
                arguments = _betamax_old_arguments(
                    case, suite_config, positives, negatives, broken
                )
            else:
                raise ValueError(f"unknown implementation: {implementation}")

            stdout, stderr, return_code, timed_out = _launch(
                arguments, working_directory, timeout
            )

        if timed_out:
            error = f"Algorithm exceeded {configured_timeout:g} seconds."
        elif return_code != 0:
            error = f"Process exited with code {return_code}."
        elif implementation == "gammamax":
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
        else:
            output = stdout[:-1] if stdout.endswith("\n") else stdout
            if output.endswith("\r"):
                output = output[:-1]
            if "\n" in output or "\r" in output:
                raise ValueError("betaMax-old emitted more than one stdout line")
    except Exception as exception:
        error = f"{type(exception).__name__}: {exception}"

    elapsed = time.perf_counter() - started
    accepted = False
    if not error:
        try:
            accepted = _validator_accepts(case["format"], output)
            if not accepted:
                error = "Repair was rejected by the format validator."
        except Exception as exception:
            error = f"{type(exception).__name__}: {exception}"


    return {
        "implementation": implementation,
        "k": "" if k is None else k,
        "n": "" if n is None else n,
        "rsr_batch_size": suite_config["gammamax"]["rsr_batch_size"] if implementation == "gammamax" else "",
        "ngrams_batch_size": suite_config["gammamax"]["ngrams_batch_size"] if implementation == "gammamax" else "",
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
    k: int | None,
    n: int | None,
    cases: list[dict[str, Any]],
    config: dict[str, Any],
    workers: int,
    total_offset: int,
    total_executions: int,
    timer_started: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any] | None] = [None] * len(cases)
    label = implementation if k is None else f"{implementation}-k-{k}-n-{n}"
    print(f"{label}: {len(cases)} cases, {workers} workers", flush=True)
    progress = ProgressReporter(
        label, len(cases), total_executions, total_offset, timer_started
    )
    progress.start()
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(execute_case, implementation, k, n, index, case, config): index
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
        int(row["observed_edit_distance"])
        if row["accuracy"] and not row["error"]
        else float("inf")
        for row in rows
    ]
    measurement_fields = (
        "rsr_execution_time_ns", "ktails_execution_time_ns",
        "edsm_execution_time_ns", "ngrams_execution_time_ns",
        "initial_state_merge_ns", "merge_replay_ns",
        "resumed_state_merge_ns", "candidate_copy_or_rollback_ns",
        "negative_validation_ns",
    )
    measurement_samples = {
        field: [int(row[field]) for row in observed if row[field] != ""]
        for field in measurement_fields
    }
    measurement_totals = {
        field: (sum(values) if values else None)
        for field, values in measurement_samples.items()
    }
    measurement_means = {
        field: (statistics.fmean(values) if values else None)
        for field, values in measurement_samples.items()
    }
    iteration_samples = [
        int(row["total_iterations"])
        for row in observed
        if row["total_iterations"] != ""
    ]
    median_edit_distance = (
        statistics.median(edit_distances) if edit_distances else None
    )
    median_edit_distance_is_infinite = (
        isinstance(median_edit_distance, float)
        and not math.isfinite(median_edit_distance)
    )
    return {
        "cases": len(rows),
        "observed_runtime_samples": len(wall_times),
        "censored_timeout_samples": sum(int(row["timed_out"]) for row in rows),
        "accepted_repairs": sum(int(row["accuracy"]) for row in rows),
        "timeouts": sum(int(row["timed_out"]) for row in rows),
        "errors": sum(bool(row["error"]) for row in rows),
        "measurement_scope": "successful non-error cases only",
        "successful_case_total_iterations": (
            sum(iteration_samples) if iteration_samples else None
        ),
        "successful_case_subalgorithm_total_time_ns": measurement_totals,
        "successful_case_subalgorithm_mean_time_ns": measurement_means,
        "outputs_in_positive_examples": sum(
            int(row["output_in_positive_examples"]) for row in rows
        ),
        "median_observed_edit_distance": (
            None if median_edit_distance_is_infinite else median_edit_distance
        ),
        "median_observed_edit_distance_is_infinite": (
            median_edit_distance_is_infinite
        ),
        "mean_wall_time_seconds": statistics.fmean(wall_times) if wall_times else None,
        "median_wall_time_seconds": statistics.median(wall_times) if wall_times else None,
    }


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

    combinations = k_n_combinations(config)
    total_executions = len(cases) * (len(combinations) + 1)
    all_rows: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    total_offset = 0
    for k, n in combinations:
        label = f"gammamax-k-{k}-n-{n}"
        rows = _run_phase(
            "gammamax", k, n, cases, config, workers,
            total_offset=total_offset, total_executions=total_executions,
            timer_started=timer_started,
        )
        all_rows.extend(rows)
        summaries[label] = {
            "k": k,
            "n": n,
            "rsr_batch_size": int(config["gammamax"]["rsr_batch_size"]),
            "ngrams_batch_size": int(config["gammamax"]["ngrams_batch_size"]),
            **_summary(rows),
        }
        total_offset += len(cases)

    betamax_rows = _run_phase(
        "betamax-old", None, None, cases, config, workers,
        total_offset=total_offset, total_executions=total_executions,
        timer_started=timer_started,
    )
    all_rows.extend(betamax_rows)
    summaries["betamax-old"] = _summary(betamax_rows)

    results_path = RESULTS / f"{result_stem}.csv"
    summary_path = RESULTS / f"{result_stem}-summary.json"
    _write_csv(results_path, RESULT_FIELDS, all_rows)
    summary = {
        "workers": workers,
        "seed": config["seed"],
        "case_timeout_seconds": config["case_timeout_seconds"],
        "k_n_combinations": len(combinations),
        "base_cases": len(cases),
        "implementations_per_case": len(combinations) + 1,
        "total_case_runs": total_executions,
        "environment": _environment_metadata(),
        "suite_config": config,
        "elapsed_wall_time_seconds": time.perf_counter() - started,
        "implementations": summaries,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {results_path}", flush=True)
    print(f"wrote {summary_path}", flush=True)
