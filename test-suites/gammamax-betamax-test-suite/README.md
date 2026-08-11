# gammaMax/betaMax-old test suite

Self-contained benchmark comparing the best-performing gammaMax configuration
with the legacy `betamax-old` implementation on the same 300 deterministic
repair cases. The corpus contains 50 cases for each of six formats: date, time,
URL, ISBN, IPv4, and IPv6.

## Configurations

gammaMax uses the best-performing configuration from the preceding k/n sweep:

```text
k: 3
n: 2
rsr_batch_size: 8
ngrams_batch_size: 8
```

All gammaMax resource limits are unbounded. `betamax-old` runs with unbounded
repair attempts, edit cost, and per-oracle timeout, and uses a candidate batch
size of 8 (`--attempt-candidates 8` and `--max-candidates 8`); mutation and
equivalence-query sampling are disabled. Both implementations use seed 0 and
a 300-second outer timeout.

There is one gammaMax configuration and one `betamax-old` configuration:

```text
300 base cases x 2 configurations = 600 test-case runs
```

Each configuration runs as a separate phase. Within each phase, `workers: -1`
uses every CPU allowed by process affinity, falling back to operating-system
logical CPU count.

## Run

Requirements are a C++20 compiler, Make, and Python 3.9 or newer.

```sh
make test
```

For a one-base-case validation run across both configurations (2 runs):

```sh
make smoke
```

The equivalent CMake workflow is:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
python3 run_smoke_tests.py
```

Results are written under `results/`:

- `benchmark[-smoke].csv`: long-form results for every implementation/configuration.
- `benchmark[-smoke]-summary.json`: aggregate results for each gammaMax k/n pair
  and `betamax-old`, plus base-case and total-run counts. Measurement totals
  cover successful, non-error cases only. Failed repair edit distances count as
  infinite; strict JSON represents an infinite median as `null` with
  `median_observed_edit_distance_is_infinite: true`.

Neither implementation receives the expected regex, hidden valid source, or
true edit distance. The legacy adapter writes positive, negative, and broken
string files and uses filename-based validators. Hidden scoring fields are used
only by the harness after execution. Final accuracy is checked by the same
compiled validator implementation used as the algorithms' oracle, not by the
descriptive regex stored in each case.
