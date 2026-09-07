#pragma once

#include "gammamax/types.hpp"

#include <algorithm>
#include <limits>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace gammamax {

struct DfaState {
    bool accepting{false};
    std::map<Symbol, StateId> transitions;
    std::set<StateId> original_states;
};

class Automaton {
public:
    StateId add_state(bool accepting = false) {
        if (states_.size() > static_cast<std::size_t>(std::numeric_limits<StateId>::max())) {
            throw std::runtime_error("DFA state identifier overflow");
        }
        const auto id = static_cast<StateId>(states_.size());
        DfaState state;
        state.accepting = accepting;
        state.original_states.insert(id);
        states_.push_back(std::move(state));
        parent_.push_back(id);
        return id;
    }

    StateId start_state() const noexcept { return start_; }
    void set_start_state(StateId state) { start_ = state; }

    std::size_t storage_size() const noexcept { return states_.size(); }

    StateId resolve(StateId state) const {
        if (state >= parent_.size()) {
            throw std::runtime_error("invalid DFA state");
        }
        while (parent_[state] != state) {
            state = parent_[state];
        }
        return state;
    }

    bool active(StateId state) const { return state < parent_.size() && resolve(state) == state; }

    DfaState& state(StateId id) { return states_.at(resolve(id)); }
    const DfaState& state(StateId id) const { return states_.at(resolve(id)); }

    std::size_t active_state_count() const {
        std::size_t count = 0;
        for (StateId id = 0; id < states_.size(); ++id) {
            count += active(id) ? 1U : 0U;
        }
        return count;
    }

    StateId canonical(StateId id) const {
        const auto& originals = state(id).original_states;
        if (originals.empty()) {
            throw std::runtime_error("DFA state has no original identity");
        }
        return *originals.begin();
    }

    std::vector<StateId> original_vector(StateId id) const {
        const auto& originals = state(id).original_states;
        return {originals.begin(), originals.end()};
    }

    std::vector<StateId> active_states() const {
        std::vector<StateId> result;
        for (StateId id = 0; id < states_.size(); ++id) {
            if (active(id)) {
                result.push_back(id);
            }
        }
        std::sort(result.begin(), result.end(), [this](StateId left, StateId right) {
            return canonical(left) < canonical(right);
        });
        return result;
    }

    std::vector<StateId> children(StateId id) const {
        std::set<StateId> unique;
        for (const auto& [symbol, destination] : state(id).transitions) {
            (void)symbol;
            unique.insert(resolve(destination));
        }
        std::vector<StateId> result(unique.begin(), unique.end());
        std::sort(result.begin(), result.end(), [this](StateId left, StateId right) {
            return canonical(left) < canonical(right);
        });
        return result;
    }

    bool transition(StateId source, Symbol symbol, StateId& destination) const {
        const auto& transitions = state(source).transitions;
        const auto found = transitions.find(symbol);
        if (found == transitions.end()) {
            return false;
        }
        destination = resolve(found->second);
        return true;
    }

    bool accepts(std::string_view value) const {
        StateId current = resolve(start_);
        for (unsigned char byte : value) {
            StateId next{};
            if (!transition(current, byte, next)) {
                return false;
            }
            current = next;
        }
        return state(current).accepting;
    }

    std::vector<StateId> path(std::string_view value) const {
        std::vector<StateId> result;
        StateId current = resolve(start_);
        result.push_back(current);
        for (unsigned char byte : value) {
            StateId next{};
            if (!transition(current, byte, next)) {
                return {};
            }
            current = next;
            result.push_back(current);
        }
        return result;
    }

    StateId merge_states(StateId left, StateId right) {
        return merge_impl(resolve(left), resolve(right));
    }

    StateId find_exact_original_set(const std::vector<StateId>& originals) const {
        const std::set<StateId> wanted(originals.begin(), originals.end());
        for (StateId id : active_states()) {
            if (state(id).original_states == wanted) {
                return id;
            }
        }
        throw std::runtime_error("recorded merge endpoint is unavailable during replay");
    }

    std::string fingerprint() const {
        std::ostringstream out;
        out << "start=" << canonical(start_) << ';';
        for (StateId id : active_states()) {
            out << canonical(id) << ':' << (state(id).accepting ? '1' : '0') << '[';
            for (StateId original : state(id).original_states) {
                out << original << ',';
            }
            out << "]{";
            for (const auto& [symbol, destination] : state(id).transitions) {
                out << static_cast<unsigned int>(symbol) << '>' << canonical(destination) << ',';
            }
            out << "};";
        }
        return out.str();
    }

    bool has_cycle() const {
        std::vector<unsigned char> colors(states_.size(), 0);
        const auto visit = [&](const auto& self, StateId raw) -> bool {
            const StateId id = resolve(raw);
            if (colors[id] == 1) {
                return true;
            }
            if (colors[id] == 2) {
                return false;
            }
            colors[id] = 1;
            for (const auto& [symbol, destination] : state(id).transitions) {
                (void)symbol;
                if (self(self, destination)) {
                    return true;
                }
            }
            colors[id] = 2;
            return false;
        };
        return visit(visit, start_);
    }

private:
    StateId merge_impl(StateId left, StateId right) {
        left = resolve(left);
        right = resolve(right);
        if (left == right) {
            return left;
        }
        StateId winner = canonical(left) <= canonical(right) ? left : right;
        StateId loser = winner == left ? right : left;

        parent_[loser] = winner;
        states_[winner].accepting = states_[winner].accepting || states_[loser].accepting;
        states_[winner].original_states.insert(states_[loser].original_states.begin(),
                                                states_[loser].original_states.end());

        const auto losing_transitions = states_[loser].transitions;
        for (const auto& [symbol, raw_destination] : losing_transitions) {
            StateId destination = resolve(raw_destination);
            auto found = states_[winner].transitions.find(symbol);
            if (found == states_[winner].transitions.end()) {
                states_[winner].transitions.emplace(symbol, destination);
            } else {
                const StateId folded = merge_impl(resolve(found->second), destination);
                states_[winner].transitions[symbol] = folded;
                winner = resolve(winner);
            }
        }
        normalize_transitions();
        start_ = resolve(start_);
        return resolve(winner);
    }

    void normalize_transitions() {
        for (StateId id = 0; id < states_.size(); ++id) {
            if (!active(id)) {
                continue;
            }
            for (auto& [symbol, destination] : states_[id].transitions) {
                (void)symbol;
                destination = resolve(destination);
            }
        }
    }

    std::vector<DfaState> states_;
    std::vector<StateId> parent_;
    StateId start_{0};
};

}  // namespace gammamax
