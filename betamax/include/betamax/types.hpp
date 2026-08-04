#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace betamax {

using StateId = std::uint32_t;
using Symbol = unsigned char;

struct InputData {
    std::vector<std::string> positive_examples;
    std::vector<std::string> negative_examples;
    std::string corrupt_string;
};

struct Config {
    std::uint64_t seed{};
    std::filesystem::path oracle_executable;

    std::size_t target_negative_examples{};
    std::size_t neighborhood_max_oracle_calls{};
    std::size_t cross_merge_samples{};

    std::size_t candidate_count{};
    std::uint64_t match_cost{};
    std::uint64_t insertion_cost{};
    std::uint64_t deletion_cost{};
    std::uint64_t substitution_cost{};
    std::size_t max_candidate_length{};

    std::size_t max_iterations{};
    std::size_t max_total_oracle_calls{};
    std::size_t max_states{};
    std::size_t max_queue_size{};
};

struct MergeRecord {
    std::vector<StateId> red_original_states;
    std::vector<StateId> blue_original_states;
};
using MergeHistory = std::vector<MergeRecord>;

enum class EditKind : std::uint8_t {
    Start,
    Match,
    Insert,
    SigmaPlus,
    Substitute
};

struct RepairNode {
    StateId state{};
    std::size_t input_position{};
    std::uint64_t cost{};
    int predecessor{-1};
    EditKind edit{EditKind::Start};
    char emitted{};
};

struct RepairCandidate {
    std::string value;
    std::uint64_t cost{};
    std::string edit_order;
};

struct ProgramResult {
    std::string output_string;
    std::uint64_t peak_memory_bytes{};
    std::uint64_t total_execution_time_ns{};
};

}  // namespace betamax
