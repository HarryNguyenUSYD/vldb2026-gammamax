#!/usr/bin/env python3
"""DataVinci: unsupervised pattern-based string error detection and repair."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from concretization import ConstraintModel, RankedCandidate, rank_candidates
from execution_guided import ExecutionPartition, execute_rows
from repair import EditProgram, UnsupportedRegex, matching_trace, repair_regex
from semantic import AbstractedValue, SemanticAbstractor


HERE = Path(__file__).resolve().parent


@dataclass
class DataVinciConfig:
    max_patterns: int = 10
    significance_threshold: float = 0.1
    minimum_tree_accuracy: float = 0.8
    semantic_abstraction: bool = True
    semantic_token_budget: int = 3500
    max_candidates: int = 100
    max_edits: int | None = None
    seed: int = 0
    rank_weights: dict[str, float] = field(default_factory=lambda: {
        "edit_distance": 1.0,
        "alphanumeric_edits": 1.0,
        "nearest_value": 1.0,
        "pattern_coverage": 1.0,
    })
    bridge_command: list[str] | None = None
    profile_cache: str | None = None
    semantic_cache: str | None = None

    def validate(self) -> None:
        if self.max_patterns < 1 or self.max_candidates < 1 or (self.max_edits is not None and self.max_edits < 0):
            raise ValueError("pattern/candidate counts must be positive and max_edits non-negative or null")
        if not 0 < self.significance_threshold <= 1:
            raise ValueError("significance_threshold must be in (0, 1]")
        if not 0 < self.minimum_tree_accuracy <= 1:
            raise ValueError("minimum_tree_accuracy must be in (0, 1]")
        required = {"edit_distance", "alphanumeric_edits", "nearest_value", "pattern_coverage"}
        if set(self.rank_weights) != required:
            raise ValueError(f"rank_weights keys must be {sorted(required)}")


@dataclass(frozen=True)
class LearnedPattern:
    display: str
    regex: str | None
    regexes_to_exclude: tuple[str, ...]
    matching_fraction: float
    matched_indices: tuple[int, ...]
    is_null: bool
    examples: tuple[str, ...]


@dataclass
class CellResult:
    row_index: int
    input_value: str
    abstracted_value: str
    detected: bool
    candidates: list[RankedCandidate]
    repair: str | None
    error: str | None = None


@dataclass
class CleanResult:
    target_column: str
    sdk_version: str
    patterns: list[LearnedPattern]
    significant_patterns: list[LearnedPattern]
    cells: list[CellResult]
    repaired_rows: list[dict[str, str]]
    execution: ExecutionPartition | None
    measurements: dict[str, Any]

    def report(self) -> dict[str, Any]:
        return {
            "target_column": self.target_column,
            "sdk_version": self.sdk_version,
            "patterns": [asdict(pattern) for pattern in self.patterns],
            "significant_patterns": [asdict(pattern) for pattern in self.significant_patterns],
            "cells": [asdict(cell) for cell in self.cells],
            "execution": asdict(self.execution) if self.execution else None,
            "measurements": self.measurements,
        }


class FlashProfileError(RuntimeError):
    pass


class FlashProfileClient:
    def __init__(self, config: DataVinciConfig) -> None:
        self.config = config
        self.cache_path = Path(config.profile_cache) if config.profile_cache else None
        self.cache = self._load_cache()

    def learn(self, values: list[str | None]) -> tuple[str, list[LearnedPattern]]:
        key = hashlib.sha256(json.dumps({
            "package": "Microsoft.ProgramSynthesis.Matching.Text@10.16.5",
            "values": values,
        }, ensure_ascii=False).encode()).hexdigest()
        if key in self.cache:
            return self._parse(self.cache[key])
        command = self.config.bridge_command or self._default_command()
        try:
            completed = subprocess.run(command, input=json.dumps({
                "operation": "learn", "values": values,
            }), text=True, capture_output=True, cwd=HERE, check=False)
        except OSError as error:
            raise FlashProfileError(f"cannot start FlashProfile bridge: {error}") from error
        if completed.returncode:
            detail = completed.stderr.strip() or f"exit code {completed.returncode}"
            raise FlashProfileError(f"FlashProfile bridge failed: {detail}")
        try:
            payload = json.loads(completed.stdout)
            parsed = self._parse(payload)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise FlashProfileError(f"invalid FlashProfile bridge output: {error}") from error
        self.cache[key] = payload
        self._save_cache()
        return parsed

    def match(self, values: list[str | None], patterns: list[LearnedPattern]) -> set[int]:
        if not values or not patterns:
            return set()
        payload = {
            "operation": "match",
            "values": values,
            "patterns": [{
                "regex": pattern.regex,
                "regexes_to_exclude": list(pattern.regexes_to_exclude),
                "is_null": pattern.is_null,
            } for pattern in patterns],
        }
        command = self.config.bridge_command or self._default_command()
        try:
            completed = subprocess.run(command, input=json.dumps(payload), text=True,
                                       capture_output=True, cwd=HERE, check=False)
        except OSError as error:
            raise FlashProfileError(f"cannot start FlashProfile bridge: {error}") from error
        if completed.returncode:
            raise FlashProfileError("FlashProfile match failed: "
                                    + (completed.stderr.strip() or str(completed.returncode)))
        try:
            response = json.loads(completed.stdout)
            return set(map(int, response["accepted_indices"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise FlashProfileError(f"invalid FlashProfile match output: {error}") from error

    @staticmethod
    def _default_command() -> list[str]:
        executable = HERE / "flashprofile_bridge" / "bin" / "Release" / "net8.0"
        executable /= "FlashProfileBridge.exe" if os.name == "nt" else "FlashProfileBridge"
        if executable.is_file():
            return [str(executable)]
        return ["dotnet", "run", "--project", str(HERE / "flashprofile_bridge"),
                "--configuration", "Release", "--no-launch-profile"]

    @staticmethod
    def _parse(payload: dict[str, Any]) -> tuple[str, list[LearnedPattern]]:
        version = str(payload["sdk_version"])
        patterns = []
        for item in payload["patterns"]:
            patterns.append(LearnedPattern(
                display=str(item["display"]),
                regex=None if item.get("regex") is None else str(item["regex"]),
                regexes_to_exclude=tuple(map(str, item.get("regexes_to_exclude", []))),
                matching_fraction=float(item["matching_fraction"]),
                matched_indices=tuple(map(int, item["matched_indices"])),
                is_null=bool(item.get("is_null", False)),
                examples=tuple(map(str, item.get("examples", []))),
            ))
        return version, patterns

    def _load_cache(self) -> dict[str, Any]:
        if self.cache_path and self.cache_path.is_file():
            try: return json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError): return {}
        return {}

    def _save_cache(self) -> None:
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")


def _python_regex(expression: str) -> str:
    replacements = {
        r"\p{Lu}": "[A-Z]", r"\p{Ll}": "[a-z]", r"\p{L}": "[^\\W\\d_]",
        r"\p{Nd}": "[0-9]", r"\p{N}": "[0-9]", r"\z": r"\Z",
    }
    for source, target in replacements.items():
        expression = expression.replace(source, target)
    if r"\p{" in expression or r"\P{" in expression:
        raise UnsupportedRegex("unsupported .NET Unicode category")
    return expression


def _matches(value: str, pattern: LearnedPattern) -> bool:
    if pattern.is_null or pattern.regex is None:
        return False
    expression = _python_regex(pattern.regex)
    if re.search(expression, value) is None:
        return False
    return all(re.search(_python_regex(exclusion), value) is None
               for exclusion in pattern.regexes_to_exclude)


def _reconcretize(value: str, abstraction: AbstractedValue) -> str:
    result = value
    for span in abstraction.spans:
        result = result.replace(span.marker, span.replacement, 1)
    return result


class _PatternConstraints:
    """One paper-style decision tree for every abstract regex edge position."""

    def __init__(self, expression: str, profile_values: list[str], profile_rows: list[dict[str, str]],
                 matched_indices: tuple[int, ...], minimum_accuracy: float, seed: int) -> None:
        self.entries: dict[int, tuple[ConstraintModel, list[dict[str, str]]]] = {}
        edge_examples: dict[int, tuple[list[dict[str, str]], list[str]]] = {}
        for local_index in matched_indices:
            if local_index >= len(profile_values):
                continue
            value = profile_values[local_index]
            try:
                trace = matching_trace(expression, value)
            except UnsupportedRegex:
                trace = None
            if trace is None:
                continue
            for edge_id, label, character in trace:
                if len(label) == 1:
                    continue
                rows, labels = edge_examples.setdefault(edge_id, ([], []))
                rows.append(profile_rows[local_index]); labels.append(character)
        for edge_id, (rows, labels) in edge_examples.items():
            model = ConstraintModel(minimum_accuracy, seed)
            model.fit(rows, {"edge": labels})
            self.entries[edge_id] = (model, rows)

    def predict(self, row: dict[str, str]) -> dict[int, str]:
        result = {}
        for edge_id, (model, rows) in self.entries.items():
            values = model.predict("edge", row, rows)
            if values:
                result[edge_id] = values[0]
        return result


class DataVinci:
    def __init__(self, config: DataVinciConfig | None = None,
                 abstractor: SemanticAbstractor | None = None) -> None:
        self.config = config or DataVinciConfig()
        self.config.validate()
        self.abstractor = abstractor or SemanticAbstractor(
            enabled=self.config.semantic_abstraction,
            cache_path=Path(self.config.semantic_cache) if self.config.semantic_cache else None)
        self.profiler = FlashProfileClient(self.config)

    def clean_table(self, rows: list[dict[str, str]], target_column: str,
                    program: Callable[[dict[str, str]], Any] | None = None) -> CleanResult:
        started = time.perf_counter_ns()
        if not rows:
            raise ValueError("rows must not be empty")
        if any(target_column not in row for row in rows):
            raise ValueError(f"target column {target_column!r} is missing from at least one row")
        normalized = [{key: str(value) for key, value in row.items()} for row in rows]
        values = [row[target_column] for row in normalized]
        abstraction_started = time.perf_counter_ns()
        abstractions = self.abstractor.abstract_column(values, self.config.semantic_token_budget)
        abstracted = [item.abstracted for item in abstractions]
        abstraction_time = time.perf_counter_ns() - abstraction_started

        execution = execute_rows(normalized, program) if program else None
        profile_indices = list(execution.successful_indices) if execution else list(range(len(rows)))
        if not profile_indices:
            raise ValueError("execution-guided repair requires at least one successful row")
        profile_values = [abstracted[index] for index in profile_indices]
        profile_started = time.perf_counter_ns()
        sdk_version, patterns = self.profiler.learn(profile_values)
        profile_time = time.perf_counter_ns() - profile_started
        if execution:
            significant = patterns
            detected_indices = set(execution.failed_indices)
        else:
            significant = [pattern for pattern in patterns
                           if pattern.matching_fraction >= self.config.significance_threshold]
            accepted_indices = self.profiler.match(abstracted, significant)
            detected_indices = set(range(len(abstracted))) - accepted_indices

        profile_rows = [normalized[index] for index in profile_indices]
        constraints: dict[LearnedPattern, _PatternConstraints] = {}
        for pattern in significant:
            if not pattern.regex:
                continue
            try:
                expression = _python_regex(pattern.regex)
                constraints[pattern] = _PatternConstraints(
                    expression, profile_values, profile_rows, pattern.matched_indices,
                    self.config.minimum_tree_accuracy, self.config.seed)
            except (UnsupportedRegex, re.error):
                pass

        cells: list[CellResult] = []
        repaired_rows = [dict(row) for row in normalized]
        repair_started = time.perf_counter_ns()
        for index, (source, abstract_source) in enumerate(zip(values, abstracted)):
            if index not in detected_indices:
                cells.append(CellResult(index, source, abstract_source, False, [], None))
                continue
            candidates: list[RankedCandidate] = []
            errors: list[str] = []
            for pattern in significant:
                if not pattern.regex:
                    continue
                try:
                    programs = repair_regex(abstract_source, _python_regex(pattern.regex),
                                            self.config.max_edits, self.config.max_candidates,
                                            constraints.get(pattern).predict(normalized[index])
                                            if pattern in constraints else None)
                    accepted_programs = self.profiler.match(
                        [program.value for program in programs], [pattern])
                    programs = [program for program_index, program in enumerate(programs)
                                if program_index in accepted_programs]
                    concrete = [_reconcretize(program.value, abstractions[index]) for program in programs]
                    programs_by_value = {
                        concrete_value: program for concrete_value, program in zip(concrete, programs)
                    }
                    candidates.extend(rank_candidates(source, concrete, values,
                                                      pattern.matching_fraction,
                                                      self.config.rank_weights,
                                                      programs_by_value))
                except (UnsupportedRegex, re.error) as error:
                    errors.append(f"{pattern.display}: {error}")
            candidates = sorted({candidate.value: candidate for candidate in candidates}.values(),
                                key=lambda item: (item.score, item.value))[:self.config.max_candidates]
            repair = candidates[0].value if candidates else None
            if repair is not None:
                repaired_rows[index][target_column] = repair
            cells.append(CellResult(index, source, abstract_source, True, candidates, repair,
                                    "; ".join(errors) or None))
        repair_time = time.perf_counter_ns() - repair_started
        return CleanResult(target_column, sdk_version, patterns, significant, cells, repaired_rows,
                           execution, {
                               "total_execution_time_ns": time.perf_counter_ns() - started,
                               "semantic_abstraction_time_ns": abstraction_time,
                               "profile_learning_time_ns": profile_time,
                               "repair_time_ns": repair_time,
                               "llm_calls": self.abstractor.call_count,
                               "input_rows": len(rows),
                               "patterns_learned": len(patterns),
                               "significant_patterns": len(significant),
                               "detected_cells": len(detected_indices),
                           })


def _load_callable(specification: str) -> Callable[[dict[str, str]], Any]:
    module_name, separator, attribute = specification.partition(":")
    if not separator:
        raise ValueError("--program must use module:function syntax")
    value = getattr(importlib.import_module(module_name), attribute)
    if not callable(value):
        raise TypeError(f"{specification} is not callable")
    return value


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = [{field: row.get(field) or "" for field in fields} for row in reader]
    return rows, fields


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--target-column", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--program")
    parser.add_argument("--disable-semantic-abstraction", action="store_true")
    args = parser.parse_args()
    try:
        settings = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
        if args.disable_semantic_abstraction:
            settings["semantic_abstraction"] = False
        config = DataVinciConfig(**settings)
        rows, fields = _read_csv(args.input)
        program = _load_callable(args.program) if args.program else None
        result = DataVinci(config).clean_table(rows, args.target_column, program)
        _write_csv(args.output, fields, result.repaired_rows)
        args.report.write_text(json.dumps(result.report(), indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
        return 0
    except Exception as error:
        print(f"DataVinci: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
