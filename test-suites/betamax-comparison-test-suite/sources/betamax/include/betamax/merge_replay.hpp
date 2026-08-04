#pragma once

#include "betamax/consistency_check.hpp"
#include "betamax/pta.hpp"
#include "betamax/types.hpp"

#include <string>
#include <vector>

namespace betamax {

inline Automaton replay_merges(const Automaton& pta,
                               const std::vector<std::string>& negatives,
                               const MergeHistory& history) {
    Automaton automaton = pta;
    for (const auto& record : history) {
        StateId red{};
        StateId blue{};
        try {
            red = automaton.find_exact_original_set(record.red_original_states);
            blue = automaton.find_exact_original_set(record.blue_original_states);
        } catch (const std::runtime_error&) {
            continue;
        }
        Automaton candidate = automaton;
        candidate.merge_states(red, blue);
        if (rejects_all(candidate, negatives)) {
            automaton = std::move(candidate);
        }
    }
    return automaton;
}

}  // namespace betamax
