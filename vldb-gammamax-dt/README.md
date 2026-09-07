# VLDB GammaMax + shallow decision tree test suite

This suite runs a two-stage pipeline against centrally generated test cases:
GammaMax repairs malformed non-empty strings, then shallow decision tree
imputation fills missing cells. Its local `evaluator.py` writes schema-v2
`benchmark.json` files using the common metric formulas.

## Modular pipeline boundary

The GammaMax core headers and `Config` type are identical to the standalone
`vldb-gammamax` implementation. The independent `decision_tree.hpp` module uses an
immutable table snapshot plus its own `TreeConfig`; it does not include or call
GammaMax, its oracle, or its model. `src/main.cpp` is the composition layer: it
runs GammaMax first, converts unresolved invalid cells to missing values, then
passes the snapshot to the imputer. The two algorithms share no mutable model state.

The imputer trains one tree per target with missing cells, using every row with
a present target and all other columns as candidate predictors. Numerical targets
use squared-error splits and mean leaves; categorical targets use Gini splits
and mode leaves. A column is numerical only when all present values parse as
finite numbers, including numeric-looking category codes.

Numerical predictors use a bounded set of quantile thresholds; categorical
predictors use equality splits. Empty strings and `?` are explicit missing
states, distinct from the literal category `MISSING`. Numerical threshold nodes
can have a separate missing child; an unseen missing branch uses the node's
prediction. All populated children satisfy the configured minimum leaf size.
Split and mode ties are deterministic.

Only cells missing in the **post-GammaMax snapshot** may be written, including
invalidated cells and timed-out repairs. There is one pass, no initialization,
and no reuse of predicted values as predictors or training targets. Insufficient
training data or an unsplittable root uses the global mean/mode. Columns without
known targets remain missing, and other columns continue normally.

### Imputation configuration

```json
"imputation": {
  "max_depth": 5,
  "min_samples_leaf": 5,
  "max_thresholds": 16,
  "max_decimal_places": 6
}
```

All four fields are required integers: depth 0–5 (root depth zero), leaf size at
least 1, threshold count 1–32, and decimal places 0–15. Other imputation fields
are rejected. No external ML packages or dataset-specific rules are used.

### Oracle validation and reporting

Numerical predictions first use the mean's shortest round-trip decimal string
without exponent notation. Additional candidates round that same value to
`max_decimal_places`, then progressively fewer decimal places down to zero;
halfway cases round away from zero. Duplicate strings are removed and negative
zero becomes `0`. Candidates are tried by numerical closeness, with stable ties.
For example, `23.6784` produces `23.6784`, `23.678`, `23.68`, `23.7`, `24`.

The first oracle-accepted candidate becomes the repair. Categorical modes also
require oracle acceptance. Acceptance results are cached per column. If every
candidate fails, the cell remains missing with reason `oracle_rejected`; no
observed-value substitution or second fallback prediction is attempted. Missing
training targets use reason `no_training_targets`. Every final nonmissing value
must pass its oracle; missing cells must have an explicit unresolved reason.

Telemetry schema 3 includes every cell, prediction source, candidate attempts,
rounding flags, unresolved reasons, and per-column tree size, training rows,
timings, oracle calls, and repair/fallback/unresolved counts. Benchmark schema 2
retains the existing accuracy formulas and reports `dt_imputed`,
`dt_fallback_predictions`, `dt_rounded_repairs`, and `dt_unresolved` counters.

## Requirements

- Python 3.10 or newer
- GNU Make
- A C++20 compiler
- CMake 3.20 or newer (optional; direct compiler invocation is supported)

On macOS, install Apple Clang with `xcode-select --install` if necessary. No
network access or third-party Python packages are required.

The external-oracle process adapter supports Windows, macOS, and Linux.

## Run

```sh
make test-50  # all four 50% cases
make test-90  # all four 90% cases
make test     # both rates
make smoke    # shared 100-row adult_20 case
```

Restrict a rate run with, for example:

```sh
make test-50 DATASETS="adult_20 support2_880"
```

These targets compile and test the algorithm and oracles, run repairs, and
evaluate the outputs. They consume existing `generated-50`, `generated-90`,
and `generated-smoke` cases without regenerating or copying datasets.

For each full dataset, `shared-generation/<dataset>/` holds the common
1,000-row `original.csv`, `oracles.json`, and `compiled-oracles/` used by both
corruption rates. The `generated-50` and `generated-90` directories contain
only rate-specific case data and outputs. The 100-row smoke case remains
self-contained under `generated-smoke` and uses its own oracle build.

Runs refuse to overwrite existing result files. Use `make clean-results` with
the desired `VLDB_CASES_ROOT`, or archive the results before rerunning.

## Individual commands

```sh
make build-oracles VLDB_CASES_ROOT=generated-50
make build-algorithm
make cpp-test
VLDB_CASES_ROOT=generated-50 python3 vldb_suite.py run adult_20
python3 tests/smoke_imputation.py  # two validated runs in a fresh build directory
```

`case.json` records sampled source rows and corruption metadata. The algorithm
runner writes `algorithm-config.json` under the cases root and `repaired.csv`,
`telemetry.json`, and `benchmark.json` in each case directory. Benchmark metrics
are calculated by the suite-local evaluator. Existing generated datasets and
historical results are not migrated automatically.
