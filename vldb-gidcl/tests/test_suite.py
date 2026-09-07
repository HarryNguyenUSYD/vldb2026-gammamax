from __future__ import annotations

import csv
import importlib.util
import json
import copy
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "vldb_suite.py"
SPEC = importlib.util.spec_from_file_location("vldb_suite", MODULE_PATH)
suite = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(suite)
sys.modules.setdefault("vldb_suite", suite)

GIDCL_PATH = Path(__file__).resolve().parents[1] / "gidcl_runner.py"
GIDCL_SPEC = importlib.util.spec_from_file_location("gidcl_runner_test", GIDCL_PATH)
gidcl = importlib.util.module_from_spec(GIDCL_SPEC)
assert GIDCL_SPEC.loader
GIDCL_SPEC.loader.exec_module(gidcl)


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




class GidclTests(unittest.TestCase):
    def test_benchmark_entry_point_on_shared_smoke_case(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            case = root / "adult_20"
            case.mkdir()
            source = suite.HERE / "generated-smoke" / "adult_20"
            for filename in ("original.csv", "corrupted.csv", "oracles.json", "case.json"):
                (case / filename).write_bytes((source / filename).read_bytes())
            real_run = gidcl.run
            def run_mock(case, output, config):
                real_run(case, output, config, lambda *_: {"corrections": {}})
            with patch.dict(sys.modules, {"gidcl_runner": gidcl}), \
                 patch.object(gidcl, "check_environment"), \
                 patch.object(gidcl, "run", side_effect=run_mock), \
                 patch.object(suite, "resolved_roots", return_value=(root, root)):
                suite.run_algorithm(suite.DEFAULT_CONFIG, ["adult_20"])
                with self.assertRaises(FileExistsError):
                    suite.run_algorithm(suite.DEFAULT_CONFIG, ["adult_20"])
            result = suite.read_json(case / "run" / "benchmark.json")
            self.assertGreater(result["table"]["originally_missing_cells"], 0)
            telemetry = suite.read_json(case / "run" / "telemetry.json")
            self.assertEqual(len(telemetry["cells"]), result["table"]["cells"])

    def test_original_missing_cells_repaired_or_timed_out(self):
        config = {"retrieval_limit": 5, "model": "mock", "request_timeout_seconds": 1}
        for missing in ("", "?"):
            for timeout in (False, True):
                with self.subTest(missing=missing, timeout=timeout), tempfile.TemporaryDirectory() as name:
                    case = self.make_case(Path(name))
                    columns, rows = suite.read_csv(case / "original.csv")
                    rows[0]["code"] = missing
                    suite.write_csv(case / "original.csv", columns, rows)
                    suite.write_csv(case / "corrupted.csv", columns, rows)
                    def request(*_):
                        if timeout:
                            raise TimeoutError()
                        return {"corrections": {"code": "10"}}
                    output = Path(name) / "run"
                    gidcl.run(case, output, config, request)
                    _, repaired = suite.read_csv(output / "repaired.csv")
                    self.assertEqual(repaired[0]["code"], missing if timeout else "10")
                    result = suite.evaluate(case, output / "repaired.csv", output / "benchmark.json",
                                            output / "telemetry.json", config)
                    self.assertEqual(result["table"]["originally_missing_cells"], 1)
                    telemetry = suite.read_json(output / "telemetry.json")
                    record = next(c for c in telemetry["cells"] if c["row"] == 0 and c["column"] == "code")
                    self.assertEqual(record["timed_out"], timeout)

    def make_case(self, root: Path) -> Path:
        case = root / "case"
        case.mkdir()
        columns = ["kind", "code", "note"]
        rows = [
            ["A", "10", "x"],
            ["A", "20", "x"],
            ["B", "30", "y"],
        ]
        dirty = [list(row) for row in rows]
        dirty[0][1] = "bad"
        dirty[0][2] = "wrong"
        write_csv(case / "original.csv", columns, rows)
        write_csv(case / "corrupted.csv", columns, dirty)
        suite.write_json(case / "oracles.json", {"oracles": [
            {"column": "kind", "type": "enum", "values": ["A", "B"]},
            {"column": "code", "type": "enum", "values": ["10", "20", "30"]},
            {"column": "note", "type": "enum", "values": ["x", "y"]},
        ]})
        suite.write_json(case / "case.json", {
            "dataset": "tiny", "generation": {}, "run_metadata": {}
        })
        return case

    def test_retrieve_is_ranked_stable_and_limited(self):
        rows = [
            {"a": "x", "b": "bad", "c": "1"},
            {"a": "x", "b": "ok", "c": "2"},
            {"a": "x", "b": "ok", "c": "1"},
            {"a": "x", "b": "bad", "c": "1"},
        ]
        checks = {"b": lambda value: value == "ok"}
        result = gidcl.retrieve(rows, 0, ["b"], checks, 1)
        self.assertEqual(result, [rows[2]])

    def test_repairs_targets_only_and_writes_valid_telemetry(self):
        with tempfile.TemporaryDirectory() as name:
            case = self.make_case(Path(name))
            output = Path(name) / "run"
            def request(prompt, model, timeout):
                return {"corrections": {"code": "10", "note": "x", "kind": "B"}}
            config = {"retrieval_limit": 5, "model": "mock", "request_timeout_seconds": 1}
            gidcl.run(case, output, config, request)
            _, repaired = suite.read_csv(output / "repaired.csv")
            self.assertEqual(repaired[0], {"kind": "A", "code": "10", "note": "x"})
            telemetry = suite.read_json(output / "telemetry.json")
            columns, original = suite.read_csv(case / "original.csv")
            expected = sum(
                not suite.is_ignored(row[column]) for row in original for column in columns
            )
            self.assertEqual(len(telemetry["cells"]), expected)
            result = suite.evaluate(case, output / "repaired.csv", output / "results.json",
                                    output / "telemetry.json", config)
            self.assertEqual(result["table"]["exact_accuracy"], 1.0)

    def test_partial_response_timeout_and_malformed_response(self):
        config = {"retrieval_limit": 5, "model": "mock", "request_timeout_seconds": 1}
        with tempfile.TemporaryDirectory() as name:
            case = self.make_case(Path(name))
            gidcl.run(case, Path(name) / "partial", config,
                      lambda *_: {"corrections": {"code": "10"}})
            telemetry = suite.read_json(Path(name) / "partial" / "telemetry.json")
            self.assertEqual(telemetry["columns"]["note"]["missing_corrections"], 1)
            gidcl.run(case, Path(name) / "timeout", config,
                      lambda *_: (_ for _ in ()).throw(TimeoutError()))
            telemetry = suite.read_json(Path(name) / "timeout" / "telemetry.json")
            self.assertEqual(telemetry["columns"]["code"]["timeouts"], 1)
            with self.assertRaisesRegex(ValueError, "JSON object"):
                gidcl.run(case, Path(name) / "bad", config, lambda *_: [])
            with self.assertRaisesRegex(RuntimeError, "API failed"):
                gidcl.run(case, Path(name) / "failed", config,
                          lambda *_: (_ for _ in ()).throw(RuntimeError("API failed")))


if __name__ == "__main__":
    unittest.main()
