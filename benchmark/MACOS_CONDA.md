# Shared macOS Conda environment

ZeroEC and GIDCL benchmark adapters share one Python environment, OpenAI API
key, API endpoint, and model. GammaMax also uses compiler tools installed by
this environment.

Run these commands from repository root on the Mac server.

## 1. Create environment

```zsh
conda env create -f benchmark/environment-macos.yml
conda activate cleaning-benchmark
```

If environment already exists, synchronize it with file:

```zsh
conda env update -f benchmark/environment-macos.yml --prune
conda activate cleaning-benchmark
```

## 2. Load shared OpenAI settings for current SSH session

Enter API key invisibly. Do not type key directly into command or save it in
repository:

```zsh
read -s "OPENAI_API_KEY?OpenAI API key: "
printf '\n'
export OPENAI_API_KEY
export OPENAI_API_BASE="https://api.openai.com/v1"
export BENCHMARK_MODEL="gpt-4o-mini"
```

Verify variables without printing secret:

```zsh
[[ -n "$OPENAI_API_KEY" ]] && echo "API key loaded" || echo "API key missing"
echo "$OPENAI_API_BASE"
echo "$BENCHMARK_MODEL"
```

`OPENAI_API_KEY`, `OPENAI_API_BASE`, and `BENCHMARK_MODEL` are inherited by
both ZeroEC and GIDCL. They remain in current shell session only. Closing SSH
session removes them.

## 3. Enter benchmark directory

```zsh
cd benchmark
```

## 4. Run smoke tests first

```zsh
make smoke-zeroec DATASET=adult_20
make smoke-gidcl DATASET=adult_20
make smoke-gammamax DATASET=adult_20
```

ZeroEC and GIDCL make paid API requests. Smoke runs use at most 100 rows and
always include at least one corrupted row.

## 5. Run complete benchmark

```zsh
make zeroec
make gidcl
make gammamax
```

Each full command runs Adult, Bank Marketing, Census-Income KDD, and SUPPORT2.

Results are written under:

```text
benchmark/results/<algorithm>/<dataset>/<full-or-smoke>/
```

## 6. Reactivate later

```zsh
conda activate cleaning-benchmark
```

OpenAI variables are session-only, so load them again using step 2 after a new
SSH login.
