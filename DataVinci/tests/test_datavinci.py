from __future__ import annotations

import json
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from concretization import edit_distance, rank_candidates, row_features
from datavinci import DataVinci, DataVinciConfig, LearnedPattern
from execution_guided import execute_rows
from repair import UnsupportedRegex, repair_regex
from semantic import AbstractedValue, SemanticAbstractor


class IdentityAbstractor:
    call_count = 0

    def abstract_column(self, values, token_budget=3500):
        return [AbstractedValue(value, value, value, ()) for value in values]


class FakeProfiler:
    def __init__(self, patterns):
        self.patterns = patterns

    def learn(self, values):
        return "10.16.5-test", self.patterns

    def match(self, values, patterns):
        accepted = set()
        for index, value in enumerate(values):
            for item in patterns:
                if item.is_null and value is None:
                    accepted.add(index)
                elif item.regex and value is not None and re.search(item.regex, value) \
                        and not any(re.search(exclusion, value) for exclusion in item.regexes_to_exclude):
                    accepted.add(index)
        return accepted


def pattern(regex, matched, fraction=0.75):
    return LearnedPattern(regex, regex, (), fraction, tuple(matched), False, ())


class DataVinciTests(unittest.TestCase):
    def test_edit_distance_and_paper_aaa3_example(self):
        self.assertEqual(edit_distance("AAA3", "A2.A3."), 3)
        repairs = repair_regex("AAA3", r"(?:A[0-9]\.)+", max_edits=3)
        self.assertTrue(repairs)
        self.assertEqual(repairs[0].cost, 3)
        self.assertTrue(all(item.value.endswith(".") for item in repairs))

    def test_insert_missing_delimiter(self):
        repairs = repair_regex("c3", r"c-[0-9]", max_edits=1)
        self.assertEqual(repairs[0].value, "c-3")
        self.assertEqual(repairs[0].cost, 1)

    def test_default_repair_has_no_invented_three_edit_limit(self):
        repairs = repair_regex("x", r"^abcdef$")
        self.assertTrue(repairs)
        self.assertEqual(repairs[0].value, "abcdef")
        self.assertGreater(repairs[0].cost, 3)

    def test_tied_minimum_repairs_are_retained(self):
        repairs = repair_regex("x", r"^(?:a|b)$")
        self.assertEqual({item.value for item in repairs}, {"a", "b"})

    def test_unsupported_regex_is_explicit(self):
        with self.assertRaises(UnsupportedRegex):
            repair_regex("x", r"(?=x)x")

    def test_execution_partition_handles_exceptional_results(self):
        rows = [{"x": "1"}, {"x": "bad"}, {"x": "nan"}]
        def program(row):
            if row["x"] == "bad": raise ValueError("bad input")
            return math.nan if row["x"] == "nan" else int(row["x"])
        result = execute_rows(rows, program)
        self.assertEqual(result.successful_indices, (0,))
        self.assertEqual(result.failed_indices, (1, 2))

    def test_row_features_are_stable(self):
        rows = [{"x": "AB-1"}, {"x": "CD-2"}]
        matrix, names = row_features(rows)
        self.assertEqual(len(matrix), 2)
        self.assertEqual(len(matrix[0]), len(names))
        self.assertEqual(names, row_features(rows)[1])

    def test_ranking_prefers_near_candidate(self):
        weights = {"edit_distance": 1, "alphanumeric_edits": 1,
                   "nearest_value": 1, "pattern_coverage": 1}
        ranked = rank_candidates("c3", ["c-3", "x-999"], ["c-1", "c-2"], .8, weights)
        self.assertEqual(ranked[0].value, "c-3")

    def test_end_to_end_without_llm_or_real_bridge(self):
        model = DataVinci(DataVinciConfig(semantic_abstraction=False, max_edits=1),
                          abstractor=IdentityAbstractor())
        model.profiler = FakeProfiler([pattern(r"^c-[0-9]$", [0, 1], 2 / 3)])
        result = model.clean_table([{"x": "c-1"}, {"x": "c-2"}, {"x": "c3"}], "x")
        self.assertTrue(result.cells[2].detected)
        self.assertEqual(result.cells[2].repair, "c-3")
        self.assertEqual(result.repaired_rows[2]["x"], "c-3")

    def test_execution_guided_profiles_only_successes(self):
        model = DataVinci(DataVinciConfig(semantic_abstraction=False, max_edits=1),
                          abstractor=IdentityAbstractor())
        model.profiler = FakeProfiler([pattern(r"^c-[0-9]$", [0, 1], 1.0)])
        def program(row):
            if "-" not in row["x"]: raise ValueError("missing delimiter")
            return row["x"].split("-")[1]
        result = model.clean_table([{"x": "c-1"}, {"x": "c-2"}, {"x": "c3"}], "x", program)
        self.assertEqual(result.execution.failed_indices, (2,))
        self.assertEqual(result.cells[2].repair, "c-3")

    def test_semantic_parser_rejects_wrong_cardinality(self):
        with self.assertRaises(ValueError):
            SemanticAbstractor._parse(["US"], {"values": []})

    def test_semantic_span_becomes_one_stable_atomic_symbol(self):
        parsed = SemanticAbstractor._parse(["u.k.-392"], {"values": [{"spans": [{
            "start": 0, "end": 4, "type": "country",
            "original": "u.k.", "replacement": "UK",
        }]}]})[0]
        self.assertEqual(len(parsed.spans[0].marker), 1)
        self.assertEqual(parsed.abstracted, parsed.spans[0].marker + "-392")
        self.assertEqual(parsed.spans[0].original, "u.k.")


if __name__ == "__main__":
    unittest.main()
