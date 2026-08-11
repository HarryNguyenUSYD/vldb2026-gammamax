#pragma once

#include "gammamax/config.hpp"
#include "gammamax/types.hpp"

#include <fstream>
#include <stdexcept>
#include <string>

#include <nlohmann/json.hpp>

namespace gammamax {

inline nlohmann::json read_json_file(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        throw std::runtime_error("cannot open " + path.string());
    }
    nlohmann::json result;
    try {
        stream >> result;
    } catch (const nlohmann::json::exception& error) {
        throw std::runtime_error("invalid JSON in " + path.string() + ": " + error.what());
    }
    return result;
}

inline bool is_ascii(const std::string& value) {
    for (unsigned char byte : value) {
        if (byte > 0x7fU) {
            return false;
        }
    }
    return true;
}

inline std::vector<std::string> parse_string_array(const nlohmann::json& value,
                                                   const std::string& context) {
    if (!value.is_array()) {
        throw std::runtime_error(context + " must be an array");
    }
    std::vector<std::string> result;
    result.reserve(value.size());
    for (const auto& item : value) {
        if (!item.is_string()) {
            throw std::runtime_error(context + " must contain only strings");
        }
        auto text = item.get<std::string>();
        if (!is_ascii(text)) {
            throw std::runtime_error(context + " contains a non-ASCII string");
        }
        result.push_back(std::move(text));
    }
    return result;
}

inline InputData parse_input_value(const nlohmann::json& root) {
    require_object(root, "input");
    if (!root.contains("positive_examples") || !root.contains("corrupt_string")) {
        throw std::runtime_error("input requires positive_examples and corrupt_string");
    }
    if (!root.at("corrupt_string").is_string()) {
        throw std::runtime_error("input.corrupt_string must be a string");
    }
    InputData result;
    result.positive_examples =
        parse_string_array(root.at("positive_examples"), "input.positive_examples");
    if (root.contains("negative_examples")) result.negative_examples =
        parse_string_array(root.at("negative_examples"), "input.negative_examples");
    result.corrupt_string = root.at("corrupt_string").get<std::string>();
    if (!is_ascii(result.corrupt_string)) {
        throw std::runtime_error("input.corrupt_string must be ASCII");
    }
    if (result.positive_examples.empty()) {
        throw std::runtime_error("input.positive_examples must not be empty");
    }
    return result;
}

inline InputData read_input_json(const std::filesystem::path& path) {
    return parse_input_value(read_json_file(path));
}

inline Config read_config_json(const std::filesystem::path& path) {
    return parse_config_value(read_json_file(path));
}

inline std::string serialize_result(const ProgramResult& result) {
    nlohmann::json output = {
        {"output_string", result.output_string},
        {"effective_seed", result.effective_seed},
        {"peak_memory_bytes", result.peak_memory_bytes},
        {"total_execution_time_ns", result.total_execution_time_ns},
        {"rsr_execution_time_ns", result.measurements.rsr_execution_time_ns},
        {"ktails_execution_time_ns", result.measurements.ktails_execution_time_ns},
        {"edsm_execution_time_ns", result.measurements.edsm_execution_time_ns},
        {"ngrams_execution_time_ns", result.measurements.ngrams_execution_time_ns},
        {"initial_state_merge_ns", result.measurements.initial_state_merge_ns},
        {"merge_replay_ns", result.measurements.merge_replay_ns},
        {"resumed_state_merge_ns", result.measurements.resumed_state_merge_ns},
        {"candidate_copy_or_rollback_ns", result.measurements.candidate_copy_or_rollback_ns},
        {"negative_validation_ns", result.measurements.negative_validation_ns},
        {"total_iterations", result.measurements.total_iterations},
    };
    return output.dump();
}

}  // namespace gammamax
