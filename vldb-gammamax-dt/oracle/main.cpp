#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <regex>
#include <set>
#include <string>

int main(int argc, char** argv) {
    try {
        const auto executable = std::filesystem::absolute(argv[0]);
        auto spec_path = executable;
        spec_path.replace_extension(".json");
        std::ifstream spec_stream(spec_path);
        if (!spec_stream) throw std::runtime_error("missing oracle specification");
        nlohmann::json spec; spec_stream >> spec;
        std::string value((std::istreambuf_iterator<char>(std::cin)), {});
        if (value.empty() || value == "?") return 1;
        if (spec.at("type") == "enum") {
            for (const auto& item : spec.at("values"))
                if (item.get_ref<const std::string&>() == value) return 0;
            return 1;
        }
        if (spec.at("type") == "regex") {
            std::regex expression(spec.at("regex").get<std::string>(), std::regex::ECMAScript);
            return std::regex_match(value, expression) ? 0 : 1;
        }
        throw std::runtime_error("unsupported oracle type");
    } catch (const std::exception& error) {
        std::cerr << "oracle error: " << error.what() << '\n';
        return 2;
    }
}
