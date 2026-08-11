#include "gammamax/gamma_max.hpp"
#include "gammamax/json_io.hpp"
#include "gammamax/memory.hpp"
#include "gammamax/oracle.hpp"

#include <chrono>
#include <cstdint>
#include <exception>
#include <iostream>
#include <random>

int main() {
    try {
        const gammamax::InputData input = gammamax::read_input_json("input.json");
        const gammamax::Config config = gammamax::read_config_json("config.json");
        const auto start = std::chrono::steady_clock::now();
        const std::uint64_t effective_seed = config.seed.value_or(
            (static_cast<std::uint64_t>(std::random_device{}()) << 32U) ^ std::random_device{}());
        gammamax::ExternalOracle oracle(config.oracle_executable,
                                       config.max_total_oracle_calls);
        gammamax::AlgorithmMeasurements measurements;
        const std::string repaired =
            gammamax::gamma_max(input, config, oracle, &measurements);
        const std::uint64_t peak_memory = gammamax::peak_memory_bytes();
        const auto end = std::chrono::steady_clock::now();
        const auto elapsed =
            std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
        if (elapsed < 0) {
            throw std::runtime_error("steady clock returned a negative duration");
        }

        const gammamax::ProgramResult result{repaired, effective_seed, peak_memory,
                                            static_cast<std::uint64_t>(elapsed),
                                            measurements};
        std::cout << gammamax::serialize_result(result) << '\n';
        if (!std::cout) {
            throw std::runtime_error("failed to write result JSON to stdout");
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "gammaMax: " << error.what() << '\n';
        return 1;
    } catch (...) {
        std::cerr << "gammaMax: unknown fatal error\n";
        return 1;
    }
}

