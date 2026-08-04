"""Shared execution machinery for the standalone betaMax test suite."""

from __future__ import annotations

import csv
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from generate_cases import edit_distance


ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
CASES = ROOT / "test-cases" / "test-cases.json"
RESULTS = ROOT / "results" / "betamax.csv"
SMOKE_RESULTS = ROOT / "results" / "betamax-smoke.csv"
FORMATS = ("date", "time", "url", "isbn", "ipv4", "ipv6")
EXE_SUFFIX = ".exe" if os.name == "nt" else ""
EXECUTABLE = BUILD / f"betamax{EXE_SUFFIX}"
VALIDATORS = {
    name: BUILD / f"validate_{name}{EXE_SUFFIX}"
    for name in FORMATS
}
CSV_FIELDS = (
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


class ProgressReporter:
    """Print monotonic completion counters plus a once-per-second timer."""

    def __init__(
        self,
        label: str,
        algorithm_total: int,
        total_executions: int,
        total_offset: int = 0,
    ) -> None:
        self.label = label
        self.algorithm_total = algorithm_total
        self.total_executions = total_executions
        self.total_offset = total_offset
        self.algorithm_completed = 0
        self.started = time.monotonic()
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


def load_config() -> dict[str, Any]:
    return json.loads((ROOT / "suite-config.json").read_text(encoding="utf-8"))


def load_cases() -> list[dict[str, Any]]:
    if not CASES.exists():
        raise FileNotFoundError(
            f"{CASES} does not exist; run generate_cases.py first"
        )
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
    missing = [path for path in (EXECUTABLE, *VALIDATORS.values()) if not path.is_file()]
    if missing:
        listing = "\n".join(f"  {path}" for path in missing)
        raise FileNotFoundError(
            "Build the suite before running it; missing executables:\n" + listing
        )


def _betamax_config(
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


def execute_case(
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
    result: dict[str, Any] | None = None
    error = ""

    try:
        validator = VALIDATORS[case["format"]]
        with tempfile.TemporaryDirectory(prefix="betamax-") as directory:
            working_directory = Path(directory)
            input_json = {
                "positive_examples": case["positive_examples"],
                "negative_examples": case["negative_examples"],
                "corrupt_string": case["corrupt_string"],
            }
            config_json = _betamax_config(suite_config, validator, case_index)
            (working_directory / "input.json").write_text(
                json.dumps(input_json, indent=2) + "\n", encoding="utf-8"
            )
            (working_directory / "config.json").write_text(
                json.dumps(config_json, indent=2) + "\n", encoding="utf-8"
            )

            process = subprocess.Popen(
                [str(EXECUTABLE.resolve())],
                cwd=working_directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=(os.name == "posix"),
            )
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_process_group(process)
                stdout, stderr = process.communicate()
            return_code = process.returncode

        if timed_out:
            error = f"Algorithm exceeded {timeout:g} seconds."
        elif return_code != 0:
            error = f"Process exited with code {return_code}."
        else:
            parsed = json.loads(stdout)
            required = {
                "output_string",
                "peak_memory_bytes",
                "total_execution_time_ns",
            }
            if not isinstance(parsed, dict) or set(parsed) != required:
                raise ValueError("betaMax stdout has an unexpected JSON shape")
            if not isinstance(parsed["output_string"], str):
                raise ValueError("betaMax output_string is not a string")
            if not isinstance(parsed["peak_memory_bytes"], int):
                raise ValueError("betaMax peak_memory_bytes is not an integer")
            if not isinstance(parsed["total_execution_time_ns"], int):
                raise ValueError("betaMax total_execution_time_ns is not an integer")
            result = parsed
    except Exception as exception:
        error = f"{type(exception).__name__}: {exception}"

    elapsed = time.perf_counter() - started
    output = result["output_string"] if result is not None else ""
    accepted = result is not None and re.fullmatch(case["regex"], output) is not None
    if result is not None and not accepted and not error:
        error = "Repair was rejected by the format validator."

    return {
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
        "observed_edit_distance": edit_distance(case["corrupt_string"], output),
        "total_execution_time_ns": (
            result["total_execution_time_ns"] if result is not None else ""
        ),
        "wall_time_seconds": elapsed,
        "peak_memory_bytes": result["peak_memory_bytes"] if result is not None else "",
        "timed_out": int(timed_out),
        "error": error,
        "return_code": "" if return_code is None else return_code,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def run_suite(
    workers: int,
    case_limit: int | None = None,
    result_path: Path = RESULTS,
) -> None:
    _ensure_binaries()
    cases = load_cases()
    if case_limit is not None:
        if case_limit < 1:
            raise ValueError("case_limit must be at least 1")
        cases = cases[:case_limit]
    config = load_config()
    rows: list[dict[str, Any] | None] = [None] * len(cases)
    started = time.perf_counter()
    print(f"betaMax: {len(cases)} cases, {workers} workers", flush=True)
    progress = ProgressReporter("betaMax", len(cases), len(cases))
    progress.start()
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(execute_case, index, case, config): index
                for index, case in enumerate(cases)
            }
            for future in as_completed(futures):
                index = futures[future]
                rows[index] = future.result()
                progress.advance()
    finally:
        progress.close()

    final_rows = [row for row in rows if row is not None]
    _write_csv(result_path, final_rows)
    passed = sum(int(row["accuracy"]) for row in final_rows)
    print(
        f"wrote {result_path}: {passed}/{len(final_rows)} accepted repairs "
        f"in {time.perf_counter() - started:.2f}s",
        flush=True,
    )
