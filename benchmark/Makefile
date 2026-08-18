PYTHON ?= python3
CMAKE ?= cmake
CXX ?= c++
DATASET ?= adult_20
DATASETS := adult_20 bank_marketing_222 census_income_kdd_117 support2_880
SEED ?= 0
CORRUPTION_RATE ?= 0.20
MAX_ERRORS_PER_CELL ?= 5
BUILD_DIR ?= build
GAMMAMAX_BINARY := $(BUILD_DIR)/gammamax/gammamax
ORACLE_DIR := $(BUILD_DIR)/oracles/$(DATASET)

.PHONY: generate generate-one oracles gammamax zeroec gidcl full smoke-gammamax smoke-zeroec smoke-gidcl smoke clean

generate:
	$(PYTHON) test-case-constructor/generate_cases.py \
		--corruption-rate $(CORRUPTION_RATE) \
		--max-errors-per-cell $(MAX_ERRORS_PER_CELL) \
		--seed $(SEED)

generate-one:
	$(PYTHON) test-case-constructor/generate_cases.py $(DATASET) \
		--corruption-rate $(CORRUPTION_RATE) \
		--max-errors-per-cell $(MAX_ERRORS_PER_CELL) \
		--seed $(SEED)

$(GAMMAMAX_BINARY):
	$(CMAKE) -S gammamax-batch -B $(BUILD_DIR)/gammamax -DCMAKE_BUILD_TYPE=Release
	$(CMAKE) --build $(BUILD_DIR)/gammamax --config Release

oracles:
	$(PYTHON) oracles/oracle-gen.py datasets/$(DATASET)/oracles.json --output-dir oracles/$(DATASET)
	mkdir -p $(ORACLE_DIR)
	set -e; for source in oracles/$(DATASET)/*.cpp; do \
		name=$$(basename "$$source" .cpp); \
		$(CXX) -std=c++20 -O2 "$$source" -o "$(ORACLE_DIR)/$$name"; \
	done

gammamax: generate $(GAMMAMAX_BINARY)
	$(PYTHON) oracles/regenerate-all.py
	set -e; for dataset in $(DATASETS); do \
		oracle_dir="$(BUILD_DIR)/oracles/$$dataset"; \
		mkdir -p "$$oracle_dir"; \
		for source in oracles/$$dataset/*.cpp; do \
			name=$$(basename "$$source" .cpp); \
			$(CXX) -std=c++20 -O2 "$$source" -o "$$oracle_dir/$$name"; \
		done; \
		$(PYTHON) gammamax-batch/benchmark_runner.py "$$dataset" \
			--binary $(GAMMAMAX_BINARY) --oracle-dir "$$oracle_dir" --seed $(SEED); \
	done

zeroec: generate
	set -e; for dataset in $(DATASETS); do \
		$(PYTHON) ZeroEC/benchmark_runner.py "$$dataset" --seed $(SEED); \
	done

gidcl: generate
	set -e; for dataset in $(DATASETS); do \
		$(PYTHON) GIDCL/benchmark_runner.py "$$dataset" --seed $(SEED); \
	done

full: gammamax zeroec gidcl

smoke-gammamax: generate-one $(GAMMAMAX_BINARY) oracles
	$(PYTHON) gammamax-batch/benchmark_runner.py $(DATASET) \
		--binary $(GAMMAMAX_BINARY) --oracle-dir $(ORACLE_DIR) --seed $(SEED) --smoke

smoke-zeroec: generate-one
	$(PYTHON) ZeroEC/benchmark_runner.py $(DATASET) --seed $(SEED) --smoke

smoke-gidcl: generate-one
	$(PYTHON) GIDCL/benchmark_runner.py $(DATASET) --seed $(SEED) --smoke

smoke: smoke-gammamax smoke-zeroec smoke-gidcl

clean:
	$(CMAKE) -E remove_directory $(BUILD_DIR)
	$(CMAKE) -E remove_directory results
