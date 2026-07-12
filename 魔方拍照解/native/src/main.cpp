#include "cube.hpp"
#include "pdb.hpp"
#include "solver.hpp"
#include "symmetry.hpp"
#include "tail.hpp"

#include <algorithm>
#include <array>
#include <exception>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <thread>
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

void print_progress_json(std::ostream &output, const cube::NativeSearchProgress &progress) {
    output << "{\"type\":\"progress\",\"lower_bound\":" << progress.lower_bound
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
           << ",\"timed_out\":" << (progress.timed_out ? "true" : "false") << "}\n"
           << std::flush;
}

void print_result_json(std::ostream &output, const cube::NativeSolveResult &result,
                       const cube::NativeOptimalSolver &solver, bool framed = false) {
    output << "{\"ok\":true";
    if (framed)
        output << ",\"type\":\"result\"";
    output << ",\"status\":\"" << (result.timed_out ? "timeout" : "complete")
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
           << ",\"tail_pdb\":" << (solver.has_tail_database() ? "true" : "false") << "}\n"
           << std::flush;
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

} // namespace

int main(int argc, char **argv) {
    try {
        if (argc < 2) {
            print_usage();
            return 2;
        }
        const std::string command = argv[1];
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
            cube::build_corner_pattern_database(argv[2], *tables, threads, coverage_depth, force);
            cube::CornerPatternDatabase pdb(argv[2]);
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
            cube::build_phase1_pattern_database(argv[2], *tables, threads, coverage_depth, force);
            cube::Phase1PatternDatabase pdb(argv[2]);
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
            cube::build_edge_pattern_database(argv[2], group, threads, coverage_depth, force);
            cube::EdgePatternDatabase pdb(argv[2], group);
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
            cube::build_tail_database(argv[2], depth, threads, force);
            cube::TailDatabase tail(argv[2]);
            std::cout << "{\"ok\":true,\"depth\":" << tail.depth() << ",\"version\":" << tail.format_version() << "}\n";
            return 0;
        }
        if (command == "serve") {
            std::filesystem::path pdb_path;
            std::filesystem::path phase1_pdb_path;
            std::filesystem::path tail_pdb_path;
            std::array<std::filesystem::path, 8> edge_pdb_paths{};
            const std::array<std::string, 8> edge_flags{"--edge-pdb-a", "--edge-pdb-b", "--edge-pdb-c", "--edge-pdb-d",
                                                        "--edge-pdb-e", "--edge-pdb-f", "--edge-pdb-g", "--edge-pdb-h"};
            for (int index = 2; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--pdb" && index + 1 < argc)
                    pdb_path = argv[++index];
                else if (option == "--phase1-pdb" && index + 1 < argc)
                    phase1_pdb_path = argv[++index];
                else if (option == "--tail-pdb" && index + 1 < argc)
                    tail_pdb_path = argv[++index];
                else {
                    const auto flag = std::find(edge_flags.begin(), edge_flags.end(), option);
                    if (flag == edge_flags.end() || index + 1 >= argc) {
                        throw std::invalid_argument("unknown serve option: " + option);
                    }
                    edge_pdb_paths[static_cast<std::size_t>(flag - edge_flags.begin())] = argv[++index];
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
            std::cout << "{\"ok\":true,\"type\":\"ready\"}\n" << std::flush;

            std::string request;
            while (std::getline(std::cin, request)) {
                try {
                    const auto fields = split_tabs(request);
                    if (fields.size() != 5)
                        throw std::invalid_argument("invalid serve request");
                    const cube::CubieCube state = cube::from_facelets(fields[0]);
                    cube::SolverOptions options;
                    options.max_depth = std::stoi(fields[1]);
                    options.timeout_seconds = std::stod(fields[2]);
                    options.threads = std::stoi(fields[3]);
                    options.incumbent_moves = parse_moves(fields[4]);
                    options.progress_callback = [](const cube::NativeSearchProgress &progress) {
                        print_progress_json(std::cout, progress);
                    };
                    print_result_json(std::cout, solver.solve(state, options), solver, true);
                } catch (const std::exception &error) {
                    std::cout << "{\"ok\":false,\"type\":\"error\",\"error\":\"" << error.what() << "\"}\n"
                              << std::flush;
                }
            }
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
                    pdb_path = argv[++index];
                else if (option == "--phase1-pdb" && index + 1 < argc)
                    phase1_pdb_path = argv[++index];
                else if (option == "--edge-pdb-a" && index + 1 < argc)
                    edge_pdb_a_path = argv[++index];
                else if (option == "--edge-pdb-b" && index + 1 < argc)
                    edge_pdb_b_path = argv[++index];
                else if (option == "--edge-pdb-c" && index + 1 < argc)
                    edge_pdb_c_path = argv[++index];
                else if (option == "--edge-pdb-d" && index + 1 < argc)
                    edge_pdb_d_path = argv[++index];
                else if (option == "--edge-pdb-e" && index + 1 < argc)
                    more_edge_pdb_paths[0] = argv[++index];
                else if (option == "--edge-pdb-f" && index + 1 < argc)
                    more_edge_pdb_paths[1] = argv[++index];
                else if (option == "--edge-pdb-g" && index + 1 < argc)
                    more_edge_pdb_paths[2] = argv[++index];
                else if (option == "--edge-pdb-h" && index + 1 < argc)
                    more_edge_pdb_paths[3] = argv[++index];
                else if (option == "--tail-pdb" && index + 1 < argc)
                    tail_pdb_path = argv[++index];
                else if (option == "--incumbent" && index + 1 < argc)
                    options.incumbent_moves = parse_moves(argv[++index]);
                else if (option == "--transposition")
                    options.use_transposition = true;
                else if (option == "--no-transposition")
                    options.use_transposition = false;
                else if (option == "--no-direction-probe")
                    options.use_direction_probe = false;
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
