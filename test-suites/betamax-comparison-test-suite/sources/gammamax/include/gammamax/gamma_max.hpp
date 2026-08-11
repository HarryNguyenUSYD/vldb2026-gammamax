#pragma once
#include "gammamax/merge_replay.hpp"
#include "gammamax/ngram.hpp"
#include "gammamax/pta.hpp"
#include "gammamax/rsr.hpp"
#include "gammamax/state_merge.hpp"
#include "gammamax/oracle.hpp"
#include <algorithm>
#include <chrono>
#include <set>
#include <stdexcept>

namespace gammamax {
inline std::uint64_t measurement_ns(std::chrono::steady_clock::time_point started) {
    return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now()-started).count());
}
inline std::string gamma_max(const InputData& input,const Config& config,Oracle& oracle,
                             AlgorithmMeasurements* measurements=nullptr) {
    AlgorithmMeasurements local_measurements;
    if (!measurements) measurements=&local_measurements;
    if (oracle.accepts(input.corrupt_string)) return input.corrupt_string;
    auto positives=input.positive_examples;
    std::sort(positives.begin(),positives.end());
    positives.erase(std::unique(positives.begin(),positives.end()),positives.end());
    std::set<std::string> known(input.negative_examples.begin(),input.negative_examples.end());
    known.insert(input.corrupt_string);
    for (const auto& p:positives) if (known.contains(p))
        throw std::runtime_error("the same example is labeled both positive and negative");
    const Automaton pta=build_pta(positives,config.max_states);
    auto stage_started=std::chrono::steady_clock::now();
    NGramModel model(positives,config.n,input.corrupt_string);
    measurements->ngrams_execution_time_ns+=measurement_ns(stage_started);
    stage_started=std::chrono::steady_clock::now();
    const KSignatures k_signatures=compute_k_signatures(pta,config.k);
    measurements->ktails_execution_time_ns+=measurement_ns(stage_started);
    MergeHistory history;
    std::set<std::string> fingerprints;
    for (std::size_t iteration=0;iteration<config.max_iterations;++iteration) {
        ++measurements->total_iterations;
        PartitionedDfa partition(pta);
        MergeHistory valid_history;
        if (iteration!=0) {
            stage_started=std::chrono::steady_clock::now();
            auto replay=replay_merges(pta,std::move(partition),known,history,
                                      k_signatures,measurements);
            const std::uint64_t replay_time=measurement_ns(stage_started);
            measurements->merge_replay_ns+=replay_time;
            measurements->edsm_execution_time_ns+=replay_time;
            partition=std::move(replay.partition);
            valid_history=std::move(replay.valid_history);
        }

        stage_started=std::chrono::steady_clock::now();
        auto merged=state_merge(pta,std::move(partition),known,k_signatures,
                                std::move(valid_history),measurements);
        const std::uint64_t merge_time=measurement_ns(stage_started);
        if (iteration==0)
            measurements->initial_state_merge_ns+=merge_time;
        else
            measurements->resumed_state_merge_ns+=merge_time;
        measurements->edsm_execution_time_ns+=merge_time;
        history=std::move(merged.history);
        Automaton working=merged.partition.materialize(pta);
        if (!fingerprints.insert(working.fingerprint()).second)
            throw std::runtime_error("grammar repeated without progress");

        stage_started=std::chrono::steady_clock::now();
        const std::uint64_t ngrams_before=measurements->ngrams_execution_time_ns;
        auto repairs=rsr_repairs_in_place(
            working,input.corrupt_string,model,config.rsr_batch_size,
            config.ngrams_batch_size,config.max_candidate_length,
            config.max_queue_size,known,
            &measurements->ngrams_execution_time_ns);
        const std::uint64_t combined_time=measurement_ns(stage_started);
        const std::uint64_t ngrams_time=
            measurements->ngrams_execution_time_ns-ngrams_before;
        measurements->rsr_execution_time_ns+=
            combined_time>=ngrams_time?combined_time-ngrams_time:0;
        if (repairs.empty())
            throw std::runtime_error("RSR produced no unseen repair candidates");
        bool rejected=false;
        for (const auto& repair:repairs) {
            if (!known.insert(repair.value).second) continue;
            if (oracle.accepts(repair.value)) return repair.value;
            rejected=true;
        }
        if (!rejected)
            throw std::runtime_error("RSR produced no queryable repair candidates");
    }
    throw std::runtime_error("maximum repair-iteration limit exhausted");
}
} // namespace gammamax

