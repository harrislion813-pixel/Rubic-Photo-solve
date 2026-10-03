#include "cube.hpp"
#include "paths.hpp"
#include "pdb.hpp"
#include "solver.hpp"
#include "symmetry.hpp"
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

void print_usage() {
    std::cerr << "usage:\n"
              << "  cube_solver validate FACELETS\n"
              << "  cube_solver apply FACELETS [MOVES...]\n"
              << "  cube_solver symmetry-info\n"
              << "  cube_solver solve FACELETS [--max-depth N] [--timeout S] [--threads N]\n"
              << "                    [--pdb PATH] [--incumbent \"MOVES\"] [--transposition]\n"
              << "  cube_solver serve [--pdb PATH] [--phase1-pdb PATH] [--tail-pdb PATH]\n"
              << "  cube_solver build-corner-pdb PATH [--coverage-depth N] [--threads N] [--force]\n"
              << "  cube_solver build-phase1-pdb PATH [--coverage-depth N] [--threads N] [--force]\n"
              << "  cube_solver build-edge-pdb PATH --group 0..7 [--coverage-depth N]\n"
              << "                    [--threads N] [--force]\n"
              << "  cube_solver build-tail-pdb PATH [--depth 0..7] [--threads N] [--force]\n";
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
           << ",\"edge_queries\":" << counters.edge_queries << ",\"axis_rejects\":[" << counters.axis_rejects[0] << ','
           << counters.axis_rejects[1] << ',' << counters.axis_rejects[2] << ']'
           << ",\"equality_rejects\":" << counters.equality_rejects << ",\"corner_rejects\":" << counters.corner_rejects
           << ",\"edge_rejects\":" << counters.edge_rejects << ",\"workers\":[";
    for (std::size_t i = 0; i < workers.size(); ++i) {
        if (i)
            output << ',';
        output << "{\"nodes\":" << workers[i].nodes << ",\"generated\":" << workers[i].generated
               << ",\"busy_seconds\":" << workers[i].busy_seconds << ",\"idle_seconds\":" << workers[i].idle_seconds
               << '}';
    }
    output << ']';
}

void print_progress_json(std::ostream &output, const cube::NativeSearchProgress &progress, const std::string &id = "") {
    output << "{\"type\":\"progress\",\"threads\":" << progress.threads << ",\"lower_bound\":" << progress.lower_bound
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
                                  : "complete")
           << "\",\"inverse_direction\":" << (result.inverse_direction ? "true" : "false") << ",\"moves\":";
    print_moves_json(output, result.moves);
    output << ",\"solution\":\"" << moves_text(result.moves) << "\",\"depth\":" << result.depth
           << ",\"metric\":\"HTM\",\"optimal\":" << (result.optimal ? "true" : "false")
           << ",\"elapsed_seconds\":" << std::fixed << std::setprecision(6) << result.elapsed_seconds
           << ",\"nodes\":" << result.nodes << ",\"split_nodes\":" << result.split_nodes
           << ",\"transposition_hits\":" << result.transposition_hits << ",\"tail_queries\":" << result.tail_queries
           << ",\"tail_bloom_rejects\":" << result.tail_bloom_rejects
           << ",\"tail_exact_queries\":" << result.tail_exact_queries << ",\"tail_probes\":" << result.tail_probes
           << ",\"tail_hits\":" << result.tail_hits
           << ",\"corner_pdb\":" << (solver.has_corner_pdb() ? "true" : "false")
           << ",\"phase1_pdb\":" << (solver.has_phase1_pdb() ? "true" : "false")
           << ",\"edge_pdbs\":" << (solver.has_edge_pdbs() ? "true" : "false")
           << ",\"extra_edge_pdbs\":" << (solver.has_extra_edge_pdbs() ? "true" : "false")
           << ",\"edge_pdb_count\":" << solver.edge_pdb_count()
           << ",\"tail_pdb\":" << (solver.has_tail_database() ? "true" : "false")
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
    std::filesystem::path corner_path, phase1_path;
    for (int i = 2; i < argc; ++i) {
        const std::string flag = argv[i];
        if (flag == "--depth" && i + 1 < argc)
            depth_limit = std::stoi(argv[++i]);
        else if (flag == "--pdb" && i + 1 < argc)
            corner_path = cube::path_from_utf8(argv[++i]);
        else if (flag == "--phase1-pdb" && i + 1 < argc)
            phase1_path = cube::path_from_utf8(argv[++i]);
        else
            throw std::invalid_argument("unknown heuristic check option");
    }
    if (depth_limit < 0 || depth_limit > 4)
        throw std::invalid_argument("heuristic check depth must be 0..4");
    cube::CoordinateTables tables;
    std::unique_ptr<cube::CornerPatternDatabase> corner;
    std::unique_ptr<cube::Phase1PatternDatabase> phase1;
    if (!corner_path.empty())
        corner = std::make_unique<cube::CornerPatternDatabase>(corner_path);
    if (!phase1_path.empty())
        phase1 = std::make_unique<cube::Phase1PatternDatabase>(phase1_path);
    cube::CoordinateFeatures features;
    features.axis_coordinates = bool(phase1);
    features.edge_pattern_a = features.edge_pattern_b = false;
    features.small_corner = !corner || !corner->complete();
    features.small_phase1 = !phase1 || !phase1->complete();
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
            if (depth < depth_limit && seen.insert(cube::to_facelets(child_cube)).second)
                queue.emplace_back(child_cube, depth + 1);
        }
        ++checked;
    }
    if (!features.small_phase1 && !features.small_corner && counters.small_queries != 0)
        throw std::runtime_error("complete PDB path queried covered small tables");
    std::cout << "{\"ok\":true,\"checked\":" << checked << ",\"depth\":" << depth_limit
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
        if (command == "build-corner-pdb") {
            if (argc < 3) {
                print_usage();
                return 2;
            }
            int threads = static_cast<int>(std::max(1U, std::thread::hardware_concurrency()));
            int coverage_depth = 11;
            bool force = false;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--threads" && index + 1 < argc)
                    threads = std::stoi(argv[++index]);
                else if (option == "--coverage-depth" && index + 1 < argc)
                    coverage_depth = std::stoi(argv[++index]);
                else if (option == "--force")
                    force = true;
                else
                    throw std::invalid_argument("unknown build option: " + option);
            }
            auto tables = std::make_shared<cube::CoordinateTables>();
            cube::build_corner_pattern_database(cube::path_from_utf8(argv[2]), *tables, threads, coverage_depth, force);
            cube::CornerPatternDatabase pdb(cube::path_from_utf8(argv[2]));
            std::cout << "{\"ok\":true,\"complete\":" << (pdb.complete() ? "true" : "false")
                      << ",\"max_value\":" << static_cast<int>(pdb.max_value()) << "}\n";
            return 0;
        }
        if (command == "build-phase1-pdb") {
            if (argc < 3) {
                print_usage();
                return 2;
            }
            int threads = static_cast<int>(std::max(1U, std::thread::hardware_concurrency()));
            int coverage_depth = 12;
            bool force = false;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--threads" && index + 1 < argc)
                    threads = std::stoi(argv[++index]);
                else if (option == "--coverage-depth" && index + 1 < argc)
                    coverage_depth = std::stoi(argv[++index]);
                else if (option == "--force")
                    force = true;
                else
                    throw std::invalid_argument("unknown build option: " + option);
            }
            auto tables = std::make_shared<cube::CoordinateTables>();
            cube::build_phase1_pattern_database(cube::path_from_utf8(argv[2]), *tables, threads, coverage_depth, force);
            cube::Phase1PatternDatabase pdb(cube::path_from_utf8(argv[2]));
            std::cout << "{\"ok\":true,\"complete\":" << (pdb.complete() ? "true" : "false")
                      << ",\"max_value\":" << static_cast<int>(pdb.max_value()) << "}\n";
            return 0;
        }
        if (command == "build-edge-pdb") {
            if (argc < 3) {
                print_usage();
                return 2;
            }
            int threads = static_cast<int>(std::max(1U, std::thread::hardware_concurrency()));
            int coverage_depth = 10;
            int group = -1;
            bool force = false;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--threads" && index + 1 < argc)
                    threads = std::stoi(argv[++index]);
                else if (option == "--coverage-depth" && index + 1 < argc)
                    coverage_depth = std::stoi(argv[++index]);
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
            cube::build_edge_pattern_database(cube::path_from_utf8(argv[2]), group, threads, coverage_depth, force);
            cube::EdgePatternDatabase pdb(cube::path_from_utf8(argv[2]), group);
            std::cout << "{\"ok\":true,\"complete\":" << (pdb.complete() ? "true" : "false")
                      << ",\"max_value\":" << static_cast<int>(pdb.max_value()) << "}\n";
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
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--depth" && index + 1 < argc)
                    depth = std::stoi(argv[++index]);
                else if (option == "--threads" && index + 1 < argc)
                    threads = std::stoi(argv[++index]);
                else if (option == "--force")
                    force = true;
                else
                    throw std::invalid_argument("unknown build option: " + option);
            }
            cube::build_tail_database(cube::path_from_utf8(argv[2]), depth, threads, force);
            cube::TailDatabase tail(cube::path_from_utf8(argv[2]));
            std::cout << "{\"ok\":true,\"depth\":" << tail.depth() << ",\"version\":" << tail.format_version() << "}\n";
            return 0;
        }
        if (command == "serve") {
            cube::SolverOptions defaults;
            std::filesystem::path pdb_path;
            std::filesystem::path phase1_pdb_path;
            std::filesystem::path tail_pdb_path;
            std::array<std::filesystem::path, 8> edge_pdb_paths{};
            const std::array<std::string, 8> edge_flags{"--edge-pdb-a", "--edge-pdb-b", "--edge-pdb-c", "--edge-pdb-d",
                                                        "--edge-pdb-e", "--edge-pdb-f", "--edge-pdb-g", "--edge-pdb-h"};
            for (int index = 2; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--pdb" && index + 1 < argc)
                    pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--phase1-pdb" && index + 1 < argc)
                    phase1_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--tail-pdb" && index + 1 < argc)
                    tail_pdb_path = cube::path_from_utf8(argv[++index]);
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
                solver.load_phase1_pdb(phase1_pdb_path);
            if (!pdb_path.empty())
                solver.load_corner_pdb(pdb_path);
            for (int group = 0; group < 8; ++group) {
                if (!edge_pdb_paths[group].empty())
                    solver.load_edge_pdb(group, edge_pdb_paths[group]);
            }
            if (!tail_pdb_path.empty())
                solver.load_tail_database(tail_pdb_path);
            std::cout << "{\"ok\":true,\"type\":\"ready\",\"protocol_version\":2,\"proof_version\":1,\"dynamic_"
                         "threads\":true}\n"
                      << std::flush;

            std::thread search;
            std::atomic<bool> running{false};
            std::atomic<bool> cancel{false};
            std::atomic<int> requested_threads{1};
            std::mutex output_mutex;
            std::mutex incumbent_mutex;
            std::vector<int> incumbent;
            std::string active_id;
            cube::CubieCube active_state;
            // In-memory only: loaded PDBs, HTM and proof rules are immutable for this process.
            std::unordered_map<std::string, int> proofs;
            std::string request;
            while (std::getline(std::cin, request)) {
                std::string id;
                try {
                    const auto fields = split_tabs(request);
                    if (fields.size() == 3 && fields[0] == "threads") {
                        if (fields[1] == active_id && running.load()) {
                            const int count = std::stoi(fields[2]);
                            if (count < 1 || count > 64)
                                throw std::invalid_argument("thread count must be in 1..64");
                            requested_threads.store(count, std::memory_order_relaxed);
                        }
                        continue;
                    }
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
                            if (incumbent.empty() || moves.size() < incumbent.size())
                                incumbent = std::move(moves);
                        }
                        continue;
                    }
                    const bool framed = fields.size() == 7 && fields[0] == "solve";
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
                    options.max_depth = std::stoi(fields[offset + 1]);
                    options.timeout_seconds = std::stod(fields[offset + 2]);
                    options.threads = std::stoi(fields[offset + 3]);
                    requested_threads.store(options.threads > 0
                                                ? options.threads
                                                : static_cast<int>(std::max(1U, std::thread::hardware_concurrency())),
                                            std::memory_order_relaxed);
                    options.thread_count_callback = [&] { return requested_threads.load(std::memory_order_relaxed); };
                    options.incumbent_moves = parse_moves(fields[offset + 4]);
                    incumbent = options.incumbent_moves;
                    cancel.store(false);
                    options.cancel_requested = &cancel;
                    const auto key = cube::to_facelets(active_state);
                    const auto previous = proofs.find(key);
                    if (framed && previous != proofs.end())
                        options.completed_depth = previous->second;
                    // Legacy benchmark requests deliberately rerun each proof.
                    options.incumbent_callback = [&] {
                        std::lock_guard lock(incumbent_mutex);
                        return incumbent;
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
                            if (framed) {
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
            options.progress_callback = [](const cube::NativeSearchProgress &progress) {
                print_progress_json(std::cerr, progress);
            };
            std::filesystem::path pdb_path;
            std::filesystem::path phase1_pdb_path;
            std::filesystem::path edge_pdb_a_path;
            std::filesystem::path edge_pdb_b_path;
            std::filesystem::path edge_pdb_c_path;
            std::filesystem::path edge_pdb_d_path;
            std::array<std::filesystem::path, 4> more_edge_pdb_paths{};
            std::filesystem::path tail_pdb_path;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--max-depth" && index + 1 < argc)
                    options.max_depth = std::stoi(argv[++index]);
                else if (option == "--timeout" && index + 1 < argc)
                    options.timeout_seconds = std::stod(argv[++index]);
                else if (option == "--threads" && index + 1 < argc)
                    options.threads = std::stoi(argv[++index]);
                else if (option == "--pdb" && index + 1 < argc)
                    pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--phase1-pdb" && index + 1 < argc)
                    phase1_pdb_path = cube::path_from_utf8(argv[++index]);
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
                else if (option == "--incumbent" && index + 1 < argc)
                    options.incumbent_moves = parse_moves(argv[++index]);
                else if (tuning_option(option, options))
                    continue;
                else
                    throw std::invalid_argument("unknown solve option: " + option);
            }
            cube::NativeOptimalSolver solver;
            if (!phase1_pdb_path.empty() && std::filesystem::exists(phase1_pdb_path)) {
                solver.load_phase1_pdb(phase1_pdb_path);
            }
            if (!pdb_path.empty() && std::filesystem::exists(pdb_path))
                solver.load_corner_pdb(pdb_path);
            const std::array<std::filesystem::path, 4> first_edge_pdb_paths{edge_pdb_a_path, edge_pdb_b_path,
                                                                            edge_pdb_c_path, edge_pdb_d_path};
            for (int group = 0; group < 4; ++group) {
                const auto &path = first_edge_pdb_paths[group];
                if (!path.empty()) {
                    if (!std::filesystem::exists(path))
                        throw std::invalid_argument("edge PDB does not exist");
                    solver.load_edge_pdb(group, path);
                }
            }
            for (int group = 4; group < 8; ++group) {
                const auto &path = more_edge_pdb_paths[group - 4];
                if (!path.empty()) {
                    if (!std::filesystem::exists(path))
                        throw std::invalid_argument("extra edge PDB does not exist");
                    solver.load_edge_pdb(group, path);
                }
            }
            if (!tail_pdb_path.empty()) {
                if (!std::filesystem::exists(tail_pdb_path))
                    throw std::invalid_argument("tail database does not exist");
                solver.load_tail_database(tail_pdb_path);
            }
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
