from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vldb_suite", ROOT / "vldb_suite.py")
suite = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(suite)


class ConfigurationTests(unittest.TestCase):
    def test_repository_config_is_algorithm_only_and_valid(self):
        path = ROOT / "config.json"
        raw = suite.read_json(path)
        self.assertEqual(set(raw), {"algorithm"})
        config = suite.load_config(path)
        self.assertEqual(config["algorithm"]["state_merging"]["k"], 5)
        self.assertEqual(config["algorithm"]["repair"]["n"], 4)


if __name__ == "__main__":
    unittest.main()
