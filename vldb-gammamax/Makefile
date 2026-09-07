PYTHON ?= python3
CMAKE ?= cmake
export CMAKE
CONFIG ?= config.json
DATASETS ?=
SMOKE_DATASET ?= adult_20

SUITE := $(PYTHON) vldb_suite.py
DATASET_ARGS := $(strip $(DATASETS))

.PHONY: all test test-50 test-90 smoke check build-oracles build-algorithm cpp-test python-test run clean clean-results

all: test

# Reuse pre-generated cases; these targets never generate or copy datasets.
test: check
	$(MAKE) run VLDB_CASES_ROOT=generated-50 DATASETS="$(DATASETS)"
	$(MAKE) run VLDB_CASES_ROOT=generated-90 DATASETS="$(DATASETS)"

test-50: check
	$(MAKE) run VLDB_CASES_ROOT=generated-50 DATASETS="$(DATASETS)"

test-90: check
	$(MAKE) run VLDB_CASES_ROOT=generated-90 DATASETS="$(DATASETS)"

smoke: check
	$(MAKE) run VLDB_CASES_ROOT=generated-smoke DATASETS="$(SMOKE_DATASET)"

check: python-test build-algorithm cpp-test

build-oracles:
	$(SUITE) build-oracles $(DATASET_ARGS) --config $(CONFIG)

build-algorithm:
	$(SUITE) build-algorithm

python-test:
	$(PYTHON) -m unittest discover -s tests -v

cpp-test: build-algorithm
	$(SUITE) test-algorithm

run: build-oracles build-algorithm
	$(SUITE) run $(DATASET_ARGS) --config $(CONFIG)

clean-results:
	$(SUITE) clean-results --config $(CONFIG)

clean:
	$(SUITE) clean --config $(CONFIG)
