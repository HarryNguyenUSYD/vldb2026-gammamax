"""Run Adult twice in a fresh build directory, preserving generated cases."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vldb_suite as suite
from evaluator import predicate


def main() -> None:
    binary = Path(os.environ["VLDB_ALGORITHM_BINARY"]) if os.getenv("VLDB_ALGORITHM_BINARY") else suite.build_algorithm()
    oracle = Path(os.environ["VLDB_ORACLE_BINARY"]) if os.getenv("VLDB_ORACLE_BINARY") else suite.cmake_build(
        suite.HERE / "oracle", suite.HERE / "build" / "oracle", "vldb_theory_oracle")
    case = suite.HERE / "generated-smoke" / "adult_20"
    parent = suite.HERE / "build" / "dt-smoke"
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    print(f"Smoke artifacts: {output}", flush=True)
    specs = suite.read_json(case / "oracles.json")["oracles"]
    oracles = output / "compiled-oracles"
    oracles.mkdir()
    for index, spec in enumerate(specs):
        shutil.copy2(oracle, oracles / (f"oracle_{index:03d}" + oracle.suffix))
        suite.write_json(oracles / f"oracle_{index:03d}.json", spec)
    config = suite.load_config(suite.DEFAULT_CONFIG)["algorithm"]
    suite.write_json(output / "algorithm-config.json", config)
    columns, corrupted = suite.read_csv(case / "corrupted.csv")
    accepts = {item["column"]: predicate(item) for item in specs}
    first_csv = None
    for run in (1, 2):
        repaired_path = output / f"repaired-{run}.csv"
        telemetry_path = output / f"telemetry-{run}.json"
        with (output / f"progress-{run}.log").open("w") as log:
            subprocess.run([
                str(binary), "--input", str(case / "corrupted.csv"),
                "--config", str(output / "algorithm-config.json"),
                "--oracles-dir", str(oracles), "--output", str(repaired_path),
                "--telemetry", str(telemetry_path),
            ], stderr=log, check=True, timeout=3600)
        repaired_columns, repaired = suite.read_csv(repaired_path)
        telemetry = suite.read_json(telemetry_path)
        assert columns == repaired_columns and len(corrupted) == len(repaired)
        assert telemetry["schema_version"] == 3
        assert len(telemetry["cells"]) == len(repaired) * len(columns)
        for record in telemetry["cells"]:
            row, column = record["row"], record["column"]
            value = repaired[row][column]
            if suite.is_ignored(value):
                assert record["unresolved_reason"] in {"no_training_targets", "oracle_rejected"}
            else:
                assert accepts[column](value)
            if record["gamma_outcome"] == "gamma_valid":
                assert value == corrupted[row][column]
            if record["gamma_outcome"] in {"gamma_valid", "gamma_repaired"}:
                assert not record["dt_imputed"] and not record["candidate_attempts"]
        benchmark = suite.evaluate_shared(case, repaired_path, telemetry_path, config)
        counts = benchmark["table"]
        assert counts["final_invalid"] == 0
        assert counts["dt_imputed"] == telemetry["dt_imputed_cells"]
        assert counts["final_missing"] == counts["dt_unresolved"] == telemetry["dt_unresolved_cells"]
        for column in columns:
            metrics = telemetry["columns"][column]
            cells = [cell for cell in telemetry["cells"] if cell["column"] == column]
            assert metrics["dt_imputed"] == sum(cell["dt_imputed"] for cell in cells)
            assert metrics["dt_unresolved"] == sum(bool(cell["unresolved_reason"]) for cell in cells)
            assert metrics["dt_depth"] <= config["imputation"]["max_depth"]
        suite.write_json(output / f"benchmark-{run}.json", benchmark)
        csv_bytes = repaired_path.read_bytes()
        if first_csv is not None:
            assert first_csv == csv_bytes, "repaired CSV changed between identical runs"
        first_csv = csv_bytes
        print(f"Run {run}: {counts['dt_imputed']} DT repairs, {counts['dt_rounded_repairs']} rounded, "
              f"{counts['dt_unresolved']} unresolved, zero invalid values", flush=True)
    print("Smoke checks passed; repaired CSVs are byte-identical.", flush=True)


if __name__ == "__main__":
    main()
