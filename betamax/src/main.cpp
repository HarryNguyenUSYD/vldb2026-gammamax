#include "betamax/beta_max.hpp"
#include "betamax/json_io.hpp"
#include "betamax/memory.hpp"
#include "betamax/oracle.hpp"
#include "betamax/random.hpp"

#include <chrono>
#include <cstdint>
#include <exception>
#include <iostream>

int main() {
    try {
        const betamax::InputData input = betamax::read_input_json("input.json");
        const betamax::Config config = betamax::read_config_json("config.json");

        const auto start = std::chrono::steady_clock::now();
        betamax::Random random(config.seed);
        betamax::ExternalOracle oracle(config.oracle_executable,
                                       config.max_total_oracle_calls);
        const std::string repaired =
            betamax::beta_max(input, config, oracle, random.engine());
        const std::uint64_t peak_memory = betamax::peak_memory_bytes();
        const auto end = std::chrono::steady_clock::now();
        const auto elapsed =
            std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
        if (elapsed < 0) {
            throw std::runtime_error("steady clock returned a negative duration");
        }

        const betamax::ProgramResult result{repaired, peak_memory,
                                            static_cast<std::uint64_t>(elapsed)};
        std::cout << betamax::serialize_result(result) << '\n';
        if (!std::cout) {
            throw std::runtime_error("failed to write result JSON to stdout");
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "betaMax: " << error.what() << '\n';
        return 1;
    } catch (...) {
        std::cerr << "betaMax: unknown fatal error\n";
        return 1;
    }
}
