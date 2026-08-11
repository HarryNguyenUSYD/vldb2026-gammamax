#pragma once

#include "gammamax/partitioned_dfa.hpp"
#include "gammamax/state_merge.hpp"

namespace gammamax {

struct ReplayResult {
    PartitionedDfa partition;
    MergeHistory valid_history;
    bool conflict{};
};

inline ReplayResult replay_merges(const Automaton& base,
                                  PartitionedDfa partition,
                                  const std::set<std::string>& negatives,
                                  const MergeHistory& history,
                                  const KSignatures& signatures,
                                  AlgorithmMeasurements* measurements = nullptr) {
    MergeHistory valid_history;
    bool conflict = false;
    for (const auto& record : history) {
        StateId red{}, blue{};
        try {
            red = partition.find_exact_members(record.red_original_states);
            blue = partition.find_exact_members(record.blue_original_states);
        } catch (const std::runtime_error&) {
            conflict = true;
            break;
        }
        const auto checkpoint = partition.checkpoint();
        if (!partition.merge_with_closure(base, red, blue, signatures)) {
            partition.rollback(checkpoint);
            conflict = true;
            break;
        }
        const auto validation_started = std::chrono::steady_clock::now();
        const bool consistent = rejects_all(base, partition, negatives);
        if (measurements)
            measurements->negative_validation_ns +=
                state_merge_elapsed_ns(validation_started);
        if (!consistent) {
            partition.rollback(checkpoint);
            conflict = true;
            break;
        }
        partition.commit(checkpoint);
        valid_history.push_back(record);
    }
    return {std::move(partition), std::move(valid_history), conflict};
}

inline ReplayResult replay_merges(const Automaton& base,
                                  const std::set<std::string>& negatives,
                                  const MergeHistory& history,
                                  const KSignatures& signatures,
                                  AlgorithmMeasurements* measurements = nullptr) {
    return replay_merges(base, PartitionedDfa(base), negatives, history,
                         signatures, measurements);
}

inline ReplayResult replay_merges(const Automaton& base,
                                  const std::set<std::string>& negatives,
                                  const MergeHistory& history) {
    return replay_merges(base, negatives, history,
                         KSignatures(base.storage_size(), 0), nullptr);
}

}  // namespace gammamax

