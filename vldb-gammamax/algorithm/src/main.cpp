#include "gammamax/batch_session.hpp"
#include "gammamax/oracle.hpp"
#include <nlohmann/json.hpp>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <optional>
#include <random>
#include <sstream>
#include <unordered_map>

namespace fs = std::filesystem;
using json = nlohmann::json;

struct Table { std::vector<std::string> columns; std::vector<std::vector<std::string>> rows; };

static Table read_csv(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("cannot open input CSV: " + path.string());
    std::vector<std::vector<std::string>> records;
    std::vector<std::string> record;
    std::string field;
    bool quoted = false;
    for (char ch; in.get(ch);) {
        if (quoted) {
            if (ch == '"') {
                if (in.peek() == '"') { in.get(); field.push_back('"'); }
                else quoted = false;
            } else field.push_back(ch);
        } else if (ch == '"' && field.empty()) quoted = true;
        else if (ch == ',') { record.push_back(std::move(field)); field.clear(); }
        else if (ch == '\n') {
            if (!field.empty() && field.back() == '\r') field.pop_back();
            record.push_back(std::move(field)); field.clear();
            records.push_back(std::move(record)); record.clear();
        } else field.push_back(ch);
    }
    if (quoted) throw std::runtime_error("unterminated quoted CSV field");
    if (!field.empty() || !record.empty()) { record.push_back(std::move(field)); records.push_back(std::move(record)); }
    if (records.empty() || records.front().empty()) throw std::runtime_error("CSV has no header");
    Table table{std::move(records.front()), {}};
    std::set<std::string> unique(table.columns.begin(), table.columns.end());
    if (unique.size() != table.columns.size()) throw std::runtime_error("CSV headers must be unique");
    for (std::size_t i = 1; i < records.size(); ++i) {
        if (records[i].size() != table.columns.size())
            throw std::runtime_error("CSV row " + std::to_string(i + 1) + " has wrong field count");
        table.rows.push_back(std::move(records[i]));
    }
    return table;
}

static std::string csv_field(const std::string& value) {
    if (value.find_first_of(",\"\r\n") == std::string::npos) return value;
    std::string result = "\"";
    for (char ch : value) { if (ch == '"') result.push_back('"'); result.push_back(ch); }
    return result + '"';
}

static void write_csv(const fs::path& path, const Table& table) {
    std::ofstream out(path, std::ios::binary);
    if (!out) throw std::runtime_error("cannot write CSV: " + path.string());
    auto write_record = [&](const auto& record) {
        for (std::size_t i = 0; i < record.size(); ++i) {
            if (i) out << ',';
            out << csv_field(record[i]);
        }
        out << '\n';
    };
    write_record(table.columns);
    for (const auto& row : table.rows) write_record(row);
    if (!out) throw std::runtime_error("failed writing CSV: " + path.string());
}

static json read_json(const fs::path& path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot open JSON: " + path.string());
    json value; in >> value; return value;
}

static gammamax::Config parse_config(const fs::path& path) {
    return gammamax::parse_config_value(read_json(path));
}

static double seconds(std::chrono::steady_clock::duration duration) {
    return std::chrono::duration<double>(duration).count();
}

static fs::path oracle_path(const fs::path& root, std::size_t index) {
    std::ostringstream name;
    name << "oracle_" << std::setfill('0') << std::setw(3) << index;
#ifdef _WIN32
    name << ".exe";
#endif
    auto path = root / name.str();
    if (!fs::is_regular_file(path)) throw std::runtime_error("missing oracle: " + path.string());
    return fs::absolute(path);
}

struct CellState {
    bool timed_out{}; double gamma_elapsed{}; std::string gamma_outcome;
};

static int run(int argc, char** argv) {
    std::map<std::string, fs::path> args;
    for (int i = 1; i < argc; i += 2) {
        if (i + 1 >= argc) throw std::runtime_error("every CLI option requires a value");
        args.emplace(argv[i], argv[i + 1]);
    }
    for (const char* required : {"--input", "--config", "--oracles-dir", "--output", "--telemetry"})
        if (!args.contains(required)) throw std::runtime_error(std::string("missing option ") + required);
    const auto overall_started = std::chrono::steady_clock::now();
    auto config = parse_config(args["--config"]);
    auto input = read_csv(args["--input"]);
    auto repaired = input;
    std::vector<std::vector<CellState>> cell_states(input.rows.size(), std::vector<CellState>(input.columns.size()));
    json column_telemetry = json::object();
    const std::size_t total_cells = input.rows.size() * input.columns.size();
    std::size_t completed_cells = 0;
    const auto report_progress = [&]() {
        std::cerr << "VLDB_PROGRESS " << completed_cells << ' ' << total_cells << '\n';
    };
    report_progress();

    const auto ignored = [](const std::string& value) {
        return value.empty() || value == "?";
    };

    for (std::size_t column = 0; column < input.columns.size(); ++column) {
        const auto column_started = std::chrono::steady_clock::now();
        gammamax::ExternalOracle oracle(oracle_path(args["--oracles-dir"], column),
                                        config.max_total_oracle_calls);
        std::set<std::string> accepted_set;
        std::vector<std::string> rejected_order;
        std::unordered_map<std::string, std::vector<std::size_t>> occurrences;
        for (std::size_t row = 0; row < input.rows.size(); ++row) {
            const auto& value = input.rows[row][column];
            if (ignored(value)) {
                cell_states[row][column].gamma_outcome = "gamma_skipped_missing";
                ++completed_cells;
                continue;
            }
            if (oracle.accepts(value)) {
                cell_states[row][column].gamma_outcome = "gamma_valid";
                accepted_set.insert(value);
                ++completed_cells;
            }
            else {
                if (!occurrences.contains(value)) rejected_order.push_back(value);
                occurrences[value].push_back(row);
            }
        }
        report_progress();
        if (accepted_set.empty()) throw std::runtime_error("column has no accepted non-empty values: " + input.columns[column]);
        std::vector<std::string> positives(accepted_set.begin(), accepted_set.end());
        std::mt19937_64 sampler(config.seed.value_or(0) + column);
        std::shuffle(positives.begin(), positives.end(), sampler);
        if (positives.size() > config.max_positive_examples) positives.resize(config.max_positive_examples);
        const auto training_count=positives.size();
        gammamax::AlgorithmMeasurements measurements;
        gammamax::BatchSession session(std::move(positives),config,&measurements);
        std::size_t repaired_values = 0, timed_out_values = 0;
        for (const auto& dirty : rejected_order) {
            const auto started = std::chrono::steady_clock::now();
            const auto deadline = started + std::chrono::seconds(config.cell_timeout_seconds);
            bool timed_out = false;
            std::optional<std::string> replacement;
            try {
                replacement=session.repair(dirty,oracle,deadline,measurements);
            } catch (const std::runtime_error& error) {
                if (std::string(error.what()) == "cell timeout") timed_out = true;
                else throw;
            }
            const double elapsed = seconds(std::chrono::steady_clock::now() - started);
            const bool replacement_valid = !timed_out && replacement.has_value();
            const auto& rows = occurrences.at(dirty);
            for (std::size_t occurrence = 0; occurrence < rows.size(); ++occurrence) {
                auto row = rows[occurrence];
                auto& state = cell_states[row][column];
                state.timed_out = timed_out;
                state.gamma_elapsed = occurrence == 0 ? elapsed : 0.0;
                if (timed_out) {
                    repaired.rows[row][column].clear();
                    state.gamma_outcome = "gamma_timeout";
                } else if (replacement_valid) {
                    repaired.rows[row][column] = *replacement;
                    state.gamma_outcome = "gamma_repaired";
                } else {
                    repaired.rows[row][column].clear();
                    state.gamma_outcome = "gamma_invalidated";
                }
            }
            completed_cells += rows.size();
            report_progress();
            repaired_values += replacement_valid;
            timed_out_values += timed_out;
        }
        column_telemetry[input.columns[column]] = {
            {"execution_time_seconds", seconds(std::chrono::steady_clock::now() - column_started)},
            {"distinct_accepted", accepted_set.size()}, {"distinct_rejected", rejected_order.size()},
            {"distinct_repaired", repaired_values}, {"distinct_timed_out", timed_out_values},
            {"oracle_calls", oracle.calls()}, {"training_examples", training_count},
            {"max_positive_examples_stored", training_count},
            {"max_negative_examples_stored", session.negative_count()},
            {"k", config.k}, {"n", config.n},
            {"rsr_execution_time_ns",measurements.rsr_execution_time_ns},
            {"ktails_execution_time_ns",measurements.ktails_execution_time_ns},
            {"edsm_execution_time_ns",measurements.edsm_execution_time_ns},
            {"ngrams_execution_time_ns",measurements.ngrams_execution_time_ns},
            {"initial_state_merge_ns",measurements.initial_state_merge_ns},
            {"merge_replay_ns",measurements.merge_replay_ns},
            {"resumed_state_merge_ns",measurements.resumed_state_merge_ns},
            {"candidate_copy_or_rollback_ns",measurements.candidate_copy_or_rollback_ns},
            {"negative_validation_ns",measurements.negative_validation_ns},
            {"total_iterations",measurements.total_iterations},
            {"rsr_iterations",measurements.rsr_iterations.size()},
            {"rsr_candidates_generated",[&] {
                std::uint64_t total=0; for (const auto& item:measurements.rsr_iterations) total+=item.unique_candidates; return total;
            }()},
            {"rsr_enumeration_truncated",[&] {
                for (const auto& item:measurements.rsr_iterations)
                    if (!item.enumeration_complete) return true;
                return false;
            }()}
        };
    }
    const auto gamma_finished = std::chrono::steady_clock::now();
    for (std::size_t column = 0; column < input.columns.size(); ++column) {
        gammamax::ExternalOracle validator(oracle_path(args["--oracles-dir"], column),
                                           std::numeric_limits<std::size_t>::max());
        for (std::size_t row = 0; row < repaired.rows.size(); ++row) {
            auto& state = cell_states[row][column];
            if (state.gamma_outcome == "gamma_repaired" && !validator.accepts(repaired.rows[row][column])) {
                repaired.rows[row][column].clear();
                state.gamma_outcome = "gamma_invalidated";
            }
        }
    }
    for (std::size_t column = 0; column < input.columns.size(); ++column) {
        std::map<std::string, std::size_t> outcomes;
        for (std::size_t row = 0; row < input.rows.size(); ++row)
            ++outcomes[cell_states[row][column].gamma_outcome];
        column_telemetry[input.columns[column]]["gamma_outcomes"] = outcomes;
    }
    json cells = json::array();
    for (std::size_t row = 0; row < input.rows.size(); ++row)
        for (std::size_t column = 0; column < input.columns.size(); ++column)
            {
                const auto& state = cell_states[row][column];
                cells.push_back({
                {"row", row}, {"column", input.columns[column]},
                {"timed_out", state.timed_out},
                {"execution_time_seconds", state.gamma_elapsed},
                {"gamma_outcome", state.gamma_outcome},
                {"knn_imputed", false}
                });
            }
    json telemetry = {{"schema_version", 2}, {"cells", std::move(cells)},
                      {"columns", std::move(column_telemetry)},
                      {"gamma_execution_time_seconds", seconds(gamma_finished - overall_started)},
                      {"total_execution_time_seconds", seconds(std::chrono::steady_clock::now() - overall_started)}};
    completed_cells = total_cells;
    report_progress();
    auto output_tmp = args["--output"]; output_tmp += ".tmp";
    auto telemetry_tmp = args["--telemetry"]; telemetry_tmp += ".tmp";
    write_csv(output_tmp, repaired);
    { std::ofstream out(telemetry_tmp); if (!out) throw std::runtime_error("cannot write telemetry"); out << telemetry.dump(2) << '\n'; }
    fs::rename(output_tmp, args["--output"]);
    fs::rename(telemetry_tmp, args["--telemetry"]);
    return 0;
}

int main(int argc, char** argv) {
    try { return run(argc, argv); }
    catch (const std::exception& error) { std::cerr << "error: " << error.what() << '\n'; return 1; }
}
