#pragma once

#include "betamax/oracle.hpp"
#include "betamax/pta.hpp"
#include "betamax/types.hpp"

#include <algorithm>
#include <map>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace betamax {

struct NeighborhoodResult {
    std::vector<std::string> rejected;
};

struct TransitionUse {
    const std::string* value{};
    std::size_t position{};
};

inline NeighborhoodResult explore_neighborhood(
    const Automaton& pta,
    const std::vector<std::string>& initial_positives,
    const std::vector<std::string>& initial_negatives, const std::string& corrupt,
    const Config& config, Oracle& oracle, std::mt19937_64& random) {
    std::set<std::string> known(initial_positives.begin(), initial_positives.end());
    known.insert(initial_negatives.begin(), initial_negatives.end());
    known.insert(corrupt);

    // Paper NE mutates one PTA transition, then generates strings whose paths use
    // that transition. Relabeling one transition changes exactly one symbol in
    // each generated string; insertion and deletion neighbors are not NE here.
    using TransitionKey = std::pair<StateId, Symbol>;
    std::map<TransitionKey, std::vector<TransitionUse>> uses;
    for (const auto& value : initial_positives) {
        StateId state = pta.start_state();
        for (std::size_t position = 0; position < value.size(); ++position) {
            const Symbol symbol = static_cast<unsigned char>(value[position]);
            uses[{pta.resolve(state), symbol}].push_back(TransitionUse{&value, position});
            StateId destination{};
            if (!pta.transition(state, symbol, destination)) {
                throw std::runtime_error("positive string has no path through its PTA");
            }
            state = destination;
        }
    }

    std::set<std::string> unique_neighbors;
    for (const auto& [transition, transition_uses] : uses) {
        const Symbol original = transition.second;
        for (unsigned int raw = 32; raw <= 126; ++raw) {
            const Symbol replacement = static_cast<Symbol>(raw);
            if (replacement == original) {
                continue;
            }
            for (const auto& use : transition_uses) {
                std::string neighbor = *use.value;
                neighbor[use.position] = static_cast<char>(replacement);
                if (!known.contains(neighbor)) {
                    unique_neighbors.insert(std::move(neighbor));
                }
            }
        }
    }

    std::vector<std::string> candidates(unique_neighbors.begin(), unique_neighbors.end());
    std::shuffle(candidates.begin(), candidates.end(), random);

    NeighborhoodResult result;
    std::size_t local_calls = 0;
    for (const auto& candidate : candidates) {
        if (result.rejected.size() >= config.target_negative_examples ||
            local_calls >= config.neighborhood_max_oracle_calls) {
            break;
        }
        ++local_calls;
        if (!oracle.accepts(candidate)) {
            result.rejected.push_back(candidate);
        }
    }
    std::sort(result.rejected.begin(), result.rejected.end());
    result.rejected.erase(std::unique(result.rejected.begin(), result.rejected.end()),
                          result.rejected.end());
    return result;
}

}  // namespace betamax
