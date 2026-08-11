# gammaMax test suite

Self-contained benchmark for `gammamax` over 150 deterministic date, time, URL,
ISBN, IPv4, and IPv6 repair cases. It bundles the source snapshot, validators,
configuration, generator, and generated cases.

## Run

Requirements: a C++20 compiler, Make, and Python 3.9 or newer.

```sh
make test
```

`make smoke` builds everything and runs the first ten cases. Cases use the
maximum available worker count and have a 300-second per-case outer timeout.

CMake may be used instead:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
python3 run_smoke_tests.py
```

Results are written under `results/` as long-form CSV and aggregate summary
JSON. gammaMax receives `input.json` and `config.json`; it does not receive the
expected regex, source string, or true edit distance.

The benchmark uses seed 0, `k=3`, `n=3`, `rsr_batch_size=8`, and
`ngrams_batch_size=1`. All exposed iteration and resource limits are unbounded;
the only runtime bound is the 300-second outer timeout per case.
