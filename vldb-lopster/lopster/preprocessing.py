"""Deterministic, leakage-free preprocessing for LoPSTER."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

IGNORED = {"", "?"}


def select_training_rows(frame: pd.DataFrame, excluded: set[int], limit: int,
                         seed: int) -> tuple[pd.DataFrame, list[int]]:
    """Select at most ``limit`` source rows without touching evaluation rows."""
    candidates = [index for index in range(len(frame)) if index not in excluded]
    random.Random(seed).shuffle(candidates)
    selected = candidates[:limit]
    return frame.iloc[selected].reset_index(drop=True), selected


@dataclass
class TabularPreprocessor:
    columns: list[str]
    modeled_columns: list[str]
    categorical_columns: list[str]
    integer_columns: list[str]
    float_columns: list[str]
    excluded_columns: list[str]
    allow_negative_columns: list[str]
    categories: dict[str, list[str]]
    imputations: dict[str, Any]
    means: dict[str, float]
    scales: dict[str, float]
    missing_value_replacement: float

    @classmethod
    def fit(cls, frame: pd.DataFrame, schema: dict[str, Any],
            missing_value_replacement: float) -> "TabularPreprocessor":
        columns = list(frame.columns)
        categorical = list(schema["categorical_columns"])
        integers = list(schema["integer_columns"])
        floats = list(schema["float_columns"])
        excluded = list(schema.get("id_columns", [])) + list(schema.get("date_columns", []))
        allow_negative = list(schema.get("allow_negative_columns", []))
        modeled = [column for column in columns if column not in excluded]
        declared = set(categorical) | set(integers) | set(floats) | set(excluded)
        if declared != set(columns):
            missing = sorted(set(columns) - declared)
            extra = sorted(declared - set(columns))
            raise ValueError(f"schema mismatch; undeclared={missing}, unknown={extra}")

        categories: dict[str, list[str]] = {}
        imputations: dict[str, Any] = {}
        encoded: dict[str, np.ndarray] = {}
        for column in modeled:
            values = frame[column].astype(str)
            if column in categorical:
                valid = values[~values.isin(IGNORED)]
                if valid.empty:
                    raise ValueError(f"categorical column {column!r} has no training values")
                mode = str(valid.mode(dropna=True).iloc[0])
                levels = sorted(set(valid.tolist()))
                categories[column] = levels
                imputations[column] = mode
                mapping = {value: index for index, value in enumerate(levels)}
                encoded[column] = np.asarray(
                    [mapping[mode if value in IGNORED else value] for value in values], dtype=np.float32)
            else:
                numeric = pd.to_numeric(values.where(~values.isin(IGNORED)), errors="coerce")
                if not numeric.notna().any():
                    raise ValueError(f"numeric column {column!r} has no training values")
                median = float(numeric.median())
                imputations[column] = median
                encoded[column] = numeric.fillna(median).to_numpy(dtype=np.float32)

        means = {column: float(np.mean(encoded[column])) for column in modeled}
        scales = {}
        for column in modeled:
            scale = float(np.std(encoded[column]))
            scales[column] = scale if math.isfinite(scale) and scale > 0 else 1.0
        if not set(allow_negative) <= (set(integers) | set(floats)):
            raise ValueError("allow_negative_columns must contain only numeric columns")
        return cls(columns, modeled, categorical, integers, floats, excluded, allow_negative,
                   categories, imputations, means, scales, float(missing_value_replacement))

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        if list(frame.columns) != self.columns:
            raise ValueError("CSV headers or column order do not match preprocessing schema")
        result = np.empty((len(frame), len(self.modeled_columns)), dtype=np.float32)
        for position, column in enumerate(self.modeled_columns):
            values = frame[column].astype(str)
            if column in self.categorical_columns:
                mapping = {value: index for index, value in enumerate(self.categories[column])}
                raw = np.asarray([
                    float(mapping[value]) if value in mapping else -1.0 for value in values
                ], dtype=np.float32)
                missing = values.isin(IGNORED).to_numpy()
            else:
                numeric = pd.to_numeric(values.where(~values.isin(IGNORED)), errors="coerce")
                missing = numeric.isna().to_numpy()
                raw = numeric.fillna(self.imputations[column]).to_numpy(dtype=np.float32)
            normalized = (raw - self.means[column]) / self.scales[column]
            normalized[missing] = self.missing_value_replacement
            result[:, position] = normalized
        return result

    def inverse(self, values: np.ndarray, source: pd.DataFrame,
                unchanged: np.ndarray) -> pd.DataFrame:
        repaired = source.copy(deep=True)
        for position, column in enumerate(self.modeled_columns):
            decoded = values[:, position] * self.scales[column] + self.means[column]
            for row in range(len(source)):
                original = str(source.iloc[row][column])
                if original in IGNORED or unchanged[row, position]:
                    continue
                if column in self.categorical_columns:
                    levels = self.categories[column]
                    index = int(np.clip(np.rint(decoded[row]), 0, len(levels) - 1))
                    repaired.iat[row, repaired.columns.get_loc(column)] = levels[index]
                elif column in self.integer_columns:
                    value = decoded[row] if column in self.allow_negative_columns else max(0.0, decoded[row])
                    repaired.iat[row, repaired.columns.get_loc(column)] = str(int(np.rint(value)))
                else:
                    value = decoded[row] if column in self.allow_negative_columns else max(0.0, decoded[row])
                    repaired.iat[row, repaired.columns.get_loc(column)] = format(float(value), ".12g")
        return repaired

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns, "modeled_columns": self.modeled_columns,
            "categorical_columns": self.categorical_columns,
            "integer_columns": self.integer_columns, "float_columns": self.float_columns,
            "excluded_columns": self.excluded_columns,
            "allow_negative_columns": self.allow_negative_columns, "categories": self.categories,
            "imputations": self.imputations, "means": self.means, "scales": self.scales,
            "missing_value_replacement": self.missing_value_replacement,
        }
