#pragma once
#include <algorithm>
#include <charconv>
#include <cmath>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace gammamax {
// Composition-layer formatting: independent decimal rounding of the shortest
// round-trip representation avoids chained rounding and binary halfway errors.
inline std::string normalize_decimal(std::string value) {
    if (value.find('.') != std::string::npos) {
        while (value.back() == '0') value.pop_back();
        if (value.back() == '.') value.pop_back();
    }
    if (value.find_first_not_of("-0.") == std::string::npos) return "0";
    return value;
}
inline std::string decimal_prediction(double value) {
    if (!std::isfinite(value)) throw std::runtime_error("nonfinite tree prediction");
    char buffer[64];
    const auto converted = std::to_chars(buffer, buffer + sizeof(buffer), value);
    if (converted.ec != std::errc{}) throw std::runtime_error("cannot format tree prediction");
    std::string text(buffer, converted.ptr);
    const auto exponent_at = text.find_first_of("eE");
    if (exponent_at == std::string::npos) return normalize_decimal(text);
    const int exponent = std::stoi(text.substr(exponent_at + 1));
    std::string digits = text.substr(0, exponent_at);
    const bool negative = digits.front() == '-';
    if (negative) digits.erase(0, 1);
    auto dot = digits.find('.');
    int position = static_cast<int>(dot == std::string::npos ? digits.size() : dot) + exponent;
    if (dot != std::string::npos) digits.erase(dot, 1);
    if (position <= 0) digits = "0." + std::string(-position, '0') + digits;
    else if (position >= static_cast<int>(digits.size())) digits.append(position - digits.size(), '0');
    else digits.insert(position, ".");
    return normalize_decimal((negative ? "-" : "") + digits);
}
inline std::string round_decimal(const std::string& original, std::size_t places) {
    const bool negative = original.front() == '-';
    std::string magnitude = negative ? original.substr(1) : original;
    const auto dot = magnitude.find('.');
    if (dot == std::string::npos || magnitude.size() - dot - 1 <= places) return original;
    const auto cutoff = dot + 1 + places;
    const bool increment = magnitude[cutoff] >= '5';
    magnitude.resize(cutoff);
    if (increment) {
        bool carry = true;
        for (std::size_t i = magnitude.size(); i > 0 && carry;) {
            char& digit = magnitude[--i];
            if (digit == '.') continue;
            if (digit == '9') digit = '0';
            else { ++digit; carry = false; }
        }
        if (carry) magnitude.insert(0, "1");
    }
    return normalize_decimal((negative ? "-" : "") + magnitude);
}
inline std::vector<std::string> numeric_candidates(double prediction, std::size_t max_places) {
    if (max_places > 15) throw std::runtime_error("invalid decimal precision");
    const auto original = decimal_prediction(prediction);
    std::vector<std::string> result{original};
    for (int places = static_cast<int>(max_places); places >= 0; --places) {
        auto candidate = round_decimal(original, static_cast<std::size_t>(places));
        if (std::find(result.begin(), result.end(), candidate) == result.end()) result.push_back(std::move(candidate));
    }
    // Some libc++ versions lack from_chars(long double&). Classic-locale
    // streams preserve long-double precision without using the user's locale.
    auto distance = [&](const std::string& candidate) {
        long double number{};
        std::istringstream input(candidate);
        input.imbue(std::locale::classic());
        input >> std::noskipws >> number;
        if (input.fail() || !input.eof() || !std::isfinite(number))
            throw std::runtime_error("cannot parse numeric candidate");
        return std::abs(number - static_cast<long double>(prediction));
    };
    std::stable_sort(result.begin() + 1, result.end(), [&](const auto& a, const auto& b) { return distance(a) < distance(b); });
    return result;
}
} // namespace gammamax
