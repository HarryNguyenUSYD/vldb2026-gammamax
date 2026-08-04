CXX ?= c++
PYTHON ?= python

BUILD_DIR := build
BETAMAX_DIR := ../betamax
BETAMAX := $(BUILD_DIR)/betamax
VALIDATOR_SOURCE := validators/validator.cpp
FORMATS := date time url isbn ipv4 ipv6
VALIDATORS := $(addprefix $(BUILD_DIR)/validate_,$(FORMATS))
BETAMAX_HEADERS := $(wildcard $(BETAMAX_DIR)/include/betamax/*.hpp)
JSON_HEADER := $(BETAMAX_DIR)/third_party/nlohmann/json.hpp

CPPFLAGS := -I$(BETAMAX_DIR)/include -I$(BETAMAX_DIR)/third_party
CXXFLAGS ?= -O2 -DNDEBUG -std=c++20 -Wall -Wextra -Wpedantic

ifeq ($(OS),Windows_NT)
  EXE_SUFFIX := .exe
  # Test workers launch from isolated temporary directories. Keep the MinGW
  # runtimes in the executables so Windows cannot load incompatible DLLs.
  LDFLAGS := -static
  LDLIBS := -lpsapi
endif

BETAMAX_TARGET := $(BETAMAX)$(EXE_SUFFIX)
VALIDATOR_TARGETS := $(addsuffix $(EXE_SUFFIX),$(VALIDATORS))

.PHONY: all generate smoke test

all: $(BETAMAX_TARGET) $(VALIDATOR_TARGETS)

$(BUILD_DIR):
	$(PYTHON) -c "from pathlib import Path; Path(r'$@').mkdir(parents=True, exist_ok=True)"

$(BETAMAX_TARGET): $(BETAMAX_DIR)/src/main.cpp $(BETAMAX_HEADERS) $(JSON_HEADER) Makefile | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $< $(LDFLAGS) $(LDLIBS) -o $@

$(BUILD_DIR)/validate_%$(EXE_SUFFIX): $(VALIDATOR_SOURCE) Makefile | $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $< $(LDFLAGS) -o $@

generate:
	$(PYTHON) generate_cases.py

smoke: all generate
	$(PYTHON) run_smoke_tests.py

test: all generate
	$(PYTHON) run_tests.py
