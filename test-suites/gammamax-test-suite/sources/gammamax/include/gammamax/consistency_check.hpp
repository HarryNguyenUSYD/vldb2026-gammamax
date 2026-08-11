#pragma once

#include "gammamax/automaton.hpp"

#include <string>
#include <set>

namespace gammamax {

inline bool rejects_all(const Automaton& automaton,
                        const std::set<std::string>& negatives) {
    for (const auto& negative : negatives) {
        if (automaton.accepts(negative)) {
            return false;
        }
    }
    return true;
}

}  // namespace gammamax
