#!/usr/bin/env python3
"""Run the first ten betaMax test cases."""

from runner_support import SMOKE_RESULTS, run_suite, worker_count


if __name__ == "__main__":
    run_suite(worker_count(), case_limit=10, result_path=SMOKE_RESULTS)
