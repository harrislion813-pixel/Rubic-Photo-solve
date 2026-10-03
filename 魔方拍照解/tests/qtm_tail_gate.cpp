// Executes the real Tail improver and late-adoption solver path without timing races.
#include "fast.hpp"
#include "solver.hpp"
#include "tail.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

using namespace cube;
using Clock = std::chrono::steady_clock;

namespace {
void require(bool value, const char *message) {
    if (!value)
        throw std::runtime_error(message);
}
std::vector<int> moves(const std::string &text) {
    std::vector<int> result;
    std::istringstream stream(text);
    for (std::string name; stream >> name;) {
        int move = 0;
        while (move < 18 && name != kMoveNames[move])
            ++move;
        require(move < 18, "invalid gate move");
        result.push_back(move);
    }
    return result;
}
CubieCube replay_moves(CubieCube cube, const std::vector<int> &path) {
    for (int move : path)
        cube = cube.apply_move(move);
    return cube;
}
void print_moves(const std::vector<int> &path) {
    std::cout << '[';
    for (std::size_t index = 0; index < path.size(); ++index) {
        if (index)
            std::cout << ',';
        std::cout << '"' << kMoveNames[path[index]] << '"';
    }
    std::cout << ']';
}
} // namespace

int wmain(int argc, wchar_t **argv) {
    try {
        require(argc == 2, "expected the complete QTM Tail path");
        NativeOptimalSolver base;
        auto adopted = std::make_shared<NativeOptimalSolver>(base);
        adopted->load_tail_database(std::filesystem::path(argv[1]), MoveMetric::QTM);
        TailDatabase tail{std::filesystem::path(argv[1])};
        const auto shallow = replay_moves(CubieCube{}, moves("R U F"));
        const auto detour = moves("F' U' R' R L R' L'");
        std::cout << "{\"direct\":[";
        for (int outcome = 0; outcome < 4; ++outcome) {
            std::atomic<bool> cancel{outcome == 1}, request_cancel{outcome == 2};
            FastCandidateOptions options;
            options.timeout_seconds = 0.2;
            options.cancel_requested = &cancel;
            options.request_cancel_requested = &request_cancel;
            if (outcome == 3)
                options.absolute_deadline = Clock::now() - std::chrono::seconds(1);
            int callbacks = 0;
            options.on_improved = [&](const std::vector<int> &path) {
                require(replay_moves(shallow, path).solved(), "direct Tail published an invalid formula");
                ++callbacks;
            };
            const auto result = improve_qtm_candidate_with_tail(shallow, detour, tail, options);
            require(replay_moves(shallow, result.moves).solved(), "Tail altered the whole-cube effect");
            if (outcome == 0) {
                require(result.cost == 3 && result.window_replacements > 0 && callbacks == 1,
                        "gate did not execute a real Tail replacement");
            } else {
                require(result.moves == detour && callbacks == 0 && result.window_replacements == 0,
                        "cancelled or expired Tail work changed or published an incumbent");
                require(result.timed_out, "aborted Tail work failed to report its stop condition");
            }
            if (outcome)
                std::cout << ',';
            std::cout << "{\"outcome\":" << outcome << ",\"facelets\":\"" << to_facelets(shallow)
                      << "\",\"cost\":" << result.cost << ",\"window_replacements\":" << result.window_replacements
                      << ",\"callbacks\":" << callbacks << ",\"moves\":";
            print_moves(result.moves);
            std::cout << '}';
        }
        std::cout << "],\"solves\":[";
        for (int threads = 1; threads <= 3; ++threads) {
            for (int outcome = 0; outcome < 3; ++outcome) {
                const auto scramble = outcome == 0 ? moves("R U F")
                    : moves("U' F L R' D' B' F U' B2 L D R2 B2 L2 U2 L' U2 R'");
                const auto state = replay_moves(CubieCube{}, scramble);
                auto incumbent = invert_moves(scramble);
                const auto redundant = moves("R L R' L'");
                incumbent.insert(incumbent.end(), redundant.begin(), redundant.end());
                std::atomic<bool> cancel{false}, tail_done{false};
                SolverOptions options;
                options.metric = MoveMetric::QTM;
                options.max_depth = 26;
                options.threads = threads;
                options.use_native_candidate = false;
                options.use_direction_probe = false;
                options.late_tail_improvement = true;
                options.timeout_seconds = outcome == 2 ? 0.06 : 1.0;
                options.incumbent_moves = incumbent;
                options.cancel_requested = &cancel;
                // The production loader publishes the same kind of immutable snapshot.
                // Dropping the external owner after adoption checks the held lifetime.
                std::shared_ptr<const NativeOptimalSolver> next = std::make_shared<NativeOptimalSolver>(*adopted);
                std::weak_ptr<const NativeOptimalSolver> held = next;
                options.asset_snapshot_callback = [&] {
                    auto snapshot = next;
                    next.reset();
                    return snapshot;
                };
                int attempts = 0, replacements = 0, candidates = 0, maximum_reserved = 0;
                int last_completed = -1;
                const auto began = Clock::now();
                options.late_tail_callback = [&](const FastCandidateResult &part) {
                    require(!held.expired(), "Tail snapshot expired while the worker was using it");
                    ++attempts;
                    replacements += part.window_replacements;
                    if (outcome == 1)
                        cancel.store(true);
                    if (outcome == 2)
                        while (Clock::now() - began < std::chrono::milliseconds(70))
                            std::this_thread::sleep_for(std::chrono::milliseconds(1));
                    tail_done.store(true, std::memory_order_release);
                };
                options.candidate_callback = [&](const std::vector<int> &path) {
                    require(replay_moves(state, path).solved(), "late Tail published an invalid formula");
                    ++candidates;
                };
                options.thread_activity_callback = [&](int loading, int candidate, int proof) {
                    maximum_reserved = std::max(maximum_reserved, loading + candidate + proof);
                    require(loading + candidate + proof <= threads, "late Tail exceeded the shared thread quota");
                    // Pause only the test's main coordinator until the real worker returns.
                    // This makes a replacement deterministic before the shallow proof wins.
                    const auto until = Clock::now() + std::chrono::seconds(1);
                    while (!tail_done.load(std::memory_order_acquire) && Clock::now() < until)
                        std::this_thread::sleep_for(std::chrono::milliseconds(1));
                    require(tail_done.load(std::memory_order_acquire), "late Tail worker did not return");
                };
                options.progress_callback = [&](const NativeSearchProgress &progress) {
                    require(progress.completed_depth >= last_completed, "complete-layer credit regressed");
                    last_completed = progress.completed_depth;
                };
                const auto result = base.solve(state, options);
                require(attempts == 1 && result.late_tail_attempts == 1 && replacements > 0,
                        "solver gate did not execute exactly one late Tail replacement");
                require(replay_moves(state, result.moves).solved(), "solver returned an invalid incumbent");
                require(result.late_tail_budget_seconds > 0 && result.late_tail_budget_seconds <= 0.2,
                        "late Tail failed to preserve its bounded request budget");
                if (outcome == 0)
                    require(result.optimal && result.depth == 3 && candidates == 1,
                            "shallow late Tail result disagrees with the independent oracle");
                else {
                    require(!result.optimal && result.completed_depth < result.depth - 1,
                            "aborted layer signed a shortest-path certificate");
                    require(outcome == 1 ? result.cancelled : result.timed_out,
                            "late Tail lost the original cancellation or absolute deadline");
                }
                if (threads != 1 || outcome != 0)
                    std::cout << ',';
                std::cout << "{\"threads\":" << threads << ",\"outcome\":" << outcome
                          << ",\"facelets\":\"" << to_facelets(state) << "\",\"depth\":" << result.depth
                          << ",\"optimal\":" << (result.optimal ? "true" : "false")
                          << ",\"completed_depth\":" << result.completed_depth
                          << ",\"max_reserved\":" << maximum_reserved << ",\"attempts\":" << attempts
                          << ",\"window_replacements\":" << replacements << ",\"moves\":";
                print_moves(result.moves);
                std::cout << '}';
            }
        }
        std::cout << "]}\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
