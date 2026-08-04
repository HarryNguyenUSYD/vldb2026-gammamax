#pragma once

#include <cstdint>
#include <random>

namespace betamax {

class Random {
public:
    explicit Random(std::uint64_t seed) : engine_(seed) {}
    std::mt19937_64& engine() noexcept { return engine_; }

private:
    std::mt19937_64 engine_;
};

}  // namespace betamax
