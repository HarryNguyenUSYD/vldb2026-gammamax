#pragma once

#include "betamax/covering_grammar.hpp"
#include "betamax/types.hpp"

#include <algorithm>
#include <cstdint>
#include <limits>
#include <map>
#include <optional>
#include <queue>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace betamax {

inline std::uint64_t checked_add_cost(std::uint64_t left, std::uint64_t right) {
    if (right > std::numeric_limits<std::uint64_t>::max() - left) {
        throw std::runtime_error("repair cost overflow");
    }
    return left + right;
}

inline unsigned char edit_rank(EditKind kind) {
    switch (kind) {
        case EditKind::Start: return 0;
        case EditKind::Match: return 1;
        case EditKind::Insert: return 2;
        case EditKind::SigmaPlus: return 3;
        case EditKind::Substitute: return 4;
    }
    return 255;
}

struct SearchEnvelope {
    RepairNode node;
    std::string output;
    std::string edit_order;
};

struct SearchQueueOrder {
    const std::vector<SearchEnvelope>* nodes{};
    const Automaton* automaton{};
    std::size_t input_size{};

    bool operator()(std::size_t left_index, std::size_t right_index) const {
        const auto& left = nodes->at(left_index);
        const auto& right = nodes->at(right_index);
        if (left.node.cost != right.node.cost) {
            return left.node.cost > right.node.cost;
        }
        const bool left_complete =
            left.node.input_position == input_size &&
            automaton->state(left.node.state).accepting;
        const bool right_complete =
            right.node.input_position == input_size &&
            automaton->state(right.node.state).accepting;
        if (left_complete != right_complete) {
            return !left_complete;
        }
        if (left.node.input_position != right.node.input_position) {
            return left.node.input_position < right.node.input_position;
        }
        const auto left_key = std::tie(left.output, left.edit_order);
        const auto right_key = std::tie(right.output, right.edit_order);
        if (left_key != right_key) {
            return left_key > right_key;
        }
        return left_index > right_index;
    }
};

inline std::string reconstruct_candidate(const std::vector<SearchEnvelope>& nodes,
                                         std::size_t index) {
    std::string reversed;
    for (int cursor = static_cast<int>(index); cursor >= 0;
         cursor = nodes.at(static_cast<std::size_t>(cursor)).node.predecessor) {
        const auto& node = nodes.at(static_cast<std::size_t>(cursor)).node;
        if (node.edit == EditKind::Match || node.edit == EditKind::Insert ||
            node.edit == EditKind::SigmaPlus || node.edit == EditKind::Substitute) {
            reversed.push_back(node.emitted);
        }
    }
    std::reverse(reversed.begin(), reversed.end());
    return reversed;
}

inline std::optional<RepairCandidate> min_penalty_repair(
    const CoveringGrammar& grammar, const std::string& input, const Config& config) {
    const Automaton& automaton = grammar.automaton();
    if (grammar.insertion_cost() == 0 && automaton.has_cycle()) {
        throw std::runtime_error("unsafe zero-cost cycle in covering grammar");
    }

    using SeenKey = std::tuple<std::size_t, StateId, std::uint64_t, std::string>;
    std::map<SeenKey, std::string> best_edit_order;
    std::vector<SearchEnvelope> nodes;
    nodes.reserve(std::min<std::size_t>(config.max_queue_size, 4096));
    SearchQueueOrder queue_order{&nodes, &automaton, input.size()};
    std::priority_queue<std::size_t, std::vector<std::size_t>, SearchQueueOrder> queue(
        queue_order);

    const auto enqueue = [&](RepairNode node, std::string output, std::string edit_order,
                             auto& self) -> void {
        (void)self;
        const SeenKey key{node.input_position, automaton.resolve(node.state), node.cost, output};
        auto found = best_edit_order.find(key);
        if (found != best_edit_order.end() && found->second <= edit_order) {
            return;
        }
        best_edit_order[key] = edit_order;
        node.state = automaton.resolve(node.state);
        nodes.push_back(SearchEnvelope{node, std::move(output), std::move(edit_order)});
        queue.push(nodes.size() - 1);
        if (queue.size() > config.max_queue_size) {
            throw std::runtime_error("maximum repair queue-size limit exceeded");
        }
    };

    RepairNode start;
    start.state = automaton.start_state();
    start.edit = EditKind::Start;
    enqueue(start, {}, {}, enqueue);

    std::set<std::pair<std::size_t, StateId>> settled;
    while (!queue.empty()) {
        const std::size_t index = queue.top();
        queue.pop();
        const SearchEnvelope current = nodes.at(index);
        const SeenKey current_key{current.node.input_position, current.node.state,
                                  current.node.cost, current.output};
        const auto best = best_edit_order.find(current_key);
        if (best == best_edit_order.end() || best->second != current.edit_order) {
            continue;
        }
        const auto configuration =
            std::pair(current.node.input_position, current.node.state);
        if (!settled.insert(configuration).second) {
            continue;
        }
        if (current.node.input_position == input.size() &&
            automaton.state(current.node.state).accepting) {
            const std::string reconstructed = reconstruct_candidate(nodes, index);
            if (reconstructed != current.output) {
                throw std::runtime_error("internal repair reconstruction mismatch");
            }
            return RepairCandidate{reconstructed, current.node.cost, current.edit_order};
        }

        const auto make_edit_order = [&current](EditKind kind, char emitted) {
            std::string result = current.edit_order;
            result.push_back(static_cast<char>(edit_rank(kind)));
            result.push_back(emitted);
            return result;
        };
        const auto append_node = [&](StateId state, std::size_t position, std::uint64_t cost,
                                     EditKind edit, char emitted, std::string output) {
            RepairNode next;
            next.state = state;
            next.input_position = position;
            next.cost = cost;
            if (index > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
                throw std::runtime_error("repair predecessor index overflow");
            }
            next.predecessor = static_cast<int>(index);
            next.edit = edit;
            next.emitted = emitted;
            enqueue(next, std::move(output), make_edit_order(edit, emitted), enqueue);
        };

        for (const auto& [symbol, raw_destination] :
             automaton.state(current.node.state).transitions) {
            const StateId destination = automaton.resolve(raw_destination);
            const char emitted = static_cast<char>(symbol);
            if (current.output.size() < config.max_candidate_length) {
                std::string inserted_output = current.output;
                inserted_output.push_back(emitted);
                append_node(destination, current.node.input_position,
                            checked_add_cost(current.node.cost, grammar.insertion_cost()),
                            EditKind::Insert, emitted, std::move(inserted_output));
            }
            if (current.node.input_position >= input.size() ||
                current.output.size() >= config.max_candidate_length) {
                continue;
            }
            std::string consumed_output = current.output;
            consumed_output.push_back(emitted);
            if (static_cast<unsigned char>(input[current.node.input_position]) == symbol) {
                append_node(destination, current.node.input_position + 1,
                            checked_add_cost(current.node.cost, grammar.match_cost()),
                            EditKind::Match, emitted, std::move(consumed_output));
            } else {
                append_node(destination, current.node.input_position + 1,
                            checked_add_cost(current.node.cost, grammar.substitution_cost()),
                            EditKind::Substitute, emitted, std::move(consumed_output));
            }

            // Covering production T_x -> Sigma+ x: consume one or more extra
            // input symbols followed by x, emit x, and charge once for the
            // production regardless of how many extra symbols it consumes.
            for (std::size_t end = current.node.input_position + 1;
                 end < input.size(); ++end) {
                if (static_cast<unsigned char>(input[end]) != symbol) {
                    continue;
                }
                std::string repaired_output = current.output;
                repaired_output.push_back(emitted);
                append_node(destination, end + 1,
                            checked_add_cost(current.node.cost,
                                             grammar.deletion_cost()),
                            EditKind::SigmaPlus, emitted,
                            std::move(repaired_output));
            }
        }
    }
    return std::nullopt;
}

}  // namespace betamax
