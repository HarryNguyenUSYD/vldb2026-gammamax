#!/usr/bin/env python3
"""Run the full standalone betaMax test suite."""

from runner_support import run_suite, worker_count


if __name__ == "__main__":
    run_suite(worker_count())
