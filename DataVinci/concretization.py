"""DataVinci row predicates, concretization constraints, and candidate ranking."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for row, left_character in enumerate(left, 1):
        current = [row]
        for column, right_character in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + (left_character != right_character)))
        previous = current
    return previous[-1]


def tokenize(value: str) -> set[str]:
    parts = {value}
    parts.update(part for part in re.split(r"([^A-Za-z0-9]+)|(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", value) if part)
    return parts


def _build_feature_specs(rows: list[dict[str, str]]) -> list[tuple[str, str, str | int | None]]:
    specs: list[tuple[str, str, str | int | None]] = []
    for column in rows[0] if rows else ():
        values = [row.get(column, "") for row in rows]
        constants = sorted({token for value in values for token in tokenize(value)})
        for constant in constants:
            for operation in ("equals", "contains", "startsWith", "endsWith"):
                specs.append((operation, column, constant))
        frequent_lengths = [length for length, _ in
                            sorted(Counter(map(len, values)).items(), key=lambda item: (-item[1], item[0]))[:5]]
        specs.extend(("length", column, length) for length in frequent_lengths)
        specs.extend((operation, column, None) for operation in
                     ("hasDigits", "isNum", "isError", "isFormula", "isLogical", "isNA", "isText"))
    return specs


def _evaluate_features(rows: list[dict[str, str]],
                       specs: list[tuple[str, str, str | int | None]]) -> list[list[int]]:
    matrix: list[list[int]] = []
    for row in rows:
        features: list[int] = []
        for operation, column, argument in specs:
            value = row.get(column, "")
            if operation == "equals": result = value == argument
            elif operation == "contains": result = str(argument) in value
            elif operation == "startsWith": result = value.startswith(str(argument))
            elif operation == "endsWith": result = value.endswith(str(argument))
            elif operation == "length": result = len(value) == argument
            elif operation == "hasDigits": result = any(c.isdigit() for c in value)
            elif operation == "isNum":
                try: float(value); result = True
                except ValueError: result = False
            elif operation == "isError": result = value.startswith(("#", "ERROR", "!"))
            elif operation == "isFormula": result = value.startswith("=")
            elif operation == "isLogical": result = value.casefold() in {"true", "false"}
            elif operation == "isNA": result = value.casefold() in {"", "na", "n/a", "nan", "null", "none"}
            else: result = isinstance(value, str)
            features.append(int(result))
        matrix.append(features)
    return matrix


def row_features(rows: list[dict[str, str]]) -> tuple[list[list[int]], list[str]]:
    """Generate paper Table 2 boolean predicate features."""
    specs = _build_feature_specs(rows)
    matrix = _evaluate_features(rows, specs)
    if matrix:
        keep = [index for index in range(len(specs))
                if len({row[index] for row in matrix}) > 1]
        specs = [specs[index] for index in keep]
        matrix = [[row[index] for index in keep] for row in matrix]
    names = [f"{operation}({column},{argument!r})" for operation, column, argument in specs]
    return matrix, names


class ConstraintModel:
    def __init__(self, minimum_accuracy: float = 0.8, seed: int = 0) -> None:
        self.minimum_accuracy = minimum_accuracy
        self.seed = seed
        self._models: dict[str, Any] = {}
        self._fallbacks: dict[str, tuple[str, ...]] = {}
        self._feature_names: list[str] = []
        self._feature_specs: list[tuple[str, str, str | int | None]] = []

    def fit(self, rows: list[dict[str, str]], labels: dict[str, list[str]]) -> None:
        self._feature_specs = _build_feature_specs(rows)
        features = _evaluate_features(rows, self._feature_specs)
        if features:
            keep = [index for index in range(len(self._feature_specs))
                    if len({row[index] for row in features}) > 1]
            self._feature_specs = [self._feature_specs[index] for index in keep]
            features = [[row[index] for index in keep] for row in features]
        self._feature_names = [f"{operation}({column},{argument!r})"
                               for operation, column, argument in self._feature_specs]
        for position, targets in labels.items():
            self._fallbacks[position] = tuple(dict.fromkeys(targets))
            if not features or not features[0] or len(set(targets)) < 2:
                continue
            try:
                from sklearn.tree import DecisionTreeClassifier
            except ImportError:
                continue
            best = None
            qualifying = []
            for maximum_leaves in range(2, 17):
                for depth in range(1, 7):
                    model = DecisionTreeClassifier(max_depth=depth, max_leaf_nodes=maximum_leaves,
                                                   random_state=self.seed)
                    model.fit(features, targets)
                    if model.score(features, targets) >= self.minimum_accuracy:
                        qualifying.append((model.tree_.node_count, model.get_depth(), model))
            best = min(qualifying, key=lambda item: (item[0], item[1]))[2] if qualifying else None
            if best is not None:
                self._models[position] = best

    def predict(self, position: str, row: dict[str, str], all_rows: list[dict[str, str]]) -> tuple[str, ...]:
        model = self._models.get(position)
        if model is None:
            return self._fallbacks.get(position, ())
        features = _evaluate_features([row], self._feature_specs)
        return (str(model.predict(features)[0]),)


@dataclass(frozen=True)
class RankedCandidate:
    value: str
    score: float
    edit_distance: int
    alphanumeric_edits: int
    nearest_distance: int
    pattern_coverage: float


def rank_candidates(source: str, candidates: Iterable[str], column: list[str], coverage: float,
                    weights: dict[str, float], programs: dict[str, Any] | None = None) -> list[RankedCandidate]:
    raw = []
    for value in dict.fromkeys(candidates):
        distance = edit_distance(source, value)
        program = (programs or {}).get(value)
        if program is not None:
            alpha_edits = sum(
                1
                for action in program.actions
                if action.kind != "match"
                and (
                    (action.source is not None and action.source.isalnum())
                    or (action.emitted is not None and action.emitted.isalnum())
                )
            )
        else:
            alpha_edits = edit_distance(
                "".join(c for c in source if c.isalnum()),
                "".join(c for c in value if c.isalnum()),
            )
        nearest = min((edit_distance(value, other) for other in column), default=len(value))
        raw.append((value, distance, alpha_edits, nearest))
    ranked = []
    for value, distance, alpha_edits, nearest in raw:
        score = (weights["edit_distance"] * distance
                 + weights["alphanumeric_edits"] * alpha_edits
                 + weights["nearest_value"] * nearest
                 - weights["pattern_coverage"] * coverage)
        ranked.append(RankedCandidate(value, score, distance, alpha_edits, nearest, coverage))
    return sorted(ranked, key=lambda item: (item.score, item.value))
