# Benchmark resources

See `STRUCTURE.md` for a complete file-by-file inventory and
`MACOS_CONDA.md` for shared Conda setup instructions.

- `datasets/`: four UCI datasets (`adult_20`, `bank_marketing_222`,
  `census_income_kdd_117`, and `support2_880`), inferred column information,
  and oracle manifests.
- `oracles/`: generated standalone C++ validators and their generator.
- `gammamax-batch/`: source snapshot used for batch column repair.
- `ZeroEC/`: ZeroEC Python source, prompts, requirements, and upstream README.
- `test-case-constructor/`: deterministic generator that copies a complete
  dataset and randomly corrupts a configurable fraction of cells.

ZeroEC and GIDCL include benchmark adapters that consume generated cases and
write the shared result format alongside GammaMax.

Run `python regenerate_dataset_info.py` to infer metadata and manifests from
current clean tables and regenerate matching C++ oracles. The compatibility
wrapper `prepare_shared_datasets.ps1` performs the same action on PowerShell.
Per-column oracles validate numeric ranges, numeric syntax with missing values,
or closed categorical domains; cross-column dependencies remain outside scope.

Generate all current corrupted datasets with default settings (20% of cells,
one to five edits per selected cell):

```sh
python benchmark/test-case-constructor/generate_cases.py
```

Pass one dataset name to generate only that dataset.

Use `--corruption-rate`, `--max-errors-per-cell`, and `--seed` to change the
generation settings. Outputs are `original.csv`, `corrupted.csv`, and
`corruptions.json` under `benchmark/test-cases/<dataset>/`.

## GammaMax column input

Run GammaMax once per dataset column with that column's oracle. `input.json`
contains every cell from the column, without pre-classified labels:

```json
{
  "cells": ["12", "16", "1#2", "12"]
}
```

At startup GammaMax queries the oracle for every cell. Accepted cells become
positive examples; rejected cells become repair inputs. It then runs the normal
batch learning and repair pipeline. Startup scan counts and timing are reported
under `oracle_scan` in the output JSON. The oracle-call limit must be large
enough for the complete scan and subsequent repair-candidate queries.
All benchmark oracles reserve and reject `#`, the generator's insertion and
substitution marker. Make targets regenerate C++ oracles before compiling them.
Empty string and literal `?` are also globally rejected, even when present as
missing-value markers in a clean source table.

## Running algorithms

Run from `benchmark/`. Every full target processes all four datasets in this
order: Adult, Bank Marketing, Census-Income KDD, and SUPPORT2.

```sh
make gammamax
make zeroec
make gidcl
```

Run all three algorithms across all four datasets:

```sh
make full
```

Choose generation settings for all four datasets:

```sh
make gammamax CORRUPTION_RATE=0.10 MAX_ERRORS_PER_CELL=3 SEED=42
```

GammaMax requires CMake and a C++20 compiler. Its target builds GammaMax and
all selected dataset column oracles. ZeroEC and GIDCL require
`OPENAI_API_KEY`. They honor `OPENAI_API_BASE`; models default to
`gpt-4o-mini`. Set `BENCHMARK_MODEL` to force both adapters to use the same
model. Without it, algorithm-specific `ZEROEC_MODEL` and `GIDCL_MODEL` values
remain available. See `MACOS_CONDA.md` for shared macOS setup instructions.

Outputs:

```text
results/<algorithm>/<dataset>/<full-or-smoke>/
├── repaired.csv
└── metrics.json
```

`metrics.json` includes exact repair matches/rate, exact clean-table cell
matches/rate, and exact clean-table row matches/rate in addition to precision,
recall, and F1.

### Smoke tests

```sh
make smoke-gammamax
make smoke-zeroec
make smoke-gidcl
```

Each smoke target samples `min(ceil(5% * rows), 100)` deterministic random
rows. If that sample has no corrupted row, one row is replaced by a random
corrupted row. Smoke targets use `DATASET=adult_20` by default; override that
variable to smoke-test another single dataset. `make smoke` runs all three on
the selected smoke dataset.

GammaMax detects errors with compiled column oracles. ZeroEC and GIDCL apply
equivalent manifest predicates before correction. ZeroEC performs zero-shot
row correction. GIDCL retrieves up to five related rows by agreement on
non-target attributes and supplies them as graph-style correction context.
