#include "gammamax/batch_session.hpp"
#include "gammamax/json_io.hpp"
#include "gammamax/memory.hpp"
#include "gammamax/oracle.hpp"

#include <chrono>
#include <cstdint>
#include <exception>
#include <iostream>
#include <random>

#include <nlohmann/json.hpp>

namespace {

nlohmann::json measurements_json(const gammamax::AlgorithmMeasurements& value) {
    return {
        {"rsr_execution_time_ns", value.rsr_execution_time_ns},
        {"ktails_execution_time_ns", value.ktails_execution_time_ns},
        {"edsm_execution_time_ns", value.edsm_execution_time_ns},
        {"ngrams_execution_time_ns", value.ngrams_execution_time_ns},
        {"initial_state_merge_ns", value.initial_state_merge_ns},
        {"merge_replay_ns", value.merge_replay_ns},
        {"resumed_state_merge_ns", value.resumed_state_merge_ns},
        {"candidate_copy_or_rollback_ns", value.candidate_copy_or_rollback_ns},
        {"negative_validation_ns", value.negative_validation_ns},
        {"total_iterations", value.total_iterations},
    };
}

}  // namespace

int main() {
    try {
        const auto input = gammamax::read_batch_input_json("input.json");
        const auto config = gammamax::read_config_json("config.json");
        const auto process_started = std::chrono::steady_clock::now();
        const std::uint64_t effective_seed = config.seed.value_or(
            (static_cast<std::uint64_t>(std::random_device{}()) << 32U) ^
            std::random_device{}());
        gammamax::ExternalOracle oracle(config.oracle_executable,
                                        config.max_total_oracle_calls);
        std::vector<std::string> positive_examples;
        std::vector<std::string> corrupt_strings;
        std::vector<std::size_t> corrupt_indices;
        positive_examples.reserve(input.cells.size());
        corrupt_strings.reserve(input.cells.size());
        const auto scan_started = std::chrono::steady_clock::now();
        for (std::size_t cell_index = 0; cell_index < input.cells.size(); ++cell_index) {
            const auto& cell = input.cells[cell_index];
            if (oracle.accepts(cell)) positive_examples.push_back(cell);
            else {
                corrupt_strings.push_back(cell);
                corrupt_indices.push_back(cell_index);
            }
        }
        const auto scan_elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now() - scan_started).count();
        if (scan_elapsed < 0)
            throw std::runtime_error("steady clock returned negative duration");
        if (positive_examples.empty())
            throw std::runtime_error("oracle rejected every cell; no positive examples available");
        gammamax::BatchSession session(positive_examples, corrupt_strings, config);

        nlohmann::json results = nlohmann::json::array();
        for (std::size_t corrupt_index = 0;
             corrupt_index < corrupt_strings.size(); ++corrupt_index) {
            const auto& corrupt = corrupt_strings[corrupt_index];
            gammamax::AlgorithmMeasurements measurements;
            std::uint64_t repair_time_ns = 0;
            nlohmann::json result;
            result["input_string"] = corrupt;
            result["cell_index"] = corrupt_indices[corrupt_index];
            result["output_string"] = nullptr;
            result["timed_out"] = false;
            result["error"] = nullptr;
            try {
                result["output_string"] =
                    session.repair(corrupt, oracle, measurements, repair_time_ns, true);
            } catch (const gammamax::CellTimeout& error) {
                result["timed_out"] = true;
                result["error"] = error.what();
            } catch (const std::exception& error) {
                result["error"] = error.what();
            }
            result["repair_time_ns"] = repair_time_ns;
            result["measurements"] = measurements_json(measurements);
            results.push_back(std::move(result));
        }

        const auto& shared = session.shared_measurements();
        const auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now() - process_started).count();
        if (elapsed < 0) throw std::runtime_error("steady clock returned negative duration");
        nlohmann::json output = {
            {"effective_seed", effective_seed},
            {"peak_memory_bytes", gammamax::peak_memory_bytes()},
            {"total_execution_time_ns", static_cast<std::uint64_t>(elapsed)},
            {"oracle_scan", {
                {"execution_time_ns", static_cast<std::uint64_t>(scan_elapsed)},
                {"cell_count", input.cells.size()},
                {"positive_count", positive_examples.size()},
                {"corrupt_count", corrupt_strings.size()},
            }},
            {"shared_preprocessing", {
                {"deduplication_time_ns", shared.deduplication_time_ns},
                {"pta_build_time_ns", shared.pta_build_time_ns},
                {"ktails_preprocessing_time_ns", shared.ktails_preprocessing_time_ns},
                {"input_positive_count", shared.input_positive_count},
                {"unique_positive_count", shared.unique_positive_count},
                {"used_positive_count", shared.used_positive_count},
                {"ignored_positive_count", shared.ignored_positive_count},
                {"pta_state_count", shared.pta_state_count},
            }},
            {"results", std::move(results)},
        };
        std::cout << output.dump() << '\n';
        return std::cout ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << "gammaMax: " << error.what() << '\n';
        return 1;
    } catch (...) {
        std::cerr << "gammaMax: unknown fatal error\n";
        return 1;
    }
}
