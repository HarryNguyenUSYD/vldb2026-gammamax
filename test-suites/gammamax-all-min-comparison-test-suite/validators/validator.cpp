#include <algorithm>
#include <cctype>
#include <filesystem>
#include <iostream>
#include <iterator>
#include <regex>
#include <string>
#include <string_view>
#include <vector>

namespace {

bool all_digits(std::string_view value) {
    return !value.empty() &&
           std::all_of(value.begin(), value.end(), [](unsigned char byte) {
               return std::isdigit(byte) != 0;
           });
}

std::vector<std::string_view> split(std::string_view value, char separator) {
    std::vector<std::string_view> parts;
    std::size_t start = 0;
    for (;;) {
        const std::size_t end = value.find(separator, start);
        parts.push_back(value.substr(start, end - start));
        if (end == std::string_view::npos) return parts;
        start = end + 1;
    }
}

bool is_date(std::string_view value) {
    return value.size() == 10 && value[4] == '-' && value[7] == '-' &&
           all_digits(value.substr(0, 4)) && all_digits(value.substr(5, 2)) &&
           all_digits(value.substr(8, 2));
}

bool is_time(std::string_view value) {
    return value.size() == 8 && value[2] == ':' && value[5] == ':' &&
           all_digits(value.substr(0, 2)) && all_digits(value.substr(3, 2)) &&
           all_digits(value.substr(6, 2));
}

bool is_isbn(std::string_view value) {
    std::size_t position = 0;
    for (int digit = 0; digit < 9; ++digit) {
        if (position >= value.size() ||
            !std::isdigit(static_cast<unsigned char>(value[position]))) return false;
        ++position;
        if (position < value.size() &&
            (value[position] == '-' || value[position] == ' ')) ++position;
    }
    return position + 1 == value.size() &&
           (std::isdigit(static_cast<unsigned char>(value[position])) ||
            value[position] == 'X');
}

bool is_ipv4(std::string_view value) {
    const auto parts = split(value, '.');
    return parts.size() == 4 &&
           std::all_of(parts.begin(), parts.end(), [](std::string_view part) {
               return part.size() >= 1 && part.size() <= 3 && all_digits(part);
           });
}

bool is_ipv6(std::string_view value) {
    const auto parts = split(value, ':');
    return parts.size() == 8 &&
           std::all_of(parts.begin(), parts.end(), [](std::string_view part) {
               return part.size() >= 1 && part.size() <= 4 &&
                      std::all_of(part.begin(), part.end(), [](unsigned char byte) {
                          return std::isxdigit(byte) != 0;
                      });
           });
}

bool is_url(const std::string& value) {
    static const std::regex expression(
        R"(^https?://(www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_+.~#?&/=]*)$)",
        std::regex::ECMAScript);
    return std::regex_match(value, expression);
}

}  // namespace

int main(int argc, char** argv) {
    std::string input;
    if (argc != 1) return 2;
    input.assign(std::istreambuf_iterator<char>(std::cin), {});

    std::string name = std::filesystem::path(argv[0]).stem().string();
    constexpr std::string_view prefix = "validate_";
    if (!name.starts_with(prefix)) return 2;
    name.erase(0, prefix.size());

    bool accepted = false;
    if (name == "date") accepted = is_date(input);
    else if (name == "time") accepted = is_time(input);
    else if (name == "url") accepted = is_url(input);
    else if (name == "isbn") accepted = is_isbn(input);
    else if (name == "ipv4") accepted = is_ipv4(input);
    else if (name == "ipv6") accepted = is_ipv6(input);
    else return 2;
    return accepted ? 0 : 1;
}
