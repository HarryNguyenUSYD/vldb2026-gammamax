#pragma once

#include "betamax/can_merge.hpp"
#include "betamax/consistency_check.hpp"
#include "betamax/pta.hpp"
#include "betamax/types.hpp"

#include <algorithm>
#include <random>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace betamax {

struct StateMergeResult {
    Automaton automaton;
    MergeHistory history;
};

inline std::set<StateId> normalize_state_set(const Automaton& automaton,
                                             const std::set<StateId>& states) {
    std::set<StateId> result;
    for (StateId state : states) {
        result.insert(automaton.resolve(state));
    }
    return result;
}

inline std::vector<StateId> sorted_canonical(const Automaton& automaton,
                                             const std::set<StateId>& states) {
    std::vector<StateId> result(states.begin(), states.end());
    std::sort(result.begin(), result.end(), [&automaton](StateId left, StateId right) {
        return automaton.canonical(left) < automaton.canonical(right);
    });
    return result;
}

inline StateMergeResult state_merge(const Automaton& pta,
                                    const std::vector<std::string>& positives,
                                    const std::vector<std::string>& negatives,
                                    const Config& config, Oracle& oracle,
                                    std::mt19937_64& random) {
    StateMergeResult result{pta, {}};
    std::set<StateId> red{result.automaton.start_state()};

    for (;;) {
        red = normalize_state_set(result.automaton, red);
        std::set<StateId> blue;
        for (StateId red_state : red) {
            for (StateId child : result.automaton.children(red_state)) {
                child = result.automaton.resolve(child);
                if (!red.contains(child)) {
                    blue.insert(child);
                }
            }
        }
        if (blue.empty()) {
            break;
        }
        const auto ordered_blue = sorted_canonical(result.automaton, blue);
        const StateId selected_blue = ordered_blue.front();
        const auto ordered_red = sorted_canonical(result.automaton, red);
        bool merged = false;

        for (StateId red_state : ordered_red) {
            if (!can_merge(result.automaton, red_state, selected_blue, positives,
                           config.cross_merge_samples, oracle, random)) {
                continue;
            }
            const auto red_originals = result.automaton.original_vector(red_state);
            const auto blue_originals = result.automaton.original_vector(selected_blue);
            Automaton candidate = result.automaton;
            candidate.merge_states(red_state, selected_blue);
            if (!rejects_all(candidate, negatives)) {
                continue;
            }
            result.automaton = std::move(candidate);
            result.history.push_back(MergeRecord{red_originals, blue_originals});
            red = normalize_state_set(result.automaton, red);
            merged = true;
            break;
        }
        if (!merged) {
            red.insert(selected_blue);
        }
    }
    return result;
}

}  // namespace betamax
