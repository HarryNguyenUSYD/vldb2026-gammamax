#pragma once

#include "betamax/automaton.hpp"

#include <string>
#include <vector>

namespace betamax {

inline bool rejects_all(const Automaton& automaton,
                        const std::vector<std::string>& negatives) {
    for (const auto& negative : negatives) {
        if (automaton.accepts(negative)) {
            return false;
        }
    }
    return true;
}

}  // namespace betamax
