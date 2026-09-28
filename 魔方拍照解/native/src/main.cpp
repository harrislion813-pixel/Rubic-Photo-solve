#include "cube.hpp"
#include "fast.hpp"
#include "paths.hpp"
#include "pdb.hpp"
#include "solver.hpp"
#include "symmetry.hpp"
#include "strong_coords.hpp"
#include "strong_pdb.hpp"
#include "tail.hpp"

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <deque>
#include <exception>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace {

const char *asset_profile(const cube::NativeOptimalSolver &solver, cube::MoveMetric metric) {
    if (metric == cube::MoveMetric::HTM)
        return "htm";
    const bool qtm_base = solver.has_corner_pdb(metric) && solver.corner_pdb_metric(metric) == metric &&
                          solver.corner_pdb_complete(metric) && solver.has_phase1_pdb(metric) &&
                          solver.phase1_pdb_metric(metric) == metric && solver.phase1_pdb_complete(metric);
    if (qtm_base && solver.has_strong_pdb(metric) && solver.tail_database_depth(metric) >= 8)
        return "strong";
    if (qtm_base && solver.tail_database_depth(metric) >= 7)
        return "standard";
    if (qtm_base)
        return "base";
    if ((solver.has_corner_pdb(metric) && solver.corner_pdb_metric(metric) == metric) ||
        (solver.has_phase1_pdb(metric) && solver.phase1_pdb_metric(metric) == metric))
        return "partial";
    return "fallback";
}

int parse_integer(const std::string &value) {
    std::size_t consumed = 0;
    const int parsed = std::stoi(value, &consumed);
    if (consumed != value.size())
        throw std::invalid_argument("expected an integer: " + value);
    return parsed;
}

void print_usage() {
    std::cerr << "usage:\n"
              << "  cube_solver validate FACELETS\n"
              << "  cube_solver apply FACELETS [MOVES...]\n"
              << "  cube_solver symmetry-info\n"
              << "  cube_solver strong-symmetry-info\n"
              << "  cube_solver build-strong-pdb PATH --metric QTM [--coverage-depth N] [--threads N] [--resume] [--memory-limit-gib N]\n"
              << "  cube_solver verify-strong-pdb PATH [--threads N]\n"
              << "  cube_solver fast-solve FACELETS --qtm-phase1-pdb PATH [--timeout N] [--incumbent-cost N]\n"
              << "  cube_solver solve FACELETS [--metric HTM|QTM] [--max-depth N] [--timeout S] [--threads N]\n"
              << "                    [--pdb PATH] [--incumbent \"MOVES\"] [--transposition]\n"
              << "  cube_solver serve [--pdb PATH] [--phase1-pdb PATH] [--qtm-pdb PATH] [--qtm-phase1-pdb PATH] [--strong-pdb PATH]\n"
              << "  cube_solver build-corner-pdb PATH [--metric HTM|QTM] [--coverage-depth N] [--threads N] [--force]\n"
              << "  cube_solver build-phase1-pdb PATH [--metric HTM|QTM] [--coverage-depth N] [--threads N] [--force]\n"
              << "  cube_solver build-edge-pdb PATH --group 0..7 [--coverage-depth N]\n"
              << "                    [--threads N] [--force]\n"
              << "  cube_solver build-tail-pdb PATH [--metric HTM|QTM] [--depth N] [--threads N] [--force]\n"
              << "  cube_solver verify-tail-pdb PATH [--threads N]\n"
              << "  cube_solver verify-pdb PATH --pattern corner|phase1|edge [--group 0..7] [--threads N] --full\n";
}

std::vector<int> parse_moves(const std::string &text) {
    std::istringstream input(text);
    std::vector<int> result;
    std::string token;
    while (input >> token) {
        const int move = cube::move_index(token);
        if (move < 0)
            throw std::invalid_argument("unknown move: " + token);
        result.push_back(move);
    }
    return result;
}

std::string moves_text(const std::vector<int> &moves) {
    std::string result;
    for (int move : moves) {
        if (!result.empty())
            result.push_back(' ');
        result += cube::kMoveNames[move];
    }
    return result;
}

void print_moves_json(std::ostream &output, const std::vector<int> &moves) {
    output << '[';
    for (std::size_t index = 0; index < moves.size(); ++index) {
        if (index != 0)
            output << ',';
        output << '\"' << cube::kMoveNames[moves[index]] << '\"';
    }
    output << ']';
}

void print_counters_json(std::ostream &output, const cube::SearchCounters &counters,
                         const std::vector<cube::WorkerStatistics> &workers) {
    output << ",\"generated_candidates\":" << counters.generated << ",\"small_pdb_queries\":" << counters.small_queries
           << ",\"phase1_queries\":" << counters.phase1_queries << ",\"corner_queries\":" << counters.corner_queries
           << ",\"edge_queries\":" << counters.edge_queries << ",\"strong_queries\":" << counters.strong_queries
           << ",\"tt_keys\":" << counters.tt_keys << ",\"tt_lookups\":" << counters.tt_lookups
           << ",\"tt_stores\":" << counters.tt_stores
           << ",\"strong_rejects\":" << counters.strong_rejects << ",\"axis_rejects\":[" << counters.axis_rejects[0] << ','
           << counters.axis_rejects[1] << ',' << counters.axis_rejects[2] << ']'
           << ",\"equality_rejects\":" << counters.equality_rejects << ",\"corner_rejects\":" << counters.corner_rejects
           << ",\"edge_rejects\":" << counters.edge_rejects << ",\"workers\":[";
    for (std::size_t i = 0; i < workers.size(); ++i) {
        if (i)
            output << ',';
        output << "{\"nodes\":" << workers[i].nodes << ",\"generated\":" << workers[i].generated
               << ",\"busy_seconds\":" << workers[i].busy_seconds << ",\"idle_seconds\":" << workers[i].idle_seconds
               << ",\"tasks\":" << workers[i].tasks
               << ",\"longest_task_seconds\":" << workers[i].longest_task_seconds
               << ",\"queue_lock_wait_seconds\":" << workers[i].queue_lock_wait_seconds
               << '}';
    }
    output << ']';
}

void print_progress_json(std::ostream &output, const cube::NativeSearchProgress &progress, const std::string &id = "") {
    output << "{\"type\":\"progress\",\"lower_bound\":" << progress.lower_bound << ",\"metric\":\""
           << cube::metric_name(progress.metric) << "\""
           << ",\"upper_bound\":" << progress.upper_bound << ",\"current_depth\":" << progress.current_depth
           << ",\"completed_depth\":" << progress.completed_depth << ",\"iteration_nodes\":" << progress.iteration_nodes
           << ",\"iteration_split_nodes\":" << progress.iteration_split_nodes << ",\"nodes\":" << progress.total_nodes
           << ",\"split_nodes\":" << progress.total_split_nodes
           << ",\"transposition_hits\":" << progress.transposition_hits << ",\"tail_queries\":" << progress.tail_queries
           << ",\"tail_bloom_rejects\":" << progress.tail_bloom_rejects
           << ",\"tail_exact_queries\":" << progress.tail_exact_queries << ",\"tail_probes\":" << progress.tail_probes
           << ",\"tail_hits\":" << progress.tail_hits << ",\"iteration_seconds\":" << std::fixed << std::setprecision(6)
           << progress.iteration_seconds << ",\"elapsed_seconds\":" << progress.elapsed_seconds
           << ",\"found\":" << (progress.found ? "true" : "false")
           << ",\"timed_out\":" << (progress.timed_out ? "true" : "false")
           << ",\"cancelled\":" << (progress.cancelled ? "true" : "false");
    if (!id.empty())
        output << ",\"request_id\":" << std::quoted(id);
    print_counters_json(output, progress.counters, progress.workers);
    output << "}\n" << std::flush;
}

void print_result_json(std::ostream &output, const cube::NativeSolveResult &result,
                       const cube::NativeOptimalSolver &solver, bool framed = false, const std::string &id = "") {
    output << "{\"ok\":true";
    if (framed)
        output << ",\"type\":\"result\"";
    if (!id.empty())
        output << ",\"request_id\":" << std::quoted(id);
    output << ",\"status\":\""
           << (result.cancelled   ? "cancelled"
               : result.timed_out ? "timeout"
               : !result.optimal  ? "budget_exhausted"
                                  : "complete")
           << "\",\"inverse_direction\":" << (result.inverse_direction ? "true" : "false") << ",\"moves\":";
    print_moves_json(output, result.moves);
    output << ",\"solution\":\"" << moves_text(result.moves) << "\",\"depth\":" << result.depth << ",\"metric\":\""
           << cube::metric_name(result.metric) << "\",\"optimal\":" << (result.optimal ? "true" : "false")
           << ",\"elapsed_seconds\":" << std::fixed << std::setprecision(6) << result.elapsed_seconds
           << ",\"nodes\":" << result.nodes << ",\"split_nodes\":" << result.split_nodes
           << ",\"transposition_hits\":" << result.transposition_hits << ",\"tail_queries\":" << result.tail_queries
           << ",\"tail_bloom_rejects\":" << result.tail_bloom_rejects
           << ",\"tail_exact_queries\":" << result.tail_exact_queries << ",\"tail_probes\":" << result.tail_probes
           << ",\"tail_hits\":" << result.tail_hits
           << ",\"candidate_phase1_nodes\":" << result.candidate_phase1_nodes
           << ",\"candidate_phase2_nodes\":" << result.candidate_phase2_nodes
           << ",\"candidate_improvements\":" << result.candidate_improvements
           << ",\"candidate_window_replacements\":" << result.candidate_window_replacements
           << ",\"first_candidate_seconds\":" << result.first_candidate_seconds
           << ",\"corner_pdb\":" << (solver.has_corner_pdb(result.metric) ? "true" : "false")
           << ",\"corner_pdb_metric\":\"" << cube::metric_name(solver.corner_pdb_metric(result.metric)) << "\""
           << ",\"corner_pdb_complete\":" << (solver.corner_pdb_complete(result.metric) ? "true" : "false")
           << ",\"phase1_pdb\":" << (solver.has_phase1_pdb(result.metric) ? "true" : "false")
           << ",\"phase1_pdb_metric\":\"" << cube::metric_name(solver.phase1_pdb_metric(result.metric)) << "\""
           << ",\"phase1_pdb_complete\":" << (solver.phase1_pdb_complete(result.metric) ? "true" : "false")
           << ",\"edge_pdbs\":" << (solver.has_edge_pdbs(result.metric) ? "true" : "false")
           << ",\"extra_edge_pdbs\":" << (solver.has_extra_edge_pdbs(result.metric) ? "true" : "false")
           << ",\"edge_pdb_count\":" << solver.edge_pdb_count(result.metric)
           << ",\"tail_pdb\":" << (solver.has_tail_database(result.metric) ? "true" : "false") << ",\"tail_enabled\":"
           << (solver.has_tail_database(result.metric) ? "true" : "false")
           << ",\"strong_pdb\":" << (solver.has_strong_pdb(result.metric) ? "true" : "false")
           << ",\"asset_profile\":\"" << asset_profile(solver, result.metric) << "\""
           << ",\"tail_depth\":" << solver.tail_database_depth(result.metric)
           << ",\"completed_depth\":" << result.completed_depth;
    print_counters_json(output, result.counters, result.workers);
    output << "}\n" << std::flush;
}

std::vector<std::string> split_tabs(const std::string &line) {
    std::vector<std::string> fields;
    std::size_t start = 0;
    while (true) {
        const std::size_t separator = line.find('\t', start);
        if (separator == std::string::npos) {
            fields.push_back(line.substr(start));
            return fields;
        }
        fields.push_back(line.substr(start, separator - start));
        start = separator + 1;
    }
}

bool tuning_option(const std::string &option, cube::SolverOptions &options) {
    if (option == "--no-axis-strengthening")
        options.strengthen_axes = false;
    else if (option == "--keep-small-tables")
        options.omit_covered_small_tables = false;
    else if (option == "--no-staged-expansion")
        options.staged_expansion = false;
    else if (option == "--no-direction-probe")
        options.use_direction_probe = false;
    else if (option == "--no-qtm-parity")
        options.use_qtm_parity = false;
    else if (option == "--no-native-candidate")
        options.use_native_candidate = false;
    else if (option == "--legacy-split")
        options.adaptive_split = false;
    else if (option == "--tt-every-node")
        options.selective_transposition = false;
    else if (option == "--inverse-direction")
        options.inverse_direction = true;
    else if (option == "--transposition")
        options.use_transposition = true;
    else if (option == "--no-transposition")
        options.use_transposition = false;
    else
        return false;
    return true;
}

void check_heuristic(int argc, char **argv) {
    int depth_limit = 3;
    cube::MoveMetric metric = cube::MoveMetric::HTM;
    std::filesystem::path corner_path, phase1_path, strong_path;
    for (int i = 2; i < argc; ++i) {
        const std::string flag = argv[i];
        if (flag == "--depth" && i + 1 < argc)
            depth_limit = std::stoi(argv[++i]);
        else if (flag == "--metric" && i + 1 < argc)
            metric = cube::parse_metric(argv[++i]);
        else if (flag == "--pdb" && i + 1 < argc)
            corner_path = cube::path_from_utf8(argv[++i]);
        else if (flag == "--phase1-pdb" && i + 1 < argc)
            phase1_path = cube::path_from_utf8(argv[++i]);
        else if (flag == "--strong-pdb" && i + 1 < argc)
            strong_path = cube::path_from_utf8(argv[++i]);
        else
            throw std::invalid_argument("unknown heuristic check option");
    }
    if (depth_limit < 0 || depth_limit > 5)
        throw std::invalid_argument("heuristic check depth must be 0..5");
    cube::CoordinateTables tables;
    std::unique_ptr<cube::CornerPatternDatabase> corner;
    std::unique_ptr<cube::Phase1PatternDatabase> phase1;
    std::unique_ptr<cube::StrongPatternDatabase> strong;
    if (!corner_path.empty())
        corner = std::make_unique<cube::CornerPatternDatabase>(corner_path);
    if (!phase1_path.empty())
        phase1 = std::make_unique<cube::Phase1PatternDatabase>(phase1_path);
    if (!strong_path.empty()) {
        if (metric != cube::MoveMetric::QTM)
            throw std::invalid_argument("strong PDB requires QTM heuristic verification");
        strong = std::make_unique<cube::StrongPatternDatabase>(strong_path);
    }
    cube::CoordinateFeatures features;
    features.metric = metric;
    features.strong_pdb = strong.get();
    features.axis_coordinates = bool(phase1) || bool(strong);
    features.edge_pattern_a = features.edge_pattern_b = false;
    features.small_corner = !corner || !corner->complete() ||
                            (metric == cube::MoveMetric::QTM && corner->metric() == cube::MoveMetric::HTM);
    features.small_phase1 = !phase1 || !phase1->complete() ||
                            (metric == cube::MoveMetric::QTM && phase1->metric() == cube::MoveMetric::HTM);
    features.strengthen_axes = !phase1 || phase1->metric() == cube::MoveMetric::HTM;
    std::deque<std::pair<cube::CubieCube, int>> queue{{cube::CubieCube{}, 0}};
    std::unordered_set<std::string> seen{cube::to_facelets(cube::CubieCube{})};
    std::uint64_t checked = 0;
    cube::SearchCounters counters;
    while (!queue.empty()) {
        const auto [state, depth] = queue.front();
        queue.pop_front();
        const auto coordinates = tables.from_cube(state, features);
        const auto lower = tables.heuristic(coordinates, phase1.get(), corner.get(), {}, 255, features, &counters);
        if (lower > depth || tables.materialize(coordinates) != state)
            throw std::runtime_error("heuristic exceeds BFS distance or compact state differs");
        auto baseline_features = features;
        baseline_features.strengthen_axes = false;
        baseline_features.small_phase1 = baseline_features.small_corner = true;
        const auto baseline = tables.heuristic(coordinates, phase1.get(), corner.get(), {}, 255, baseline_features);
        if (lower < baseline)
            throw std::runtime_error("optimized heuristic is weaker than covered projections");
        for (int move = 0; move < 18; ++move) {
            const auto child_cube = state.apply_move(move);
            const auto expected = tables.moved(coordinates, move, features);
            if (tables.materialize(expected) != child_cube)
                throw std::runtime_error("compact coordinate transition differs");
            for (std::uint8_t cutoff : {std::uint8_t{0}, std::uint8_t{3}, std::uint8_t{255}}) {
                cube::CoordinateState child;
                const auto bound =
                    tables.expand(coordinates, move, child, phase1.get(), corner.get(), {}, cutoff, features, counters);
                const auto full_bound = tables.heuristic(expected, phase1.get(), corner.get(), {}, 255, features);
                if ((bound <= cutoff) != (full_bound <= cutoff) ||
                    (bound <= cutoff && tables.materialize(child) != child_cube))
                    throw std::runtime_error("staged expansion differs from full evaluation");
            }
            // An independent unit-cost oracle: QTM expands only quarter turns and allows repeated faces.
            if (depth < depth_limit && cube::move_cost(move, metric) == 1 &&
                seen.insert(cube::to_facelets(child_cube)).second)
                queue.emplace_back(child_cube, depth + 1);
        }
        ++checked;
    }
    if (!features.small_phase1 && !features.small_corner && counters.small_queries != 0)
        throw std::runtime_error("complete PDB path queried covered small tables");
    std::cout << "{\"ok\":true,\"checked\":" << checked << ",\"depth\":" << depth_limit << ",\"metric\":\""
              << cube::metric_name(metric) << "\""
              << ",\"small_pdb_queries\":" << counters.small_queries << "}\n";
}

} // namespace

int wmain(int argc, wchar_t **wide_argv) {
    try {
        // Keep filesystem arguments lossless, including paths outside the ANSI code page.
        std::vector<std::string> arguments;
        arguments.reserve(argc);
        for (int index = 0; index < argc; ++index) {
            const int size =
                WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide_argv[index], -1, nullptr, 0, nullptr, nullptr);
            if (size == 0)
                throw std::invalid_argument("invalid Unicode command-line argument");
            std::string argument(size, '\0');
            if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide_argv[index], -1, argument.data(), size,
                                     nullptr, nullptr))
                throw std::invalid_argument("invalid Unicode command-line argument");
            argument.pop_back();
            arguments.push_back(std::move(argument));
        }
        std::vector<char *> argv_storage;
        for (auto &argument : arguments)
            argv_storage.push_back(argument.data());
        char **argv = argv_storage.data();
        if (argc < 2) {
            print_usage();
            return 2;
        }
        const std::string command = argv[1];
        if (command == "check-heuristic") {
            check_heuristic(argc, argv);
            return 0;
        }
        if (command == "symmetry-info") {
            cube::Phase1Symmetry symmetry;
            std::cout << "{\"ok\":true,\"symmetries\":16,\"flip_slice_classes\":" << symmetry.class_count() << "}\n";
            return 0;
        }
        if (command == "strong-symmetry-info") {
            cube::SortedSliceSymmetry symmetry;
            std::cout << "{\"ok\":true,\"raw_sorted_slice\":" << cube::kSortedSliceCount
                      << ",\"classes\":" << symmetry.class_count() << ",\"joint_entries\":"
                      << static_cast<std::uint64_t>(symmetry.class_count()) * 2048U * 2187U << "}\n";
            return 0;
        }
        if (command == "build-strong-pdb") {
            if (argc < 3) {
                print_usage();
                return 2;
            }
            int threads = 8;
            int coverage_depth = 254;
            bool resume = false;
            double memory_limit_gib = 12.0;
            cube::MoveMetric metric = cube::MoveMetric::QTM;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--threads" && index + 1 < argc)
                    threads = std::stoi(argv[++index]);
                else if (option == "--coverage-depth" && index + 1 < argc)
                    coverage_depth = std::stoi(argv[++index]);
                else if (option == "--memory-limit-gib" && index + 1 < argc)
                    memory_limit_gib = std::stod(argv[++index]);
                else if (option == "--metric" && index + 1 < argc)
                    metric = cube::parse_metric(argv[++index]);
                else if (option == "--resume")
                    resume = true;
                else
                    throw std::invalid_argument("unknown strong PDB build option: " + option);
            }
            if (metric != cube::MoveMetric::QTM)
                throw std::invalid_argument("strong PDB currently requires QTM");
            cube::CoordinateTables tables;
            const auto path = cube::path_from_utf8(argv[2]);
            cube::build_strong_pattern_database(path, tables, threads, coverage_depth, resume, memory_limit_gib);
            cube::StrongPatternDatabase pdb(path);
            std::cout << "{\"ok\":true,\"metric\":\"QTM\",\"entries\":" << cube::kStrongPatternEntries
                      << ",\"complete\":" << (pdb.complete() ? "true" : "false")
                      << ",\"coverage_depth\":" << pdb.coverage_depth() << ",\"max_distance\":"
                      << static_cast<int>(pdb.max_distance()) << "}\n";
            return 0;
        }
        if (command == "verify-strong-pdb") {
            if (argc < 3) {
                print_usage();
                return 2;
            }
            int threads = 8;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--threads" && index + 1 < argc)
                    threads = std::stoi(argv[++index]);
                else
                    throw std::invalid_argument("unknown strong verification option: " + option);
            }
            cube::CoordinateTables tables;
            cube::StrongPatternDatabase pdb(cube::path_from_utf8(argv[2]));
            const auto verified = pdb.verify_all(tables, threads);
            std::cout << "{\"ok\":true,\"metric\":\"QTM\",\"entries\":" << verified.entries
                      << ",\"histogram\":[";
            for (int depth = 0; depth <= pdb.max_distance(); ++depth) {
                if (depth)
                    std::cout << ',';
                std::cout << verified.distance_histogram[static_cast<std::size_t>(depth)];
            }
            std::cout << "]}\n";
            return 0;
        }
        if (command == "fast-solve") {
            if (argc < 3) {
                print_usage();
                return 2;
            }
            std::filesystem::path phase1_path;
            std::filesystem::path tail_path;
            cube::FastCandidateOptions options;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--qtm-phase1-pdb" && index + 1 < argc)
                    phase1_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-tail-pdb" && index + 1 < argc)
                    tail_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--timeout" && index + 1 < argc)
                    options.timeout_seconds = std::stod(argv[++index]);
                else if (option == "--incumbent-cost" && index + 1 < argc)
                    options.incumbent_cost = std::stoi(argv[++index]);
                else if (option == "--max-phase1-cost" && index + 1 < argc)
                    options.max_phase1_cost = std::stoi(argv[++index]);
                else if (option == "--max-phase2-cost" && index + 1 < argc)
                    options.max_phase2_cost = std::stoi(argv[++index]);
                else
                    throw std::invalid_argument("unknown fast-solve option: " + option);
            }
            if (phase1_path.empty())
                throw std::invalid_argument("fast-solve requires --qtm-phase1-pdb");
            cube::CoordinateTables tables;
            cube::Phase1PatternDatabase phase1(phase1_path);
            std::unique_ptr<cube::TailDatabase> tail;
            if (!tail_path.empty()) {
                tail = std::make_unique<cube::TailDatabase>(tail_path);
                if (tail->metric() != cube::MoveMetric::QTM)
                    throw std::invalid_argument("fast-solve QTM tail asset has the wrong metric");
                options.local_tail = tail.get();
            }
            const auto state = cube::from_facelets(argv[2]);
            const auto result = cube::find_fast_qtm_candidate(state, tables, phase1, options);
            std::cout << "{\"ok\":true,\"metric\":\"QTM\",\"cost\":" << result.cost
                      << ",\"moves\":[";
            for (std::size_t index = 0; index < result.moves.size(); ++index) {
                if (index)
                    std::cout << ',';
                std::cout << '"' << cube::kMoveNames[result.moves[index]] << '"';
            }
            std::cout << "],\"phase1_nodes\":" << result.phase1_nodes
                      << ",\"phase2_nodes\":" << result.phase2_nodes
                      << ",\"phase1_max_distance\":" << result.phase1_max_distance
                      << ",\"phase2_max_distance\":" << result.phase2_max_distance
                      << ",\"improvements\":" << result.improvements
                      << ",\"window_replacements\":" << result.window_replacements
                      << ",\"timed_out\":" << (result.timed_out ? "true" : "false") << "}\n";
            return 0;
        }
        if (command == "verify-pdb") {
            if (argc < 3) {
                print_usage();
                return 2;
            }
            std::string pattern;
            int group = -1;
            int threads = static_cast<int>(std::max(1U, std::thread::hardware_concurrency()));
            bool full = false;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--pattern" && index + 1 < argc)
                    pattern = argv[++index];
                else if (option == "--group" && index + 1 < argc)
                    group = std::stoi(argv[++index]);
                else if (option == "--threads" && index + 1 < argc)
                    threads = std::stoi(argv[++index]);
                else if (option == "--full")
                    full = true;
                else
                    throw std::invalid_argument("unknown PDB verification option: " + option);
            }
            if (!full)
                throw std::invalid_argument("verify-pdb requires --full");
            const auto path = cube::path_from_utf8(argv[2]);
            cube::PdbVerification verified;
            if (pattern == "edge")
                verified = cube::verify_qtm_edge_pdb(path, group, threads);
            else if (pattern == "corner" || pattern == "phase1") {
                cube::CoordinateTables tables;
                verified = pattern == "corner" ? cube::verify_qtm_corner_pdb(path, tables, threads)
                                                   : cube::verify_qtm_phase1_pdb(path, tables, threads);
            } else
                throw std::invalid_argument("PDB pattern must be corner, phase1 or edge");
            std::cout << "{\"ok\":true,\"metric\":\"QTM\",\"pattern\":" << std::quoted(pattern)
                      << ",\"checked\":" << verified.checked << ",\"transitions\":" << verified.transitions
                      << ",\"max_distance\":" << verified.max_distance << ",\"histogram\":[";
            for (int distance = 0; distance <= verified.max_distance; ++distance) {
                if (distance)
                    std::cout << ',';
                std::cout << verified.histogram[distance];
            }
            std::cout << "]}\n";
            return 0;
        }
        if (command == "build-corner-pdb") {
            if (argc < 3) {
                print_usage();
                return 2;
            }
            int threads = static_cast<int>(std::max(1U, std::thread::hardware_concurrency()));
            int coverage_depth = -1;
            cube::MoveMetric metric = cube::MoveMetric::HTM;
            bool force = false;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--threads" && index + 1 < argc)
                    threads = std::stoi(argv[++index]);
                else if (option == "--coverage-depth" && index + 1 < argc)
                    coverage_depth = std::stoi(argv[++index]);
                else if (option == "--metric" && index + 1 < argc)
                    metric = cube::parse_metric(argv[++index]);
                else if (option == "--force")
                    force = true;
                else
                    throw std::invalid_argument("unknown build option: " + option);
            }
            auto tables = std::make_shared<cube::CoordinateTables>();
            if (coverage_depth < 0)
                coverage_depth = metric == cube::MoveMetric::QTM ? 254 : 11;
            if (metric == cube::MoveMetric::QTM)
                cube::build_qtm_corner_pattern_database(cube::path_from_utf8(argv[2]), *tables, threads,
                                                        coverage_depth, force);
            else
                cube::build_corner_pattern_database(cube::path_from_utf8(argv[2]), *tables, threads,
                                                    coverage_depth, force);
            cube::CornerPatternDatabase pdb(cube::path_from_utf8(argv[2]));
            std::cout << "{\"ok\":true,\"complete\":" << (pdb.complete() ? "true" : "false")
                      << ",\"metric\":\"" << cube::metric_name(pdb.metric()) << "\",\"coverage_depth\":"
                      << pdb.coverage_depth() << ",\"max_value\":" << static_cast<int>(pdb.max_value()) << "}\n";
            return 0;
        }
        if (command == "build-phase1-pdb") {
            if (argc < 3) {
                print_usage();
                return 2;
            }
            int threads = static_cast<int>(std::max(1U, std::thread::hardware_concurrency()));
            int coverage_depth = -1;
            cube::MoveMetric metric = cube::MoveMetric::HTM;
            bool force = false;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--threads" && index + 1 < argc)
                    threads = std::stoi(argv[++index]);
                else if (option == "--coverage-depth" && index + 1 < argc)
                    coverage_depth = std::stoi(argv[++index]);
                else if (option == "--metric" && index + 1 < argc)
                    metric = cube::parse_metric(argv[++index]);
                else if (option == "--force")
                    force = true;
                else
                    throw std::invalid_argument("unknown build option: " + option);
            }
            auto tables = std::make_shared<cube::CoordinateTables>();
            if (coverage_depth < 0)
                coverage_depth = metric == cube::MoveMetric::QTM ? 254 : 12;
            if (metric == cube::MoveMetric::QTM)
                cube::build_qtm_phase1_pattern_database(cube::path_from_utf8(argv[2]), *tables, threads,
                                                        coverage_depth, force);
            else
                cube::build_phase1_pattern_database(cube::path_from_utf8(argv[2]), *tables, threads,
                                                    coverage_depth, force);
            cube::Phase1PatternDatabase pdb(cube::path_from_utf8(argv[2]));
            std::cout << "{\"ok\":true,\"complete\":" << (pdb.complete() ? "true" : "false")
                      << ",\"metric\":\"" << cube::metric_name(pdb.metric()) << "\",\"coverage_depth\":"
                      << pdb.coverage_depth() << ",\"max_value\":" << static_cast<int>(pdb.max_value()) << "}\n";
            return 0;
        }
        if (command == "build-edge-pdb") {
            if (argc < 3) {
                print_usage();
                return 2;
            }
            int threads = static_cast<int>(std::max(1U, std::thread::hardware_concurrency()));
            int coverage_depth = -1;
            cube::MoveMetric metric = cube::MoveMetric::HTM;
            int group = -1;
            bool force = false;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--threads" && index + 1 < argc)
                    threads = std::stoi(argv[++index]);
                else if (option == "--coverage-depth" && index + 1 < argc)
                    coverage_depth = std::stoi(argv[++index]);
                else if (option == "--metric" && index + 1 < argc)
                    metric = cube::parse_metric(argv[++index]);
                else if (option == "--group" && index + 1 < argc)
                    group = std::stoi(argv[++index]);
                else if (option == "--first-edge" && index + 1 < argc) {
                    const int first_edge = std::stoi(argv[++index]);
                    group = first_edge == 0 ? 0 : first_edge == 6 ? 1 : -1;
                } else if (option == "--force")
                    force = true;
                else
                    throw std::invalid_argument("unknown build option: " + option);
            }
            if (coverage_depth < 0)
                coverage_depth = metric == cube::MoveMetric::QTM ? 254 : 10;
            if (metric == cube::MoveMetric::QTM)
                cube::build_qtm_edge_pattern_database(cube::path_from_utf8(argv[2]), group, threads,
                                                      coverage_depth, force);
            else
                cube::build_edge_pattern_database(cube::path_from_utf8(argv[2]), group, threads,
                                                  coverage_depth, force);
            cube::EdgePatternDatabase pdb(cube::path_from_utf8(argv[2]), group);
            std::cout << "{\"ok\":true,\"complete\":" << (pdb.complete() ? "true" : "false")
                      << ",\"metric\":\"" << cube::metric_name(pdb.metric()) << "\",\"coverage_depth\":"
                      << pdb.coverage_depth() << ",\"max_value\":" << static_cast<int>(pdb.max_value()) << "}\n";
            return 0;
        }
        if (command == "build-tail-pdb") {
            if (argc < 3) {
                print_usage();
                return 2;
            }
            int depth = 6;
            int threads = static_cast<int>(std::max(1U, std::thread::hardware_concurrency()));
            bool force = false;
            cube::MoveMetric metric = cube::MoveMetric::HTM;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--depth" && index + 1 < argc)
                    depth = std::stoi(argv[++index]);
                else if (option == "--threads" && index + 1 < argc)
                    threads = std::stoi(argv[++index]);
                else if (option == "--metric" && index + 1 < argc)
                    metric = cube::parse_metric(argv[++index]);
                else if (option == "--force")
                    force = true;
                else
                    throw std::invalid_argument("unknown build option: " + option);
            }
            cube::build_tail_database(cube::path_from_utf8(argv[2]), depth, threads, force, metric);
            cube::TailDatabase tail(cube::path_from_utf8(argv[2]));
            std::cout << "{\"ok\":true,\"metric\":\"" << cube::metric_name(tail.metric())
                      << "\",\"depth\":" << tail.depth() << ",\"version\":" << tail.format_version()
                      << "}\n";
            return 0;
        }
        if (command == "verify-tail-pdb") {
            if (argc < 3) {
                print_usage();
                return 2;
            }
            int threads = 0;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--threads" && index + 1 < argc)
                    threads = std::stoi(argv[++index]);
                else
                    throw std::invalid_argument("unknown tail verification option: " + option);
            }
            cube::TailDatabase tail(cube::path_from_utf8(argv[2]));
            const auto verified = tail.verify_all(threads);
            std::cout << "{\"ok\":true,\"metric\":\"" << cube::metric_name(tail.metric())
                      << "\",\"depth\":" << tail.depth() << ",\"states\":" << verified.states
                      << ",\"histogram\":[";
            for (int depth = 0; depth <= tail.depth(); ++depth) {
                if (depth)
                    std::cout << ',';
                std::cout << verified.distance_histogram[static_cast<std::size_t>(depth)];
            }
            std::cout << "]}\n";
            return 0;
        }
        if (command == "serve") {
            cube::SolverOptions defaults;
            bool use_proof_cache = true;
            std::filesystem::path pdb_path;
            std::filesystem::path phase1_pdb_path;
            std::filesystem::path qtm_pdb_path;
            std::filesystem::path qtm_phase1_pdb_path;
            std::filesystem::path strong_pdb_path;
            std::filesystem::path tail_pdb_path;
            std::filesystem::path qtm_tail_pdb_path;
            std::array<std::filesystem::path, 8> edge_pdb_paths{};
            std::array<std::filesystem::path, 2> qtm_edge_pdb_paths{};
            const std::array<std::string, 8> edge_flags{"--edge-pdb-a", "--edge-pdb-b", "--edge-pdb-c", "--edge-pdb-d",
                                                        "--edge-pdb-e", "--edge-pdb-f", "--edge-pdb-g", "--edge-pdb-h"};
            for (int index = 2; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--pdb" && index + 1 < argc)
                    pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--phase1-pdb" && index + 1 < argc)
                    phase1_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-pdb" && index + 1 < argc)
                    qtm_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-phase1-pdb" && index + 1 < argc)
                    qtm_phase1_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--strong-pdb" && index + 1 < argc)
                    strong_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-edge-pdb-a" && index + 1 < argc)
                    qtm_edge_pdb_paths[0] = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-edge-pdb-b" && index + 1 < argc)
                    qtm_edge_pdb_paths[1] = cube::path_from_utf8(argv[++index]);
                else if (option == "--tail-pdb" && index + 1 < argc)
                    tail_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-tail-pdb" && index + 1 < argc)
                    qtm_tail_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--no-proof-cache")
                    use_proof_cache = false;
                else if (tuning_option(option, defaults))
                    continue;
                else {
                    const auto flag = std::find(edge_flags.begin(), edge_flags.end(), option);
                    if (flag == edge_flags.end() || index + 1 >= argc) {
                        throw std::invalid_argument("unknown serve option: " + option);
                    }
                    edge_pdb_paths[static_cast<std::size_t>(flag - edge_flags.begin())] =
                        cube::path_from_utf8(argv[++index]);
                }
            }

            cube::NativeOptimalSolver solver;
            if (!phase1_pdb_path.empty())
                solver.load_phase1_pdb(phase1_pdb_path, cube::MoveMetric::HTM);
            if (!qtm_phase1_pdb_path.empty())
                solver.load_phase1_pdb(qtm_phase1_pdb_path, cube::MoveMetric::QTM);
            if (!pdb_path.empty())
                solver.load_corner_pdb(pdb_path, cube::MoveMetric::HTM);
            if (!qtm_pdb_path.empty())
                solver.load_corner_pdb(qtm_pdb_path, cube::MoveMetric::QTM);
            for (int group = 0; group < 8; ++group) {
                if (!edge_pdb_paths[group].empty())
                    solver.load_edge_pdb(group, edge_pdb_paths[group], cube::MoveMetric::HTM);
            }
            for (int group = 0; group < 2; ++group)
                if (!qtm_edge_pdb_paths[group].empty())
                    solver.load_edge_pdb(group, qtm_edge_pdb_paths[group], cube::MoveMetric::QTM);
            if (!tail_pdb_path.empty())
                solver.load_tail_database(tail_pdb_path);
            if (!qtm_tail_pdb_path.empty())
                solver.load_tail_database(qtm_tail_pdb_path, cube::MoveMetric::QTM);
            if (!strong_pdb_path.empty())
                solver.load_strong_pdb(strong_pdb_path);
            std::cout << "{\"ok\":true,\"type\":\"ready\",\"protocol_version\":3,\"proof_version\":3,\"metrics\":["
                         "\"HTM\",\"QTM\"],\"assets\":{";
            for (const auto metric : {cube::MoveMetric::HTM, cube::MoveMetric::QTM}) {
                if (metric == cube::MoveMetric::QTM)
                    std::cout << ',';
                std::cout << '\"' << cube::metric_name(metric) << "\":{\"corner\":"
                          << (solver.has_corner_pdb(metric) ? "true" : "false") << ",\"corner_metric\":\""
                          << cube::metric_name(solver.corner_pdb_metric(metric)) << "\",\"corner_complete\":"
                          << (solver.corner_pdb_complete(metric) ? "true" : "false") << ",\"phase1\":"
                          << (solver.has_phase1_pdb(metric) ? "true" : "false") << ",\"phase1_metric\":\""
                          << cube::metric_name(solver.phase1_pdb_metric(metric)) << "\",\"phase1_complete\":"
                          << (solver.phase1_pdb_complete(metric) ? "true" : "false") << ",\"edge_count\":"
                          << solver.edge_pdb_count(metric) << ",\"tail\":"
                          << (solver.has_tail_database(metric) ? "true" : "false") << ",\"strong\":"
                          << (solver.has_strong_pdb(metric) ? "true" : "false") << ",\"tail_depth\":"
                          << solver.tail_database_depth(metric) << ",\"profile\":\""
                          << asset_profile(solver, metric) << "\"}";
            }
            std::cout << "}}\n" << std::flush;

            std::thread search;
            std::atomic<bool> running{false};
            std::atomic<bool> cancel{false};
            std::mutex output_mutex;
            std::mutex incumbent_mutex;
            std::vector<int> incumbent;
            std::string active_id;
            cube::CubieCube active_state;
            cube::MoveMetric active_metric{cube::MoveMetric::HTM};
            // In-memory only: loaded PDBs and proof rules are immutable for this process.
            std::unordered_map<std::string, int> proofs;
            std::string request;
            while (std::getline(std::cin, request)) {
                std::string id;
                try {
                    const auto fields = split_tabs(request);
                    if (fields.size() == 2 && fields[0] == "cancel") {
                        if (fields[1] == active_id)
                            cancel.store(true);
                        continue;
                    }
                    if (fields.size() == 3 && fields[0] == "incumbent") {
                        if (fields[1] == active_id && running.load()) {
                            auto moves = parse_moves(fields[2]);
                            auto candidate = active_state;
                            for (int move : moves)
                                candidate = candidate.apply_move(move);
                            if (!candidate.solved())
                                throw std::invalid_argument("updated incumbent does not solve the cube");
                            std::lock_guard lock(incumbent_mutex);
                            if (incumbent.empty() || cube::solution_cost(moves, active_metric) <
                                                         cube::solution_cost(incumbent, active_metric))
                                incumbent = std::move(moves);
                        }
                        continue;
                    }
                    const bool framed = (fields.size() == 7 || fields.size() == 8) && fields[0] == "solve";
                    if (!framed && fields.size() != 5)
                        throw std::invalid_argument("invalid serve request");
                    const int offset = framed ? 2 : 0;
                    id = framed ? fields[1] : "";
                    if (running.load())
                        throw std::invalid_argument("service is already searching");
                    if (search.joinable())
                        search.join();
                    active_state = cube::from_facelets(fields[offset]);
                    active_id = id;
                    cube::SolverOptions options = defaults;
                    options.max_depth = parse_integer(fields[offset + 1]);
                    if (options.max_depth < 0)
                        throw std::invalid_argument("max depth must be nonnegative");
                    options.timeout_seconds = std::stod(fields[offset + 2]);
                    options.threads = parse_integer(fields[offset + 3]);
                    options.metric =
                        fields.size() == 8 ? cube::parse_metric(fields[offset + 4]) : cube::MoveMetric::HTM;
                    active_metric = options.metric;
                    options.incumbent_moves = parse_moves(fields[offset + (fields.size() == 8 ? 5 : 4)]);
                    incumbent = options.incumbent_moves;
                    cancel.store(false);
                    options.cancel_requested = &cancel;
                    const auto key =
                        cube::to_facelets(active_state) + ":" + cube::metric_name(options.metric) + ":proof3";
                    const auto previous = proofs.find(key);
                    if (framed && use_proof_cache && previous != proofs.end())
                        options.completed_depth = previous->second;
                    // Legacy benchmark requests deliberately rerun each proof.
                    options.incumbent_callback = [&] {
                        std::lock_guard lock(incumbent_mutex);
                        return incumbent;
                    };
                    options.candidate_callback = [&, id](const std::vector<int> &moves) {
                        const int cost = cube::solution_cost(moves, cube::MoveMetric::QTM);
                        {
                            std::lock_guard lock(incumbent_mutex);
                            if (incumbent.empty() || cost < cube::solution_cost(incumbent, cube::MoveMetric::QTM))
                                incumbent = moves;
                        }
                        std::lock_guard lock(output_mutex);
                        std::cout << "{\"ok\":true,\"type\":\"candidate\",\"request_id\":"
                                  << std::quoted(id) << ",\"metric\":\"QTM\",\"cost\":" << cost
                                  << ",\"moves\":";
                        print_moves_json(std::cout, moves);
                        std::cout << "}\n" << std::flush;
                    };
                    running.store(true);
                    search = std::thread([&, options, id, key, framed, state = active_state]() mutable {
                        int completed = options.completed_depth;
                        options.progress_callback = [&](const cube::NativeSearchProgress &progress) {
                            completed = std::max(completed, progress.completed_depth);
                            std::lock_guard lock(output_mutex);
                            print_progress_json(std::cout, progress, id);
                        };
                        try {
                            const auto result = solver.solve(state, options);
                            completed = std::max(completed, result.completed_depth);
                            if (framed && use_proof_cache) {
                                if (proofs.size() >= 128 && !proofs.contains(key))
                                    proofs.erase(proofs.begin());
                                proofs[key] = completed;
                            }
                            // Mark idle under the output lock before the terminal frame is observed.
                            std::lock_guard lock(output_mutex);
                            running.store(false);
                            print_result_json(std::cout, result, solver, true, id);
                        } catch (const std::exception &error) {
                            std::lock_guard lock(output_mutex);
                            running.store(false);
                            std::cout << "{\"ok\":false,\"type\":\"error\",\"request_id\":" << std::quoted(id)
                                      << ",\"error\":" << std::quoted(error.what()) << "}\n"
                                      << std::flush;
                        }
                    });
                } catch (const std::exception &error) {
                    std::lock_guard lock(output_mutex);
                    std::cout << "{\"ok\":false,\"type\":\"error\",\"request_id\":" << std::quoted(id)
                              << ",\"error\":" << std::quoted(error.what()) << "}\n"
                              << std::flush;
                }
            }
            cancel.store(true);
            if (search.joinable())
                search.join();
            return 0;
        }
        if (argc < 3) {
            print_usage();
            return 2;
        }

        cube::CubieCube state = cube::from_facelets(argv[2]);
        if (command == "solve") {
            cube::SolverOptions options;
            bool explicit_max_depth = false;
            options.progress_callback = [](const cube::NativeSearchProgress &progress) {
                print_progress_json(std::cerr, progress);
            };
            std::filesystem::path pdb_path;
            std::filesystem::path phase1_pdb_path;
            std::filesystem::path qtm_pdb_path;
            std::filesystem::path qtm_phase1_pdb_path;
            std::filesystem::path strong_pdb_path;
            std::filesystem::path edge_pdb_a_path;
            std::filesystem::path edge_pdb_b_path;
            std::filesystem::path qtm_edge_pdb_a_path;
            std::filesystem::path qtm_edge_pdb_b_path;
            std::filesystem::path edge_pdb_c_path;
            std::filesystem::path edge_pdb_d_path;
            std::array<std::filesystem::path, 4> more_edge_pdb_paths{};
            std::filesystem::path tail_pdb_path;
            std::filesystem::path qtm_tail_pdb_path;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--max-depth" && index + 1 < argc) {
                    options.max_depth = parse_integer(argv[++index]);
                    explicit_max_depth = true;
                } else if (option == "--metric" && index + 1 < argc)
                    options.metric = cube::parse_metric(argv[++index]);
                else if (option == "--timeout" && index + 1 < argc)
                    options.timeout_seconds = std::stod(argv[++index]);
                else if (option == "--threads" && index + 1 < argc)
                    options.threads = std::stoi(argv[++index]);
                else if (option == "--pdb" && index + 1 < argc)
                    pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--phase1-pdb" && index + 1 < argc)
                    phase1_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-pdb" && index + 1 < argc)
                    qtm_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-phase1-pdb" && index + 1 < argc)
                    qtm_phase1_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--strong-pdb" && index + 1 < argc)
                    strong_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-edge-pdb-a" && index + 1 < argc)
                    qtm_edge_pdb_a_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-edge-pdb-b" && index + 1 < argc)
                    qtm_edge_pdb_b_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--edge-pdb-a" && index + 1 < argc)
                    edge_pdb_a_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--edge-pdb-b" && index + 1 < argc)
                    edge_pdb_b_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--edge-pdb-c" && index + 1 < argc)
                    edge_pdb_c_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--edge-pdb-d" && index + 1 < argc)
                    edge_pdb_d_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--edge-pdb-e" && index + 1 < argc)
                    more_edge_pdb_paths[0] = cube::path_from_utf8(argv[++index]);
                else if (option == "--edge-pdb-f" && index + 1 < argc)
                    more_edge_pdb_paths[1] = cube::path_from_utf8(argv[++index]);
                else if (option == "--edge-pdb-g" && index + 1 < argc)
                    more_edge_pdb_paths[2] = cube::path_from_utf8(argv[++index]);
                else if (option == "--edge-pdb-h" && index + 1 < argc)
                    more_edge_pdb_paths[3] = cube::path_from_utf8(argv[++index]);
                else if (option == "--tail-pdb" && index + 1 < argc)
                    tail_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-tail-pdb" && index + 1 < argc)
                    qtm_tail_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--incumbent" && index + 1 < argc)
                    options.incumbent_moves = parse_moves(argv[++index]);
                else if (tuning_option(option, options))
                    continue;
                else
                    throw std::invalid_argument("unknown solve option: " + option);
            }
            if (!explicit_max_depth)
                options.max_depth = cube::default_max_depth(options.metric);
            else if (options.max_depth < 0)
                throw std::invalid_argument("max depth must be nonnegative");
            cube::NativeOptimalSolver solver;
            if (!phase1_pdb_path.empty() && std::filesystem::exists(phase1_pdb_path)) {
                solver.load_phase1_pdb(phase1_pdb_path, cube::MoveMetric::HTM);
            }
            if (!qtm_phase1_pdb_path.empty()) {
                if (!std::filesystem::exists(qtm_phase1_pdb_path))
                    throw std::invalid_argument("QTM phase-1 PDB does not exist");
                solver.load_phase1_pdb(qtm_phase1_pdb_path, cube::MoveMetric::QTM);
            }
            if (!pdb_path.empty() && std::filesystem::exists(pdb_path))
                solver.load_corner_pdb(pdb_path, cube::MoveMetric::HTM);
            if (!qtm_pdb_path.empty()) {
                if (!std::filesystem::exists(qtm_pdb_path))
                    throw std::invalid_argument("QTM corner PDB does not exist");
                solver.load_corner_pdb(qtm_pdb_path, cube::MoveMetric::QTM);
            }
            if (!strong_pdb_path.empty())
                solver.load_strong_pdb(strong_pdb_path);
            const std::array<std::filesystem::path, 4> first_edge_pdb_paths{edge_pdb_a_path, edge_pdb_b_path,
                                                                            edge_pdb_c_path, edge_pdb_d_path};
            for (int group = 0; group < 4; ++group) {
                const auto &path = first_edge_pdb_paths[group];
                if (!path.empty()) {
                    if (!std::filesystem::exists(path))
                        throw std::invalid_argument("edge PDB does not exist");
                    solver.load_edge_pdb(group, path, cube::MoveMetric::HTM);
                }
            }
            for (int group = 4; group < 8; ++group) {
                const auto &path = more_edge_pdb_paths[group - 4];
                if (!path.empty()) {
                    if (!std::filesystem::exists(path))
                        throw std::invalid_argument("extra edge PDB does not exist");
                    solver.load_edge_pdb(group, path, cube::MoveMetric::HTM);
                }
            }
            if (!qtm_edge_pdb_a_path.empty())
                solver.load_edge_pdb(0, qtm_edge_pdb_a_path, cube::MoveMetric::QTM);
            if (!qtm_edge_pdb_b_path.empty())
                solver.load_edge_pdb(1, qtm_edge_pdb_b_path, cube::MoveMetric::QTM);
            if (!tail_pdb_path.empty()) {
                if (!std::filesystem::exists(tail_pdb_path))
                    throw std::invalid_argument("tail database does not exist");
                solver.load_tail_database(tail_pdb_path);
            }
            if (!qtm_tail_pdb_path.empty())
                solver.load_tail_database(qtm_tail_pdb_path, cube::MoveMetric::QTM);
            const auto result = solver.solve(state, options);
            print_result_json(std::cout, result, solver);
            return 0;
        }
        if (command == "apply") {
            for (int i = 3; i < argc; ++i) {
                const int move = cube::move_index(argv[i]);
                if (move < 0)
                    throw std::invalid_argument("unknown move: " + std::string(argv[i]));
                state = state.apply_move(move);
            }
        } else if (command != "validate") {
            print_usage();
            return 2;
        }
        std::cout << "{\"ok\":true,\"facelets\":\"" << cube::to_facelets(state) << "\",\"inverse_facelets\":\""
                  << cube::to_facelets(state.inverse()) << "\",\"twist\":" << cube::twist_coord(state)
                  << ",\"flip\":" << cube::flip_coord(state) << ",\"corner_perm\":" << cube::corner_perm_coord(state)
                  << ",\"slice_comb\":" << cube::slice_comb_coord(state)
                  << ",\"corner_pattern\":" << cube::corner_pattern_coord(state)
                  << ",\"edge_pattern_a\":" << cube::edge_pattern_coord(cube::edge_pattern_state(state, 0))
                  << ",\"edge_pattern_b\":" << cube::edge_pattern_coord(cube::edge_pattern_state(state, 6)) << "}\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "{\"ok\":false,\"error\":\"" << error.what() << "\"}\n";
        return 1;
    }
}
