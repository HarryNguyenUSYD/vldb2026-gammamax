# Benchmark structure

This document describes every checked-in file and directory under `benchmark/`.
Files produced at runtime are described at the end.

## Root files

- `README.md`: benchmark overview, commands, outputs, and smoke-test behavior.
- `Makefile`: generates test data; builds GammaMax and column oracles; runs
  GammaMax, ZeroEC, GIDCL, their smoke tests, or the complete suite.
- `benchmark_common.py`: shared CSV loading, oracle predicates, deterministic
  smoke sampling, OpenAI JSON calls, metrics, and result writing.
- `environment-macos.yml`: shared macOS Conda environment containing Python,
  OpenAI client, Make, CMake, and a C++ compiler.
- `MACOS_CONDA.md`: step-by-step environment, session credential, smoke, and
  full-run instructions.
- `prepare_shared_datasets.ps1`: compatibility wrapper that refreshes metadata,
  manifests, and C++ oracles from current clean CSVs.
- `regenerate_dataset_info.py`: infers column types, observed ranges, closed
  categorical domains, missing counts, manifests, and C++ oracles.
- `STRUCTURE.md`: this inventory.

## `datasets/`

Canonical clean input data and declarative validation rules.

- `COLUMN_VALUES.md`: descriptions, observed domains, and value summaries for
  every dataset column.
- `adult_20/`, `bank_marketing_222/`, `census_income_kdd_117/`, and
  `support2_880/`: one directory per UCI dataset. Every directory contains:
  - `clean.csv`: canonical clean table copied from GIDCL.
  - `metadata.txt`: dataset name, dimensions, sharing information, and column
    descriptions.
  - `oracles.json`: source filename and one validation specification per
    column. Supported kinds are list, regex, integer range, and real range.

## `test-case-constructor/`

- `generate_cases.py`: generates every current dataset by default. It copies each
  clean table, selects a configured fraction of cells, applies 1 through a
  configured maximum of insertion/substitution/deletion edits, and records
  exact corruption ground truth. Passing a dataset name limits generation to
  that dataset.
- `README.md`: generator inputs, options, behavior, and output contract.

## `oracles/`

Standalone C++ validators used by GammaMax. Each program reads one cell from
standard input and exits 0 for accepted or 1 for rejected. Each `*.cpp` file
corresponds exactly to one CSV column.

- `oracle-gen.py`: creates one C++ validator from one oracle manifest entry.
- `regenerate-all.py`: regenerates validators for all dataset manifests.
- `adult_20/`: one validator for each Adult column: age, workclass, fnlwgt,
  education, education-num, marital-status, occupation, relationship, race,
  sex, capital-gain, capital-loss, hours-per-week, native-country, and income.
- `bank_marketing_222/`: validators for age, job, marital, education, default,
  balance, housing, loan, contact, day_of_week, month, duration, campaign,
  pdays, previous, poutcome, and y.
- `census_income_kdd_117/`: 42 validators matching AAGE through income in its
  manifest and CSV header.
- `support2_880/`: 45 validators matching age through sfdm2 in its manifest and
  CSV header.

## `gammamax-batch/`

Standalone C++20 GammaMax implementation plus benchmark adapter.

- `CMakeLists.txt`: builds `gammamax` and optional `gammamax_tests`.
- `benchmark_runner.py`: runs one GammaMax process per dataset column, supplies
  all selected cells, maps repairs back by cell index, and writes common
  benchmark outputs.
- `optimization-note.md`: documents algorithm components, implementation
  extensions, optimizations, measurements, and limits.
- `src/main.cpp`: executable entry point. Loads JSON, scans every cell with the
  configured oracle, builds accepted/rejected groups, repairs rejected cells,
  and emits JSON results and measurements.
- `tests/gammamax_tests.cpp`: unit tests for automata, k-tails, state merging,
  RSR, JSON/config parsing, batching, timeouts, and measurements.
- `third_party/nlohmann/json.hpp`: vendored single-header JSON parser/writer.

### `gammamax-batch/include/gammamax/`

- `automaton.hpp`: DFA state, transition, merge, execution, and fingerprint
  representation.
- `batch_session.hpp`: reusable per-column PTA, signatures, merge history,
  negative knowledge, repair loop, and shared measurements.
- `config.hpp`: strict `config.json` parsing and limit validation.
- `consistency_check.hpp`: checks whether learned automata reject known
  negative examples.
- `gamma_max.hpp`: standalone single-cell GammaMax algorithm.
- `json_io.hpp`: input/config loading, validation, and result serialization.
- `k_tails.hpp`: fixed-depth k-tail signatures and compatibility checks.
- `memory.hpp`: platform-specific peak resident-memory measurement.
- `merge_replay.hpp`: replays still-valid state merges after new negatives.
- `ngram.hpp`: character n-gram candidate scoring.
- `oracle.hpp`: abstract oracle plus Windows/macOS external-process protocol.
- `partitioned_dfa.hpp`: transactional union-find quotient used during merging.
- `pta.hpp`: prefix-tree acceptor construction from positive strings.
- `rsr.hpp`: edit-distance repair search and n-gram candidate ranking.
- `state_merge.hpp`: deterministic red/blue EDSM-style state merging.
- `types.hpp`: common inputs, configuration, merge, repair, and measurement
  structures.

## `ZeroEC/`

ZeroEC source snapshot plus benchmark adapter.

- `benchmark_runner.py`: reads generated benchmark tables, detects cells using
  manifest predicates, sends full dirty rows and constraints to the shared
  OpenAI model, applies returned corrections, and writes common metrics.
- `correction.py`: original full ZeroEC pipeline with embeddings, candidate
  selection, retrieval, LLM correction, generated rules/dependencies, logging,
  and evaluation.
- `correction_zero_shot.py`: original simplified zero-shot correction path.
- `perfect_detection.py`: builds a detection matrix by comparing clean and
  dirty tables; this is ground-truth detection, not realistic inference.
- `requirements.txt`: dependencies for original ZeroEC plus benchmark OpenAI
  access.
- `README.md`: upstream ZeroEC overview and original usage notes.

### `ZeroEC/prompt_templates/`

- `SystemMessage.txt`, `HumanMessage.txt`: base correction system/user prompts.
- `SystemMessage-2.txt`: alternate base system prompt.
- `SystemMessage_for_AutoCoT.txt`: system prompt for automatic chain-of-thought
  example generation.
- `SystemMessage_for_AutoCoT_with_error_type.txt`: AutoCoT system prompt that
  includes error categories.
- `HumanMessage_for_AutoCoT_small.txt`: compact AutoCoT user template.
- `HumanMessage_for_AutoCoT_large.txt`: detailed AutoCoT user template.
- `HumanMessage_for_AutoCoT_large-o1.txt`: detailed template adapted for an
  o1-style model.
- `SystemMessage_code_generation.txt`, `HumanMessage_code_generation.txt`:
  prompts for generating executable cleaning rules.
- `SystemMessage_data_augmentation.txt`, `HumanMessage_data_augmentation.txt`:
  prompts for generating augmented examples.
- `SystemMessage_fd_generation.txt`, `HumanMessage_fd_generation.txt`: prompts
  for discovering functional dependencies.
- `examples.txt`: general few-shot examples.
- `examples_for_AutoCoT.txt`: AutoCoT examples.
- `examples_for_AutoCoT_with_error_type.txt`: AutoCoT examples annotated with
  error types.
- `code_generatoin_2.txt`: additional code-generation examples; filename keeps
  upstream spelling.

## `GIDCL/`

GIDCL source snapshot plus CPU/OpenAI benchmark adapter.

- `.gitignore`: upstream GIDCL ignore patterns.
- `README.md`: upstream architecture, data, training, inference, and macOS CPU
  notes.
- `requirements-macos-cpu.txt`: CPU-safe Python requirements; excludes vLLM,
  CUDA-only Apex, bitsandbytes, and FlashAttention.
- `benchmark_runner.py`: detects invalid cells, retrieves up to five related
  rows by non-target agreement, sends graph-style context to the shared OpenAI
  model, applies corrections, and writes common metrics.
- `vllm_inference_api.py`: correction inference through either OpenAI-compatible
  API or original local vLLM/checkpoint export path.
- `detector_train.ipynb`: RoBERTa/Ditto error-detector training and inference.
- `function_set.ipynb`: LLM-generated explicit detection/corruption functions.
- `graph_embedding.ipynb`: row embedding and graph-related example selection.
- `eval.ipynb`: upstream end-to-end GIDCL detection/correction evaluation.
- `data/dataset_info.json`: LLaMA-Factory dataset registry.
- `ditto/augment.py`: Ditto text augmentation operators.
- `ditto/model.py`: Ditto/RoBERTa dataset, training, classification, and
  CPU/CUDA device handling.

### `GIDCL/evaluation/`

- `ceval/ceval.py`, `cmmlu/cmmlu.py`, `mmlu/mmlu.py`: evaluation entry points
  for C-Eval, CMMLU, and MMLU model benchmarks.
- Each `mapping.json`: maps benchmark subjects to display/category names.
- Each `ceval.zip`, `cmmlu.zip`, or `mmlu.zip`: packaged upstream evaluation
  data used by its matching script.

### `GIDCL/src/`

- `api_demo.py`: inference API demonstration.
- `cli_demo.py`: interactive command-line chat demonstration.
- `evaluate.py`: model evaluation command entry point.
- `export_model.py`: merges/exports a base model and fine-tuning adapter.
- `train_bash.py`: command-line training entry point.
- `train_web.py`: web-UI training entry point.
- `web_demo.py`: launches web demonstration UI.

### `GIDCL/src/llmtuner/`

- `__init__.py`: package marker/version surface.
- `api/__init__.py`: API package exports.
- `api/app.py`: FastAPI-style model serving application.
- `api/protocol.py`: API request/response data structures.
- `chat/__init__.py`: chat package exports.
- `chat/stream_chat.py`: streaming generation/chat implementation.
- `dsets/__init__.py`: dataset package exports.
- `dsets/loader.py`: loads configured training datasets.
- `dsets/preprocess.py`: tokenizes and formats examples by training stage.
- `dsets/utils.py`: dataset split/merge/helper functions.
- `extras/__init__.py`: utility package marker.
- `extras/callbacks.py`: training callbacks and progress reporting.
- `extras/constants.py`: shared model/template constants.
- `extras/logging.py`: project logging setup.
- `extras/misc.py`: device dispatch, availability, and general helpers.
- `extras/ploting.py`: training-loss plotting utilities; upstream spelling.
- `extras/template.py`: prompt templates and dialogue encoding.
- `extras/patches/__init__.py`: patch package exports.
- `extras/patches/llama_patch.py`: compatibility/performance patches for LLaMA
  attention/model behavior.
- `hparams/__init__.py`: hyperparameter package exports.
- `hparams/data_args.py`: dataset-related command arguments.
- `hparams/finetuning_args.py`: LoRA and fine-tuning arguments.
- `hparams/generating_args.py`: generation/sampling arguments.
- `hparams/model_args.py`: model loading and quantization arguments.
- `tuner/__init__.py`: training package exports.
- `tuner/tune.py`: selects and launches requested training stage.
- `tuner/core/__init__.py`: core tuner exports.
- `tuner/core/adapter.py`: initializes/loads PEFT adapters.
- `tuner/core/loader.py`: loads tokenizer, configuration, and model.
- `tuner/core/parser.py`: combines and validates command arguments.
- `tuner/core/utils.py`: tuner-level model and training helpers.
- `tuner/pt/__init__.py`, `tuner/pt/workflow.py`: pretraining workflow.
- `tuner/sft/__init__.py`, `tuner/sft/workflow.py`: supervised fine-tuning
  workflow.
- `tuner/sft/trainer.py`: customized sequence-to-sequence trainer.
- `tuner/sft/metric.py`: SFT generation metrics.
- `tuner/rm/__init__.py`, `tuner/rm/workflow.py`: reward-model workflow.
- `tuner/rm/trainer.py`: reward-model trainer.
- `tuner/rm/collator.py`: pairwise preference batch collation.
- `tuner/rm/metric.py`: reward/pairwise metrics.
- `tuner/ppo/__init__.py`, `tuner/ppo/workflow.py`: PPO workflow.
- `tuner/ppo/trainer.py`: PPO trainer.
- `tuner/ppo/utils.py`: PPO/reference-model helpers.
- `tuner/dpo/__init__.py`, `tuner/dpo/workflow.py`: DPO workflow.
- `tuner/dpo/trainer.py`: DPO trainer.
- `tuner/dpo/collator.py`: DPO preference-data collation.
- `webui/__init__.py`: web UI package exports.
- `webui/chatter.py`: web chat event handlers.
- `webui/common.py`: shared UI state and helper functions.
- `webui/css.py`: UI styling.
- `webui/engine.py`: model load/train/inference orchestration.
- `webui/interface.py`: assembles Gradio interface.
- `webui/locales.py`: translated UI strings.
- `webui/manager.py`: component registration and lookup.
- `webui/runner.py`: web UI launch/runtime logic.
- `webui/utils.py`: UI utility functions.
- `webui/components/__init__.py`: component package exports.
- `webui/components/chatbot.py`: chat controls.
- `webui/components/data.py`: dataset preview/configuration controls.
- `webui/components/eval.py`: evaluation controls.
- `webui/components/export.py`: model export controls.
- `webui/components/infer.py`: inference controls.
- `webui/components/top.py`: top-level language/model controls.
- `webui/components/train.py`: training controls.

### `GIDCL/tests/`

- `cal_flops.py`: estimates model FLOPs/parameter cost.
- `llamafy_baichuan2.py`: converts Baichuan2 weights/configuration toward
  LLaMA-compatible format.
- `llamafy_qwen.py`: converts Qwen weights/configuration toward LLaMA format.
- `quantize.py`: model quantization utility/test script.

## Runtime-generated directories

These are absent until commands run and should not be treated as source:

- `test-cases/<dataset>/original.csv`: exact clean source copy.
- `test-cases/<dataset>/corrupted.csv`: same table with generated corruptions.
- `test-cases/<dataset>/corruptions.json`: generation settings and exact cell
  mutation ground truth.
- `build/gammamax/`: CMake build tree and GammaMax executable.
- `build/oracles/<dataset>/`: compiled per-column oracle executables.
- `results/<algorithm>/<dataset>/<full|smoke>/repaired.csv`: repaired table.
- `results/<algorithm>/<dataset>/<full|smoke>/metrics.json`: common precision,
  recall, F1, counts, sampling metadata, and algorithm-specific diagnostics.
