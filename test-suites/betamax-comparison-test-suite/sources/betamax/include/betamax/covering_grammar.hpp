#pragma once

#include "betamax/automaton.hpp"
#include "betamax/types.hpp"

#include <cstdint>

namespace betamax {

class CoveringGrammar {
public:
    CoveringGrammar(const Automaton& automaton, const Config& config)
        : automaton_(automaton), match_cost_(config.match_cost),
          insertion_cost_(config.insertion_cost), deletion_cost_(config.deletion_cost),
          substitution_cost_(config.substitution_cost) {}

    const Automaton& automaton() const noexcept { return automaton_; }
    std::uint64_t match_cost() const noexcept { return match_cost_; }
    std::uint64_t insertion_cost() const noexcept { return insertion_cost_; }
    std::uint64_t deletion_cost() const noexcept { return deletion_cost_; }
    std::uint64_t substitution_cost() const noexcept { return substitution_cost_; }

private:
    const Automaton& automaton_;
    std::uint64_t match_cost_{};
    std::uint64_t insertion_cost_{};
    std::uint64_t deletion_cost_{};
    std::uint64_t substitution_cost_{};
};

inline CoveringGrammar cover(const Automaton& automaton, const Config& config) {
    return CoveringGrammar(automaton, config);
}

}  // namespace betamax
