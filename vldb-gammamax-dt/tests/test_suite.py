from __future__ import annotations

import importlib.util
import copy
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "vldb_suite.py"
SPEC = importlib.util.spec_from_file_location("vldb_suite", MODULE_PATH)
suite = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(suite)


class ConfigurationTests(unittest.TestCase):
    def test_build_failure_includes_compiler_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary:
            failure = subprocess.CompletedProcess([], 1, "main.cpp: error: example diagnostic\n")
            with patch.object(suite, "cxx_compiler", return_value="c++"), \
                 patch.object(suite.subprocess, "run", return_value=failure):
                with self.assertRaisesRegex(RuntimeError, "main.cpp: error: example diagnostic"):
                    suite.direct_build(suite.HERE / "algorithm", Path(temporary),
                                       "vldb_theory_algorithm")

    def test_repository_config_is_algorithm_only_and_valid(self):
        path = Path(__file__).resolve().parents[1] / "config.json"
        raw = suite.read_json(path)
        self.assertEqual(set(raw), {"algorithm"})
        config = suite.load_config(path)
        self.assertEqual(config["algorithm"]["state_merging"]["k"], 5)
        self.assertEqual(config["algorithm"]["repair"]["n"], 4)

    def test_imputation_configuration_bounds_and_types(self):
        config = suite.read_json(suite.DEFAULT_CONFIG)
        invalid = [
            ("max_depth", -1), ("max_depth", 6), ("max_depth", True),
            ("max_depth", 1.0), ("max_depth", "5"),
            ("min_samples_leaf", 0), ("min_samples_leaf", 2**64),
            ("max_thresholds", 0), ("max_thresholds", 33),
            ("max_decimal_places", -1), ("max_decimal_places", 16),
            ("passes", 2), ("k", 1),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for field, value in invalid:
                with self.subTest(field=field, value=value):
                    altered = copy.deepcopy(config)
                    altered["algorithm"]["imputation"][field] = value
                    suite.write_json(path, altered)
                    with self.assertRaises(ValueError):
                        suite.load_config(path)
            del config["algorithm"]["imputation"]["max_depth"]
            suite.write_json(path, config)
            with self.assertRaises(ValueError):
                suite.load_config(path)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = Path(os.environ["VLDB_ALGORITHM_BINARY"]) if os.getenv("VLDB_ALGORITHM_BINARY") else suite.build_algorithm()
        cls.oracle = Path(os.environ["VLDB_ORACLE_BINARY"]) if os.getenv("VLDB_ORACLE_BINARY") else suite.cmake_build(
            suite.HERE / "oracle", suite.HERE / "build" / "oracle", "vldb_theory_oracle")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.case = Path(self.temporary.name)

    def run_case(self, rows, specs, *, imputation=None, gamma_limit=None, suffix=""):
        columns = [f"c{i}" for i in range(len(specs))]
        dictionaries = [dict(zip(columns, row)) for row in rows]
        suite.write_csv(self.case / "corrupted.csv", columns, dictionaries)
        suite.write_csv(self.case / "original.csv", columns, dictionaries)
        manifest = {"oracles": [dict(spec, column=c) for c, spec in zip(columns, specs)]}
        suite.write_json(self.case / "oracles.json", manifest)
        suite.write_json(self.case / "case.json", {"dataset": "fixture", "generation": {}})
        config = suite.read_json(suite.DEFAULT_CONFIG)["algorithm"]
        config["imputation"]["min_samples_leaf"] = 1
        if imputation:
            config["imputation"].update(imputation)
        if gamma_limit is not None:
            config["repair"]["max_candidate_length"] = gamma_limit
        suite.write_json(self.case / "config.json", config)
        oracles = self.case / "oracles"
        oracles.mkdir(exist_ok=True)
        for i, spec in enumerate(specs):
            shutil.copy2(self.oracle, oracles / (f"oracle_{i:03d}" + self.oracle.suffix))
            suite.write_json(oracles / f"oracle_{i:03d}.json", spec)
        output = self.case / f"repaired{suffix}.csv"
        telemetry_path = self.case / f"telemetry{suffix}.json"
        result = subprocess.run([
            str(self.binary), "--input", str(self.case / "corrupted.csv"),
            "--config", str(self.case / "config.json"), "--oracles-dir", str(oracles),
            "--output", str(output), "--telemetry", str(telemetry_path),
        ], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        _, repaired = suite.read_csv(output)
        telemetry = suite.read_json(telemetry_path)
        self.assertEqual(telemetry["schema_version"], 3)
        self.assertEqual(len(telemetry["cells"]), len(rows) * len(columns))
        self.assertEqual(telemetry["dt_imputed_cells"], sum(cell["dt_imputed"] for cell in telemetry["cells"]))
        self.assertEqual(telemetry["dt_unresolved_cells"], sum(bool(cell["unresolved_reason"]) for cell in telemetry["cells"]))
        benchmark = suite.evaluate_shared(self.case, output, telemetry_path, config)
        for key in ("max_positive_examples_stored", "max_negative_examples_stored"):
            self.assertEqual(benchmark["table"][key],
                             max(column[key] for column in telemetry["columns"].values()))
        for column in telemetry["columns"].values():
            self.assertEqual(column["max_positive_examples_stored"], column["training_examples"])
        self.assertEqual(benchmark["schema_version"], 2)
        self.assertEqual(benchmark["table"]["final_invalid"], 0)
        self.assertEqual(benchmark["table"]["dt_imputed"], telemetry["dt_imputed_cells"])
        self.assertEqual(benchmark["table"]["final_missing"], telemetry["dt_unresolved_cells"])
        return repaired, telemetry, benchmark

    def test_rounded_mean_accepted_and_oracle_queries_cached(self):
        rows = [["23"], ["24"], ["?"], [""]]
        specs = [{"type": "regex", "regex": r"\d{2}"}]
        repaired, telemetry, benchmark = self.run_case(rows, specs)
        self.assertEqual([r["c0"] for r in repaired], ["23", "24", "24", "24"])
        self.assertTrue(telemetry["cells"][2]["rounded"])
        self.assertEqual(telemetry["cells"][2]["candidate_attempts"], 2)
        self.assertEqual(telemetry["columns"]["c0"]["dt_oracle_calls"], 2)
        self.assertEqual(benchmark["table"]["dt_rounded_repairs"], 2)
        repeated, _, _ = self.run_case(rows, specs, suffix="_repeat")
        self.assertEqual(repeated, repaired)

    def test_oracle_rejection_does_not_substitute_observed_value(self):
        repaired, telemetry, _ = self.run_case(
            [["10"], ["20"], ["?"]], [{"type": "enum", "values": ["10", "20"]}])
        self.assertEqual(repaired[-1]["c0"], "?")
        self.assertEqual(telemetry["cells"][-1]["unresolved_reason"], "oracle_rejected")

    def test_no_training_targets_does_not_abort_other_columns(self):
        repaired, telemetry, _ = self.run_case(
            [["?", "red"], ["bad", ""], ["", "red"]],
            [{"type": "enum", "values": ["allowed"]}, {"type": "enum", "values": ["red"]}])
        self.assertEqual(repaired[1], {"c0": "", "c1": "red"})
        self.assertEqual(telemetry["dt_unresolved_cells"], 3)
        self.assertEqual(telemetry["cells"][2]["gamma_outcome"], "gamma_invalidated")
        self.assertEqual(telemetry["cells"][2]["unresolved_reason"], "no_training_targets")

    def test_gamma_invalidated_cell_is_imputed(self):
        repaired, telemetry, _ = self.run_case(
            [["10"], ["20"], ["xxxxxxxx"]], [{"type": "regex", "regex": r"\d{2}"}], gamma_limit=1)
        self.assertEqual(telemetry["cells"][-1]["gamma_outcome"], "gamma_invalidated")
        self.assertTrue(telemetry["cells"][-1]["dt_imputed"])
        self.assertEqual(repaired[-1]["c0"], "15")

    def test_prediction_uses_original_missing_state_after_other_repairs(self):
        rows = [["A", "X"], ["A", "X"], ["B", "X"], ["B", "X"],
                ["?", "Y"], ["?", "Y"], ["?", "?"]]
        repaired, telemetry, _ = self.run_case(rows, [
            {"type": "enum", "values": ["A", "B"]}, {"type": "enum", "values": ["X", "Y"]}])
        self.assertEqual(repaired[-1], {"c0": "A", "c1": "Y"})
        for original, output in zip(rows, repaired):
            for c, value in enumerate(original):
                if not suite.is_ignored(value):
                    self.assertEqual(output[f"c{c}"], value)
        self.assertEqual(telemetry["columns"]["c1"]["dt_training_rows"], 6)

    def test_cpp_rejects_invalid_configuration_like_python(self):
        config = suite.read_json(suite.DEFAULT_CONFIG)["algorithm"]
        for field, value in [("max_depth", True), ("max_depth", -1), ("max_depth", 6),
                             ("max_depth", 1.0), ("min_samples_leaf", 0),
                             ("max_thresholds", 33), ("max_decimal_places", 16), ("passes", 2)]:
            with self.subTest(field=field, value=value):
                altered = copy.deepcopy(config)
                altered["imputation"][field] = value
                suite.write_json(self.case / "invalid.json", altered)
                result = subprocess.run([str(self.binary), "--input", "unused", "--config",
                    str(self.case / "invalid.json"), "--oracles-dir", "unused", "--output", "unused",
                    "--telemetry", "unused"], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("cannot open input CSV", result.stderr)

    def test_schema_three_requires_complete_telemetry(self):
        self.run_case([["red"], ["?"]], [{"type": "enum", "values": ["red"]}])
        path = self.case / "telemetry.json"
        telemetry = suite.read_json(path)
        telemetry["cells"].pop()
        suite.write_json(path, telemetry)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            suite.evaluate_shared(self.case, self.case / "repaired.csv", path, {})


if __name__ == "__main__":
    unittest.main()
