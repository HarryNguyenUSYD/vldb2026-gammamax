#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace gammamax {

using StateId = std::uint32_t;
using Symbol = unsigned char;

struct InputData {
    std::vector<std::string> positive_examples;
    std::vector<std::string> negative_examples;
    std::string corrupt_string;
};

struct Config {
    std::optional<std::uint64_t> seed;
    std::filesystem::path oracle_executable;
    std::size_t k{};
    std::size_t n{};
    std::size_t ngrams_batch_size{1};
    std::size_t max_candidate_length{};
    std::size_t max_iterations{};
    std::size_t max_total_oracle_calls{};
    std::size_t max_states{};
    std::size_t max_queue_size{};
    std::size_t max_rsr_candidates{};
    std::size_t negative_capacity{100};
    std::size_t max_positive_examples{200};
    std::size_t cell_timeout_seconds{60};
};

struct MergeRecord {
    std::vector<StateId> red_original_states;
    std::vector<StateId> blue_original_states;
};
using MergeHistory = std::vector<MergeRecord>;

struct RepairCandidate {
    std::string value;
    std::size_t edit_distance{};
    double ngram_score{};
};

struct RsrIterationMeasurement {
    std::size_t minimum_edit_cost{};
    std::size_t unique_candidates{};
    std::size_t candidates_after_ngrams{};
    bool enumeration_complete{};
};

struct AlgorithmMeasurements {
    std::uint64_t rsr_execution_time_ns{};
    std::uint64_t ktails_execution_time_ns{};
    std::uint64_t edsm_execution_time_ns{};
    std::uint64_t ngrams_execution_time_ns{};
    std::uint64_t initial_state_merge_ns{};
    std::uint64_t merge_replay_ns{};
    std::uint64_t resumed_state_merge_ns{};
    std::uint64_t candidate_copy_or_rollback_ns{};
    std::uint64_t negative_validation_ns{};
    std::uint64_t total_iterations{};
    std::vector<RsrIterationMeasurement> rsr_iterations;
};

struct ProgramResult {
    std::string output_string;
    std::uint64_t effective_seed{};
    std::uint64_t peak_memory_bytes{};
    std::uint64_t total_execution_time_ns{};
    AlgorithmMeasurements measurements;
};

}  // namespace gammamax
