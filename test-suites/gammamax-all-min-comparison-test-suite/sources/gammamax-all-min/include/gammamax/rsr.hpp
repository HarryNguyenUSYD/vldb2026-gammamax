#pragma once

#include "gammamax/automaton.hpp"
#include "gammamax/ngram.hpp"
#include "gammamax/types.hpp"
#include <algorithm>
#include <chrono>
#include <compare>
#include <functional>
#include <limits>
#include <optional>
#include <queue>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace gammamax {
struct RsrEdge { StateId source{},destination{}; Symbol symbol{}; };
enum class RsrOperation : unsigned char { none,match,deletion,insertion,substitution };
struct RsrPredecessor {
    std::size_t previous_row{},previous_column{};
    RsrOperation operation{RsrOperation::none}; Symbol symbol{};
    auto operator<=>(const RsrPredecessor&) const = default;
};
struct RsrHistoryCell { std::vector<RsrPredecessor> predecessors; };

inline bool relax_rsr_cell(std::size_t candidate_cost,const RsrPredecessor& predecessor,
                           std::size_t& current_cost,RsrHistoryCell& history) {
    if (candidate_cost<current_cost) {
        current_cost=candidate_cost;
        history.predecessors.assign(1,predecessor);
        return true;
    }
    if (candidate_cost==current_cost &&
        std::find(history.predecessors.begin(),history.predecessors.end(),predecessor)==history.predecessors.end())
        history.predecessors.push_back(predecessor);
    return false;
}

inline std::vector<RepairCandidate> rsr_minimum_repairs(
    const Automaton& automaton,std::string_view input,
    std::size_t max_candidate_length=std::numeric_limits<std::size_t>::max(),
    std::size_t max_rsr_candidates=std::numeric_limits<std::size_t>::max(),
    RsrIterationMeasurement* measurement=nullptr) {
    if (!max_candidate_length || !max_rsr_candidates)
        throw std::invalid_argument("RSR candidate limits must be positive");
    const auto active_states=automaton.active_states();
    std::vector<RsrEdge> edges;
    for (StateId source:active_states)
        for (const auto& [symbol,destination]:automaton.state(source).transitions)
            edges.push_back({source,automaton.resolve(destination),symbol});
    const std::size_t edge_count=edges.size(),phi=edge_count,columns=edge_count+1;
    const std::size_t infinity=std::numeric_limits<std::size_t>::max()/4;
    std::vector<std::vector<std::size_t>> incoming(automaton.storage_size()),outgoing(automaton.storage_size());
    for (std::size_t edge=0;edge<edge_count;++edge) {
        incoming[edges[edge].destination].push_back(edge);
        outgoing[edges[edge].source].push_back(edge);
    }
    std::vector<std::vector<std::size_t>> previous_edges(edge_count),next_edges(edge_count);
    const StateId start=automaton.resolve(automaton.start_state());
    for (std::size_t edge=0;edge<edge_count;++edge) {
        previous_edges[edge]=incoming[edges[edge].source];
        next_edges[edge]=outgoing[edges[edge].destination];
        if (edges[edge].source==start) previous_edges[edge].push_back(phi);
    }
    const std::size_t rows=input.size()+1;
    std::vector costs(rows,std::vector<std::size_t>(columns,infinity));
    std::vector history(rows,std::vector<RsrHistoryCell>(columns));
    for (std::size_t row=0;row<rows;++row) {
        costs[row][phi]=row;
        if (row) history[row][phi].predecessors.push_back({row-1,phi,RsrOperation::deletion,0});
    }
    using QueueEntry=std::pair<std::size_t,std::size_t>;
    std::priority_queue<QueueEntry,std::vector<QueueEntry>,std::greater<>> queue;
    for (std::size_t edge=0;edge<edge_count;++edge) if (edges[edge].source==start) {
        relax_rsr_cell(1,{0,phi,RsrOperation::insertion,edges[edge].symbol},costs[0][edge],history[0][edge]);
        queue.push({1,edge});
    }
    while (!queue.empty()) {
        const auto [cost,edge]=queue.top(); queue.pop();
        if (cost!=costs[0][edge]) continue;
        for (std::size_t next:next_edges[edge])
            if (relax_rsr_cell(cost+1,{0,edge,RsrOperation::insertion,edges[next].symbol},costs[0][next],history[0][next]))
                queue.push({cost+1,next});
    }
    for (std::size_t row=1;row<rows;++row) {
        const Symbol input_symbol=static_cast<unsigned char>(input[row-1]);
        for (std::size_t edge=0;edge<edge_count;++edge) {
            if (costs[row-1][edge]!=infinity)
                relax_rsr_cell(costs[row-1][edge]+1,{row-1,edge,RsrOperation::deletion,0},costs[row][edge],history[row][edge]);
            for (std::size_t predecessor:previous_edges[edge]) {
                if (costs[row-1][predecessor]==infinity) continue;
                const bool match=edges[edge].symbol==input_symbol;
                relax_rsr_cell(costs[row-1][predecessor]+(match?0:1),
                    {row-1,predecessor,match?RsrOperation::match:RsrOperation::substitution,edges[edge].symbol},
                    costs[row][edge],history[row][edge]);
            }
        }
        while (!queue.empty()) queue.pop();
        for (std::size_t edge=0;edge<edge_count;++edge)
            if (costs[row][edge]!=infinity) queue.push({costs[row][edge],edge});
        while (!queue.empty()) {
            const auto [cost,edge]=queue.top(); queue.pop();
            if (cost!=costs[row][edge]) continue;
            for (std::size_t next:next_edges[edge])
                if (relax_rsr_cell(cost+1,{row,edge,RsrOperation::insertion,edges[next].symbol},costs[row][next],history[row][next]))
                    queue.push({cost+1,next});
        }
    }
    std::size_t minimum_cost=automaton.state(start).accepting?costs.back()[phi]:infinity;
    for (std::size_t edge=0;edge<edge_count;++edge)
        if (automaton.state(edges[edge].destination).accepting)
            minimum_cost=std::min(minimum_cost,costs.back()[edge]);
    if (minimum_cost==infinity) return {};
    std::vector<std::size_t> final_columns;
    if (automaton.state(start).accepting && costs.back()[phi]==minimum_cost) final_columns.push_back(phi);
    for (std::size_t edge=0;edge<edge_count;++edge)
        if (automaton.state(edges[edge].destination).accepting && costs.back()[edge]==minimum_cost)
            final_columns.push_back(edge);
    std::set<std::string> values;
    std::string reversed;
    const auto enumerate=[&](const auto& self,std::size_t row,std::size_t column)->void {
        if (values.size()>=max_rsr_candidates) return;
        if (row==0 && column==phi) {
            values.emplace(reversed.rbegin(),reversed.rend());
            return;
        }
        for (const auto& predecessor:history[row][column].predecessors) {
            const bool emits=predecessor.operation==RsrOperation::match || predecessor.operation==RsrOperation::insertion || predecessor.operation==RsrOperation::substitution;
            if (emits) {
                if (reversed.size()==max_candidate_length)
                    throw std::runtime_error("minimum-cost RSR candidate exceeds maximum candidate length");
                reversed.push_back(static_cast<char>(predecessor.symbol));
            }
            self(self,predecessor.previous_row,predecessor.previous_column);
            if (emits) reversed.pop_back();
            if (values.size()>=max_rsr_candidates) return;
        }
    };
    for (std::size_t column:final_columns) {
        enumerate(enumerate,input.size(),column);
        if (values.size()>=max_rsr_candidates) break;
    }
    std::vector<RepairCandidate> repairs;
    repairs.reserve(values.size());
    for (const auto& value:values) repairs.push_back({value,minimum_cost,0.0});
    if (measurement) {
        measurement->minimum_edit_cost=minimum_cost;
        measurement->unique_candidates=repairs.size();
        measurement->enumeration_complete=
            max_rsr_candidates==std::numeric_limits<std::size_t>::max() ||
            repairs.size()<max_rsr_candidates;
    }
    return repairs;
}

inline std::optional<RepairCandidate> rsr_repair(const Automaton& automaton,std::string_view input) {
    auto repairs=rsr_minimum_repairs(
        automaton,input,std::numeric_limits<std::size_t>::max(),1);
    if (repairs.empty()) return std::nullopt;
    return std::move(repairs.front());
}

inline bool reject_exact_string_in_place(Automaton& automaton,std::string_view value) {
    if (!automaton.accepts(value)) return false;
    const auto source_path=automaton.path(value);
    if (source_path.size()!=value.size()+1) throw std::runtime_error("accepted string has no complete DFA path");
    std::vector<StateId> prefix_states;
    prefix_states.reserve(source_path.size());
    for (std::size_t position=0;position<source_path.size();++position)
        prefix_states.push_back(automaton.add_state(position!=value.size() && automaton.state(source_path[position]).accepting));
    for (std::size_t position=0;position<source_path.size();++position) {
        auto& transitions=automaton.state(prefix_states[position]).transitions;
        for (const auto& [symbol,destination]:automaton.state(source_path[position]).transitions)
            transitions.emplace(symbol,automaton.resolve(destination));
        if (position<value.size()) transitions[static_cast<unsigned char>(value[position])]=prefix_states[position+1];
    }
    automaton.set_start_state(prefix_states.front());
    return true;
}
inline Automaton reject_exact_string(const Automaton& source,std::string_view value) {
    Automaton result=source; reject_exact_string_in_place(result,value); return result;
}

inline std::vector<RepairCandidate> rsr_repairs_in_place(
    Automaton& working,std::string_view input,const NGramModel& model,
    std::size_t ngrams_batch_size,std::size_t max_candidate_length,
    std::size_t max_rsr_candidates,std::size_t max_queue_size,
    const std::set<std::string>& excluded={},std::uint64_t* ngrams_execution_time_ns=nullptr,
    RsrIterationMeasurement* measurement=nullptr) {
    if (!ngrams_batch_size || !max_candidate_length || !max_rsr_candidates || !max_queue_size)
        throw std::invalid_argument("configured counts and resource limits must be positive");
    (void)max_queue_size;
    for (const auto& value:excluded) reject_exact_string_in_place(working,value);
    auto repairs=rsr_minimum_repairs(
        working,input,max_candidate_length,max_rsr_candidates,measurement);
    const auto started=std::chrono::steady_clock::now();
    for (auto& repair:repairs) repair.ngram_score=model.score(repair.value);
    std::sort(repairs.begin(),repairs.end(),[](const auto& left,const auto& right) {
        if (left.ngram_score!=right.ngram_score) return left.ngram_score>right.ngram_score;
        if (left.edit_distance!=right.edit_distance) return left.edit_distance<right.edit_distance;
        return left.value<right.value;
    });
    if (ngrams_execution_time_ns)
        *ngrams_execution_time_ns+=static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-started).count());
    if (ngrams_batch_size!=std::numeric_limits<std::size_t>::max() && repairs.size()>ngrams_batch_size)
        repairs.resize(ngrams_batch_size);
    if (measurement) measurement->candidates_after_ngrams=repairs.size();
    return repairs;
}
inline std::vector<RepairCandidate> rsr_repairs(
    const Automaton& automaton,std::string_view input,const NGramModel& model,
    std::size_t ngrams_batch_size,std::size_t max_candidate_length,
    std::size_t max_rsr_candidates,std::size_t max_queue_size,
    const std::set<std::string>& excluded={},std::uint64_t* ngrams_execution_time_ns=nullptr) {
    Automaton working=automaton;
    return rsr_repairs_in_place(working,input,model,ngrams_batch_size,max_candidate_length,
        max_rsr_candidates,max_queue_size,excluded,ngrams_execution_time_ns);
}
} // namespace gammamax
