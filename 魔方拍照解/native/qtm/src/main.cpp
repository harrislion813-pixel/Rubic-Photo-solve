#include "cube.hpp"
#include "fast.hpp"
#include "loader.hpp"
#include "paths.hpp"
#include "pdb.hpp"
#include "solver.hpp"
#include "strong_coords.hpp"
#include "strong_pdb.hpp"
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
#include <fstream>
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
    if (qtm_base && solver.has_strong_pdb(metric))
        return "strong-no-tail";
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

cube::StrongValidationMode parse_strong_validation(const std::string &value) {
    if (value == "legacy")
        return cube::StrongValidationMode::Legacy;
    if (value == "fused")
        return cube::StrongValidationMode::Fused;
    if (value == "split")
        return cube::StrongValidationMode::Split;
    throw std::invalid_argument("strong validation must be legacy, fused or split");
}

void print_usage() {
    std::cerr << "usage:\n"
              << "  cube_solver validate FACELETS\n"
              << "  cube_solver apply FACELETS [MOVES...]\n"
              << "  cube_solver symmetry-info\n"
              << "  cube_solver strong-symmetry-info\n"
              << "  cube_solver build-strong-pdb PATH --metric QTM [--coverage-depth N] [--threads N] [--resume] "
                 "[--memory-limit-gib N]\n"
              << "  cube_solver verify-strong-pdb PATH [--threads N]\n"
              << "  cube_solver convert-strong-pdb SOURCE TARGET --encoding=nibble --verify-all\n"
              << "  cube_solver fast-solve FACELETS --qtm-phase1-pdb PATH [--timeout N] [--incumbent-cost N]\n"
              << "  cube_solver solve FACELETS [--metric HTM|QTM] [--max-depth N] [--timeout S] [--threads N]\n"
              << "                    [--pdb PATH] [--incumbent \"MOVES\"] [--transposition]\n"
              << "                    [--qtm-expansion=generic|full-strong]\n"
              << "  cube_solver serve [--pdb PATH] [--phase1-pdb PATH] [--qtm-pdb PATH] [--qtm-phase1-pdb PATH] "
                 "[--strong-pdb PATH] [--asset-loading=eager|staged]\n"
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

void print_candidate_direction_json(std::ostream &output, const cube::CandidateDirectionStatistics &direction) {
    output << "{\"direction\":" << direction.direction << ",\"axis\":" << direction.axis
           << ",\"inverse\":" << (direction.inverse ? "true" : "false") << ",\"visits\":" << direction.visits
           << ",\"budget_seconds\":" << direction.budget_seconds << ",\"elapsed_seconds\":" << direction.elapsed_seconds
           << ",\"phase1_nodes\":" << direction.phase1_nodes << ",\"phase2_nodes\":" << direction.phase2_nodes
           << ",\"first_candidate_seconds\":" << direction.first_candidate_seconds
           << ",\"first_cost\":" << direction.first_cost << ",\"best_cost\":" << direction.best_cost
           << ",\"improvements\":[";
    for (std::size_t index = 0; index < direction.improvements.size(); ++index) {
        if (index)
            output << ',';
        output << "{\"cost\":" << direction.improvements[index].cost
               << ",\"seconds\":" << direction.improvements[index].seconds << '}';
    }
    output << "]}";
}

void print_candidate_directions_json(std::ostream &output,
                                     const std::array<cube::CandidateDirectionStatistics, 6> &directions) {
    output << ",\"candidate_directions\":[";
    for (std::size_t index = 0; index < directions.size(); ++index) {
        if (index)
            output << ',';
        print_candidate_direction_json(output, directions[index]);
    }
    output << ']';
}

void print_counters_json(std::ostream &output, const cube::SearchCounters &counters,
                         const std::vector<cube::WorkerStatistics> &workers) {
    output << ",\"generated_candidates\":" << counters.generated << ",\"small_pdb_queries\":" << counters.small_queries
           << ",\"full_strong_expansions\":" << counters.full_strong_expansions
           << ",\"phase1_queries\":" << counters.phase1_queries << ",\"corner_queries\":" << counters.corner_queries
           << ",\"edge_queries\":" << counters.edge_queries << ",\"strong_queries\":" << counters.strong_queries
           << ",\"strong_prefetches\":" << counters.strong_prefetches << ",\"slice_updates\":" << counters.slice_updates
           << ",\"slice_updates_skipped\":" << counters.slice_updates_skipped << ",\"tt_keys\":" << counters.tt_keys
           << ",\"tt_lookups\":" << counters.tt_lookups << ",\"tt_stores\":" << counters.tt_stores
           << ",\"strong_rejects\":" << counters.strong_rejects << ",\"axis_rejects\":[" << counters.axis_rejects[0]
           << ',' << counters.axis_rejects[1] << ',' << counters.axis_rejects[2] << ']'
           << ",\"equality_rejects\":" << counters.equality_rejects
           << ",\"strong_equality_rejects\":" << counters.strong_equality_rejects
           << ",\"dual_queries\":" << counters.dual_queries << ",\"dual_rejects\":" << counters.dual_rejects
           << ",\"bpmx_rejects\":" << counters.bpmx_rejects << ",\"corner_rejects\":" << counters.corner_rejects
           << ",\"edge_rejects\":" << counters.edge_rejects << ",\"workers\":[";
    for (std::size_t i = 0; i < workers.size(); ++i) {
        if (i)
            output << ',';
        output << "{\"nodes\":" << workers[i].nodes << ",\"generated\":" << workers[i].generated
               << ",\"busy_seconds\":" << workers[i].busy_seconds << ",\"idle_seconds\":" << workers[i].idle_seconds
               << ",\"tasks\":" << workers[i].tasks << ",\"longest_task_seconds\":" << workers[i].longest_task_seconds
               << ",\"queue_lock_wait_seconds\":" << workers[i].queue_lock_wait_seconds << '}';
    }
    output << ']';
}

void print_progress_json(std::ostream &output, const cube::NativeSearchProgress &progress, const std::string &id = "",
                         const char *profile = "") {
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
    output << ",\"phase\":" << std::quoted(progress.phase);
    if (!id.empty())
        output << ",\"request_id\":" << std::quoted(id);
    if (profile[0] != '\0')
        output << ",\"asset_profile\":" << std::quoted(profile);
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
           << "\",\"inverse_direction\":" << (result.inverse_direction ? "true" : "false")
           << ",\"direction_forward_lower_bound\":" << result.direction_forward_lower_bound
           << ",\"direction_inverse_lower_bound\":" << result.direction_inverse_lower_bound
           << ",\"direction_probe_forward_generated\":" << result.direction_probe_forward_generated
           << ",\"direction_probe_inverse_generated\":" << result.direction_probe_inverse_generated
           << ",\"direction_probe_forward_rejected\":" << result.direction_probe_forward_rejected
           << ",\"direction_probe_inverse_rejected\":" << result.direction_probe_inverse_rejected
           << ",\"direction_probe_seconds\":" << result.direction_probe_seconds << ",\"moves\":";
    print_moves_json(output, result.moves);
    output << ",\"solution\":\"" << moves_text(result.moves) << "\",\"depth\":" << result.depth << ",\"metric\":\""
           << cube::metric_name(result.metric) << "\",\"optimal\":" << (result.optimal ? "true" : "false")
           << ",\"elapsed_seconds\":" << std::fixed << std::setprecision(6) << result.elapsed_seconds
           << ",\"nodes\":" << result.nodes << ",\"split_nodes\":" << result.split_nodes
           << ",\"transposition_hits\":" << result.transposition_hits << ",\"tail_queries\":" << result.tail_queries
           << ",\"tail_bloom_rejects\":" << result.tail_bloom_rejects
           << ",\"tail_exact_queries\":" << result.tail_exact_queries << ",\"tail_probes\":" << result.tail_probes
           << ",\"tail_hits\":" << result.tail_hits << ",\"candidate_phase1_nodes\":" << result.candidate_phase1_nodes
           << ",\"candidate_phase2_nodes\":" << result.candidate_phase2_nodes
           << ",\"candidate_improvements\":" << result.candidate_improvements
           << ",\"candidate_window_replacements\":" << result.candidate_window_replacements
           << ",\"candidate_budget_seconds\":" << result.candidate_budget_seconds
           << ",\"candidate_elapsed_seconds\":" << result.candidate_elapsed_seconds
           << ",\"late_tail_attempts\":" << result.late_tail_attempts
           << ",\"late_tail_improvements\":" << result.late_tail_improvements
           << ",\"late_tail_window_replacements\":" << result.late_tail_window_replacements
           << ",\"late_tail_seconds\":" << result.late_tail_seconds
           << ",\"late_tail_budget_seconds\":" << result.late_tail_budget_seconds
           << ",\"first_candidate_seconds\":" << result.first_candidate_seconds
           << ",\"candidate_worker_done_seconds\":" << result.candidate_worker_done_seconds
           << ",\"proof_worker_return_seconds\":" << result.proof_worker_return_seconds
           << ",\"corner_pdb\":" << (solver.has_corner_pdb(result.metric) ? "true" : "false")
           << ",\"corner_pdb_metric\":\"" << cube::metric_name(solver.corner_pdb_metric(result.metric)) << "\""
           << ",\"corner_pdb_complete\":" << (solver.corner_pdb_complete(result.metric) ? "true" : "false")
           << ",\"phase1_pdb\":" << (solver.has_phase1_pdb(result.metric) ? "true" : "false")
           << ",\"phase1_pdb_metric\":\"" << cube::metric_name(solver.phase1_pdb_metric(result.metric)) << "\""
           << ",\"phase1_pdb_complete\":" << (solver.phase1_pdb_complete(result.metric) ? "true" : "false")
           << ",\"edge_pdbs\":" << (solver.has_edge_pdbs(result.metric) ? "true" : "false")
           << ",\"extra_edge_pdbs\":" << (solver.has_extra_edge_pdbs(result.metric) ? "true" : "false")
           << ",\"edge_pdb_count\":" << solver.edge_pdb_count(result.metric)
           << ",\"tail_pdb\":" << (solver.has_tail_database(result.metric) ? "true" : "false")
           << ",\"tail_enabled\":" << (solver.has_tail_database(result.metric) ? "true" : "false")
           << ",\"strong_pdb\":" << (solver.has_strong_pdb(result.metric) ? "true" : "false") << ",\"asset_profile\":\""
           << asset_profile(solver, result.metric) << "\""
           << ",\"tail_depth\":" << solver.tail_database_depth(result.metric)
           << ",\"completed_depth\":" << result.completed_depth;
    output << ",\"strong_upgrade_restarts\":" << result.strong_upgrade_restarts
           << ",\"upgrade_discarded_generated\":" << result.upgrade_discarded_generated
           << ",\"upgrade_stop_seconds\":" << result.upgrade_stop_seconds;
    output << ",\"base_proof_seconds\":" << result.base_proof_seconds
           << ",\"base_last_used_seconds\":" << result.base_last_used_seconds
           << ",\"strong_wait_seconds\":" << result.strong_wait_seconds
           << ",\"base_window_yields\":" << result.base_window_yields
           << ",\"base_window_discarded_generated\":" << result.base_window_discarded_generated;
    print_candidate_directions_json(output, result.candidate_directions);
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
    if (option == "--coordinate-kernel=reference")
        options.affine_coordinates = false;
    else if (option == "--coordinate-kernel=affine")
        options.affine_coordinates = true;
    else if (option == "--dual-policy=off")
        options.dual_policy = cube::DualPolicy::Off;
    else if (option == "--dual-policy=root")
        options.dual_policy = cube::DualPolicy::Root;
    else if (option == "--dual-policy=selective")
        options.dual_policy = cube::DualPolicy::Selective;
    else if (option == "--dual-policy=all")
        options.dual_policy = cube::DualPolicy::All;
    else if (option == "--bpmx=on")
        options.bpmx = true;
    else if (option == "--bpmx=off")
        options.bpmx = false;
    else if (option == "--pdb-query-order=legacy")
        options.query_order = cube::PdbQueryOrder::Legacy;
    else if (option == "--pdb-query-order=interleaved")
        options.query_order = cube::PdbQueryOrder::Interleaved;
    else if (option == "--pdb-query-order=strong-first")
        options.query_order = cube::PdbQueryOrder::StrongFirst;
    else if (option == "--qtm-expansion=generic")
        options.qtm_expansion = cube::QtmExpansionKernel::Generic;
    else if (option == "--qtm-expansion=full-strong")
        options.qtm_expansion = cube::QtmExpansionKernel::FullStrong;
    else if (option == "--candidate-schedule=legacy")
        options.candidate_schedule = cube::CandidateSchedule::Legacy;
    else if (option == "--candidate-schedule=short-slices")
        options.candidate_schedule = cube::CandidateSchedule::ShortSlices;
    else if (option == "--late-tail-improvement=on")
        options.late_tail_improvement = true;
    else if (option == "--late-tail-improvement=off")
        options.late_tail_improvement = false;
    else if (option == "--strong-slice=omit")
        options.omit_strong_slice = true;
    else if (option == "--strong-slice=keep")
        options.omit_strong_slice = false;
    else if (option == "--strong-upgrade=restart")
        options.strong_upgrade_restart = true;
    else if (option == "--strong-upgrade=boundary")
        options.strong_upgrade_restart = false;
    else if (option == "--proof-schedule=strong-first")
        options.strong_first_proof = true;
    else if (option == "--proof-schedule=overlap")
        options.strong_first_proof = false;
    else if (option.starts_with("--base-proof-window=")) {
        std::size_t consumed = 0;
        const auto value = option.substr(20);
        options.base_proof_window_seconds = std::stod(value, &consumed);
        if (consumed != value.size())
            throw std::invalid_argument("invalid base proof window");
    } else if (option == "--pdb-prefetch=on")
        options.prefetch_strong = true;
    else if (option == "--pdb-prefetch=off")
        options.prefetch_strong = false;
    else if (option == "--qtm-axis-rule=off")
        options.qtm_phase1_axis_rule = options.qtm_strong_axis_rule = false;
    else if (option == "--qtm-axis-rule=phase1") {
        options.qtm_phase1_axis_rule = true;
        options.qtm_strong_axis_rule = false;
    } else if (option == "--qtm-axis-rule=strong") {
        options.qtm_phase1_axis_rule = false;
        options.qtm_strong_axis_rule = true;
    } else if (option == "--qtm-axis-rule=both")
        options.qtm_phase1_axis_rule = options.qtm_strong_axis_rule = true;
    else if (option == "--no-axis-strengthening")
        options.strengthen_axes = false;
    else if (option == "--keep-small-tables")
        options.omit_covered_small_tables = false;
    else if (option == "--no-staged-expansion")
        options.staged_expansion = false;
    else if (option == "--direction-policy=off") {
        options.use_direction_probe = false;
        options.direction_policy = cube::DirectionPolicy::Off;
    } else if (option == "--direction-policy=legacy") {
        options.use_direction_probe = true;
        options.direction_policy = cube::DirectionPolicy::Legacy;
    } else if (option == "--direction-policy=bounded") {
        options.use_direction_probe = true;
        options.direction_policy = cube::DirectionPolicy::Bounded;
    } else if (option == "--no-direction-probe")
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
    bool check_full_strong = false;
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
        else if (flag == "--qtm-expansion=full-strong")
            check_full_strong = true;
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
    features.strengthen_axes = true;
    if (check_full_strong && !cube::full_qtm_strong_eligible(features, phase1.get(), corner.get()))
        throw std::runtime_error("full strong hot-path check requires complete QTM phase1, corner and strong assets");
    std::deque<std::pair<cube::CubieCube, int>> queue{{cube::CubieCube{}, 0}};
    std::unordered_set<std::string> seen{cube::to_facelets(cube::CubieCube{})};
    std::uint64_t checked = 0;
    std::uint64_t hotpath_checked = 0;
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
            auto omitted = features;
            omitted.maintain_slice = !(strong && strong->complete() && !features.small_phase1 && phase1);
            for (std::uint8_t cutoff = 0; cutoff <= 30; ++cutoff) {
                cube::CoordinateState reference, optimized;
                const auto a = tables.expand(coordinates, move, reference, phase1.get(), corner.get(), {}, cutoff,
                                             features, counters);
                const auto b = tables.expand(coordinates, move, optimized, phase1.get(), corner.get(), {}, cutoff,
                                             omitted, counters);
                if (a != b || (b <= cutoff && tables.materialize(optimized) != child_cube))
                    throw std::runtime_error("slice omission changed a bound or accepted state");
                if (check_full_strong) {
                    cube::SearchCounters generic_counters, specialized_counters;
                    cube::CoordinateState generic, specialized;
                    const auto generic_bound = tables.expand(coordinates, move, generic, phase1.get(), corner.get(), {},
                                                             cutoff, features, generic_counters);
                    const auto specialized_bound = tables.expand_full_qtm_strong(
                        coordinates, move, specialized, corner.get(), strong.get(), cutoff, specialized_counters);
                    if (specialized_counters.full_strong_expansions != 1)
                        throw std::runtime_error("full strong hot-path diagnostic counter differs");
                    specialized_counters.full_strong_expansions = 0;
                    if (generic_bound != specialized_bound || generic_counters != specialized_counters)
                        throw std::runtime_error(
                            "full strong hot-path changed a bound, query order or reject counters");
                    if (specialized_bound <= cutoff &&
                        (tables.materialize(specialized) != child_cube || specialized.slice != expected.slice ||
                         specialized.sorted_slice != expected.sorted_slice ||
                         specialized.axis_twist != expected.axis_twist || specialized.axis_flip != expected.axis_flip ||
                         specialized.axis_slice != expected.axis_slice ||
                         specialized.axis_sorted_slice != expected.axis_sorted_slice))
                        throw std::runtime_error("full strong hot-path accepted incomplete coordinates");
                    const auto direct_bound =
                        tables.heuristic_full_qtm_strong(expected, corner.get(), strong.get(), cutoff);
                    const auto reference_bound =
                        tables.heuristic(expected, phase1.get(), corner.get(), {}, cutoff, features);
                    if (direct_bound != reference_bound)
                        throw std::runtime_error("full strong hot-path heuristic differs");
                    ++hotpath_checked;
                }
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
              << ",\"small_pdb_queries\":" << counters.small_queries << ",\"full_strong_checked\":" << hotpath_checked
              << "}\n";
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
        if (command == "check-strong-chunk") {
            if (argc < 3)
                throw std::invalid_argument("check-strong-chunk requires a data file");
            int coverage = 14;
            auto mode = cube::StrongValidationMode::Split;
            for (int index = 3; index < argc; ++index) {
                const std::string option = argv[index];
                if (option == "--coverage-depth" && index + 1 < argc)
                    coverage = parse_integer(argv[++index]);
                else if (option.starts_with("--strong-validation="))
                    mode = parse_strong_validation(option.substr(20));
                else
                    throw std::invalid_argument("unknown strong chunk check option");
            }
            if (coverage < 0 || coverage > 14)
                throw std::invalid_argument("nibble coverage must be 0..14");
            const auto path = cube::path_from_utf8(argv[2]);
            const auto size = std::filesystem::file_size(path);
            if (size > (64ULL << 20U))
                throw std::invalid_argument("strong chunk diagnostic accepts at most 64 MiB");
            std::vector<std::uint8_t> bytes(static_cast<std::size_t>(size));
            std::ifstream input(path, std::ios::binary);
            if (!input.read(reinterpret_cast<char *>(bytes.data()), static_cast<std::streamsize>(size)))
                throw std::runtime_error("cannot read strong chunk");
            const auto checked = cube::validate_strong_chunk(bytes, static_cast<std::uint8_t>(coverage), mode);
            std::cout << "{\"ok\":true,\"valid\":" << (checked.valid ? "true" : "false")
                      << ",\"checksum\":" << checked.checksum << ",\"maximum\":" << static_cast<int>(checked.maximum)
                      << ",\"checksum_seconds\":" << checked.checksum_seconds
                      << ",\"nibble_seconds\":" << checked.nibble_seconds << "}\n";
            return 0;
        }
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
                      << ",\"classes\":" << symmetry.class_count()
                      << ",\"joint_entries\":" << static_cast<std::uint64_t>(symmetry.class_count()) * 2048U * 2187U
                      << "}\n";
            return 0;
        }
        if (command == "convert-strong-pdb") {
            if (argc != 6 || std::string(argv[4]) != "--encoding=nibble" || std::string(argv[5]) != "--verify-all")
                throw std::invalid_argument("expected SOURCE TARGET --encoding=nibble --verify-all");
            const auto verification = cube::convert_strong_pattern_database_to_nibble(cube::path_from_utf8(argv[2]),
                                                                                      cube::path_from_utf8(argv[3]));
            std::cout << "{\"ok\":true,\"entries\":" << verification.entries << ",\"histogram\":[";
            for (int distance = 0; distance <= 14; ++distance) {
                if (distance)
                    std::cout << ',';
                std::cout << verification.distance_histogram[distance];
            }
            std::cout << "]}\n";
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
                      << ",\"coverage_depth\":" << pdb.coverage_depth()
                      << ",\"max_distance\":" << static_cast<int>(pdb.max_distance()) << "}\n";
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
            std::cout << "{\"ok\":true,\"metric\":\"QTM\",\"entries\":" << verified.entries << ",\"histogram\":[";
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
                else if (option == "--candidate-schedule=legacy")
                    options.schedule = cube::CandidateSchedule::Legacy;
                else if (option == "--candidate-schedule=short-slices")
                    options.schedule = cube::CandidateSchedule::ShortSlices;
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
            std::cout << "{\"ok\":true,\"metric\":\"QTM\",\"cost\":" << result.cost << ",\"moves\":[";
            for (std::size_t index = 0; index < result.moves.size(); ++index) {
                if (index)
                    std::cout << ',';
                std::cout << '"' << cube::kMoveNames[result.moves[index]] << '"';
            }
            std::cout << "],\"phase1_nodes\":" << result.phase1_nodes << ",\"phase2_nodes\":" << result.phase2_nodes
                      << ",\"phase1_max_distance\":" << result.phase1_max_distance
                      << ",\"phase2_max_distance\":" << result.phase2_max_distance
                      << ",\"improvements\":" << result.improvements
                      << ",\"window_replacements\":" << result.window_replacements
                      << ",\"timed_out\":" << (result.timed_out ? "true" : "false")
                      << ",\"budget_seconds\":" << result.budget_seconds
                      << ",\"elapsed_seconds\":" << result.elapsed_seconds;
            print_candidate_directions_json(std::cout, result.directions);
            std::cout << "}\n";
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
                cube::build_qtm_corner_pattern_database(cube::path_from_utf8(argv[2]), *tables, threads, coverage_depth,
                                                        force);
            else
                cube::build_corner_pattern_database(cube::path_from_utf8(argv[2]), *tables, threads, coverage_depth,
                                                    force);
            cube::CornerPatternDatabase pdb(cube::path_from_utf8(argv[2]));
            std::cout << "{\"ok\":true,\"complete\":" << (pdb.complete() ? "true" : "false") << ",\"metric\":\""
                      << cube::metric_name(pdb.metric()) << "\",\"coverage_depth\":" << pdb.coverage_depth()
                      << ",\"max_value\":" << static_cast<int>(pdb.max_value()) << "}\n";
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
                cube::build_qtm_phase1_pattern_database(cube::path_from_utf8(argv[2]), *tables, threads, coverage_depth,
                                                        force);
            else
                cube::build_phase1_pattern_database(cube::path_from_utf8(argv[2]), *tables, threads, coverage_depth,
                                                    force);
            cube::Phase1PatternDatabase pdb(cube::path_from_utf8(argv[2]));
            std::cout << "{\"ok\":true,\"complete\":" << (pdb.complete() ? "true" : "false") << ",\"metric\":\""
                      << cube::metric_name(pdb.metric()) << "\",\"coverage_depth\":" << pdb.coverage_depth()
                      << ",\"max_value\":" << static_cast<int>(pdb.max_value()) << "}\n";
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
                cube::build_qtm_edge_pattern_database(cube::path_from_utf8(argv[2]), group, threads, coverage_depth,
                                                      force);
            else
                cube::build_edge_pattern_database(cube::path_from_utf8(argv[2]), group, threads, coverage_depth, force);
            cube::EdgePatternDatabase pdb(cube::path_from_utf8(argv[2]), group);
            std::cout << "{\"ok\":true,\"complete\":" << (pdb.complete() ? "true" : "false") << ",\"metric\":\""
                      << cube::metric_name(pdb.metric()) << "\",\"coverage_depth\":" << pdb.coverage_depth()
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
                      << "\",\"depth\":" << tail.depth() << ",\"version\":" << tail.format_version() << "}\n";
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
                      << "\",\"depth\":" << tail.depth() << ",\"states\":" << verified.states << ",\"histogram\":[";
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
            bool staged_asset_loading = false;
            bool loader_managed = false;
            bool shared_loader_budget = false;
            int loader_threads = 0;
            std::string strong_validation = "legacy";
            std::filesystem::path pdb_path;
            std::filesystem::path phase1_pdb_path;
            std::filesystem::path fallback_pdb_path;
            std::filesystem::path fallback_phase1_pdb_path;
            std::filesystem::path fallback_tail_pdb_path;
            std::filesystem::path qtm_pdb_path;
            std::filesystem::path qtm_phase1_pdb_path;
            std::filesystem::path strong_pdb_path;
            std::filesystem::path strong_pdb_fallback_path;
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
                else if (option == "--fallback-pdb" && index + 1 < argc)
                    fallback_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--fallback-phase1-pdb" && index + 1 < argc)
                    fallback_phase1_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--fallback-tail-pdb" && index + 1 < argc)
                    fallback_tail_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-pdb" && index + 1 < argc)
                    qtm_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-phase1-pdb" && index + 1 < argc)
                    qtm_phase1_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--strong-pdb" && index + 1 < argc)
                    strong_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--strong-pdb-fallback" && index + 1 < argc)
                    strong_pdb_fallback_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-edge-pdb-a" && index + 1 < argc)
                    qtm_edge_pdb_paths[0] = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-edge-pdb-b" && index + 1 < argc)
                    qtm_edge_pdb_paths[1] = cube::path_from_utf8(argv[++index]);
                else if (option == "--tail-pdb" && index + 1 < argc)
                    tail_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--qtm-tail-pdb" && index + 1 < argc)
                    qtm_tail_pdb_path = cube::path_from_utf8(argv[++index]);
                else if (option == "--asset-loading=staged")
                    staged_asset_loading = true;
                else if (option == "--asset-loading=eager")
                    staged_asset_loading = false;
                else if (option == "--loader-managed")
                    loader_managed = true;
                else if (option.starts_with("--strong-validation="))
                    strong_validation = option.substr(20);
                else if (option == "--loader-budget=shared")
                    shared_loader_budget = true;
                else if (option == "--loader-budget=independent")
                    shared_loader_budget = false;
                else if (option == "--loader-threads" && index + 1 < argc) {
                    loader_threads = std::stoi(argv[++index]);
                    if (loader_threads < 1 || loader_threads > 8)
                        throw std::invalid_argument("loader threads must be 1..8");
                } else if (option == "--no-proof-cache")
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

            const auto initialization_started = std::chrono::steady_clock::now();
            const auto validation_mode = parse_strong_validation(strong_validation);
            auto solver = std::make_shared<cube::NativeOptimalSolver>();
            struct InitializationStep {
                std::string name;
                double seconds;
                std::uintmax_t mapped_bytes;
                std::string error;
            };
            std::vector<InitializationStep> initialization_steps;
            initialization_steps.push_back(
                {"coordinates",
                 std::chrono::duration<double>(std::chrono::steady_clock::now() - initialization_started).count(), 0,
                 ""});
            const auto load_asset = [&](const char *name, const std::filesystem::path &path, const auto &load,
                                        bool allow_failure = false) {
                if (path.empty())
                    return;
                const auto stage_started = std::chrono::steady_clock::now();
                std::string error;
                try {
                    load();
                } catch (const std::exception &failure) {
                    if (!allow_failure)
                        throw;
                    error = failure.what();
                }
                initialization_steps.push_back(
                    {name, std::chrono::duration<double>(std::chrono::steady_clock::now() - stage_started).count(),
                     error.empty() ? std::filesystem::file_size(path) : 0, error});
            };
            if (!phase1_pdb_path.empty())
                load_asset("htm_phase1", phase1_pdb_path,
                           [&] { solver->load_phase1_pdb(phase1_pdb_path, cube::MoveMetric::HTM); });
            if (!qtm_phase1_pdb_path.empty())
                load_asset(
                    "qtm_phase1", qtm_phase1_pdb_path,
                    [&] { solver->load_phase1_pdb(qtm_phase1_pdb_path, cube::MoveMetric::QTM); },
                    !fallback_phase1_pdb_path.empty());
            if (!pdb_path.empty())
                load_asset("htm_corner", pdb_path, [&] { solver->load_corner_pdb(pdb_path, cube::MoveMetric::HTM); });
            if (!qtm_pdb_path.empty())
                load_asset(
                    "qtm_corner", qtm_pdb_path, [&] { solver->load_corner_pdb(qtm_pdb_path, cube::MoveMetric::QTM); },
                    !fallback_pdb_path.empty());
            if ((!solver->has_phase1_pdb(cube::MoveMetric::QTM) ||
                 solver->phase1_pdb_metric(cube::MoveMetric::QTM) != cube::MoveMetric::QTM) &&
                !fallback_phase1_pdb_path.empty())
                load_asset(
                    "fallback_phase1", fallback_phase1_pdb_path,
                    [&] { solver->load_phase1_pdb(fallback_phase1_pdb_path, cube::MoveMetric::HTM); }, true);
            if ((!solver->has_corner_pdb(cube::MoveMetric::QTM) ||
                 solver->corner_pdb_metric(cube::MoveMetric::QTM) != cube::MoveMetric::QTM) &&
                !fallback_pdb_path.empty())
                load_asset(
                    "fallback_corner", fallback_pdb_path,
                    [&] { solver->load_corner_pdb(fallback_pdb_path, cube::MoveMetric::HTM); }, true);
            for (int group = 0; group < 8; ++group) {
                if (!edge_pdb_paths[group].empty())
                    solver->load_edge_pdb(group, edge_pdb_paths[group], cube::MoveMetric::HTM);
            }
            for (int group = 0; group < 2; ++group)
                if (!qtm_edge_pdb_paths[group].empty())
                    solver->load_edge_pdb(group, qtm_edge_pdb_paths[group], cube::MoveMetric::QTM);
            if (!tail_pdb_path.empty())
                load_asset("htm_tail", tail_pdb_path, [&] { solver->load_tail_database(tail_pdb_path); });
            const bool qtm_base = solver->has_phase1_pdb(cube::MoveMetric::QTM) &&
                                  solver->phase1_pdb_metric(cube::MoveMetric::QTM) == cube::MoveMetric::QTM &&
                                  solver->phase1_pdb_complete(cube::MoveMetric::QTM) &&
                                  solver->has_corner_pdb(cube::MoveMetric::QTM) &&
                                  solver->corner_pdb_metric(cube::MoveMetric::QTM) == cube::MoveMetric::QTM &&
                                  solver->corner_pdb_complete(cube::MoveMetric::QTM);
            if (!qtm_base && !fallback_tail_pdb_path.empty())
                load_asset(
                    "fallback_tail", fallback_tail_pdb_path,
                    [&] { solver->load_tail_database(fallback_tail_pdb_path); }, true);
            const double base_initialization_seconds =
                std::chrono::duration<double>(std::chrono::steady_clock::now() - initialization_started).count();
            const auto candidate_tables_started = std::chrono::steady_clock::now();
            if (solver->has_phase1_pdb(cube::MoveMetric::QTM) &&
                solver->phase1_pdb_metric(cube::MoveMetric::QTM) == cube::MoveMetric::QTM &&
                solver->phase1_pdb_complete(cube::MoveMetric::QTM))
                cube::prepare_fast_qtm_candidate_tables(solver->coordinate_tables());
            const double candidate_tables_seconds =
                std::chrono::duration<double>(std::chrono::steady_clock::now() - candidate_tables_started).count();
            double strong_initialization_seconds = 0.0;
            double tail_initialization_seconds = 0.0;
            double strong_ready_elapsed_seconds = -1.0;
            double tail_ready_elapsed_seconds = -1.0;
            cube::LoaderControl eager_loader(loader_threads);
            if (!staged_asset_loading) {
                auto stage_started = std::chrono::steady_clock::now();
                if (!strong_pdb_path.empty())
                    load_asset(
                        "strong", strong_pdb_path,
                        [&] {
                            try {
                                solver->load_strong_pdb(strong_pdb_path, &eager_loader, validation_mode);
                            } catch (const std::exception &) {
                                if (strong_pdb_fallback_path.empty())
                                    throw;
                                solver->load_strong_pdb(strong_pdb_fallback_path, &eager_loader, validation_mode);
                            }
                        },
                        true);
                strong_initialization_seconds =
                    std::chrono::duration<double>(std::chrono::steady_clock::now() - stage_started).count();
                if (solver->has_strong_pdb())
                    strong_ready_elapsed_seconds =
                        std::chrono::duration<double>(std::chrono::steady_clock::now() - initialization_started)
                            .count();
                stage_started = std::chrono::steady_clock::now();
                if (!qtm_tail_pdb_path.empty())
                    load_asset(
                        "qtm_tail", qtm_tail_pdb_path,
                        [&] { solver->load_tail_database(qtm_tail_pdb_path, cube::MoveMetric::QTM, &eager_loader); },
                        true);
                tail_initialization_seconds =
                    std::chrono::duration<double>(std::chrono::steady_clock::now() - stage_started).count();
                if (solver->has_tail_database(cube::MoveMetric::QTM))
                    tail_ready_elapsed_seconds =
                        std::chrono::duration<double>(std::chrono::steady_clock::now() - initialization_started)
                            .count();
            }
            std::atomic<std::shared_ptr<cube::NativeOptimalSolver>> active_solver{solver};
            std::cout
                << "{\"ok\":true,\"type\":\"ready\",\"protocol_version\":3,\"proof_version\":3,\"metrics\":["
                   "\"QTM\"],\"asset_loading\":\""
                << (staged_asset_loading ? "staged" : "eager")
                << "\",\"base_initialization_seconds\":" << base_initialization_seconds
                << ",\"strong_initialization_seconds\":" << strong_initialization_seconds
                << ",\"tail_initialization_seconds\":" << tail_initialization_seconds
                << ",\"candidate_tables_seconds\":" << candidate_tables_seconds
                << ",\"base_ready_elapsed_seconds\":" << base_initialization_seconds + candidate_tables_seconds
                << ",\"total_initialization_seconds\":"
                << std::chrono::duration<double>(std::chrono::steady_clock::now() - initialization_started).count();
            if (strong_ready_elapsed_seconds >= 0)
                std::cout << ",\"strong_ready_elapsed_seconds\":" << strong_ready_elapsed_seconds;
            if (tail_ready_elapsed_seconds >= 0)
                std::cout << ",\"tail_ready_elapsed_seconds\":" << tail_ready_elapsed_seconds;
            std::cout << ",\"strong_symmetry_seconds\":" << solver->strong_symmetry_initialization_seconds()
                      << ",\"strong_verification_seconds\":" << solver->strong_verification_seconds()
                      << ",\"strong_validation\":" << std::quoted(strong_validation)
                      << ",\"proof_schedule\":" << std::quoted(defaults.strong_first_proof ? "strong-first" : "overlap")
                      << ",\"strong_mapping_seconds\":" << solver->strong_mapping_seconds()
                      << ",\"strong_checksum_worker_seconds\":" << solver->strong_checksum_worker_seconds()
                      << ",\"strong_nibble_worker_seconds\":" << solver->strong_nibble_worker_seconds()
                      << ",\"initialization_steps\":[";
            for (std::size_t index = 0; index < initialization_steps.size(); ++index) {
                if (index)
                    std::cout << ',';
                const auto &step = initialization_steps[index];
                std::cout << "{\"asset\":" << std::quoted(step.name) << ",\"seconds\":" << step.seconds
                          << ",\"mapped_bytes\":" << step.mapped_bytes << ",\"error\":" << std::quoted(step.error)
                          << '}';
            }
            std::cout << "],\"assets\":{";
            for (const auto metric : {cube::MoveMetric::QTM}) {
                std::cout << '\"' << cube::metric_name(metric)
                          << "\":{\"corner\":" << (solver->has_corner_pdb(metric) ? "true" : "false")
                          << ",\"corner_metric\":\"" << cube::metric_name(solver->corner_pdb_metric(metric))
                          << "\",\"corner_complete\":" << (solver->corner_pdb_complete(metric) ? "true" : "false")
                          << ",\"phase1\":" << (solver->has_phase1_pdb(metric) ? "true" : "false")
                          << ",\"phase1_metric\":\"" << cube::metric_name(solver->phase1_pdb_metric(metric))
                          << "\",\"phase1_complete\":" << (solver->phase1_pdb_complete(metric) ? "true" : "false")
                          << ",\"edge_count\":" << solver->edge_pdb_count(metric)
                          << ",\"tail\":" << (solver->has_tail_database(metric) ? "true" : "false")
                          << ",\"strong\":" << (solver->has_strong_pdb(metric) ? "true" : "false")
                          << ",\"tail_depth\":" << solver->tail_database_depth(metric) << ",\"profile\":\""
                          << asset_profile(*solver, metric) << "\"}";
            }
            std::cout << "}}\n" << std::flush;

            std::thread search;
            std::atomic<bool> running{false};
            std::atomic<bool> cancel{false};
            std::mutex output_mutex;
            std::mutex incumbent_mutex;
            cube::LoaderControl loader(loader_threads, loader_managed);
            std::atomic<bool> loader_active{false};
            std::atomic<bool> loader_budget_suspended{false};
            std::atomic<bool> request_loader_allowed{true};
            std::atomic<bool> strong_loading{staged_asset_loading && !strong_pdb_path.empty()};
            const auto begin_stage = [&](const char *stage, const std::filesystem::path &path) {
                loader_active.store(true);
                if (loader_managed)
                    loader.request_pause();
                std::lock_guard lock(output_mutex);
                std::cout << "{\"ok\":true,\"type\":\"loader_stage\",\"stage\":" << std::quoted(stage)
                          << ",\"mapped_bytes\":" << std::filesystem::file_size(path)
                          << ",\"loader_threads\":" << (loader_threads ? loader_threads : 8) << "}\n"
                          << std::flush;
            };
            std::thread asset_loader;
            if (staged_asset_loading && (!strong_pdb_path.empty() || !qtm_tail_pdb_path.empty())) {
                asset_loader = std::thread([&] {
                    auto latest = solver;
                    const auto publish_asset = [&](const std::shared_ptr<cube::NativeOptimalSolver> &snapshot,
                                                   const char *stage, double seconds) {
                        active_solver.store(snapshot, std::memory_order_release);
                        std::lock_guard lock(output_mutex);
                        std::cout << "{\"ok\":true,\"type\":\"asset_ready\",\"metric\":\"QTM\",\"stage\":\"" << stage
                                  << "\",\"seconds\":" << seconds << ",\"profile\":\""
                                  << asset_profile(*snapshot, cube::MoveMetric::QTM)
                                  << "\",\"strong\":" << (snapshot->has_strong_pdb() ? "true" : "false")
                                  << ",\"snapshot_id\":" << reinterpret_cast<std::uintptr_t>(snapshot.get())
                                  << ",\"tail_depth\":" << snapshot->tail_database_depth(cube::MoveMetric::QTM)
                                  << ",\"strong_symmetry_seconds\":"
                                  << snapshot->strong_symmetry_initialization_seconds()
                                  << ",\"strong_verification_seconds\":" << snapshot->strong_verification_seconds()
                                  << ",\"strong_validation\":" << std::quoted(strong_validation)
                                  << ",\"strong_mapping_seconds\":" << snapshot->strong_mapping_seconds()
                                  << ",\"strong_checksum_worker_seconds\":"
                                  << snapshot->strong_checksum_worker_seconds()
                                  << ",\"strong_nibble_worker_seconds\":" << snapshot->strong_nibble_worker_seconds()
                                  << "}\n"
                                  << std::flush;
                    };
                    if (!strong_pdb_path.empty()) {
                        begin_stage("strong", strong_pdb_path);
                        const auto stage_started = std::chrono::steady_clock::now();
                        try {
                            auto next = std::make_shared<cube::NativeOptimalSolver>(*latest);
                            try {
                                next->load_strong_pdb(strong_pdb_path, &loader, validation_mode);
                            } catch (const std::exception &) {
                                if (strong_pdb_fallback_path.empty())
                                    throw;
                                next->load_strong_pdb(strong_pdb_fallback_path, &loader, validation_mode);
                            }
                            latest = std::move(next);
                            publish_asset(
                                latest, "strong",
                                std::chrono::duration<double>(std::chrono::steady_clock::now() - stage_started)
                                    .count());
                        } catch (const std::exception &error) {
                            std::cerr << "strong PDB staged load failed: " << error.what() << '\n';
                            std::lock_guard lock(output_mutex);
                            std::cout << "{\"ok\":false,\"type\":\"asset_error\",\"stage\":\"strong\",\"error\":"
                                      << std::quoted(error.what()) << "}\n"
                                      << std::flush;
                        }
                        strong_loading.store(false, std::memory_order_release);
                    }
                    if (!qtm_tail_pdb_path.empty()) {
                        begin_stage("tail", qtm_tail_pdb_path);
                        const auto stage_started = std::chrono::steady_clock::now();
                        try {
                            auto next = std::make_shared<cube::NativeOptimalSolver>(*latest);
                            next->load_tail_database(qtm_tail_pdb_path, cube::MoveMetric::QTM, &loader);
                            latest = std::move(next);
                            publish_asset(
                                latest, "tail",
                                std::chrono::duration<double>(std::chrono::steady_clock::now() - stage_started)
                                    .count());
                        } catch (const std::exception &error) {
                            std::cerr << "QTM tail staged load failed: " << error.what() << '\n';
                            std::lock_guard lock(output_mutex);
                            std::cout << "{\"ok\":false,\"type\":\"asset_error\",\"stage\":\"tail\",\"error\":"
                                      << std::quoted(error.what()) << "}\n"
                                      << std::flush;
                        }
                    }
                    loader_active.store(false);
                    std::lock_guard lock(output_mutex);
                    std::cout << "{\"ok\":true,\"type\":\"loader_done\"}\n" << std::flush;
                });
            }
            std::vector<int> incumbent;
            std::string active_id;
            cube::CubieCube active_state;
            cube::MoveMetric active_metric{cube::MoveMetric::QTM};
            // In-memory only: loaded PDBs and proof rules are immutable for this process.
            std::unordered_map<std::string, int> proofs;
            std::string request;
            while (std::getline(std::cin, request)) {
                std::string id;
                try {
                    const auto fields = split_tabs(request);
                    if (fields.size() == 2 && fields[0] == "loader_pause") {
                        const bool paused = loader.pause_for(std::chrono::milliseconds(500));
                        std::lock_guard lock(output_mutex);
                        std::cout << "{\"ok\":true,\"type\":\"loader_paused\",\"token\":" << std::quoted(fields[1])
                                  << ",\"paused\":" << (paused ? "true" : "false")
                                  << ",\"executing\":" << loader.executing() << "}\n"
                                  << std::flush;
                        continue;
                    }
                    if (fields.size() == 2 && fields[0] == "loader_deny") {
                        loader.request_pause();
                        loader_budget_suspended.store(true);
                        continue;
                    }
                    if (fields.size() == 2 && fields[0] == "loader_resume") {
                        if (!running.load() || request_loader_allowed.load()) {
                            loader_budget_suspended.store(false);
                            loader.resume();
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
                        fields.size() == 8 ? cube::parse_metric(fields[offset + 4]) : cube::MoveMetric::QTM;
                    if (options.metric != cube::MoveMetric::QTM)
                        throw std::invalid_argument("QTM service accepts QTM requests only");
                    active_metric = options.metric;
                    options.incumbent_moves = parse_moves(fields[offset + (fields.size() == 8 ? 5 : 4)]);
                    incumbent = options.incumbent_moves;
                    cancel.store(false);
                    options.cancel_requested = &cancel;
                    const int request_threads =
                        options.threads > 0 ? options.threads
                                            : static_cast<int>(std::max(1U, std::thread::hardware_concurrency()));
                    const bool allow_loader =
                        !shared_loader_budget || request_threads >= (loader_threads ? loader_threads : 8) + 2;
                    request_loader_allowed.store(allow_loader);
                    if (!allow_loader) {
                        loader_budget_suspended.store(true);
                        if (!loader.pause_for(std::chrono::milliseconds(500)))
                            throw std::runtime_error("loader could not yield the requested thread quota");
                    }
                    options.strong_loading_callback = [&] {
                        return strong_loading.load(std::memory_order_acquire) && !loader_budget_suspended.load();
                    };
                    if (shared_loader_budget)
                        options.loader_threads_callback = [&] {
                            return loader_active.load() && !loader_budget_suspended.load()
                                       ? (loader_threads ? loader_threads : 8)
                                       : 0;
                        };
                    options.thread_activity_callback = [&, id](int loading, int candidate, int proof) {
                        std::lock_guard lock(output_mutex);
                        std::cout << "{\"ok\":true,\"type\":\"thread_activity\",\"request_id\":" << std::quoted(id)
                                  << ",\"loader\":" << loader.executing() << ",\"loader_reserved\":" << loading
                                  << ",\"candidate\":" << candidate << ",\"proof\":" << proof << "}\n"
                                  << std::flush;
                    };
                    options.upgrade_callback = [&, id](int depth, std::uint64_t discarded, double stop_seconds) {
                        std::lock_guard lock(output_mutex);
                        std::cout << "{\"ok\":true,\"type\":\"strong_upgrade\",\"request_id\":" << std::quoted(id)
                                  << ",\"current_depth\":" << depth << ",\"discarded_generated\":" << discarded
                                  << ",\"stop_seconds\":" << stop_seconds << "}\n"
                                  << std::flush;
                    };
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
                    options.asset_snapshot_callback = [&active_solver] {
                        return active_solver.load(std::memory_order_acquire);
                    };
                    const auto search_solver = active_solver.load(std::memory_order_acquire);
                    const auto candidate_started = std::chrono::steady_clock::now();
                    options.candidate_direction_callback = [&, id, candidate_started](
                                                               const cube::CandidateDirectionStatistics &direction) {
                        std::lock_guard lock(output_mutex);
                        std::cout << "{\"ok\":true,\"type\":\"candidate_direction\",\"request_id\":" << std::quoted(id)
                                  << ",\"metric\":\"QTM\",\"native_event_seconds\":"
                                  << std::chrono::duration<double>(std::chrono::steady_clock::now() - candidate_started)
                                         .count()
                                  << ",\"statistics\":";
                        print_candidate_direction_json(std::cout, direction);
                        std::cout << "}\n" << std::flush;
                    };
                    options.late_tail_callback = [&, id](const cube::FastCandidateResult &part) {
                        std::lock_guard lock(output_mutex);
                        std::cout << "{\"ok\":true,\"type\":\"candidate_tail\",\"request_id\":" << std::quoted(id)
                                  << ",\"metric\":\"QTM\",\"attempts\":1,\"cost\":" << part.cost
                                  << ",\"improvements\":" << part.improvements
                                  << ",\"window_replacements\":" << part.window_replacements
                                  << ",\"budget_seconds\":" << part.budget_seconds
                                  << ",\"elapsed_seconds\":" << part.elapsed_seconds << "}\n"
                                  << std::flush;
                    };
                    options.candidate_callback = [&, id, candidate_started,
                                                  search_solver](const std::vector<int> &moves) {
                        const int cost = cube::solution_cost(moves, cube::MoveMetric::QTM);
                        {
                            std::lock_guard lock(incumbent_mutex);
                            if (incumbent.empty() || cost < cube::solution_cost(incumbent, cube::MoveMetric::QTM))
                                incumbent = moves;
                        }
                        std::lock_guard lock(output_mutex);
                        std::cout << "{\"ok\":true,\"type\":\"candidate\",\"request_id\":" << std::quoted(id)
                                  << ",\"metric\":\"QTM\",\"cost\":" << cost << ",\"native_found_seconds\":"
                                  << std::chrono::duration<double>(std::chrono::steady_clock::now() - candidate_started)
                                         .count()
                                  << ",\"asset_profile\":\"" << asset_profile(*search_solver, cube::MoveMetric::QTM)
                                  << "\""
                                  << ",\"moves\":";
                        print_moves_json(std::cout, moves);
                        std::cout << "}\n" << std::flush;
                    };
                    running.store(true);
                    search = std::thread([&, options, id, key, framed, state = active_state, search_solver]() mutable {
                        int completed = options.completed_depth;
                        std::string adopted_profile = asset_profile(*search_solver, options.metric);
                        options.asset_adopted_callback = [&](const cube::NativeOptimalSolver &snapshot, int depth,
                                                             double interrupted_seconds, double remaining,
                                                             std::uint64_t generated) {
                            adopted_profile = asset_profile(snapshot, options.metric);
                            std::lock_guard lock(output_mutex);
                            std::cout << "{\"ok\":true,\"type\":\"asset_adopted\",\"request_id\":" << std::quoted(id)
                                      << ",\"metric\":\"QTM\",\"profile\":" << std::quoted(adopted_profile)
                                      << ",\"strong\":" << (snapshot.has_strong_pdb() ? "true" : "false")
                                      << ",\"snapshot_id\":" << reinterpret_cast<std::uintptr_t>(&snapshot)
                                      << ",\"current_depth\":" << depth
                                      << ",\"interrupted_layer_seconds\":" << interrupted_seconds
                                      << ",\"remaining_seconds\":" << remaining
                                      << ",\"generated_candidates\":" << generated
                                      << ",\"tail_depth\":" << snapshot.tail_database_depth(options.metric) << "}\n"
                                      << std::flush;
                        };
                        options.progress_callback = [&](const cube::NativeSearchProgress &progress) {
                            completed = std::max(completed, progress.completed_depth);
                            std::lock_guard lock(output_mutex);
                            print_progress_json(std::cout, progress, id, adopted_profile.c_str());
                        };
                        try {
                            const auto result = search_solver->solve(state, options);
                            completed = std::max(completed, result.completed_depth);
                            if (framed && use_proof_cache) {
                                if (proofs.size() >= 128 && !proofs.contains(key))
                                    proofs.erase(proofs.begin());
                                proofs[key] = completed;
                            }
                            // Mark idle under the output lock before the terminal frame is observed.
                            std::lock_guard lock(output_mutex);
                            running.store(false);
                            print_result_json(std::cout, result,
                                              result.asset_snapshot ? *result.asset_snapshot : *search_solver, true,
                                              id);
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
            loader.resume();
            if (asset_loader.joinable())
                asset_loader.join();
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
