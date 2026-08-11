CXX ?= c++
ifeq ($(OS),Windows_NT)
  PYTHON ?= python
else
  PYTHON ?= python3
endif

BUILD_DIR := build
GAMMAMAX_DIR := sources/gammamax
FORMATS := date time url isbn ipv4 ipv6
GAMMAMAX := $(BUILD_DIR)/gammamax
STDIN_VALIDATORS := $(addprefix $(BUILD_DIR)/validate_,$(FORMATS))
VALIDATOR_SOURCE := validators/validator.cpp
GAMMAMAX_HEADERS := $(wildcard $(GAMMAMAX_DIR)/include/gammamax/*.hpp)
CPPFLAGS := -I$(GAMMAMAX_DIR)/include -I$(GAMMAMAX_DIR)/third_party
CXXFLAGS ?= -O2 -DNDEBUG -std=c++20 -Wall -Wextra -Wpedantic

ifeq ($(OS),Windows_NT)
  EXE_SUFFIX := .exe
  LDFLAGS := -static
  GAMMAMAX_LDLIBS := -lpsapi
endif

GAMMAMAX_TARGET := $(GAMMAMAX)$(EXE_SUFFIX)
STDIN_VALIDATOR_TARGETS := $(addsuffix $(EXE_SUFFIX),$(STDIN_VALIDATORS))

.PHONY: all generate smoke test clean
all: $(GAMMAMAX_TARGET) $(STDIN_VALIDATOR_TARGETS)

$(BUILD_DIR):
	$(PYTHON) -c "from pathlib import Path; Path(r'$@').mkdir(parents=True, exist_ok=True)"

$(GAMMAMAX_TARGET): $(GAMMAMAX_DIR)/src/main.cpp $(GAMMAMAX_HEADERS) $(GAMMAMAX_DIR)/third_party/nlohmann/json.hpp Makefile | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $< $(LDFLAGS) $(GAMMAMAX_LDLIBS) -o $@

$(BUILD_DIR)/validate_%$(EXE_SUFFIX): $(VALIDATOR_SOURCE) Makefile | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $< $(LDFLAGS) -o $@

generate:
	$(PYTHON) shared-suite/generate_cases.py

smoke: all generate
	$(PYTHON) run_smoke_tests.py

test: all generate
	$(PYTHON) run_tests.py

clean:
	$(PYTHON) -c "import shutil; shutil.rmtree(r'$(BUILD_DIR)', ignore_errors=True); shutil.rmtree('results', ignore_errors=True)"
