#!/usr/bin/env python3
from runner_support import run_benchmark, worker_count

if __name__ == "__main__":
    run_benchmark(worker_count())
