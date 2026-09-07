#pragma once
#include "gammamax/types.hpp"
#include <limits>
#include <stdexcept>
#include <string>
#include <nlohmann/json.hpp>

namespace gammamax {
inline void require_object(const nlohmann::json& v, const std::string& c) {
    if (!v.is_object()) throw std::runtime_error(c + " must be a JSON object");
}
template <typename T> inline T unsigned_value(const nlohmann::json& o, const char* k, const std::string& c) {
    if (!o.contains(k) || !o.at(k).is_number_integer()) throw std::runtime_error(c + "." + k + " must be a non-negative integer");
    if (!o.at(k).is_number_unsigned() && o.at(k).get<std::int64_t>() < 0) throw std::runtime_error(c + "." + k + " must be a non-negative integer");
    auto v = o.at(k).is_number_unsigned() ? o.at(k).get<std::uint64_t>() : static_cast<std::uint64_t>(o.at(k).get<std::int64_t>());
    if (v > static_cast<std::uint64_t>(std::numeric_limits<T>::max())) throw std::runtime_error(c + "." + k + " is out of range");
    return static_cast<T>(v);
}
template <typename T> inline T boundary_value(const nlohmann::json& o, const char* k, const std::string& c) {
    const auto& v = o.at(k);
    if (v.is_number_integer() && !v.is_number_unsigned() && v.get<std::int64_t>() == -1) return std::numeric_limits<T>::max();
    return unsigned_value<T>(o, k, c);
}
inline Config parse_config_value(const nlohmann::json& root) {
    require_object(root, "config");
    for (const char* key : {"state_merging", "repair", "batching", "limits"})
        if (!root.contains(key)) throw std::runtime_error("config is missing field '" + std::string(key) + "'");
    const auto& merging=root.at("state_merging"); const auto& repair=root.at("repair");
    const auto& batching=root.at("batching"); const auto& limits=root.at("limits");
    require_object(merging,"config.state_merging"); require_object(repair,"config.repair");
    require_object(batching,"config.batching"); require_object(limits,"config.limits");
    if (repair.contains("rsr_batch_size"))
        throw std::runtime_error("config.repair.rsr_batch_size is not supported");
    Config r;
    if (root.contains("seed")) r.seed=unsigned_value<std::uint64_t>(root,"seed","config");
    r.k=unsigned_value<std::size_t>(merging,"k","config.state_merging");
    r.n=unsigned_value<std::size_t>(repair,"n","config.repair");
    r.ngrams_batch_size=boundary_value<std::size_t>(repair,"ngrams_batch_size","config.repair");
    r.max_candidate_length=repair.contains("max_candidate_length")
        ? boundary_value<std::size_t>(repair,"max_candidate_length","config.repair")
        : std::numeric_limits<std::size_t>::max();
    r.max_iterations=boundary_value<std::size_t>(limits,"max_iterations","config.limits");
    r.max_total_oracle_calls=boundary_value<std::size_t>(limits,"max_total_oracle_calls","config.limits");
    r.max_states=boundary_value<std::size_t>(limits,"max_states","config.limits");
    r.max_queue_size=limits.contains("max_queue_size")
        ? boundary_value<std::size_t>(limits,"max_queue_size","config.limits")
        : std::numeric_limits<std::size_t>::max();
    r.max_rsr_candidates=limits.contains("max_rsr_candidates")
        ? boundary_value<std::size_t>(limits,"max_rsr_candidates","config.limits")
        : std::numeric_limits<std::size_t>::max();
    r.negative_capacity=boundary_value<std::size_t>(batching,"negative_capacity","config.batching");
    r.max_positive_examples=boundary_value<std::size_t>(batching,"max_positive_examples","config.batching");
    r.cell_timeout_seconds=unsigned_value<std::size_t>(batching,"cell_timeout_seconds","config.batching");
    if (!r.ngrams_batch_size ||
        !r.max_candidate_length || !r.max_iterations ||
        !r.max_total_oracle_calls || !r.max_states || !r.max_queue_size ||
        !r.max_rsr_candidates || !r.negative_capacity ||
        !r.max_positive_examples || !r.cell_timeout_seconds)
        throw std::runtime_error("configured counts and resource limits must be positive or -1 where supported");
    return r;
}
} // namespace gammamax
