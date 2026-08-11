#!/usr/bin/env python3
"""Benchmark gammaMax and betaMax-old on all shared cases."""

from runner_support import run_benchmark, worker_count


if __name__ == "__main__":
    run_benchmark(worker_count())
