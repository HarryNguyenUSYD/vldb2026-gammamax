#pragma once

#include "betamax/automaton.hpp"
#include "betamax/oracle.hpp"

#include <algorithm>
#include <limits>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace betamax {

struct PassingString {
    const std::string* value{};
    std::size_t split_position{};
};

inline std::vector<PassingString> positive_strings_through(
    const Automaton& automaton, StateId target,
    const std::vector<std::string>& positives) {
    std::vector<PassingString> result;
    target = automaton.resolve(target);
    for (const auto& value : positives) {
        const auto path = automaton.path(value);
        std::size_t last = std::numeric_limits<std::size_t>::max();
        for (std::size_t position = 0; position < path.size(); ++position) {
            if (automaton.resolve(path[position]) == target) {
                last = position;
            }
        }
        if (last != std::numeric_limits<std::size_t>::max()) {
            result.push_back(PassingString{&value, last});
        }
    }
    return result;
}

inline bool can_merge(const Automaton& automaton, StateId red, StateId blue,
                      const std::vector<std::string>& positives, std::size_t sample_count,
                      Oracle& oracle, std::mt19937_64& random) {
    const auto red_strings = positive_strings_through(automaton, red, positives);
    const auto blue_strings = positive_strings_through(automaton, blue, positives);
    if (red_strings.empty() || blue_strings.empty()) {
        return false;
    }
    if (red_strings.size() > std::numeric_limits<std::size_t>::max() / blue_strings.size()) {
        throw std::runtime_error("cross-merge sample product is too large");
    }
    const std::size_t product = red_strings.size() * blue_strings.size();
    const std::size_t wanted = std::min(sample_count, product);
    std::set<std::size_t> selected;
    std::uniform_int_distribution<std::size_t> distribution(0, product - 1);
    while (selected.size() < wanted) {
        selected.insert(distribution(random));
    }

    for (std::size_t flat : selected) {
        const auto& first = red_strings[flat / blue_strings.size()];
        const auto& second = blue_strings[flat % blue_strings.size()];
        const auto check_direction = [&oracle](const PassingString& prefix,
                                               const PassingString& suffix) {
            std::string crossover = prefix.value->substr(0, prefix.split_position);
            crossover += suffix.value->substr(suffix.split_position);
            return oracle.accepts(crossover);
        };
        if (!check_direction(first, second) || !check_direction(second, first)) {
            return false;
        }
    }
    return true;
}

}  // namespace betamax
