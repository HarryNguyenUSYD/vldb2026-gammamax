#pragma once

#include "betamax/covering_grammar.hpp"
#include "betamax/merge_replay.hpp"
#include "betamax/min_penalty_repair.hpp"
#include "betamax/neighborhood_exploration.hpp"
#include "betamax/state_merge.hpp"
#include "betamax/types.hpp"

#include <algorithm>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace betamax {

inline void sort_unique(std::vector<std::string>& values) {
    std::sort(values.begin(), values.end());
    values.erase(std::unique(values.begin(), values.end()), values.end());
}

inline std::string beta_max(const InputData& input, const Config& config, Oracle& oracle,
                            std::mt19937_64& random) {
    if (oracle.accepts(input.corrupt_string)) {
        return input.corrupt_string;
    }

    std::vector<std::string> positives = input.positive_examples;
    std::vector<std::string> negatives = input.negative_examples;
    negatives.push_back(input.corrupt_string);
    sort_unique(positives);
    sort_unique(negatives);
    for (const auto& positive : positives) {
        if (std::binary_search(negatives.begin(), negatives.end(), positive)) {
            throw std::runtime_error("the same example is labeled both positive and negative");
        }
    }

    const Automaton pta = build_pta(positives, config.max_states);
    const auto neighborhood = explore_neighborhood(pta, input.positive_examples,
                                                    input.negative_examples,
                                                    input.corrupt_string, config, oracle, random);
    negatives.insert(negatives.end(), neighborhood.rejected.begin(),
                     neighborhood.rejected.end());
    sort_unique(negatives);

    auto merged = state_merge(pta, positives, negatives, config, oracle, random);
    Automaton grammar = std::move(merged.automaton);
    const MergeHistory history = std::move(merged.history);

    std::set<std::string> queried_repair_candidates{input.corrupt_string};
    std::set<std::string> grammar_fingerprints{grammar.fingerprint()};
    for (std::size_t iteration = 0; iteration < config.max_iterations; ++iteration) {
        const auto candidate = min_penalty_repair(cover(grammar, config),
                                                  input.corrupt_string, config);
        if (!candidate) {
            throw std::runtime_error("covering grammar produced no repair candidate");
        }
        if (!queried_repair_candidates.insert(candidate->value).second) {
            throw std::runtime_error("repair candidate repeated without progress");
        }
        if (oracle.accepts(candidate->value)) {
            return candidate->value;
        }

        negatives.push_back(candidate->value);
        sort_unique(negatives);
        grammar = replay_merges(pta, negatives, history);
        const std::string fingerprint = grammar.fingerprint();
        if (!grammar_fingerprints.insert(fingerprint).second) {
            throw std::runtime_error("grammar repeated without progress");
        }
    }
    throw std::runtime_error("maximum repair-iteration limit exhausted");
}

}  // namespace betamax
