#pragma once
#include "gammamax/config.hpp"
#include "gammamax/k_tails.hpp"
#include "gammamax/merge_replay.hpp"
#include "gammamax/ngram.hpp"
#include "gammamax/oracle.hpp"
#include "gammamax/pta.hpp"
#include "gammamax/rsr.hpp"
#include "gammamax/state_merge.hpp"
#include <chrono>
#include <deque>
#include <limits>
#include <set>
#include <string>
#include <unordered_set>
#include <vector>

namespace gammamax {
using BatchClock=std::chrono::steady_clock;
using BatchDeadline=BatchClock::time_point;
inline void check_batch_deadline(BatchDeadline deadline) {
    if (BatchClock::now()>=deadline) throw std::runtime_error("cell timeout");
}

class NegativeFifo {
public:
    explicit NegativeFifo(std::size_t capacity):capacity_(capacity) {
        if (!capacity_) throw std::invalid_argument("negative capacity must be positive");
    }
    bool add(const std::string& value) {
        if (members_.contains(value)) return false;
        if (order_.size()==capacity_) { members_.erase(order_.front()); order_.pop_front(); }
        order_.push_back(value); members_.insert(value); return true;
    }
    std::set<std::string> values() const { return {order_.begin(),order_.end()}; }
    std::vector<std::string> ordered() const { return {order_.begin(),order_.end()}; }
    std::size_t size() const noexcept { return order_.size(); }
private:
    std::size_t capacity_;
    std::deque<std::string> order_;
    std::unordered_set<std::string> members_;
};

class BatchSession {
public:
    BatchSession(std::vector<std::string> positives,const Config& config,
                 AlgorithmMeasurements* measurements=nullptr)
        :config_(config),negatives_(config.negative_capacity),
         pta_(build_pta(positives,config.max_states)),
         model_(build_model(positives,config.n,measurements)),
         signatures_(build_signatures(pta_,config.k,measurements)),partition_(pta_) {
        auto started=BatchClock::now();
        auto merged=state_merge(pta_,std::move(partition_),{},signatures_,{},measurements);
        partition_=std::move(merged.partition); history_=std::move(merged.history);
        if (measurements) {
            auto ns=elapsed_ns(started); measurements->initial_state_merge_ns+=ns;
            measurements->edsm_execution_time_ns+=ns;
        }
    }

    std::string repair(const std::string& dirty,Oracle& oracle,BatchDeadline deadline,
                       AlgorithmMeasurements& measurements) {
        learn(dirty,deadline,measurements);
        std::set<std::string> fingerprints;
        for (std::size_t iteration=0;iteration<config_.max_iterations;++iteration) {
            check_batch_deadline(deadline); ++measurements.total_iterations;
            Automaton working=partition_.materialize(pta_);
            if (!fingerprints.insert(working.fingerprint()).second)
                throw std::runtime_error("grammar repeated without progress");
            auto started=BatchClock::now();
            const auto ngrams_before=measurements.ngrams_execution_time_ns;
            measurements.rsr_iterations.emplace_back();
            auto repairs=rsr_repairs_in_place(
                working,dirty,model_,config_.ngrams_batch_size,
                config_.max_candidate_length,config_.max_rsr_candidates,
                config_.max_queue_size,negatives_.values(),
                &measurements.ngrams_execution_time_ns,
                &measurements.rsr_iterations.back());
            const auto combined=elapsed_ns(started);
            const auto ngrams=measurements.ngrams_execution_time_ns-ngrams_before;
            measurements.rsr_execution_time_ns+=combined>=ngrams?combined-ngrams:0;
            check_batch_deadline(deadline);
            if (repairs.empty()) throw std::runtime_error("RSR produced no unseen repair candidates");
            bool queried=false;
            for (const auto& candidate:repairs) {
                if (negatives_.values().contains(candidate.value)) continue;
                queried=true; check_batch_deadline(deadline);
                if (oracle.accepts(candidate.value)) return candidate.value;
                learn(candidate.value,deadline,measurements);
            }
            if (!queried) throw std::runtime_error("RSR produced no queryable repair candidates");
        }
        throw std::runtime_error("maximum repair-iteration limit exhausted");
    }
    bool accepts_model(const std::string& value) const { return partition_.accepts(pta_,value); }
    std::size_t negative_count() const { return negatives_.size(); }
private:
    static std::uint64_t elapsed_ns(BatchClock::time_point started) {
        return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(BatchClock::now()-started).count());
    }
    static NGramModel build_model(const std::vector<std::string>& positives,std::size_t n,
                                  AlgorithmMeasurements* measurements) {
        auto started=BatchClock::now(); NGramModel result(positives,n);
        if (measurements) measurements->ngrams_execution_time_ns+=elapsed_ns(started);
        return result;
    }
    static KSignatures build_signatures(const Automaton& pta,std::size_t k,
                                        AlgorithmMeasurements* measurements) {
        auto started=BatchClock::now(); auto result=compute_k_signatures(pta,k);
        if (measurements) measurements->ktails_execution_time_ns+=elapsed_ns(started);
        return result;
    }
    void learn(const std::string& value,BatchDeadline deadline,AlgorithmMeasurements& measurements) {
        negatives_.add(value);
        if (partition_.accepts(pta_,value)) needs_rebuild_=true;
        if (!needs_rebuild_) return;
        check_batch_deadline(deadline);
        auto started=BatchClock::now();
        auto replay=replay_merges(pta_,PartitionedDfa(pta_),negatives_.values(),history_,signatures_,&measurements);
        auto replay_time=elapsed_ns(started);
        measurements.merge_replay_ns+=replay_time; measurements.edsm_execution_time_ns+=replay_time;
        check_batch_deadline(deadline);
        started=BatchClock::now();
        auto merged=state_merge(pta_,std::move(replay.partition),negatives_.values(),signatures_,
                                std::move(replay.valid_history),&measurements);
        auto merge_time=elapsed_ns(started);
        measurements.resumed_state_merge_ns+=merge_time; measurements.edsm_execution_time_ns+=merge_time;
        check_batch_deadline(deadline);
        partition_=std::move(merged.partition); history_=std::move(merged.history);
        needs_rebuild_=false;
    }
    Config config_;
    NegativeFifo negatives_;
    Automaton pta_;
    NGramModel model_;
    KSignatures signatures_;
    PartitionedDfa partition_;
    MergeHistory history_;
    bool needs_rebuild_{};
};
} // namespace gammamax
