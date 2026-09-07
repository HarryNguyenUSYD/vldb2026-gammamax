# gammaMax implementation optimizations and extensions

## Scope

This note documents engineering optimizations and algorithmic extensions in the
current gammaMax implementation that are not part of the source algorithms as
normally stated in their papers. The authoritative implementation for this note
is the snapshot in `test-suites/gammamax-test-suite/sources/gammamax/`. The
comparison suite contains the immediately preceding, pre-transactional snapshot
unless it is synchronized separately.

The repository-level `gammamax/` directory is currently an older snapshot and
must not be used to interpret this document.

The implementation combines three published ideas:

1. state merging, using an EDSM-style red/blue search;
2. fixed-depth k-tail compatibility;
3. C/H-matrix RSR followed by n-gram ranking.

The items below describe implementation decisions around those ideas. Some are
pure performance optimizations, some change how many alternatives gammaMax
examines, and some are operational safeguards or experimental controls. They
should be reported as implementation extensions rather than attributed to the
source papers.

## 1. Immutable, prefix-shared PTA

Positive examples are sorted and deduplicated before a prefix-tree acceptor
(PTA) is built. Common prefixes share states, so repeated prefixes are stored
and processed once. The resulting PTA remains immutable throughout learning.

Keeping a stable base automaton has two benefits:

- merge states can retain stable identities across refinement iterations;
- speculative and replayed merges do not require reconstructing the training
  automaton or destructively rewriting it.

The PTA also enforces `max_states` while it is being constructed. A value of
`-1` in JSON is converted to the largest representable value and therefore
acts as an unbounded setting.

Relevant code: `pta.hpp`, `gamma_max.hpp`, and `config.hpp`.

## 2. Quotient/partition representation for learned DFAs

Learning does not repeatedly mutate a fully materialized DFA. Instead,
`PartitionedDfa` stores a quotient of the immutable PTA using:

- a union-find parent vector;
- union-by-size metadata;
- a stable canonical PTA-state identifier per class;
- one accepting flag per class;
- transition maps associated with partition roots.

Merging two classes updates this compact equivalence relation. Conflicting
deterministic transitions are folded recursively. A conventional `Automaton`
is materialized only when an executable grammar is needed by RSR or returned
from a merge/replay operation.

This representation avoids eagerly copying sets of original states into every
committed DFA state and gives merge history a stable coordinate system.

Speculative red/blue candidates use transactional mutation rather than copying
the partition. Each union records only the root metadata and transition map it
changes. The candidate is evaluated and the log is rolled back; only the chosen
merge is reapplied and committed. This removes a deep copy of every PTA-sized
partition from the innermost EDSM loop.

Relevant code: `partitioned_dfa.hpp`, `state_merge.hpp`, and `automaton.hpp`.

## 3. Deterministic merge closure

A requested red/blue merge may give one state two transitions with the same
symbol. gammaMax restores determinism by recursively merging the corresponding
destination classes. This complete closure is treated as one candidate.

Compatibility and negative-example checks are performed on the complete
closure, not just on the original red and blue endpoints. This prevents a
locally legal merge from silently forcing an incompatible deeper merge.

The closure operation is an implementation extension needed to make state
merging safe on deterministic automata with fixed k-tail classes.

Relevant code: `PartitionedDfa::merge_with_closure()` and
`PartitionedDfa::unite()` in `partitioned_dfa.hpp`.

## 4. Precomputed fixed k-tail signatures

The implementation computes one k-signature for every state of the immutable
PTA before state merging starts. Signatures are refined for `k` rounds and then
reused for:

- initial red/blue compatibility filtering;
- every recursively forced merge in deterministic closure;
- merge-history replay after new negative examples arrive.

Precomputation avoids recomputing bounded future languages for every candidate.
It also makes the constraint stable: signatures always refer to the original
unmerged PTA rather than to an evolving learned DFA.

`k=0` assigns every state the same signature and disables this filter. Larger
values progressively include acceptance and continuation structure. The
benchmark-selected setting is `k=3`.

Relevant code: `k_tails.hpp` and `gamma_max.hpp`.

## 5. Label-based EDSM evidence and deterministic tie-breaking

Compatible state merges are ranked by the reduction in the number of accepting
partition classes. This favours agreement between positive labels rather than
incidental structural compression caused by deterministic closure.

When candidates have equal evidence, gammaMax orders them deterministically by
their canonical red and blue PTA-state identifiers. Red and blue frontiers are
also stored in ordered sets.

This removes dependence on hash iteration order and makes benchmark runs
reproducible. It also means the `seed` option currently does not affect merge or
repair selection; it is retained in the interface and reported as
`effective_seed` for reproducibility and future stochastic policies.

Relevant code: `edsm_evidence()` and `state_merge()` in `state_merge.hpp`.

## 6. Cached quotient views during consistency checks

For each current or speculative partition, gammaMax can build a cache containing:

- the active partition roots;
- resolved transitions between roots;
- accepting status for each root.

Negative strings are executed against this cache instead of repeatedly
materializing a standalone DFA. This avoids a dense state remapping for every
consistency check.

The current red/blue frontier builds one cache for the committed partition.
Speculative negative validation does not build a candidate-wide cache. It walks
the maintained root transition maps directly and resolves destinations through
the partition. This makes validation proportional to the negative strings
actually traversed rather than adding a complete quotient scan for every
candidate.

Relevant code: `PartitionedDfa::build_cache()` and `rejects_all()` in
`partitioned_dfa.hpp` and `state_merge.hpp`.

## 6a. Single-best candidate retention

EDSM retains only the best candidate descriptor seen so far: evidence,
canonical endpoints, and the endpoint member sets required for history. It no
longer stores a vector in which every consistent choice owns a complete
candidate partition.

Candidate ordering is unchanged. Higher evidence wins, followed by the same
canonical red/blue tie-break. The optimization removes large temporary memory
retention and destructor/allocation work without changing the selected merge.

Relevant code: `state_merge()` in `state_merge.hpp`.

## 6b. Incremental accepting-class evidence

`PartitionedDfa` maintains its number of accepting equivalence classes as
union operations occur. Joining two accepting classes decrements the count;
other unions leave it unchanged. Transaction undo entries restore the previous
count during rollback.

EDSM evidence is calculated as the count before a speculative closure minus the
count after it. This replaces repeated scans and sorting of all partition roots
with constant-time reads while preserving the label-agreement score.

Relevant code: `PartitionedDfa::accepting_class_count()` and `unite()` in
`partitioned_dfa.hpp`, and `state_merge()` in `state_merge.hpp`.

## 7. Negative-consistent state merging

Every speculative merge is checked against all known negative examples. A
candidate is discarded if its quotient accepts any negative string. The corrupt
input is inserted into the initial negative set after gammaMax first confirms
that the external oracle rejects it.

This integrates counterexamples directly into EDSM and prevents RSR from using
a grammar already known to accept an invalid repair. It is more restrictive
than learning only from positive examples and validating solely at the end.

Relevant code: `gamma_max.hpp` and `state_merge.hpp`.

## 8. Full merge history using original PTA identities

Each committed merge records the complete sets of original PTA states at its
red and blue endpoints. The record does not use transient materialized-DFA
indices, which may change after later merges.

This replaces the legacy implementation's bounded merge-prefix depth `m` with
a full merge history. There is consequently no `m` hyperparameter in the new
implementation.

Stable history enables exact replay after the negative set changes and avoids
discarding every earlier learning decision.

Relevant code: `MergeRecord` in `types.hpp`, `state_merge.hpp`, and
`merge_replay.hpp`.

## 9. Merge replay and resume after counterexamples

When the oracle rejects repair candidates, gammaMax adds them to the negative
set. It then:

1. starts with a fresh partition over the immutable PTA;
2. replays the recorded merge history in order;
3. stops at the first merge that is unavailable, k-incompatible, or inconsistent
   with the expanded negative set;
4. retains the longest valid history prefix;
5. resumes EDSM from the surviving partition.

This preserves still-valid learning work instead of blindly reusing an invalid
grammar or always relearning with no history. Replay itself currently starts
from the PTA on every refinement iteration, so checkpointed incremental replay
remains a possible future optimization.

Relevant code: `merge_replay.hpp` and the refinement block in `gamma_max.hpp`.

## 10. Indexed PRE/NEXT relations for paper-style RSR

The single-result RSR implementation follows the C/H dynamic-programming
formulation, but it constructs predecessor and successor edge relations by
indexing edges by source and destination state. It does not compare every pair
of edges to discover adjacency.

For a DFA with `E` edges, this replaces an avoidable quadratic adjacency-building
step with indexing proportional to the graph and its actual adjacency lists.
Insertion propagation within each matrix row uses a priority queue so lower-cost
paths are processed first.

Relevant code: `rsr_repair()` in `rsr.hpp`.

## 11. All minimum-cost candidates from one RSR run

Each C/H cell retains every predecessor that reaches the same minimum cost.
After one matrix computation, the implementation backtracks every globally
minimum-cost accepting cell and deduplicates the resulting strings. A finite
`max_rsr_candidates` stops deterministic enumeration early; `-1` is unlimited.

Relevant code: `rsr_minimum_repairs()` and `rsr_repairs()` in `rsr.hpp`.

## 12. Exact-string DFA subtraction

To make repeated RSR calls produce distinct results, `reject_exact_string()`
removes one word from a temporary DFA language without removing its prefixes,
extensions, or strings that diverge from its path.

It creates shadow prefix states that remember whether execution still exactly
matches the excluded word. A mismatching symbol returns to the corresponding
source-DFA behaviour. Only the shadow state at the end of the excluded word is
made non-accepting.

This is more precise than deleting transitions or marking the original terminal
state non-accepting, either of which could remove additional valid strings.
Exclusions are composable, so the temporary DFA can remove all candidates
already returned or queried.

Relevant code: `reject_exact_string()` in `rsr.hpp`.

## 13. N-gram candidate filtering

`ngrams_batch_size` controls how many ranked minimum-cost strings are sent to
the oracle. Positive values retain that many when available; `-1` retains all
candidates after sorting. Fewer candidates are never padded or discarded.

Relevant code: `types.hpp`, `config.hpp`, `rsr.hpp`, and `gamma_max.hpp`.

## 14. N-gram reranking with smoothing and boundary tokens

Each RSR candidate receives a character n-gram log-probability score learned
from the positive examples. Candidates are ordered by:

1. descending n-gram score;
2. ascending edit distance;
3. lexicographic output as a deterministic final tie-breaker.

The model includes explicit start and end tokens outside the byte alphabet and
uses add-one smoothing. Symbols found only in the corrupt input are added to the
vocabulary but not counted as positive observations. This prevents unseen input
bytes from receiving an accidentally underspecified vocabulary probability.

`n=0` disables language-model discrimination by assigning every string score
zero. The benchmark-selected setting is `n=3`.

Relevant code: `ngram.hpp` and `rsr.hpp`.

## 15. Global queried-candidate exclusion

gammaMax stores every candidate already presented to the oracle in an ordered
`queried` set. Before each RSR batch, all queried strings are removed exactly
from the temporary working DFA. A second insertion check immediately before an
oracle call protects against duplicates within or across batches.

This avoids spending oracle calls and refinement iterations on the same repair.
It also guarantees that an RSR iteration either produces new queryable strings
or terminates with an explicit no-progress error.

Relevant code: `gamma_max.hpp` and `rsr.hpp`.

## 16. Batched counterexample feedback

All candidates retained by the n-gram stage are queried in one iteration. If
none is accepted, every rejected candidate is added to the negative set before
merge replay and resumed learning.

Compared with feeding back one rejected repair at a time, this can reduce the
number of expensive EDSM refinement cycles. The effect is governed by
`ngrams_batch_size`: a value of one gives single-counterexample refinement,
while larger values trade additional oracle calls for fewer relearning rounds.

Relevant code: the repair loop in `gamma_max.hpp`.

## 17. Input normalization and contradiction detection

Positive and negative examples are sorted and deduplicated. The corrupt input is
deduplicated into the negative set, and gammaMax rejects an input set in which
the same string is labelled both positive and negative.

These steps reduce redundant PTA and consistency-check work and fail early on
an unsatisfiable learning problem.

Relevant code: `sort_unique()` and `gamma_max()` in `gamma_max.hpp`.

## 18. Early acceptance of an already-valid input

The corrupt string is sent to the oracle before any PTA, n-gram model, k-tail
signature, or state-merged grammar is constructed. If it is already accepted,
gammaMax returns it immediately.

This fast path avoids the complete learning and repair pipeline for false alarm
inputs.

Relevant code: the beginning of `gamma_max()`.

## 19. Grammar fingerprinting and progress detection

Every materialized grammar is converted to a deterministic structural
fingerprint based on canonical state identities, acceptance, original-state
membership, and transitions. Previously observed fingerprints are retained.

If refinement produces a grammar already seen in the current run, gammaMax
terminates with `grammar repeated without progress` rather than repeatedly
generating candidates from the same language.

Relevant code: `Automaton::fingerprint()` in `automaton.hpp` and the repair loop
in `gamma_max.hpp`.

## 20. Configurable hyperparameters

The current implementation exposes the following algorithm controls through
`config.json`:

| Option | Purpose | `-1` meaning |
|---|---|---|
| `state_merging.k` | Fixed k-tail signature depth; zero disables filtering | Not accepted |
| `repair.n` | Character n-gram order; zero disables scoring | Not accepted |
| `repair.ngrams_batch_size` | Number of ranked results queried | Unbounded |
| `repair.max_candidate_length` | Reject an RSR result longer than this | Unbounded |
| `limits.max_iterations` | Maximum repair/refinement iterations | Unbounded |
| `limits.max_total_oracle_calls` | Maximum external oracle calls | Unbounded |
| `limits.max_states` | Maximum PTA states | Unbounded |
| `limits.max_queue_size` | Compatibility limit for repair search | Unbounded |
| `limits.max_rsr_candidates` | Maximum unique minimum-cost strings enumerated | Unbounded |
| `seed` | Reproducibility metadata/future random policies | Optional |

Positive counts must be nonzero, except that `k` and `n` may be zero to disable
their corresponding filters. `-1` is converted to the maximum value of the
internal unsigned type for fields documented as unbounded.

Current caveats:

- `max_queue_size` is validated but has no effect on C/H-matrix RSR, whose
  storage is matrix-bounded; it remains for configuration compatibility.
- `max_candidate_length` is checked after a single RSR result is reconstructed;
  it does not prune the C/H dynamic program while it runs.
- `seed` is reported but does not currently alter this deterministic algorithm.

Relevant code: `Config` in `types.hpp`, `config.hpp`, and `rsr.hpp`.

## 21. Direct external-oracle protocol and global call budget

The oracle is an executable that receives the candidate directly on standard
input. gammaMax creates the child process without an intermediate candidate
file, discards normal validator output, and interprets exit code 0 as accept and
1 as reject. Unexpected exit states become explicit errors.

The implementation tracks one global oracle-call count covering the initial
corrupt-string check and every candidate check. This count can be bounded by
`max_total_oracle_calls` or made unbounded.

The current implementation supports native process creation on Windows and
macOS. It intentionally contains no internal per-call timeout; benchmark suites
apply a 300-second outer timeout to the complete gammaMax process.

Relevant code: `oracle.hpp` and `main.cpp`.

## 22. Stage-specific measurements and peak-memory reporting

The executable reports:

- total execution time;
- RSR time, excluding separately measured n-gram work;
- k-tail signature time;
- EDSM time, including merge replay and resumed state merging;
- initial state-merge time;
- merge-replay time;
- resumed state-merge time;
- speculative merge/rollback time;
- negative-validation time;
- n-gram training, scoring, and ranking time;
- total repair iterations;
- peak resident memory.

Timers use `std::chrono::steady_clock` and therefore measure elapsed wall-clock
time, including scheduling delays. Peak memory uses the platform-native process
API. This instrumentation is not an algorithmic optimization, but it was added
to make optimization effects measurable and comparable.

Relevant code: `gamma_max.hpp`, `rsr.hpp`, `memory.hpp`, `main.cpp`, and
`json_io.hpp`.

## 23. Deterministic serialization and strict input validation

The standalone implementation uses fixed `input.json` and `config.json` files,
validates their shape and numeric ranges, restricts training and repair strings
to ASCII, and emits one machine-readable JSON result object.

This does not improve the theoretical algorithm, but it removes ambiguity from
experiments and prevents implicit conversions or malformed data from changing
benchmark behaviour.

Relevant code: `json_io.hpp` and `config.hpp`.

## Current benchmark configuration

The selected configuration in `gammamax-test-suite` is:

```text
k = 3
n = 3
ngrams_batch_size = 1
max_candidate_length = unbounded
max_iterations = unbounded
max_total_oracle_calls = unbounded
max_states = unbounded
max_queue_size = unbounded (and currently operationally unused)
max_rsr_candidates = unbounded
outer test-suite timeout = 300 seconds per case
```

These values are experimental choices, not constants required by gammaMax.

## Legacy mechanisms replaced or removed

The new implementation is not merely the old CLI with different defaults.
Several legacy mechanisms were deliberately removed or replaced:

- The selectable `rpni`/`rpni_xover` learner and its crossover pair/check
  budgets were replaced by one deterministic red/blue EDSM implementation.
- The bounded merge-prefix parameter `m` was replaced by complete merge history
  plus validity-checked replay.
- The legacy mutation-based augmentation pass was removed. The new learner uses
  only the supplied examples and oracle-rejected repair candidates.
- Optional equivalence-query sampling was removed. Counterexamples now come
  directly from batched repair candidates rejected by the oracle.
- The legacy DFA cache/init-cache workflow was removed in favour of rebuilding
  the immutable PTA for each independent process invocation.
- Legacy fixed edit-cost and attempt caps were replaced by the general
  `max_candidate_length`, iteration, oracle-call, PTA-state, and queue limit
  fields, all of which support an unbounded setting.
- The legacy A*/product-graph candidate generator and its internal candidate
  and push budgets were replaced by repeated calls to paper-style C/H RSR plus
  exact-string language subtraction.
- The legacy command-line/file adapter was replaced by strict JSON input and
  configuration for the new standalone executable.

These removals reduce the number of interacting heuristics and make the tested
algorithm deterministic, but they also mean results from old and new gammaMax
cannot be attributed solely to different `k`, `n`, or batch-size values.

## Known optimization opportunity not yet implemented

Transactional speculative merging, single-best retention, incremental evidence,
and direct negative validation are implemented. Merge-history replay, however,
still begins from the PTA after every rejected batch. A future optimization
could retain validated partition checkpoints and resume from the longest
checkpoint that remains consistent with newly rejected repairs. Negative
examples could also be stored in a trie to share prefix traversal. Neither
checkpointed replay nor trie-based validation is currently implemented.
