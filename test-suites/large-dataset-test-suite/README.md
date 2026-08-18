# Adult large-dataset gammaMax suite

This self-contained suite measures gammaMax repair accuracy on the 15 columns
of the UCI Adult dataset. There is one test case per column. Each case retains
the first 80% of all complete rows as training cells and repairs the remaining
20% as independently corrupted cells in sequence.

The suite contains a vendored Adult dataset, its 15 generated C++ oracles, and
a suite-local gammaMax snapshot.

## Generation

```sh
make generate
```

Generation uses seed 0, filters the Adult dataset to complete rows, and
deterministically shuffles all eligible rows. The first 80% become the shared
training CSV and the remaining 20% are clean repair sources. The split point is
the floor of `complete_row_count * 0.8`, ensuring every complete row is used.
Every source cell receives one insertion, deletion, or substitution;
the generator retains only distance-one mutations rejected by that column's
oracle definition.

Generated files are in `shared-suite/test-cases/`:

- `training.csv`: the 80% training partition, with duplicates preserved;
- `clean-sources.csv`: the held-out 20% partition;
- `corrupted.csv`: all 150 held-out cells corrupted;
- `test-cases.json`: 15 column cases, each containing the full 20% partition.

## Algorithm behavior

For each column, gammaMax deduplicates positive strings internally and constructs
one immutable PTA and one set of k-tail signatures. The original training test
data remains unchanged. Corrupted cells are repaired sequentially while committed
merge history and rejected candidates carry forward.

Deduplication, PTA construction, k-tail preprocessing, and per-cell n-gram
training are measured but untimed. A fresh 60-second deadline begins immediately
before each cell's fixing iterations. A timeout records that cell as failed,
retains safely committed learning, and continues with the next cell.

The configuration is k=3, n=2, RSR batch size 8, n-gram batch size 1, seed 0,
and a positive-training-example cap of 500. Other algorithm resource limits
are unbounded. After deduplication, gammaMax sorts the unique values, uses the
first `max_positive_examples` values, and ignores any remaining positive
examples for PTA construction, k-tail preprocessing, and n-gram training. The
full training partition remains present in the generated test cases.

## Build and run

Requirements are Python 3.9+, Make, and a C++20 compiler.

```sh
make test
```

To run one complete column case:

```sh
make smoke
```

CMake can build the executable and all 15 oracles:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
python3 run_tests.py
```

Results are written to `results/`. Each column reports cells fixed out of its
20% held-out partition,
accuracy, exact restorations, timeouts, errors, preprocessing measurements, and
detailed per-cell measurements. Aggregate accuracy is also reported over all
held-out cells and as the macro-average of the 15 column accuracies.

While a benchmark is running, a once-per-second overall timer displays elapsed
wall time, completed column cases, and the aggregate number of cells fixed out
of all held-out cells. Completed columns are printed as permanent progress
lines beneath the timer.

The CSV and summary JSON are atomically updated after every completed column.
If the remaining benchmark is interrupted, results for all finished columns
remain available. Partial summaries report `run_complete: false` together with
the planned and completed test-case counts.
