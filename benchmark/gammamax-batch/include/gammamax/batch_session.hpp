#pragma once

#include "gammamax/gamma_max.hpp"

#include <chrono>
#include <functional>
#include <set>
#include <stdexcept>

namespace gammamax {

class CellTimeout final : public std::runtime_error {
public:
    CellTimeout() : std::runtime_error("cell repair exceeded its time limit") {}
};

struct SharedMeasurements {
    std::uint64_t deduplication_time_ns{};
    std::uint64_t pta_build_time_ns{};
    std::uint64_t ktails_preprocessing_time_ns{};
    std::size_t input_positive_count{};
    std::size_t unique_positive_count{};
    std::size_t used_positive_count{};
    std::size_t ignored_positive_count{};
    std::size_t pta_state_count{};
};

class BatchSession {
public:
    using Clock = std::chrono::steady_clock;
    using NowFunction = std::function<Clock::time_point()>;

    BatchSession(std::vector<std::string> positives,
                 const std::vector<std::string>& negatives,
                 const Config& config,
                 NowFunction now = [] { return Clock::now(); })
        : config_(config), known_(negatives.begin(), negatives.end()),
          now_(std::move(now)) {
        shared_.input_positive_count = positives.size();
        auto started = std::chrono::steady_clock::now();
        std::sort(positives.begin(), positives.end());
        positives.erase(std::unique(positives.begin(), positives.end()), positives.end());
        shared_.deduplication_time_ns = measurement_ns(started);
        shared_.unique_positive_count = positives.size();
        if (positives.size() > config_.max_positive_examples)
            positives.resize(config_.max_positive_examples);
        shared_.used_positive_count = positives.size();
        shared_.ignored_positive_count =
            shared_.unique_positive_count - shared_.used_positive_count;
        positives_ = std::move(positives);
        for (const auto& positive : positives_)
            if (known_.contains(positive))
                throw std::runtime_error("the same example is labeled both positive and negative");

        started = std::chrono::steady_clock::now();
        pta_ = build_pta(positives_, config_.max_states);
        shared_.pta_build_time_ns = measurement_ns(started);
        shared_.pta_state_count = pta_.storage_size();
        started = std::chrono::steady_clock::now();
        signatures_ = compute_k_signatures(pta_, config_.k);
        shared_.ktails_preprocessing_time_ns = measurement_ns(started);
    }

    const SharedMeasurements& shared_measurements() const noexcept { return shared_; }

    std::string repair(const std::string& corrupt, Oracle& oracle,
                       AlgorithmMeasurements& measurements,
                       std::uint64_t& repair_time_ns,
                       bool already_rejected = false) {
        // N-gram construction is deliberately outside the per-cell timeout.
        auto stage_started = std::chrono::steady_clock::now();
        NGramModel model(positives_, config_.n, corrupt);
        measurements.ngrams_execution_time_ns += measurement_ns(stage_started);

        const auto repair_started = std::chrono::steady_clock::now();
        const auto deadline = now_() +
            std::chrono::seconds(config_.cell_timeout_seconds);
        const std::function<void()> check = [this, deadline] {
            if (now_() >= deadline) throw CellTimeout();
        };
        const auto finish = [&] { repair_time_ns = measurement_ns(repair_started); };

        try {
            check();
            if (!already_rejected && oracle.accepts(corrupt)) { finish(); return corrupt; }
            known_.insert(corrupt);
            for (const auto& positive : positives_)
                if (known_.contains(positive))
                    throw std::runtime_error("the same example is labeled both positive and negative");

            std::set<std::string> fingerprints;
            for (std::size_t iteration = 0; iteration < config_.max_iterations; ++iteration) {
                check();
                ++measurements.total_iterations;
                PartitionedDfa partition(pta_);
                MergeHistory valid_history;
                if (!history_.empty()) {
                    stage_started = std::chrono::steady_clock::now();
                    auto replay = replay_merges(pta_, std::move(partition), known_, history_,
                                                signatures_, &measurements, check);
                    const auto elapsed = measurement_ns(stage_started);
                    measurements.merge_replay_ns += elapsed;
                    measurements.edsm_execution_time_ns += elapsed;
                    partition = std::move(replay.partition);
                    valid_history = std::move(replay.valid_history);
                }

                stage_started = std::chrono::steady_clock::now();
                auto merged = state_merge(pta_, std::move(partition), known_, signatures_,
                                          std::move(valid_history), &measurements, check);
                const auto merge_time = measurement_ns(stage_started);
                if (history_.empty()) measurements.initial_state_merge_ns += merge_time;
                else measurements.resumed_state_merge_ns += merge_time;
                measurements.edsm_execution_time_ns += merge_time;
                history_ = merged.history;  // Fully committed state survives later timeout.
                Automaton working = merged.partition.materialize(pta_);
                if (!fingerprints.insert(working.fingerprint()).second)
                    throw std::runtime_error("grammar repeated without progress");

                stage_started = std::chrono::steady_clock::now();
                const auto ngrams_before = measurements.ngrams_execution_time_ns;
                auto repairs = rsr_repairs_in_place(
                    working, corrupt, model, config_.rsr_batch_size,
                    config_.ngrams_batch_size, config_.max_candidate_length,
                    config_.max_queue_size, known_,
                    &measurements.ngrams_execution_time_ns, check);
                const auto combined = measurement_ns(stage_started);
                const auto ngrams = measurements.ngrams_execution_time_ns - ngrams_before;
                measurements.rsr_execution_time_ns += combined >= ngrams ? combined - ngrams : 0;
                if (repairs.empty())
                    throw std::runtime_error("RSR produced no unseen repair candidates");
                bool rejected = false;
                for (const auto& candidate : repairs) {
                    check();
                    if (known_.contains(candidate.value)) continue;
                    if (oracle.accepts(candidate.value)) { finish(); return candidate.value; }
                    known_.insert(candidate.value);
                    rejected = true;
                }
                if (!rejected)
                    throw std::runtime_error("RSR produced no queryable repair candidates");
            }
            throw std::runtime_error("maximum repair-iteration limit exhausted");
        } catch (...) {
            finish();
            throw;
        }
    }

private:
    Config config_;
    std::vector<std::string> positives_;
    Automaton pta_;
    KSignatures signatures_;
    std::set<std::string> known_;
    MergeHistory history_;
    SharedMeasurements shared_;
    NowFunction now_;
};

}  // namespace gammamax
