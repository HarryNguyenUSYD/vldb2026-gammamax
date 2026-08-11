#pragma once

#include "gammamax/automaton.hpp"

#include <map>
#include <stdexcept>
#include <utility>
#include <vector>

namespace gammamax {

using KSignatures = std::vector<std::size_t>;

struct KSignatureDescriptor {
    bool accepting{};
    std::vector<std::pair<Symbol, std::size_t>> branches;

    friend bool operator<(const KSignatureDescriptor& left,
                          const KSignatureDescriptor& right) {
        if (left.accepting != right.accepting) {
            return left.accepting < right.accepting;
        }
        return left.branches < right.branches;
    }
};

// Biermann-Feldman E_S(k) compares continuations whose length is strictly
// less than k. Starting every state in class zero and applying k refinement
// rounds implements that convention: k=0 disables k-tails, k=1 observes only
// current acceptance, and each later round adds one continuation symbol.
inline KSignatures compute_k_signatures(const Automaton& pta, std::size_t k) {
    KSignatures signatures(pta.storage_size(), 0);
    for (std::size_t depth = 0; depth < k; ++depth) {
        std::map<KSignatureDescriptor, std::size_t> interned;
        interned.emplace(KSignatureDescriptor{}, 0);
        std::size_t next_id = 1;
        KSignatures current(pta.storage_size(), 0);

        for (StateId state = 0; state < pta.storage_size(); ++state) {
            if (!pta.active(state)) {
                throw std::runtime_error(
                    "k-signatures must be trained on the unmerged PTA");
            }
            KSignatureDescriptor descriptor;
            descriptor.accepting = pta.state(state).accepting;
            for (const auto& [symbol, destination] : pta.state(state).transitions) {
                const std::size_t target = signatures.at(pta.resolve(destination));
                // Class zero represents no observed accepting continuation at
                // this depth, so it carries no membership evidence in P(S).
                if (target != 0) descriptor.branches.emplace_back(symbol, target);
            }
            auto [found, inserted] = interned.emplace(std::move(descriptor), next_id);
            if (inserted) ++next_id;
            current.at(state) = found->second;
        }
        signatures = std::move(current);
    }
    return signatures;
}

inline std::size_t state_k_signature(const Automaton& automaton, StateId state,
                                     const KSignatures& signatures) {
    const auto& originals = automaton.state(state).original_states;
    if (originals.empty()) throw std::runtime_error("DFA state has no original identity");
    const std::size_t expected = signatures.at(*originals.begin());
    for (StateId original : originals) {
        if (signatures.at(original) != expected) {
            throw std::runtime_error("merged DFA violates fixed k-signature classes");
        }
    }
    return expected;
}

inline bool same_k_signature(const Automaton& automaton, StateId left, StateId right,
                             const KSignatures& signatures) {
    return state_k_signature(automaton, left, signatures) ==
           state_k_signature(automaton, right, signatures);
}

inline bool respects_k_signatures(const Automaton& automaton,
                                  const KSignatures& signatures) {
    for (StateId state : automaton.active_states()) {
        const auto& originals = automaton.state(state).original_states;
        if (originals.empty()) return false;
        const std::size_t expected = signatures.at(*originals.begin());
        for (StateId original : originals) {
            if (signatures.at(original) != expected) return false;
        }
    }
    return true;
}

}  // namespace gammamax
