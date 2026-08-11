#pragma once

#include "gammamax/automaton.hpp"
#include "gammamax/ngram.hpp"
#include "gammamax/types.hpp"

#include <algorithm>
#include <chrono>
#include <limits>
#include <map>
#include <optional>
#include <queue>
#include <set>
#include <stdexcept>
#include <tuple>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace gammamax {

struct RsrEdge { StateId source{},destination{}; Symbol symbol{}; };
enum class RsrOperation : unsigned char { none,match,deletion,insertion,substitution };
struct RsrHistoryCell {
    std::size_t previous_row{},previous_column{};
    RsrOperation operation{RsrOperation::none}; Symbol symbol{}; bool present{};
};

inline std::optional<RepairCandidate> rsr_repair(const Automaton& automaton,
                                                  std::string_view input) {
    const auto active_states=automaton.active_states();
    std::vector<RsrEdge> edges;
    for (StateId source:active_states)
        for (const auto& [symbol,destination]:automaton.state(source).transitions)
            edges.push_back({source,automaton.resolve(destination),symbol});
    const std::size_t edge_count=edges.size(),phi=edge_count,columns=edge_count+1;
    const std::size_t infinity=std::numeric_limits<std::size_t>::max()/4;

    // Algorithm 1 needs PRE/NEXT edge relations. Indexing edges by endpoint
    // builds exactly those relations without comparing every edge pair.
    std::vector<std::vector<std::size_t>> incoming(automaton.storage_size()),
                                                  outgoing(automaton.storage_size());
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
    std::vector<std::vector<std::size_t>> costs(rows,std::vector<std::size_t>(columns,infinity));
    std::vector<std::vector<RsrHistoryCell>> history(rows,std::vector<RsrHistoryCell>(columns));
    for (std::size_t row=0;row<rows;++row) {
        costs[row][phi]=row;
        if (row) history[row][phi]={row-1,phi,RsrOperation::deletion,0,true};
    }

    using QueueEntry=std::pair<std::size_t,std::size_t>;
    std::priority_queue<QueueEntry,std::vector<QueueEntry>,std::greater<>> queue;
    for (std::size_t edge=0;edge<edge_count;++edge) {
        if (edges[edge].source!=start) continue;
        costs[0][edge]=1;
        history[0][edge]={0,phi,RsrOperation::insertion,edges[edge].symbol,true};
        queue.push({1,edge});
    }
    while (!queue.empty()) {
        const auto [cost,edge]=queue.top(); queue.pop();
        if (cost!=costs[0][edge]) continue;
        for (std::size_t next:next_edges[edge]) {
            if (cost+1>=costs[0][next]) continue;
            costs[0][next]=cost+1;
            history[0][next]={0,edge,RsrOperation::insertion,edges[next].symbol,true};
            queue.push({cost+1,next});
        }
    }

    for (std::size_t row=1;row<rows;++row) {
        const Symbol input_symbol=static_cast<unsigned char>(input[row-1]);
        for (std::size_t edge=0;edge<edge_count;++edge) {
            std::size_t predecessor=phi,predecessor_cost=infinity;
            for (std::size_t candidate:previous_edges[edge]) {
                if (costs[row-1][candidate]<predecessor_cost) {
                    predecessor=candidate; predecessor_cost=costs[row-1][candidate];
                }
            }
            if (edges[edge].symbol==input_symbol) {
                if (predecessor_cost==infinity) continue;
                costs[row][edge]=predecessor_cost;
                history[row][edge]={row-1,predecessor,RsrOperation::match,
                                    edges[edge].symbol,true};
            } else {
                const std::size_t deletion_cost=costs[row-1][edge];
                if (predecessor_cost<=deletion_cost && predecessor_cost!=infinity) {
                    costs[row][edge]=predecessor_cost+1;
                    history[row][edge]={row-1,predecessor,RsrOperation::substitution,
                                        edges[edge].symbol,true};
                } else if (deletion_cost!=infinity) {
                    costs[row][edge]=deletion_cost+1;
                    history[row][edge]={row-1,edge,RsrOperation::deletion,0,true};
                }
            }
        }
        while (!queue.empty()) queue.pop();
        for (std::size_t edge=0;edge<edge_count;++edge)
            if (costs[row][edge]!=infinity) queue.push({costs[row][edge],edge});
        while (!queue.empty()) {
            const auto [cost,edge]=queue.top(); queue.pop();
            if (cost!=costs[row][edge]) continue;
            for (std::size_t next:next_edges[edge]) {
                if (cost+1>=costs[row][next]) continue;
                costs[row][next]=cost+1;
                history[row][next]={row,edge,RsrOperation::insertion,
                                    edges[next].symbol,true};
                queue.push({cost+1,next});
            }
        }
    }

    std::size_t final_column=phi;
    std::size_t final_cost=automaton.state(start).accepting?costs.back()[phi]:infinity;
    for (std::size_t edge=0;edge<edge_count;++edge) {
        if (!automaton.state(edges[edge].destination).accepting) continue;
        if (costs.back()[edge]<final_cost) {
            final_cost=costs.back()[edge]; final_column=edge;
        }
    }
    if (final_cost==infinity) return std::nullopt;
    std::string reversed;
    std::size_t row=input.size(),column=final_column;
    while (row!=0 || column!=phi) {
        const auto& cell=history[row][column];
        if (!cell.present) return std::nullopt;
        if (cell.operation==RsrOperation::match || cell.operation==RsrOperation::insertion ||
            cell.operation==RsrOperation::substitution)
            reversed.push_back(static_cast<char>(cell.symbol));
        row=cell.previous_row; column=cell.previous_column;
    }
    std::reverse(reversed.begin(),reversed.end());
    return RepairCandidate{std::move(reversed),final_cost,0.0};
}


// Remove exactly `value` from a DFA in place. Prefix states remember that
// input still equals value; any mismatch falls back to the old DFA path.
inline bool reject_exact_string_in_place(Automaton& automaton,
                                         std::string_view value) {
    if (!automaton.accepts(value)) return false;

    const std::vector<StateId> source_path=automaton.path(value);
    if (source_path.size()!=value.size()+1)
        throw std::runtime_error("accepted string has no complete DFA path");

    std::vector<StateId> prefix_states;
    prefix_states.reserve(source_path.size());
    for (std::size_t position=0;position<source_path.size();++position) {
        const bool accepting=position!=value.size() &&
                             automaton.state(source_path[position]).accepting;
        prefix_states.push_back(automaton.add_state(accepting));
    }

    for (std::size_t position=0;position<source_path.size();++position) {
        auto& transitions=automaton.state(prefix_states[position]).transitions;
        for (const auto& [symbol,destination]:
             automaton.state(source_path[position]).transitions)
            transitions.emplace(symbol,automaton.resolve(destination));
        if (position<value.size())
            transitions[static_cast<unsigned char>(value[position])]=
                prefix_states[position+1];
    }
    automaton.set_start_state(prefix_states.front());
    return true;
}

// Compatibility wrapper returning a modified copy.
// Return a DFA whose language is source's language minus exactly `value`.
// Prefix states remember that input still equals value; any mismatch falls
// back to the corresponding source state and preserves source behavior.
inline Automaton reject_exact_string(const Automaton& source,
                                     std::string_view value) {
    Automaton result=source;
    reject_exact_string_in_place(result,value);
    return result;
}

// Run paper-style single-result C/H RSR repeatedly on a disposable DFA.
// Exclusions modify that DFA in place.
inline std::vector<RepairCandidate> rsr_repairs_in_place(
    Automaton& working, std::string_view input,
    const NGramModel& model, std::size_t rsr_batch_size,
    std::size_t ngrams_batch_size, std::size_t max_candidate_length,
    std::size_t max_queue_size, const std::set<std::string>& excluded = {},
    std::uint64_t* ngrams_execution_time_ns = nullptr) {
    if (!rsr_batch_size || !ngrams_batch_size ||
        ngrams_batch_size>rsr_batch_size || !max_queue_size)
        throw std::invalid_argument(
            "RSR and n-gram batch sizes must be positive, and n-gram batch size must not exceed RSR batch size");

    (void)max_queue_size; // C/H RSR has matrix-bounded storage, not an A* queue cap.
    for (const auto& value:excluded)
        reject_exact_string_in_place(working,value);

    std::vector<RepairCandidate> repairs;
    repairs.reserve(rsr_batch_size);
    for (std::size_t run=0;run<rsr_batch_size;++run) {
        auto repair=rsr_repair(working,input);
        if (!repair) break;
        if (repair->value.size()>max_candidate_length)
            throw std::runtime_error("single-result RSR candidate exceeds maximum candidate length");

        const auto ngram_started=std::chrono::steady_clock::now();
        repair->ngram_score=model.score(repair->value);
        if (ngrams_execution_time_ns)
            *ngrams_execution_time_ns+=static_cast<std::uint64_t>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(
                    std::chrono::steady_clock::now()-ngram_started).count());

        repairs.push_back(std::move(*repair));
        if (run+1<rsr_batch_size)
            reject_exact_string_in_place(working,repairs.back().value);
    }

    const auto ranking_started=std::chrono::steady_clock::now();
    std::sort(repairs.begin(),repairs.end(),[](const auto& left,const auto& right) {
        if (left.ngram_score!=right.ngram_score)
            return left.ngram_score>right.ngram_score;
        if (left.edit_distance!=right.edit_distance)
            return left.edit_distance<right.edit_distance;
        return left.value<right.value;
    });
    if (ngrams_execution_time_ns)
        *ngrams_execution_time_ns+=static_cast<std::uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::steady_clock::now()-ranking_started).count());
    if (repairs.size()>ngrams_batch_size) repairs.resize(ngrams_batch_size);
    return repairs;
}

// Compatibility wrapper for callers that need to preserve their DFA.
inline std::vector<RepairCandidate> rsr_repairs(
    const Automaton& automaton, std::string_view input,
    const NGramModel& model, std::size_t rsr_batch_size,
    std::size_t ngrams_batch_size, std::size_t max_candidate_length,
    std::size_t max_queue_size, const std::set<std::string>& excluded = {},
    std::uint64_t* ngrams_execution_time_ns = nullptr) {
    Automaton working=automaton;
    return rsr_repairs_in_place(
        working,input,model,rsr_batch_size,ngrams_batch_size,
        max_candidate_length,max_queue_size,excluded,
        ngrams_execution_time_ns);
}

} // namespace gammamax

