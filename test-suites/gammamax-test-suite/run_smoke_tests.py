#!/usr/bin/env python3
"""Benchmark gammaMax on the first ten generated cases."""

from runner_support import run_benchmark, worker_count


if __name__ == "__main__":
    run_benchmark(worker_count(), case_limit=10, result_stem="benchmark-smoke")
