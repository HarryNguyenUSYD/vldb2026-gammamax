#pragma once
#include <algorithm>
#include <cmath>
#include <charconv>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace gammamax {
using ImputationTable = std::vector<std::vector<std::string>>;
struct TreeConfig {
    std::size_t max_depth{5}, min_samples_leaf{5}, max_thresholds{16}, max_decimal_places{6};
};
inline void validate_tree_config(const TreeConfig& c) {
    if (c.max_depth > 5 || !c.min_samples_leaf || !c.max_thresholds || c.max_thresholds > 32 || c.max_decimal_places > 15)
        throw std::runtime_error("invalid decision tree configuration");
}
inline bool is_missing(const std::string& s) { return s.empty() || s == "?"; }
inline std::optional<double> numeric_value(const std::string& s) {
    if (is_missing(s)) return {};
    const auto first = s.find_first_not_of(" \t\r\n\f\v");
    if (first == std::string::npos) return {};
    const char* begin = s.data() + first;
    const char* end = s.data() + s.size();
    if (*begin == '+') {
        ++begin;
        if (begin == end || *begin == '-' || *begin == '+') return {};
    }
    double value{};
    const auto parsed = std::from_chars(begin, end, value);
    if (parsed.ec != std::errc{} || parsed.ptr != end || !std::isfinite(value)) return {};
    return value;
}
inline std::vector<bool> infer_tree_features(const ImputationTable& rows) {
    if (rows.empty()) return {};
    const auto width = rows.front().size();
    for (const auto& row : rows) if (row.size() != width) throw std::runtime_error("inconsistent tree row width");
    std::vector<bool> numeric(width, true), seen(width, false);
    for (const auto& row : rows) for (std::size_t c = 0; c < width; ++c) {
        if (is_missing(row[c])) continue;
        seen[c] = true;
        if (!numeric_value(row[c])) numeric[c] = false;
    }
    for (std::size_t c = 0; c < width; ++c) numeric[c] = numeric[c] && seen[c];
    return numeric;
}
struct TreePrediction {
    bool resolved{}, numeric{}, fallback{};
    double number{};
    std::string category;
};
class DecisionTree {
    enum class Kind { leaf, missing, threshold, equality };
    struct Stats {
        std::size_t count{};
        long double sum{}, squares{}, label_squares{};
        std::map<std::string, std::size_t> labels;
        void add(const std::string& value, bool numeric, long double origin, long double scale) {
            ++count;
            if (numeric) { const long double x = static_cast<long double>(*numeric_value(value))/scale - origin; sum += x; squares += x*x; }
            else {
                auto& frequency = labels[value];
                label_squares += 2.0L*frequency + 1;
                ++frequency;
            }
        }
        Stats minus(const Stats& b) const {
            auto result = *this; result.count -= b.count; result.sum -= b.sum; result.squares -= b.squares;
            for (const auto& [label, n] : b.labels) {
                auto& frequency = result.labels[label];
                result.label_squares += static_cast<long double>(n)*n - 2.0L*frequency*n;
                frequency -= n;
            }
            return result;
        }
        // Split scoring needs only the complement's scalar statistics. Avoid
        // copying the full target histogram for each categorical candidate.
        Stats difference_summary(const Stats& b) const {
            Stats result;
            result.count = count - b.count;
            result.sum = sum - b.sum;
            result.squares = squares - b.squares;
            result.label_squares = label_squares + b.label_squares;
            for (const auto& [label, n] : b.labels)
                result.label_squares -= 2.0L*labels.at(label)*n;
            return result;
        }
        long double loss(bool numeric) const {
            if (!count) return 0;
            if (numeric) return std::max(0.0L, squares - sum*sum/count);
            return std::max(0.0L, count - label_squares/count);
        }
    };
    struct Node {
        TreePrediction prediction;
        Kind kind{Kind::leaf};
        std::size_t column{};
        double threshold{};
        std::string category;
        int left{-1}, right{-1}, missing{-1};
    };
    TreeConfig config_;
    std::vector<bool> features_;
    std::vector<Node> nodes_;
    std::size_t target_{}, training_rows_{}, depth_{};
    long double origin_{}, scale_{1};
    Stats stats(const ImputationTable& table, const std::vector<std::size_t>& ids) const {
        Stats result;
        for (auto r : ids) result.add(table[r][target_], features_[target_], origin_, scale_);
        return result;
    }
    TreePrediction prediction(const Stats& s) const {
        TreePrediction p{bool(s.count), features_[target_], false, 0, {}};
        if (!s.count) return p;
        if (p.numeric) p.number = static_cast<double>(std::clamp(origin_ + s.sum/s.count, -1.0L, 1.0L)*scale_);
        else {
            std::size_t best = 0;
            for (const auto& [label, n] : s.labels) if (n > best) { best = n; p.category = label; }
        }
        return p;
    }
    int build(const ImputationTable& table, const std::vector<std::size_t>& ids, std::size_t depth) {
        const auto total = stats(table, ids);
        const int index = static_cast<int>(nodes_.size());
        nodes_.push_back(Node{prediction(total)});
        depth_ = std::max(depth_, depth);
        if (depth == config_.max_depth || ids.size()/2 < config_.min_samples_leaf || total.loss(features_[target_]) <= 0) return index;
        Node best;
        long double best_loss = total.loss(features_[target_]);
        auto consider = [&](Node candidate, const Stats& a, const Stats& b, const Stats& missing) {
            if (a.count < config_.min_samples_leaf || b.count < config_.min_samples_leaf ||
                (missing.count && missing.count < config_.min_samples_leaf)) return;
            const auto loss = a.loss(features_[target_]) + b.loss(features_[target_]) + missing.loss(features_[target_]);
            if (loss < best_loss) { best_loss = loss; best = std::move(candidate); }
        };
        for (std::size_t c = 0; c < features_.size(); ++c) {
            if (c == target_) continue;
            Stats missing;
            std::vector<std::pair<double, std::size_t>> sorted;
            std::map<std::string, Stats> groups;
            for (auto r : ids) {
                if (is_missing(table[r][c])) missing.add(table[r][target_], features_[target_], origin_, scale_);
                else if (features_[c]) sorted.emplace_back(*numeric_value(table[r][c]), r);
                else groups[table[r][c]].add(table[r][target_], features_[target_], origin_, scale_);
            }
            const auto present = total.minus(missing);
            Node candidate; candidate.column = c; candidate.kind = Kind::missing;
            consider(candidate, missing, present, {});
            if (features_[c]) {
                std::sort(sorted.begin(), sorted.end());
                std::vector<double> thresholds;
                for (std::size_t q = 1; q <= config_.max_thresholds && sorted.size() > 1; ++q) {
                    const auto pos = q*sorted.size()/(config_.max_thresholds+1);
                    if (pos && pos < sorted.size() && sorted[pos].first > sorted.front().first)
                        thresholds.push_back(sorted[pos].first);
                }
                thresholds.erase(std::unique(thresholds.begin(), thresholds.end()), thresholds.end());
                Stats left; std::size_t pos = 0;
                for (double threshold : thresholds) {
                    while (pos < sorted.size() && sorted[pos].first < threshold) {
                        left.add(table[sorted[pos].second][target_], features_[target_], origin_, scale_); ++pos;
                    }
                    candidate.kind = Kind::threshold; candidate.threshold = threshold;
                    consider(candidate, left, present.difference_summary(left), missing);
                }
            } else for (const auto& [category, group] : groups) {
                candidate.kind = Kind::equality; candidate.category = category;
                consider(candidate, group, total.difference_summary(group), {});
            }
        }
        if (best.kind == Kind::leaf) return index;
        std::vector<std::size_t> left, right, missing;
        for (auto r : ids) {
            const auto& value = table[r][best.column];
            if (best.kind == Kind::threshold && is_missing(value)) missing.push_back(r);
            else {
                const bool goes_left = best.kind == Kind::missing ? is_missing(value) :
                    best.kind == Kind::equality ? value == best.category : *numeric_value(value) < best.threshold;
                (goes_left ? left : right).push_back(r);
            }
        }
        best.prediction = nodes_[index].prediction;
        best.left = build(table, left, depth+1); best.right = build(table, right, depth+1);
        if (!missing.empty()) best.missing = build(table, missing, depth+1);
        nodes_[index] = std::move(best);
        return index;
    }
public:
    DecisionTree(const ImputationTable& table, std::size_t target, const TreeConfig& config = {}) : config_(config), features_(infer_tree_features(table)), target_(target) {
        validate_tree_config(config);
        if (table.empty()) return;
        if (target >= features_.size()) throw std::runtime_error("tree target column out of range");
        std::vector<std::size_t> ids;
        for (std::size_t r = 0; r < table.size(); ++r) if (!is_missing(table[r][target])) ids.push_back(r);
        training_rows_ = ids.size();
        if (ids.empty()) return;
        if (features_[target]) {
            // Normalize before squaring, including subunit targets. This keeps
            // regression loss finite even where long double is just double.
            scale_ = 0;
            for (auto row : ids) scale_ = std::max(scale_, std::abs(static_cast<long double>(*numeric_value(table[row][target]))));
            if (scale_ == 0) scale_ = 1;
            origin_ = static_cast<long double>(*numeric_value(table[ids.front()][target]))/scale_;
        }
        build(table, ids, 0);
    }
    TreePrediction predict(const std::vector<std::string>& row) const {
        if (nodes_.empty()) return {};
        if (row.size() != features_.size()) throw std::runtime_error("inconsistent prediction row width");
        int index = 0;
        while (true) {
            const auto& n = nodes_[index];
            auto result = n.prediction; result.fallback = nodes_[0].kind == Kind::leaf;
            if (n.kind == Kind::leaf) return result;
            const auto& value = row[n.column];
            if (n.kind == Kind::threshold && is_missing(value)) {
                if (n.missing < 0) return result;
                index = n.missing;
            } else if (n.kind == Kind::threshold) {
                const auto number = numeric_value(value);
                if (!number) throw std::runtime_error("nonnumeric tree predictor");
                index = *number < n.threshold ? n.left : n.right;
            } else index = (n.kind == Kind::missing ? is_missing(value) : value == n.category) ? n.left : n.right;
        }
    }
    std::size_t training_rows() const { return training_rows_; }
    std::size_t node_count() const { return nodes_.size(); }
    std::size_t depth() const { return depth_; }
    bool numeric() const { return !features_.empty() && features_[target_]; }
};
} // namespace gammamax
