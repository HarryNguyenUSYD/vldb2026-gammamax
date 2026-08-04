# betaMax implementation comparison suite

This directory is a self-contained benchmark for `betamax` and `betamax-old`.
It includes source snapshots of both implementations, the vendored JSON header,
both validator protocols, suite configuration, deterministic generator, and
150 generated cases. It requires no repository checkout, archive extraction,
package download, or network access on the server.

## Run on a remote Mac

Requirements:

- macOS with Xcode Command Line Tools (`clang++` and `make`)
- Python 3.9 or newer

Install the command-line tools if necessary:

```sh
xcode-select --install
```

Copy this entire directory to the Mac, for example:

```sh
scp -r betamax-comparison-test-suite user@server:/path/to/
```

Then run on the server:

```sh
cd /path/to/betamax-comparison-test-suite
make test
```

That single command compiles both implementations and all validators,
regenerates the deterministic corpus, and runs all 150 cases. `make smoke`
runs only the first 10 cases. Each implementation runs as a separate phase so
they do not compete with one another. Every test phase uses the largest worker
count exposed by CPU affinity or the operating system. Each case has a
300-second timeout, so the legacy phase can take a long time when many cases
reach that timeout.

The equivalent CMake build is:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel "$(sysctl -n hw.logicalcpu)"
python3 run_smoke_tests.py
```

Outputs are placed in `results/`:

- `benchmark[-smoke].csv`: long-form raw results for both implementations.
- `benchmark[-smoke]-comparison.csv`: one side-by-side row per case.
- `benchmark[-smoke]-summary.json`: aggregate accuracy, timeout, reuse, and
  wall-time measurements.

The current implementation receives its normal `input.json` and `config.json`.
The legacy adapter converts the same case into its required positive, negative,
and broken-string files. Its validator takes a filename because that is the
protocol hard-coded by the legacy oracle. Neither implementation receives the
case's `valid_source`, regular expression, or true edit distance; those values
are used only after execution for scoring.

The shared `-1` limits map directly to the current implementation. The old CLI
supports `-1` for attempts and repair cost, so those are also unbounded. Modern
limits with no old equivalent are omitted, and its internal hard-coded search
safeguards remain. Both versions retain the suite's outer 300-second per-case
timeout.

Live progress uses `completed A/B (total C/D)`: `A/B` resets for each
implementation, while `C/D` spans both phases. The elapsed-seconds prefix
updates every second and continues across the phase boundary.
