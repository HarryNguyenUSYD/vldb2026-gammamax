#pragma once

#include "gammamax/k_tails.hpp"
#include "gammamax/partitioned_dfa.hpp"
#include "gammamax/types.hpp"

#include <algorithm>
#include <chrono>
#include <optional>
#include <set>
#include <tuple>
#include <utility>
#include <vector>

namespace gammamax {

struct StateMergeResult {
    PartitionedDfa partition;
    MergeHistory history;
};

inline std::set<StateId> normalized(const PartitionedDfa& partition,
                                    const std::set<StateId>& states) {
    std::set<StateId> result;
    for (StateId state : states) result.insert(partition.find(state));
    return result;
}

inline bool rejects_all(const Automaton& base, const PartitionedDfa& partition,
                        const std::set<std::string>& negatives) {
    for (const auto& negative : negatives)
        if (partition.accepts(base, negative)) return false;
    return true;
}

inline std::uint64_t state_merge_elapsed_ns(
    std::chrono::steady_clock::time_point started) {
    return static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now() - started).count());
}

inline std::size_t edsm_evidence(const PartitionedDfa& before,
                                 const PartitionedDfa& after) {
    return before.accepting_class_count() - after.accepting_class_count();
}

// Compatibility helper retained for callers comparing materialized DFAs.
inline std::size_t edsm_evidence(const Automaton& before, const Automaton& after) {
    std::set<StateId> resulting_accepting_classes;
    std::size_t accepting_classes = 0;
    for (StateId state : before.active_states()) {
        if (!before.state(state).accepting) continue;
        ++accepting_classes;
        resulting_accepting_classes.insert(after.resolve(state));
    }
    return accepting_classes - resulting_accepting_classes.size();
}

inline StateMergeResult state_merge(const Automaton& base, PartitionedDfa initial,
                                    const std::set<std::string>& negatives,
                                    const KSignatures& signatures,
                                    MergeHistory history = {},
                                    AlgorithmMeasurements* measurements = nullptr) {
    PartitionedDfa partition = std::move(initial);
    std::set<StateId> red{partition.find(base.start_state())};

    for (;;) {
        red = normalized(partition, red);
        const auto cache = partition.build_cache(base);
        std::set<StateId> blue;
        for (StateId red_state : red) {
            for (const auto& [symbol, destination] : cache.transitions[red_state]) {
                (void)symbol;
                const StateId child = partition.find(destination);
                if (!red.contains(child)) blue.insert(child);
            }
        }
        if (blue.empty()) break;

        struct Choice {
            std::size_t evidence{};
            StateId red_canonical{};
            StateId blue_canonical{};
            std::vector<StateId> red_members;
            std::vector<StateId> blue_members;
        };
        std::optional<Choice> best;

        for (StateId blue_state : blue) {
            for (StateId red_state : red) {
                if (signatures.at(partition.canonical(red_state)) !=
                    signatures.at(partition.canonical(blue_state)))
                    continue;
                auto red_members = partition.members(red_state);
                auto blue_members = partition.members(blue_state);
                const std::size_t before_accepting =
                    partition.accepting_class_count();
                const auto checkpoint = partition.checkpoint();
                auto transaction_started = std::chrono::steady_clock::now();
                const bool compatible = partition.merge_with_closure(
                    base, red_state, blue_state, signatures);
                if (measurements)
                    measurements->candidate_copy_or_rollback_ns +=
                        state_merge_elapsed_ns(transaction_started);

                bool consistent = false;
                std::size_t evidence = 0;
                if (compatible) {
                    auto validation_started = std::chrono::steady_clock::now();
                    consistent = rejects_all(base, partition, negatives);
                    if (measurements)
                        measurements->negative_validation_ns +=
                            state_merge_elapsed_ns(validation_started);
                }

                // Evidence is the accepting-class reduction from the checkpoint.
                const std::size_t after_accepting = partition.accepting_class_count();
                transaction_started = std::chrono::steady_clock::now();
                partition.rollback(checkpoint);
                if (measurements)
                    measurements->candidate_copy_or_rollback_ns +=
                        state_merge_elapsed_ns(transaction_started);
                if (!compatible || !consistent) continue;
                evidence = before_accepting - after_accepting;

                Choice choice{evidence, partition.canonical(red_state),
                              partition.canonical(blue_state),
                              std::move(red_members), std::move(blue_members)};
                const auto worse = [](const Choice& left, const Choice& right) {
                    if (left.evidence != right.evidence)
                        return left.evidence < right.evidence;
                    return std::tie(left.red_canonical, left.blue_canonical) >
                           std::tie(right.red_canonical, right.blue_canonical);
                };
                if (!best || worse(*best, choice)) best = std::move(choice);
            }
        }

        if (!best) {
            red.insert(*blue.begin());
            continue;
        }
        const auto checkpoint = partition.checkpoint();
        auto transaction_started = std::chrono::steady_clock::now();
        if (!partition.merge_with_closure(base, best->red_canonical,
                                          best->blue_canonical, signatures))
            throw std::runtime_error("selected EDSM merge could not be reapplied");
        partition.commit(checkpoint);
        if (measurements)
            measurements->candidate_copy_or_rollback_ns +=
                state_merge_elapsed_ns(transaction_started);
        history.push_back({std::move(best->red_members), std::move(best->blue_members)});
    }

    return {std::move(partition), std::move(history)};
}

inline StateMergeResult state_merge(const Automaton& base,
                                    const std::set<std::string>& negatives,
                                    const KSignatures& signatures,
                                    MergeHistory history = {},
                                    AlgorithmMeasurements* measurements = nullptr) {
    return state_merge(base, PartitionedDfa(base), negatives, signatures,
                       std::move(history), measurements);
}

inline StateMergeResult state_merge(const Automaton& base,
                                    const std::set<std::string>& negatives,
                                    std::size_t k, MergeHistory history = {}) {
    return state_merge(base, negatives, compute_k_signatures(base, k),
                       std::move(history));
}

}  // namespace gammamax
