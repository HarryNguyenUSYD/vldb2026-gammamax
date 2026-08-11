#!/usr/bin/env python3
"""Run one base case for gammaMax and betaMax-old."""

from runner_support import run_benchmark, worker_count


if __name__ == "__main__":
    run_benchmark(worker_count(), case_limit=1, result_stem="benchmark-smoke")
