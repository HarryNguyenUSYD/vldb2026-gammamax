#pragma once

#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include <string>
#include <string_view>
#include <vector>

namespace gammamax {

class NGramModel {
public:
    using Token = int;
    using Context = std::vector<Token>;

    NGramModel(const std::vector<std::string>& samples, std::size_t n,
               std::string_view additional_alphabet = {})
        : n_(n) {
        for (const auto& sample : samples) {
            for (unsigned char byte : sample) vocabulary_.insert(byte);
        }
        for (unsigned char byte : additional_alphabet) vocabulary_.insert(byte);
        vocabulary_.insert(end_token);

        if (!n_) return;
        for (const auto& sample : samples) {
            Context context(n_ - 1, start_token);
            for (unsigned char byte : sample) {
                observe(context, byte);
                advance(context, byte);
            }
            observe(context, end_token);
        }
    }

    double score(std::string_view value) const {
        if (!n_) return 0.0;

        Context context(n_ - 1, start_token);
        double result = 0.0;
        for (unsigned char byte : value) {
            result += log_probability(context, byte);
            advance(context, byte);
        }
        result += log_probability(context, end_token);
        return result;
    }

private:
    static constexpr Token start_token = -1;
    static constexpr Token end_token = 256;

    void observe(const Context& context, Token token) {
        ++counts_[context][token];
        ++totals_[context];
    }

    void advance(Context& context, Token token) const {
        if (n_ <= 1) return;
        context.erase(context.begin());
        context.push_back(token);
    }

    double log_probability(const Context& context, Token token) const {
        std::size_t count = 0;
        std::size_t total = 0;
        if (const auto found = counts_.find(context); found != counts_.end()) {
            if (const auto token_count = found->second.find(token);
                token_count != found->second.end()) {
                count = token_count->second;
            }
        }
        if (const auto found = totals_.find(context); found != totals_.end()) {
            total = found->second;
        }
        return std::log((static_cast<double>(count) + 1.0) /
                        (static_cast<double>(total) +
                         static_cast<double>(vocabulary_.size())));
    }

    std::size_t n_{};
    std::set<Token> vocabulary_;
    std::map<Context, std::map<Token, std::size_t>> counts_;
    std::map<Context, std::size_t> totals_;
};

}  // namespace gammamax

