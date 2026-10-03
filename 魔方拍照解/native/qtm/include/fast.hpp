#pragma once

#include "cube.hpp"
#include "metric.hpp"

#include <array>
#include <atomic>
#include <chrono>
#include <functional>
#include <vector>

namespace cube {

class CoordinateTables;
class Phase1PatternDatabase;
class TailDatabase;
void prepare_fast_qtm_candidate_tables(const CoordinateTables &tables);

enum class CandidateSchedule { Legacy, ShortSlices };

struct CandidateImprovement {
    int cost{};
    double seconds{};
};

struct CandidateDirectionStatistics {
    int direction{};
    int axis{-1};
    bool inverse{};
    int visits{};
    double budget_seconds{};
    double elapsed_seconds{};
    std::uint64_t phase1_nodes{};
    std::uint64_t phase2_nodes{};
    double first_candidate_seconds{-1.0};
    int first_cost{-1};
    int best_cost{-1};
    std::vector<CandidateImprovement> improvements;
};

struct FastCandidateOptions {
    MoveMetric metric{MoveMetric::QTM};
    double timeout_seconds{1.0};
    int max_phase1_cost{20};
    int max_phase2_cost{26};
    int incumbent_cost{100};
    CandidateSchedule schedule{CandidateSchedule::Legacy};
    std::chrono::steady_clock::time_point absolute_deadline{std::chrono::steady_clock::time_point::max()};
    const std::atomic<bool> *cancel_requested{nullptr};
    const std::atomic<bool> *request_cancel_requested{nullptr};
    const TailDatabase *local_tail{nullptr};
    std::function<void(const std::vector<int> &)> on_improved;
    std::function<void(const CandidateDirectionStatistics &)> on_direction;
};

struct FastCandidateResult {
    std::vector<int> moves;
    int cost{-1};
    int phase1_max_distance{};
    int phase2_max_distance{};
    std::uint64_t phase1_nodes{};
    std::uint64_t phase2_nodes{};
    int improvements{};
    int window_replacements{};
    bool timed_out{};
    std::array<CandidateDirectionStatistics, 6> directions;
    double elapsed_seconds{};
    double budget_seconds{};
};

[[nodiscard]] FastCandidateResult find_fast_qtm_candidate(const CubieCube &cube, const CoordinateTables &tables,
                                                          const Phase1PatternDatabase &phase1_pdb,
                                                          const FastCandidateOptions &options);

// Bounded window replacement only; callers supply a verified incumbent and a held Tail snapshot.
[[nodiscard]] FastCandidateResult improve_qtm_candidate_with_tail(const CubieCube &cube,
                                                                  const std::vector<int> &incumbent,
                                                                  const TailDatabase &tail,
                                                                  const FastCandidateOptions &options);

} // namespace cube
