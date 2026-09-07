#!/usr/bin/env python3
"""Portable, offline LoPSTER adapter for prepared VLDB suite cases."""

from __future__ import annotations

import hashlib
import json
import platform
import time
from pathlib import Path
from typing import Any

import vldb_suite as suite


def check_environment() -> None:
    try:
        import numpy  # noqa: F401
        import pandas  # noqa: F401
        import tensorflow  # noqa: F401
    except ImportError as error:
        raise RuntimeError(
            "LoPSTER dependencies are missing; install requirements-macos.txt in Python 3.11"
        ) from error


def cache_key(clean_csv: Path, excluded_indices: set[int], schema: dict[str, Any],
              config: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(clean_csv.read_bytes())
    relevant = {
        key: config[key] for key in (
            "seed", "training_max_rows", "validation_fraction", "epochs",
            "learning_rate", "latent_dimension", "operators", "batch_size",
            "missing_value_replacement",
        )
    }
    digest.update(json.dumps({
        "excluded": sorted(excluded_indices), "schema": schema,
        "config": relevant, "preprocessing_version": 1,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


def run(case_dir: Path, clean_csv: Path, output_dir: Path, config: dict[str, Any],
        schema: dict[str, Any], excluded_source_indices: set[int],
        cache_root: Path) -> None:
    import numpy as np
    import pandas as pd

    from lopster.model import train_and_repair
    from lopster.preprocessing import IGNORED, TabularPreprocessor, select_training_rows

    started = time.monotonic()
    columns, dirty_rows = suite.read_csv(case_dir / "corrupted.csv")
    dirty = pd.DataFrame(dirty_rows, columns=columns, dtype=str)
    clean = pd.read_csv(clean_csv, dtype=str, keep_default_na=False, na_filter=False)
    if list(clean.columns) != columns:
        raise ValueError("clean and corrupted CSV schemas do not match")
    if any(index < 0 or index >= len(clean) for index in excluded_source_indices):
        raise ValueError("case contains an invalid source_row_indices entry")

    selected, selected_indices = select_training_rows(
        clean, excluded_source_indices, config["training_max_rows"], config["seed"])
    if set(selected_indices) & excluded_source_indices:
        raise RuntimeError("training/evaluation row leakage detected")
    validation_count = max(1, round(len(selected) * config["validation_fraction"]))
    training_count = len(selected) - validation_count
    if training_count < 1:
        raise ValueError("not enough rows for LoPSTER training and validation")
    training_frame = selected.iloc[:training_count].reset_index(drop=True)
    validation_frame = selected.iloc[training_count:].reset_index(drop=True)

    preprocessor = TabularPreprocessor.fit(
        training_frame, schema, config["missing_value_replacement"])
    train_values = preprocessor.transform(training_frame)
    validation_values = preprocessor.transform(validation_frame)
    dirty_values = preprocessor.transform(dirty)
    preprocessing_seconds = time.monotonic() - started

    key = cache_key(clean_csv, excluded_source_indices, schema, config)
    model_dir = cache_root / clean_csv.parent.name / key
    result = train_and_repair(train_values, validation_values, dirty_values, config, model_dir)

    decode_started = time.monotonic()
    repaired = preprocessor.inverse(result.repaired, dirty, result.unchanged)
    output_dir.mkdir(parents=True, exist_ok=False)
    suite.write_csv(output_dir / "repaired.csv", columns, repaired.to_dict("records"))
    decode_seconds = time.monotonic() - decode_started
    inference_seconds = result.inference_seconds
    training_seconds = result.training_seconds

    effective = dict(config)
    effective.update({
        "cache_key": key, "cache_hit": result.cache_hit,
        "effective_training_rows": training_count,
        "effective_validation_rows": validation_count,
        "training_source_indices": selected_indices[:training_count],
        "validation_source_indices": selected_indices[training_count:],
        "evaluation_overlap": 0,
    })
    suite.write_json(output_dir / "algorithm-config.json", effective)
    suite.write_json(model_dir / "preprocessing.json", preprocessor.to_dict())

    eligible = [(row, column) for row in range(len(dirty)) for column in columns
                if str(dirty.iloc[row][column]) not in IGNORED]
    per_cell = inference_seconds / len(eligible) if eligible else 0.0
    column_data = {}
    for column in columns:
        position = columns.index(column)
        modeled_position = (preprocessor.modeled_columns.index(column)
                            if column in preprocessor.modeled_columns else None)
        eligible_rows = [row for row in range(len(dirty))
                         if str(dirty.iloc[row][column]) not in IGNORED]
        changed = sum(
            str(repaired.iloc[row][column]) != str(dirty.iloc[row][column])
            for row in eligible_rows
        )
        detected = (sum(not bool(result.unchanged[row, modeled_position]) for row in eligible_rows)
                    if modeled_position is not None else 0)
        column_data[column] = {
            "execution_time_seconds": per_cell * len(eligible_rows),
            "detected_cells": detected, "changed_cells": changed,
        }
    cells = [
        {"row": row, "column": column, "timed_out": False,
         "execution_time_seconds": per_cell,
         "detected": (not bool(result.unchanged[row, preprocessor.modeled_columns.index(column)]))
                     if column in preprocessor.modeled_columns else False,
         "changed": str(repaired.iloc[row][column]) != str(dirty.iloc[row][column])}
        for row, column in eligible
    ]
    total_seconds = time.monotonic() - started
    suite.write_json(output_dir / "telemetry.json", {
        "total_execution_time_seconds": total_seconds,
        "preprocessing_time_seconds": preprocessing_seconds,
        "training_time_seconds": training_seconds,
        "inference_time_seconds": inference_seconds,
        "decoding_time_seconds": decode_seconds,
        "model_cache_hit": result.cache_hit,
        "training_rows": training_count, "validation_rows": validation_count,
        "train_loss": result.train_loss, "validation_loss": result.validation_loss,
        "tensorflow_version": result.tensorflow_version,
        "architecture": platform.machine(), "device": "CPU",
        "columns": column_data, "cells": cells,
    })
