#pragma once

#include "cube.hpp"
#include "metric.hpp"

#include <atomic>
#include <functional>
#include <vector>

namespace cube {

class CoordinateTables;
class Phase1PatternDatabase;
class TailDatabase;

struct FastCandidateOptions {
    MoveMetric metric{MoveMetric::QTM};
    double timeout_seconds{1.0};
    int max_phase1_cost{20};
    int max_phase2_cost{26};
    int incumbent_cost{100};
    const std::atomic<bool> *cancel_requested{nullptr};
    const TailDatabase *local_tail{nullptr};
    std::function<void(const std::vector<int> &)> on_improved;
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
};

[[nodiscard]] FastCandidateResult find_fast_qtm_candidate(const CubieCube &cube, const CoordinateTables &tables,
                                                          const Phase1PatternDatabase &phase1_pdb,
                                                          const FastCandidateOptions &options);

} // namespace cube
