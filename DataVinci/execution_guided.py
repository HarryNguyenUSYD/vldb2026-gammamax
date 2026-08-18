"""Execution-guided error signal from row-local transformation programs."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ExecutionPartition:
    successful_indices: tuple[int, ...]
    failed_indices: tuple[int, ...]
    errors: dict[int, str]


def _exceptional(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, (list, tuple, set)):
        return any(_exceptional(item) for item in value)
    if isinstance(value, dict):
        return any(_exceptional(item) for item in value.values())
    return False


def execute_rows(rows: list[dict[str, str]], program: Callable[[dict[str, str]], Any]) -> ExecutionPartition:
    successful: list[int] = []
    failed: list[int] = []
    errors: dict[int, str] = {}
    for index, row in enumerate(rows):
        try:
            value = program(dict(row))
            if _exceptional(value):
                raise ValueError("program returned an exceptional value")
            successful.append(index)
        except Exception as error:
            failed.append(index)
            errors[index] = str(error)
    return ExecutionPartition(tuple(successful), tuple(failed), errors)
