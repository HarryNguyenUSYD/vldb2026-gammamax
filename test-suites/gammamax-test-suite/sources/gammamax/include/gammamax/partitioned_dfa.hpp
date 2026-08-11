#pragma once

#include "gammamax/automaton.hpp"
#include "gammamax/types.hpp"

#include <algorithm>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string_view>
#include <utility>
#include <vector>

namespace gammamax {

// Lightweight quotient over an immutable PTA.  The PTA owns all transitions;
// this object stores only the current equivalence relation and class metadata.
class PartitionedDfa {
public:
    using Checkpoint = std::size_t;

    struct Cache {
        std::vector<std::map<Symbol, StateId>> transitions;
        std::vector<unsigned char> accepting;
        std::vector<StateId> roots;
    };

    explicit PartitionedDfa(const Automaton& base)
        : parent_(base.storage_size()), size_(base.storage_size(), 1),
          canonical_(base.storage_size()), accepting_(base.storage_size(), 0),
          transitions_(base.storage_size()) {
        for (StateId state = 0; state < base.storage_size(); ++state) {
            parent_[state] = state;
            canonical_[state] = state;
            accepting_[state] = base.state(state).accepting ? 1U : 0U;
            accepting_class_count_ += accepting_[state] ? 1U : 0U;
            transitions_[state] = base.state(state).transitions;
        }
    }

    StateId find(StateId state) const {
        if (state >= parent_.size()) throw std::runtime_error("invalid partition state");
        while (parent_[state] != state) state = parent_[state];
        return state;
    }

    StateId canonical(StateId state) const { return canonical_.at(find(state)); }
    bool accepting(StateId state) const { return accepting_.at(find(state)) != 0; }

    std::vector<StateId> roots() const {
        std::vector<StateId> result;
        for (StateId state = 0; state < parent_.size(); ++state)
            if (find(state) == state) result.push_back(state);
        std::sort(result.begin(), result.end(), [this](StateId left, StateId right) {
            return canonical_[left] < canonical_[right];
        });
        return result;
    }

    std::vector<StateId> members(StateId state) const {
        const StateId root = find(state);
        std::vector<StateId> result;
        for (StateId original = 0; original < parent_.size(); ++original)
            if (find(original) == root) result.push_back(original);
        return result;
    }

    StateId find_exact_members(const std::vector<StateId>& wanted) const {
        if (wanted.empty()) throw std::runtime_error("empty merge endpoint");
        const StateId root = find(wanted.front());
        if (members(root) != wanted)
            throw std::runtime_error("recorded merge endpoint is unavailable during replay");
        return root;
    }

    Cache build_cache(const Automaton& base) const {
        (void)base;
        Cache cache;
        cache.transitions.resize(parent_.size());
        cache.accepting.resize(parent_.size(), 0);
        cache.roots = roots();
        for (StateId root : cache.roots) cache.accepting[root] = accepting_[root];
        for (StateId root : cache.roots) {
            for (const auto& [symbol, destination] : transitions_[root])
                cache.transitions[root].emplace(symbol, find(destination));
        }
        return cache;
    }

    bool merge_with_closure(const Automaton& base, StateId left, StateId right,
                            const std::vector<std::size_t>& signatures) {
        (void)base;
        std::vector<std::pair<StateId, StateId>> pending{{left, right}};
        while (!pending.empty()) {
            auto [first, second] = pending.back();
            pending.pop_back();
            first = find(first);
            second = find(second);
            if (first == second) continue;
            if (class_signature(first, signatures) != class_signature(second, signatures))
                return false;
            unite(first, second, pending);
        }
        return true;
    }

    bool accepts(const Automaton& base, const Cache& cache, std::string_view value) const {
        StateId current = find(base.start_state());
        for (unsigned char symbol : value) {
            const auto found = cache.transitions[current].find(symbol);
            if (found == cache.transitions[current].end()) return false;
            current = find(found->second);
        }
        return accepting_[current] != 0;
    }

    // Execute directly on the maintained quotient. This avoids constructing a
    // complete Cache for every speculative merge during negative validation.
    bool accepts(const Automaton& base, std::string_view value) const {
        StateId current = find(base.start_state());
        for (unsigned char symbol : value) {
            const auto found = transitions_[current].find(symbol);
            if (found == transitions_[current].end()) return false;
            current = find(found->second);
        }
        return accepting_[current] != 0;
    }

    Checkpoint checkpoint() const noexcept { return undo_.size(); }

    void rollback(Checkpoint checkpoint) {
        if (checkpoint > undo_.size())
            throw std::runtime_error("invalid partition rollback checkpoint");
        while (undo_.size() > checkpoint) {
            UndoEntry entry = std::move(undo_.back());
            undo_.pop_back();
            parent_[entry.right] = entry.right;
            size_[entry.left] = entry.left_size;
            canonical_[entry.left] = entry.left_canonical;
            accepting_[entry.left] = entry.left_accepting;
            transitions_[entry.left] = std::move(entry.left_transitions);
            accepting_class_count_ = entry.accepting_class_count;
        }
    }

    // Keep changes made since checkpoint while discarding their rollback data.
    void commit(Checkpoint checkpoint) {
        if (checkpoint > undo_.size())
            throw std::runtime_error("invalid partition commit checkpoint");
        undo_.resize(checkpoint);
    }

    Automaton materialize(const Automaton& base) const {
        const Cache cache = build_cache(base);
        Automaton result;
        std::vector<StateId> dense(parent_.size(), std::numeric_limits<StateId>::max());
        for (StateId root : cache.roots)
            dense[root] = result.add_state(cache.accepting[root] != 0);
        result.set_start_state(dense.at(find(base.start_state())));
        for (StateId root : cache.roots) {
            for (const auto& [symbol, destination] : cache.transitions[root])
                result.state(dense[root]).transitions.emplace(
                    symbol, dense.at(find(destination)));
        }
        return result;
    }

    std::size_t accepting_class_count() const {
        return accepting_class_count_;
    }

private:
    struct UndoEntry {
        StateId left{};
        StateId right{};
        std::uint32_t left_size{};
        StateId left_canonical{};
        unsigned char left_accepting{};
        std::map<Symbol, StateId> left_transitions;
        std::size_t accepting_class_count{};
    };

    std::size_t class_signature(StateId root,
                                const std::vector<std::size_t>& signatures) const {
        return signatures.at(canonical_[find(root)]);
    }

    void unite(StateId left, StateId right,
               std::vector<std::pair<StateId, StateId>>& pending) {
        left = find(left);
        right = find(right);
        if (left == right) return;
        if (size_[left] < size_[right]) std::swap(left, right);
        undo_.push_back({left, right, size_[left], canonical_[left],
                         accepting_[left], transitions_[left],
                         accepting_class_count_});
        for (const auto& [symbol, raw_destination] : transitions_[right]) {
            const StateId destination = find(raw_destination);
            auto found = transitions_[left].find(symbol);
            if (found == transitions_[left].end()) {
                transitions_[left].emplace(symbol, destination);
            } else {
                const StateId existing = find(found->second);
                found->second = existing;
                if (existing != destination)
                    pending.emplace_back(existing, destination);
            }
        }
        parent_[right] = left;
        size_[left] += size_[right];
        canonical_[left] = std::min(canonical_[left], canonical_[right]);
        if (accepting_[left] && accepting_[right]) --accepting_class_count_;
        accepting_[left] = accepting_[left] || accepting_[right];
    }

    std::vector<StateId> parent_;
    std::vector<std::uint32_t> size_;
    std::vector<StateId> canonical_;
    std::vector<unsigned char> accepting_;
    std::vector<std::map<Symbol, StateId>> transitions_;
    std::size_t accepting_class_count_{};
    std::vector<UndoEntry> undo_;
};

}  // namespace gammamax
