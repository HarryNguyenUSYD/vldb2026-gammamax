#pragma once

#include "betamax/types.hpp"

#include <limits>
#include <stdexcept>
#include <string>

#include <nlohmann/json.hpp>

namespace betamax {

inline void require_exact_keys(const nlohmann::json& value,
                               std::initializer_list<const char*> keys,
                               const std::string& context) {
    if (!value.is_object()) {
        throw std::runtime_error(context + " must be a JSON object");
    }
    if (value.size() != keys.size()) {
        throw std::runtime_error(context + " has missing or unknown fields");
    }
    for (const char* key : keys) {
        if (!value.contains(key)) {
            throw std::runtime_error(context + " is missing field '" + key + "'");
        }
    }
}

template <typename T>
inline T required_unsigned(const nlohmann::json& object, const char* key,
                           const std::string& context) {
    const auto& value = object.at(key);
    if (!value.is_number_unsigned()) {
        throw std::runtime_error(context + "." + key + " must be an unsigned integer");
    }
    const auto raw = value.get<std::uint64_t>();
    if (raw > static_cast<std::uint64_t>(std::numeric_limits<T>::max())) {
        throw std::runtime_error(context + "." + key + " is out of range");
    }
    return static_cast<T>(raw);
}

template <typename T>
inline T required_boundary(const nlohmann::json& object, const char* key,
                           const std::string& context) {
    const auto& value = object.at(key);
    if (value.is_number_integer() && !value.is_number_unsigned()) {
        const auto raw = value.get<std::int64_t>();
        if (raw == -1) {
            return std::numeric_limits<T>::max();
        }
        if (raw < 0) {
            throw std::runtime_error(context + "." + key +
                                     " must be a non-negative integer or -1");
        }
        if (static_cast<std::uint64_t>(raw) >
            static_cast<std::uint64_t>(std::numeric_limits<T>::max())) {
            throw std::runtime_error(context + "." + key + " is out of range");
        }
        return static_cast<T>(raw);
    }
    if (!value.is_number_unsigned()) {
        throw std::runtime_error(context + "." + key +
                                 " must be a non-negative integer or -1");
    }
    const auto raw = value.get<std::uint64_t>();
    if (raw > static_cast<std::uint64_t>(std::numeric_limits<T>::max())) {
        throw std::runtime_error(context + "." + key + " is out of range");
    }
    return static_cast<T>(raw);
}

inline Config parse_config_value(const nlohmann::json& root) {
    require_exact_keys(root,
                       {"seed", "oracle", "neighborhood_exploration", "state_merging",
                        "repair", "limits"},
                       "config");

    const auto& oracle = root.at("oracle");
    const auto& ne = root.at("neighborhood_exploration");
    const auto& merging = root.at("state_merging");
    const auto& repair = root.at("repair");
    const auto& limits = root.at("limits");
    require_exact_keys(oracle, {"executable"}, "config.oracle");
    require_exact_keys(ne, {"target_negative_examples", "max_oracle_calls"},
                       "config.neighborhood_exploration");
    require_exact_keys(merging, {"cross_merge_samples"}, "config.state_merging");
    require_exact_keys(repair,
                       {"candidate_count", "match_cost", "insertion_cost", "deletion_cost",
                        "substitution_cost", "max_candidate_length"},
                       "config.repair");
    require_exact_keys(limits,
                       {"max_iterations", "max_total_oracle_calls", "max_states",
                        "max_queue_size"},
                       "config.limits");
    if (!oracle.at("executable").is_string() ||
        oracle.at("executable").get_ref<const std::string&>().empty()) {
        throw std::runtime_error("config.oracle.executable must be a non-empty string");
    }

    Config result;
    result.seed = required_unsigned<std::uint64_t>(root, "seed", "config");
    const auto executable_text = oracle.at("executable").get<std::string>();
    const std::u8string executable_utf8(
        reinterpret_cast<const char8_t*>(executable_text.data()), executable_text.size());
    result.oracle_executable = std::filesystem::path(executable_utf8);
    result.target_negative_examples =
        required_unsigned<std::size_t>(ne, "target_negative_examples",
                                       "config.neighborhood_exploration");
    result.neighborhood_max_oracle_calls =
        required_boundary<std::size_t>(ne, "max_oracle_calls",
                                       "config.neighborhood_exploration");
    result.cross_merge_samples =
        required_unsigned<std::size_t>(merging, "cross_merge_samples", "config.state_merging");
    result.candidate_count =
        required_unsigned<std::size_t>(repair, "candidate_count", "config.repair");
    result.match_cost = required_unsigned<std::uint64_t>(repair, "match_cost", "config.repair");
    result.insertion_cost =
        required_unsigned<std::uint64_t>(repair, "insertion_cost", "config.repair");
    result.deletion_cost =
        required_unsigned<std::uint64_t>(repair, "deletion_cost", "config.repair");
    result.substitution_cost =
        required_unsigned<std::uint64_t>(repair, "substitution_cost", "config.repair");
    result.max_candidate_length =
        required_boundary<std::size_t>(repair, "max_candidate_length", "config.repair");
    result.max_iterations =
        required_boundary<std::size_t>(limits, "max_iterations", "config.limits");
    result.max_total_oracle_calls =
        required_boundary<std::size_t>(limits, "max_total_oracle_calls", "config.limits");
    result.max_states = required_boundary<std::size_t>(limits, "max_states", "config.limits");
    result.max_queue_size =
        required_boundary<std::size_t>(limits, "max_queue_size", "config.limits");

    if (result.cross_merge_samples == 0 || result.candidate_count == 0 ||
        result.max_iterations == 0 || result.max_total_oracle_calls == 0 ||
        result.max_states == 0 || result.max_queue_size == 0) {
        throw std::runtime_error("configured counts and resource limits must be positive");
    }
    if (result.candidate_count != 1) {
        throw std::runtime_error("config.repair.candidate_count must be 1");
    }
    if (result.match_cost != 0 || result.insertion_cost == 0 ||
        result.deletion_cost == 0 || result.substitution_cost == 0) {
        throw std::runtime_error(
            "covering grammar requires zero match cost and positive error costs");
    }
    return result;
}

}  // namespace betamax
