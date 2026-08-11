#!/usr/bin/env python3
"""Generate the deterministic gammaMax/betaMax-old test corpus."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "suite-config.json"
TEST_CASES = ROOT / "test-cases"


def _date(rng: random.Random) -> str:
    return f"{rng.randrange(10000):04d}-{rng.randrange(100):02d}-{rng.randrange(100):02d}"


def _time(rng: random.Random) -> str:
    return f"{rng.randrange(100):02d}:{rng.randrange(100):02d}:{rng.randrange(100):02d}"


def _url(rng: random.Random) -> str:
    scheme = rng.choice(("http", "https"))
    prefix = rng.choice(("", "www."))
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    domain = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8)))
    tld = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 3)))
    path = rng.choice(("", "/" + "".join(
        rng.choice(alphabet) for _ in range(rng.randint(1, 8))
    )))
    return f"{scheme}://{prefix}{domain}.{tld}{path}"


def _isbn(rng: random.Random) -> str:
    separator = rng.choice(("", "-", " "))
    digits = [str(rng.randrange(10)) for _ in range(9)]
    return separator.join(digits) + separator + rng.choice("0123456789X")


def _ipv4(rng: random.Random) -> str:
    return ".".join(str(rng.randrange(1000)) for _ in range(4))


def _ipv6(rng: random.Random) -> str:
    hexadecimal = "0123456789abcdef"
    nonzero = "123456789abcdef"

    def group() -> str:
        length = rng.randint(1, 4)
        return rng.choice(nonzero) + "".join(
            rng.choice(hexadecimal) for _ in range(length - 1)
        )

    return ":".join(group() for _ in range(8))


FORMATS: tuple[tuple[str, str, str, Callable[[random.Random], str]], ...] = (
    ("date", "Date", r"^\d{4}-\d{2}-\d{2}$", _date),
    ("time", "Time", r"^\d{2}:\d{2}:\d{2}$", _time),
    ("url", "URL", r"^https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)$", _url),
    ("isbn", "ISBN", r"^(?:\d[- ]?){9}[\dX]$", _isbn),
    ("ipv4", "IPv4", r"^(\d{1,3}\.){3}\d{1,3}$", _ipv4),
    ("ipv6", "IPv6", r"^(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$", _ipv6),
)


def edit_distance(left: str, right: str) -> int:
    """Return character-level Levenshtein distance."""
    previous = list(range(len(right) + 1))
    for row, left_character in enumerate(left, 1):
        current = [row]
        for column, right_character in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (left_character != right_character),
            ))
        previous = current
    return previous[-1]


def _unique_valid_strings(
    regex: str,
    generator: Callable[[random.Random], str],
    count: int,
    rng: random.Random,
    excluded: set[str] | None = None,
) -> set[str]:
    values: set[str] = set()
    forbidden = excluded or set()
    while len(values) < count:
        value = generator(rng)
        if value not in forbidden and re.fullmatch(regex, value):
            values.add(value)
    return values


def _invalid_mutant(
    source: str,
    regex: str,
    target_distance: int,
    rng: random.Random,
    forbidden: set[str],
    min_length: int | None = None,
    max_length: int | None = None,
) -> str:
    for _ in range(4000):
        characters = list(source)
        for _ in range(target_distance):
            operations = ["insert"]
            if characters:
                operations.extend(("delete", "substitute"))
            operation = rng.choice(operations)
            if operation == "insert":
                characters.insert(rng.randrange(len(characters) + 1), "#")
            elif operation == "delete":
                del characters[rng.randrange(len(characters))]
            else:
                characters[rng.randrange(len(characters))] = "#"
        mutant = "".join(characters)
        if (
            mutant not in forbidden
            and not re.fullmatch(regex, mutant)
            and edit_distance(source, mutant) == target_distance
            and (min_length is None or len(mutant) >= min_length)
            and (max_length is None or len(mutant) <= max_length)
        ):
            return mutant
    raise RuntimeError(
        f"Could not generate distance-{target_distance} mutant for {source!r}."
    )


def _generate_case(
    format_name: str,
    category: str,
    regex: str,
    generator: Callable[[random.Random], str],
    format_index: int,
    config: dict[str, int],
    rng: random.Random,
) -> dict[str, Any]:
    positives = _unique_valid_strings(
        regex,
        generator,
        rng.randint(config["S_plus_min"], config["S_plus_max"]),
        rng,
    )
    negatives: set[str] = set()
    target_negatives = rng.randint(config["S_minus_min"], config["S_minus_max"])
    while len(negatives) < target_negatives:
        source = rng.choice(sorted(positives))
        target_distance = rng.randint(config["d_min"], config["d_max"])
        negatives.add(_invalid_mutant(
            source, regex, target_distance, rng, positives | negatives
        ))

    examples = positives | negatives
    for _ in range(4000):
        valid_source = next(iter(_unique_valid_strings(
            regex, generator, 1, rng, examples
        )))
        if (
            valid_source not in examples
            and config["s_min"] - config["d_min"]
            <= len(valid_source)
            <= config["s_max"]
        ):
            break
    else:
        raise RuntimeError(f"Could not generate feasible source for {format_name}.")

    target_distance = rng.randint(config["d_min"], config["d_max"])
    corrupt = _invalid_mutant(
        valid_source,
        regex,
        target_distance,
        rng,
        examples | {valid_source},
        config["s_min"],
        config["s_max"],
    )
    return {
        "case_id": f"{format_name}-{format_index:03d}",
        "format": format_name,
        "category": category,
        "positive_examples": sorted(positives),
        "negative_examples": sorted(negatives),
        "regex": regex,
        "corrupt_string": corrupt,
        "valid_source": valid_source,
        "true_edit_distance": edit_distance(corrupt, valid_source),
    }


def generate_cases(config: dict[str, int]) -> list[dict[str, Any]]:
    target_count = config["N"]
    if target_count % len(FORMATS):
        raise ValueError("N must be divisible by six formats.")
    per_format = target_count // len(FORMATS)
    rng = random.Random(config["seed"])
    return [
        _generate_case(name, category, regex, generator, index, config, rng)
        for name, category, regex, generator in FORMATS
        for index in range(per_format)
    ]


def validate_cases(cases: list[dict[str, Any]], config: dict[str, int]) -> None:
    if len(cases) != config["N"]:
        raise AssertionError(f"Expected {config['N']} cases.")
    expected_per_format = config["N"] // len(FORMATS)
    for name, _, _, _ in FORMATS:
        if sum(case["format"] == name for case in cases) != expected_per_format:
            raise AssertionError(f"Incorrect case count for {name}.")
    for case in cases:
        examples = set(case["positive_examples"]) | set(case["negative_examples"])
        if re.fullmatch(case["regex"], case["valid_source"]) is None:
            raise AssertionError(f"Invalid valid_source in {case['case_id']}.")
        if case["valid_source"] in examples:
            raise AssertionError(
                f"valid_source duplicates a training example in {case['case_id']}."
            )
        if re.fullmatch(case["regex"], case["corrupt_string"]) is not None:
            raise AssertionError(f"Corrupt string is valid in {case['case_id']}.")
        if case["corrupt_string"] in examples:
            raise AssertionError(
                f"corrupt_string duplicates a training example in {case['case_id']}."
            )
        if not config["s_min"] <= len(case["corrupt_string"]) <= config["s_max"]:
            raise AssertionError(f"Corrupt length is out of range in {case['case_id']}.")
        measured = edit_distance(case["corrupt_string"], case["valid_source"])
        if measured != case["true_edit_distance"]:
            raise AssertionError(f"Incorrect distance in {case['case_id']}.")
        if not config["d_min"] <= measured <= config["d_max"]:
            raise AssertionError(f"Distance is out of range in {case['case_id']}.")


def load_generation_config() -> dict[str, int]:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {
        key: int(value)
        for key, value in raw.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }


def write_cases() -> None:
    config = load_generation_config()
    cases = generate_cases(config)
    validate_cases(cases, config)
    TEST_CASES.mkdir(parents=True, exist_ok=True)
    path = TEST_CASES / "test-cases.json"
    path.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    print(f"generated {path}: {len(cases)} cases")


if __name__ == "__main__":
    write_cases()
