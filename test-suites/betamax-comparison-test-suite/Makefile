CXX ?= c++
ifeq ($(OS),Windows_NT)
  PYTHON ?= python
else
  PYTHON ?= python3
endif

BUILD_DIR := build
BETAMAX_DIR := sources/betamax
BETAMAX_OLD_DIR := sources/betamax-old
SHARED_SUITE_DIR := shared-suite
BETAMAX := $(BUILD_DIR)/betamax
BETAMAX_OLD := $(BUILD_DIR)/betamax-old
VALIDATOR_SOURCE := validators/validator.cpp
FORMATS := date time url isbn ipv4 ipv6
STDIN_VALIDATORS := $(addprefix $(BUILD_DIR)/validate_,$(FORMATS))
FILE_VALIDATORS := $(addprefix $(BUILD_DIR)/validate_old_,$(FORMATS))
BETAMAX_HEADERS := $(wildcard $(BETAMAX_DIR)/include/betamax/*.hpp)
JSON_HEADER := $(BETAMAX_DIR)/third_party/nlohmann/json.hpp

CPPFLAGS := -I$(BETAMAX_DIR)/include -I$(BETAMAX_DIR)/third_party
CXXFLAGS ?= -O2 -DNDEBUG -std=c++20 -Wall -Wextra -Wpedantic

ifeq ($(OS),Windows_NT)
  EXE_SUFFIX := .exe
  # Workers launch from temporary directories; embed MinGW runtimes.
  LDFLAGS := -static
  BETAMAX_LDLIBS := -lpsapi
endif

BETAMAX_TARGET := $(BETAMAX)$(EXE_SUFFIX)
BETAMAX_OLD_TARGET := $(BETAMAX_OLD)$(EXE_SUFFIX)
STDIN_VALIDATOR_TARGETS := $(addsuffix $(EXE_SUFFIX),$(STDIN_VALIDATORS))
FILE_VALIDATOR_TARGETS := $(addsuffix $(EXE_SUFFIX),$(FILE_VALIDATORS))

.PHONY: all generate smoke test clean

all: $(BETAMAX_TARGET) $(BETAMAX_OLD_TARGET) $(STDIN_VALIDATOR_TARGETS) $(FILE_VALIDATOR_TARGETS)

$(BUILD_DIR):
	$(PYTHON) -c "from pathlib import Path; Path(r'$@').mkdir(parents=True, exist_ok=True)"

$(BETAMAX_TARGET): $(BETAMAX_DIR)/src/main.cpp $(BETAMAX_HEADERS) $(JSON_HEADER) Makefile | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $< $(LDFLAGS) $(BETAMAX_LDLIBS) -o $@

$(BETAMAX_OLD_TARGET): $(BETAMAX_OLD_DIR)/main.cpp Makefile | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $< $(LDFLAGS) -o $@

$(BUILD_DIR)/validate_old_%$(EXE_SUFFIX): $(VALIDATOR_SOURCE) Makefile | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -DVALIDATOR_FILE_INPUT=1 $< $(LDFLAGS) -o $@

$(BUILD_DIR)/validate_%$(EXE_SUFFIX): $(VALIDATOR_SOURCE) Makefile | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $< $(LDFLAGS) -o $@

generate:
	$(PYTHON) $(SHARED_SUITE_DIR)/generate_cases.py

smoke: all generate
	$(PYTHON) run_smoke_tests.py

test: all generate
	$(PYTHON) run_tests.py

clean:
	$(PYTHON) -c "import shutil; shutil.rmtree(r'$(BUILD_DIR)', ignore_errors=True); shutil.rmtree('results', ignore_errors=True)"
