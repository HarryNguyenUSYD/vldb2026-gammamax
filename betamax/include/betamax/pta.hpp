#pragma once

#include "betamax/automaton.hpp"

#include <algorithm>
#include <stdexcept>
#include <string>
#include <vector>

namespace betamax {

inline Automaton build_pta(std::vector<std::string> positives, std::size_t max_states) {
    std::sort(positives.begin(), positives.end());
    positives.erase(std::unique(positives.begin(), positives.end()), positives.end());

    Automaton automaton;
    const StateId root = automaton.add_state(false);
    automaton.set_start_state(root);
    for (const auto& value : positives) {
        StateId current = root;
        if (value.empty()) {
            automaton.state(current).accepting = true;
            continue;
        }
        for (unsigned char byte : value) {
            StateId next{};
            if (!automaton.transition(current, byte, next)) {
                if (automaton.storage_size() >= max_states) {
                    throw std::runtime_error("maximum DFA state limit exceeded while building PTA");
                }
                next = automaton.add_state(false);
                automaton.state(current).transitions.emplace(byte, next);
            }
            current = next;
        }
        automaton.state(current).accepting = true;
    }
    return automaton;
}

}  // namespace betamax
