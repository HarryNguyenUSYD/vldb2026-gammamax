# VLDB LoPSTER test suite

Test cases are generated centrally and copied into this suite manually. Result
scoring uses the suite-local copy of the common schema-v2 CSV evaluator and
writes `benchmark.json`.

Self-contained benchmark adapter for **Generalizable Data Cleaning of Tabular
Data in Latent Space (LoPSTER)** by dos Reis, Abdelaal, and Binnig (PVLDB 2024).
It vendors the algorithm needed at runtime, uses no network service, and keeps
the case and result formats of the sibling VLDB suites.

## macOS setup

The supported baseline is Python 3.11 on Intel or Apple Silicon, using CPU only.

```sh
cd vldb-theory-test-suite-lopster
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-macos.txt
```

TensorFlow training is compute intensive. Full configurations use at most 8,000
clean rows per dataset and 100 epochs.

No API key, network connection, GPU, external repository, or files outside this
directory are needed after dependencies have been installed.

## Runs

Run both corruption rates, either individual rate, or the shared 100-row smoke
case:

```sh
make test
make test-50
make test-90
make smoke
```

Restrict a run to selected datasets:

```sh
make test-50 DATASETS="adult_20 support2_880"
```

Cases are copied manually from `../vldb_shared`; all Make targets use them
without rewriting them:

```sh
VLDB_CASES_ROOT=generated-50 python3 vldb_suite.py run adult_20 --config config.json
```

Each execution writes:

```text
generated-50/adult_20/run/
|-- algorithm-config.json
|-- repaired.csv
|-- telemetry.json
`-- benchmark.json
```

`benchmark.json` retains oracle accuracy, exact accuracy, timeout rate, and
execution-time metrics at column and table level. LoPSTER additionally records
training, inference, preprocessing, cache, loss, architecture, and changed-cell
telemetry. Per-cell timeouts are always false because LoPSTER trains and infers
in batches rather than issuing independent cell requests.

## Training and leakage prevention

For each case, the adapter excludes every source row listed in `case.json` from
the clean training pool, deterministically shuffles the remainder, selects up to
8,000 rows, and reserves 10% for validation. Numeric nulls are imputed with
training medians and categorical nulls with training modes. Encoders, scaling,
and imputation are fitted only on training rows. The algorithm never reads
`original.csv` or `oracles.json`; those files are used only by the evaluator.

Models are cached under `models/` using the source-data hash, excluded indices,
schema, preprocessing version, and hyperparameters. Identical 50% and 90% cases
can therefore share a model safely.

## Cleanup and evaluation

```sh
make clean-results VLDB_CASES_ROOT=generated-50  # remove run outputs, retain cases
make clean-models                         # remove cached models
make clean                                # remove outputs, models, and build files
```

Manual evaluation uses the same contract as the GIDCL suite:

```sh
python3 vldb_suite.py evaluate generated-50/adult_20 \
  generated-50/adult_20/run/repaired.csv \
  --telemetry generated-50/adult_20/run/telemetry.json \
  --algorithm-config generated-50/adult_20/run/algorithm-config.json
```

The shared benchmark introduces arbitrary character edits, whereas released
LoPSTER training synthesizes missing values and proportional numeric changes.
That distribution mismatch is intentional so all algorithms see the same cases.

## Attribution

```bibtex
@inproceedings{lopster2024,
  title   = {Generalizable Data Cleaning of Tabular Data in Latent Space},
  author  = {Eduardo dos Reis and Mohamed Abdelaal and Carsten Binnig},
  journal = {Proceedings of the VLDB Endowment},
  volume  = {17},
  number  = {13},
  pages   = {4786--4798},
  year    = {2024}
}
```
