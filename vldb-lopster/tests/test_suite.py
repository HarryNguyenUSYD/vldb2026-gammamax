from __future__ import annotations

import csv
import importlib.util
import json
import copy
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "vldb_suite.py"
SPEC = importlib.util.spec_from_file_location("vldb_suite", MODULE_PATH)
suite = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(suite)
sys.modules.setdefault("vldb_suite", suite)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import lopster_runner as runner


GENERATION = {
    "seed": 7,
    "max_rows": 3,
    "corruption_rate": 0.5,
    "min_edits_per_cell": 1,
    "max_edits_per_cell": 5,
    "numeric_enum_max_distinct": 3,
    "text_enum_max_distinct": 3,
}


def write_csv(path: Path, columns: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)




class LopsterTests(unittest.TestCase):
    def setUp(self):
        try:
            import numpy as np
            import pandas as pd
        except ImportError as error:
            self.skipTest(f"LoPSTER preprocessing dependencies unavailable: {error}")
        self.np = np
        self.pd = pd
        from lopster.preprocessing import TabularPreprocessor, select_training_rows
        self.Preprocessor = TabularPreprocessor
        self.select_training_rows = select_training_rows

    def test_disjoint_deterministic_selection_and_cap(self):
        frame = self.pd.DataFrame({"x": [str(index) for index in range(20)]})
        first, indices = self.select_training_rows(frame, {1, 4, 9}, 8, 7)
        second, second_indices = self.select_training_rows(frame, {1, 4, 9}, 8, 7)
        self.assertEqual(indices, second_indices)
        self.assertEqual(len(first), 8)
        self.assertFalse(set(indices) & {1, 4, 9})
        self.assertTrue(first.equals(second))

    def test_train_only_imputation_unknown_category_and_round_trip(self):
        frame = self.pd.DataFrame({
            "kind": ["A", "", "B", "A"], "count": ["1", "", "3", "5"],
            "ratio": ["1.5", "2.5", "?", "4.5"],
        })
        schema = {"categorical_columns": ["kind"], "integer_columns": ["count"],
                  "float_columns": ["ratio"], "allow_negative_columns": [],
                  "id_columns": [], "date_columns": []}
        processor = self.Preprocessor.fit(frame, schema, 3.0)
        self.assertEqual(processor.imputations["kind"], "A")
        self.assertEqual(processor.imputations["count"], 3.0)
        dirty = self.pd.DataFrame({"kind": ["NEW", "A"], "count": ["bad", "5"],
                                   "ratio": ["2.5", "4.5"]})
        values = processor.transform(dirty)
        self.assertEqual(values[0, 1], 3.0)
        restored = processor.inverse(values, dirty, self.np.zeros(values.shape, dtype=bool))
        self.assertEqual(restored.iloc[1]["count"], "5")
        self.assertIn(restored.iloc[0]["kind"], ["A", "B"])

    def test_all_repository_schemas_cover_headers(self):
        schemas = suite.read_json(ROOT / "schemas.json")
        for dataset, schema in schemas.items():
            columns, _ = suite.read_csv(ROOT.parent / "vldb_shared" / "datasets" / dataset / "clean.csv")
            declared = (schema["categorical_columns"] + schema["integer_columns"] +
                        schema["float_columns"] + schema["id_columns"] + schema["date_columns"])
            self.assertEqual(set(columns), set(declared), dataset)
            self.assertEqual(len(columns), len(declared), dataset)

    def test_cache_key_changes_with_inputs(self):
        with tempfile.TemporaryDirectory() as name:
            source = Path(name) / "clean.csv"
            write_csv(source, ["x"], [["1"], ["2"]])
            config = suite.load_config(ROOT / "config.json")["algorithm"]
            schema = {"categorical_columns": [], "integer_columns": ["x"],
                      "float_columns": [], "allow_negative_columns": [],
                      "id_columns": [], "date_columns": []}
            first = runner.cache_key(source, {0}, schema, config)
            second = runner.cache_key(source, {1}, schema, config)
            self.assertNotEqual(first, second)

    def test_mocked_run_is_offline_and_writes_complete_outputs(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            case = root / "case"
            case.mkdir()
            write_csv(case / "corrupted.csv", ["kind", "count"], [["A", "bad"], ["", "2"]])
            clean = root / "clean.csv"
            write_csv(clean, ["kind", "count"], [["A", "1"], ["B", "2"], ["A", "3"], ["B", "4"]])
            schema = {"categorical_columns": ["kind"], "integer_columns": ["count"],
                      "float_columns": [], "allow_negative_columns": [],
                      "id_columns": [], "date_columns": []}
            config = dict(suite.load_config(ROOT / "config.json")["algorithm"])
            config.update({"training_max_rows": 3, "validation_fraction": 0.34})
            fake = SimpleNamespace(
                repaired=self.np.asarray([[0.0, 0.0], [0.0, 0.0]], dtype=self.np.float32),
                unchanged=self.np.ones((2, 2), dtype=bool), train_loss=0.1,
                validation_loss=0.2, cache_hit=False, tensorflow_version="mock",
                training_seconds=0.01, inference_seconds=0.01)
            with mock.patch("lopster.model.train_and_repair", return_value=fake):
                runner.run(case, clean, root / "run", config, schema, {0}, root / "models")
            self.assertTrue((root / "run" / "repaired.csv").is_file())
            telemetry = suite.read_json(root / "run" / "telemetry.json")
            self.assertTrue(all(not cell["timed_out"] for cell in telemetry["cells"]))
            self.assertEqual(len(telemetry["cells"]), 3)

    @unittest.skipUnless(__import__("os").getenv("LOPSTER_RUN_TF_TESTS") == "1",
                         "set LOPSTER_RUN_TF_TESTS=1 for the TensorFlow integration test")
    def test_one_epoch_tensorflow_integration(self):
        from lopster.model import train_and_repair
        values = self.np.asarray([[0.0, 1.0], [1.0, 0.0], [0.5, 0.5], [0.2, 0.8]],
                                 dtype=self.np.float32)
        config = dict(suite.load_config(ROOT / "config.json")["algorithm"])
        config.update({"epochs": 1, "latent_dimension": 4, "operators": 2, "batch_size": 2,
                       "reuse_model": False})
        with tempfile.TemporaryDirectory() as name:
            result = train_and_repair(values[:3], values[3:], values[:1], config, Path(name))
        self.assertEqual(result.repaired.shape, (1, 2))


if __name__ == "__main__":
    unittest.main()

