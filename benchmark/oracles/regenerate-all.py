#!/usr/bin/env python3
"""Regenerate every dataset's C++ oracles from its oracles.json manifest."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
BENCHMARK_DIR = SCRIPT_DIR.parent
DEFAULT_DATASETS_DIR = BENCHMARK_DIR / "datasets"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Regenerate all dataset C++ oracles from JSON manifests."
    )
    parser.add_argument(
        "--datasets-dir",
        type=Path,
        default=DEFAULT_DATASETS_DIR,
        help="directory containing dataset folders (default: benchmark/datasets)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SCRIPT_DIR,
        help="parent directory for generated dataset folders (default: benchmark/oracles)",
    )
    return parser


def find_manifests(datasets_dir: Path) -> list[Path]:
    if not datasets_dir.is_dir():
        raise ValueError(f"datasets directory does not exist: {datasets_dir}")
    manifests = sorted(
        path
        for path in datasets_dir.glob("*/oracles.json")
        if path.parent.is_dir()
    )
    if not manifests:
        raise ValueError(f"no */oracles.json manifests found in {datasets_dir}")
    return manifests


def regenerate(manifests: list[Path], output_dir: Path) -> int:
    generator = SCRIPT_DIR / "oracle-gen.py"
    if not generator.is_file():
        raise ValueError(f"oracle generator does not exist: {generator}")

    total = 0
    for manifest in manifests:
        dataset = manifest.parent.name
        destination = output_dir / dataset
        print(f"regenerating {dataset} ...", flush=True)
        subprocess.run(
            [
                sys.executable,
                str(generator),
                str(manifest),
                "--output-dir",
                str(destination),
            ],
            check=True,
        )
        total += 1
    return total


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        manifests = find_manifests(args.datasets_dir.resolve())
        count = regenerate(manifests, args.output_dir.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"regenerate-all: {error}\n")
    print(f"regenerated oracle sets for {count} dataset(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
