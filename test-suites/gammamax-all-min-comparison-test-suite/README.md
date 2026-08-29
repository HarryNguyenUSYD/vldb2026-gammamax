# gammaMax all-minimum comparison suite

This self-contained suite compares the original `gammamax` with
`gammamax-all-min` on the same 150 deterministic date, time, URL, ISBN, IPv4,
and IPv6 repair cases. Both source snapshots, validators, generated cases, and
runner scripts are included; the suite does not use `fse-benchmark`.

The original implementation invokes single-result RSR repeatedly with
`rsr_batch_size=8`. The new implementation performs one C/H computation per
refinement iteration, enumerates all distinct candidates tied at the lowest
edit cost, and then applies the same n-gram ranking. Its
`max_rsr_candidates=-1` setting leaves enumeration unlimited. Both variants
use seed 0, `k=3`, `n=3`, and `ngrams_batch_size=1` by default.

## Run

Requirements are a C++20 compiler, Make, and Python 3.9 or newer.

```sh
make smoke
make test
```

Smoke mode runs a deterministic prefix through both implementations. CMake can
be used directly:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
python3 run_smoke_tests.py
```

Results are written under `results/`. The CSV contains one row per case and
implementation. Summary JSON reports per-implementation aggregates and paired
new-implementation wins, losses, and ties for accuracy, edit distance, wall
time, and peak memory.

For `gammamax-all-min`, each row also records the total RSR calls, total unique
minimum-cost candidates, largest candidate set, calls that returned multiple
candidates, whether a finite enumeration guard was reached, and a JSON array of
per-call minimum cost, candidate count, retained count, and completion status.
The summary aggregates these diagnostics across completed cases.

`ngrams_batch_size=-1` keeps every enumerated candidate after sorting. A finite
`max_rsr_candidates` stops deterministic enumeration after that many unique
strings and ranks the partial set. Exhaustive enumeration may be exponential;
the per-case outer timeout remains the final runtime guard.
