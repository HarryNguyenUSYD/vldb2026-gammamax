# VLDB GIDCL test suite

Test cases are generated centrally and copied into this suite manually. Result
scoring uses the suite-local copy of the common schema-v2 CSV evaluator and
writes `benchmark.json`.

Portable GIDCL adapter for four shared local datasets. The adapter detects invalid cells with generated column
constraints, retrieves up to five related rows, and requests corrections from
an OpenAI-compatible API. It does not use original trained RoBERTa detector or
LoRA checkpoint.

## Requirements

- Python 3.10 or newer
- GNU Make
- `openai` Python package
- `OPENAI_API_KEY`

The suite can run in a macOS SSH session with these dependencies; it does not
compile C++ or require a GPU. Use Python 3.10 or newer rather than the macOS
system Python if it is older. Unit tests use mocked API responses and require
neither an API key nor the `openai` package.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install openai
export OPENAI_API_KEY="..."
export OPENAI_API_BASE="https://api.openai.com/v1" # optional
export GIDCL_MODEL="gpt-4o-mini"                   # optional config override
```

## Run

Run both corruption rates, either individual rate, or the shared smoke case:

```sh
make test
make test-50
make test-90
make smoke
```

Restrict full run:

```sh
make test DATASETS="adult_20 support2_880"
```

GIDCL makes paid API requests. `config.json` contains only algorithm settings;
all commands consume manually copied cases and never regenerate them. Start
with `make smoke`, which runs 100 rows of `adult_20`.

## Outputs

```text
generated-50/
`-- adult_20/
    |-- original.csv
    |-- corrupted.csv
    |-- oracles.json
    |-- case.json
    `-- run/
        |-- algorithm-config.json
        |-- repaired.csv
        |-- telemetry.json
        `-- benchmark.json
```

Runs refuse to overwrite an existing `run/` directory. `make clean-results`
removes algorithm run outputs. `make clean` also removes temporary
build files.

Telemetry uses schema version 2 and records every cell, including originally
missing cells, so their repairs and timeouts are included in evaluation.

## Direct commands

```sh
python3 vldb_suite.py run adult_20 --config config.json
python3 ../vldb_shared/benchmark.py generate
python3 ../vldb_shared/benchmark.py benchmarks
python3 -m unittest discover -s tests -v
```

Use `python3 ../vldb_shared/benchmark.py benchmarks` to recalculate every saved
run with the shared GammaMax-kNN schema-v2 formulas.

Manual evaluation requires case directory, repaired CSV, telemetry, and saved
algorithm config:

```sh
python3 vldb_suite.py evaluate generated-50/adult_20 \
  generated-50/adult_20/run/repaired.csv \
  --telemetry generated-50/adult_20/run/telemetry.json \
  --algorithm-config generated-50/adult_20/run/algorithm-config.json
```
