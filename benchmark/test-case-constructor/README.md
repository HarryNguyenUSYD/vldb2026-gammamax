# Random cell-corruption generator

This generator copies a complete benchmark CSV and randomly corrupts a
configurable fraction of its cells. It preserves row and column structure; only
selected cell values change.

For every selected cell, it applies a random number of character edits from 1
through `--max-errors-per-cell`. Each edit is an insertion, substitution, or
deletion. Final value must be rejected by that column's oracle.
The synthetic marker `#` is reserved and rejected by every benchmark oracle.
This guarantees insertion and substitution corruptions remain detectable.

Selection and mutations are deterministic for a given seed. Headers are never
selected. A cell is selected at most once.

## Usage

Default: generate every dataset directory under `benchmark/datasets/`,
corrupting 20% of cells with at most five edits per selected cell:

```sh
python benchmark/test-case-constructor/generate_cases.py
```

Generate one dataset only:

```sh
python benchmark/test-case-constructor/generate_cases.py adult_20
```

Custom configuration:

```sh
python benchmark/test-case-constructor/generate_cases.py \
  --corruption-rate 0.10 \
  --max-errors-per-cell 3 \
  --seed 42
```

External dataset and output directory:

```sh
python benchmark/test-case-constructor/generate_cases.py /path/to/dataset \
  --output /path/to/output
```

## Output

- `original.csv`: exact source CSV copy;
- `corrupted.csv`: same table with selected cells corrupted;
- `corruptions.json`: settings and ground truth, including row, column, clean
  value, corrupted value, and edit sequence.

Corrupted count is `round(rows * columns * corruption_rate)`. Small datasets
may therefore differ slightly from requested percentage.
