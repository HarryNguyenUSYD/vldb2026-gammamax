# VLDB GammaMax test suite

This self-contained suite runs GammaMax against centrally generated cases that
are copied into the suite manually. Its local `evaluator.py` uses the same
schema-v2 CSV metric formulas as the other test suites.

## Requirements

- Python 3.10 or newer
- GNU Make
- A C++20 compiler
- CMake 3.20 or newer (optional; direct compiler invocation is supported)

The external-oracle adapter supports Windows, macOS, and Linux. No network
access or third-party Python packages are required.

## Run

```sh
make test-50  # all four 50% cases
make test-90  # all four 90% cases
make test     # both rates
make smoke    # shared 100-row adult_20 case
```

Restrict a rate run with:

```sh
make test-50 DATASETS="adult_20 support2_880"
```

These targets consume existing `generated-50`, `generated-90`, and
`generated-smoke` cases. They never generate or copy datasets. Runs write
`algorithm-config.json`, `repaired.csv`, `telemetry.json`, and `benchmark.json`
under each case's `run/` directory and refuse to overwrite an existing run.
Timed-out, unsuccessful, or post-validation-rejected malformed repairs become
missing values. Schema-v2 telemetry records the same `gamma_outcome` boundary
used by the first stage of `vldb-gammamax-knn`; this suite stops at that boundary.

For each full dataset, `shared-generation/<dataset>/` holds the common
1,000-row `original.csv`, `oracles.json`, and `compiled-oracles/` used by both
corruption rates. The `generated-50` and `generated-90` directories contain
only rate-specific case data and outputs. The 100-row smoke case remains
self-contained under `generated-smoke` and uses its own oracle build.

## Individual commands

```sh
make build-algorithm
make cpp-test
make build-oracles VLDB_CASES_ROOT=generated-50
VLDB_CASES_ROOT=generated-50 python3 vldb_suite.py run adult_20
```

Remove run outputs while retaining cases with:

```sh
make clean-results VLDB_CASES_ROOT=generated-50
```
