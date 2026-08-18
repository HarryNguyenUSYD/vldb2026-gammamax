# DataVinci

Paper-based reimplementation of **DataVinci: Learning Syntactic and Semantic
String Repairs**. It detects and repairs qualitative string errors by learning
column patterns, finding minimum edits into significant patterns, resolving
abstract edits from row context, and optionally using downstream execution as
an error signal.

This directory is standalone. It does not use or modify this repository's
benchmark interfaces.

## Architecture

- `datavinci.py` orchestrates CSV loading, abstraction, profiling, detection,
  repair, and reports.
- `flashprofile_bridge/` calls Microsoft's official FlashProfile release,
  `Microsoft.ProgramSynthesis.Matching.Text` 10.16.5.
- `repair.py` compiles supported regex constructs to an NFA and finds minimum
  match/insert/delete/substitute programs over its product with the input.
- `concretization.py` implements row predicates, decision-tree constraints,
  and four-feature candidate ranking.
- `semantic.py` uses an OpenAI-compatible LLM to abstract and reconcretize
  semantic substrings.
- `execution_guided.py` partitions row-local program executions into successes
  and failures.

FlashProfile was publicly released as the `Matching.Text` module in Microsoft
PROSE. The bridge uses the documented `Session.Inputs.Add()` and
`Session.LearnPatterns()` API. A separate bridge operation evaluates returned
`PatternInfo.Regex` and `RegexesToExclude` with the .NET regex engine, so Python
does not reinterpret profile membership. It does not inspect private SDK internals.

## Requirements

- Python 3.10+
- .NET SDK 8.0
- Microsoft PROSE SDK's non-commercial license must be acceptable for the use
  case. Review the license shipped with the NuGet package.
- An OpenAI-compatible API when semantic abstraction is enabled

Install and build:

```sh
python -m pip install -r requirements.txt
dotnet restore flashprofile_bridge/FlashProfileBridge.csproj
dotnet build flashprofile_bridge/FlashProfileBridge.csproj -c Release
```

The NuGet reference is pinned to version `10.16.5`. Do not upgrade it without
reviewing profile golden outputs.

## Usage

Configure the LLM using the same style as ZeroEC:

```sh
export OPENAI_API_KEY=...
export OPENAI_API_BASE=https://api.openai.com/v1
export DATAVINCI_MODEL=gpt-3.5-turbo-0125
```

Windows PowerShell:

```powershell
$env:OPENAI_API_KEY = "..."
$env:OPENAI_API_BASE = "https://api.openai.com/v1"
$env:DATAVINCI_MODEL = "gpt-3.5-turbo-0125"
```

Clean one target column:

```sh
python datavinci.py --input dirty.csv --target-column player_id \
  --output repaired.csv --report report.json
```

Run without LLM abstraction:

```sh
python datavinci.py --input dirty.csv --target-column player_id \
  --output repaired.csv --report report.json --disable-semantic-abstraction
```

Execution-guided mode loads a row-local callable:

```sh
python datavinci.py --input dirty.csv --target-column player_id \
  --program my_module:transform --output repaired.csv --report report.json
```

The callable receives `dict[str, str]`. Exceptions, `None`, `NaN`, or a
collection containing those values mark that row as failed. Patterns are then
learned only from successful rows, and failed target values are repaired.

Python API:

```python
from datavinci import DataVinci, DataVinciConfig

model = DataVinci(DataVinciConfig())
result = model.clean_table(rows, target_column="player_id")
print(result.repaired_rows)
print(result.report())
```

Configuration JSON maps directly to `DataVinciConfig` fields. Important
defaults are `significance_threshold=0.1`, `minimum_tree_accuracy=0.8`,
`max_candidates=100`, and unbounded `max_edits=null`. `max_patterns` remains a
deprecated configuration field for compatibility and is not imposed because
the documented Matching.Text API exposes no pattern-count setting.

LLM safeguards can be controlled with:

- `DATAVINCI_OPENAI_MAX_ATTEMPTS` (default `3`)
- `DATAVINCI_OPENAI_MAX_REQUESTS` (default `2000`)
- `DATAVINCI_OPENAI_MIN_REQUEST_INTERVAL_SECONDS` (default `2`)
- `DATAVINCI_OPENAI_RETRY_BASE_SECONDS` (default `2`)

## Testing

```sh
python -m unittest discover -s tests -p "test_*.py"
dotnet test tests/FlashProfileBridge.Tests.csproj
```

The Python suite uses a deterministic fake profiler for algorithm tests. The
.NET test is an integration smoke test against the pinned official package.

## Assumptions and underspecified details

The paper does not provide its source. These assumptions are necessary:

1. **Profiler identity.** DataVinci names FlashProfile. FlashProfile's paper
   states it was released as PROSE `Matching.Text`; this implementation uses
   current official package 10.16.5. It is not proven byte-identical to the
   authors' 2023 build.
2. **Profiler version.** DataVinci does not state its PROSE version. Version
   10.16.5 is pinned because it is the selected official package version.
3. **Pattern limit.** The paper and documented SDK API provide no `k`. The
   bridge preserves every pattern and its official ordering. The legacy
   `max_patterns` option is deliberately ignored.
4. **Significance threshold.** The paper defines `delta` but gives no selected
   value. Default is `0.1`.
5. **Pattern representation.** Public `PatternInfo` exposes .NET regexes, not
   FlashProfile's internal AST. Repair supports literals, classes, categories,
   branches, groups, anchors, and bounded/unbounded repetition. Unsupported
   public regex constructs produce explicit per-pattern errors.
6. **NFA execution.** The paper presents cycle unrolling followed by DAG dynamic
   programming. This implementation computes the same minimum edit objective
   directly on the finite input/NFA product using Dijkstra search. It does not
   materialize the paper's DAG, and an optional user limit may cap edit cost.
7. **Candidate bound.** Paper gives no bound on tied minimum edit programs.
   Default is `100` candidates per value.
8. **Ranking weights.** Paper lists four features but does not publish the
   selected weights. Raw features default to weight `1.0`; coverage is
   subtracted because greater coverage is preferred.
9. **Alphanumeric edit count.** Counted from the actual minimum-cost edit
   program: a non-match action counts when its consumed or emitted character is
   alphanumeric.
10. **Tie breaking.** Equal-cost/equal-score results use lexical order for
    reproducibility.
11. **Semantic categories.** Authors use the 20 most frequent Sherlock types
    in a private 25,000-column corpus but do not list them. This implementation
    uses the documented list in `semantic.py`, based on common Sherlock types
    and paper examples.
12. **Semantic prompt.** Figure 3 describes prompt structure but does not give
    exact text or demonstrations. `semantic_abstraction.txt` reconstructs it.
13. **LLM snapshot.** Paper says GPT-3.5 with a 4,000-token prompt but gives no
    exact snapshot. Default is configurable `gpt-3.5-turbo-0125`.
14. **Batching.** Paper uses a 4,000-token prompt but does not specify tokenizer
    or boundary algorithm. Inputs use a configurable 3,500-token budget,
    `tiktoken` when available, and a deterministic four-characters-per-token
    estimate otherwise.
15. **Malformed LLM responses.** After three attempts, abstraction fails
    explicitly. Cached successful outputs are keyed by model and ordered input.
16. **Semantic correction timing.** LLM replacements are retained during
    abstraction and applied when mask-bearing repair candidates are concrete.
17. **Decision-tree search.** Paper says it samples trees of varying node count
    and depth but omits distribution and bounds. Implementation deterministically
    searches leaf counts 2–16 and depths 1–6, then chooses the smallest tree
    reaching accuracy 0.8.
18. **Failed constraint learning.** When no qualifying tree exists, observed
    target values are retained as fallback candidates.
19. **Feature constants.** String constants come from full cells and tokenizing
    on non-alphanumeric, case, and alphabetic/numeric boundaries. The five most
    frequent lengths are retained; constant predicates are removed.
20. **Missing values.** CSV missing cells become empty strings. Literal strings
    such as `null` remain literal strings.
21. **Duplicates.** Duplicate rows remain and contribute to pattern frequency
    and constraint training.
22. **No significant patterns.** Ordinary mode detects no repairable errors and
    leaves values unchanged.
23. **Recoverable pattern failure.** One unsupported pattern does not abort
    other candidate patterns; its error is recorded in the cell report.
24. **Execution failure.** Exception, `None`, numeric `NaN`, or exceptional
    member in a returned collection counts as failure. Multi-output success
    requires every member to be non-exceptional.
25. **Mutation scope.** Only target column changes. Other columns supply row
    predicates and are copied unchanged.
26. **Language scope.** Semantic abstraction targets English, matching paper's
    stated evaluation limitation.
27. **Inter-table constraints.** Not supported, matching paper limitation.
28. **Benchmark separation.** No benchmark oracle, clean source, generated case,
    or benchmark input/output contract is used.
