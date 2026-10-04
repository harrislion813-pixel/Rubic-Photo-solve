#pragma once

#include "cube.hpp"

#include <atomic>
#include <chrono>
#include <functional>
#include <vector>

namespace cube {
class CoordinateTables;

struct HtmCandidateOptions {
    double timeout_seconds{1.5};
    int directions{1};
    int max_phase1_depth{12};
    int max_phase2_depth{14};
    const std::atomic<bool> *cancel_requested{};
    std::function<void(const std::vector<int> &, double, int)> on_improved;
};

struct HtmCandidateResult {
    std::vector<int> moves;
    std::uint64_t phase1_nodes{};
    std::uint64_t phase2_nodes{};
    int improvements{};
    bool cancelled{};
    bool solution_found{};
    double elapsed_seconds{};
};

void prepare_htm_candidate_tables(const CoordinateTables &tables);
[[nodiscard]] HtmCandidateResult find_htm_candidate(const CubieCube &cube, const CoordinateTables &tables,
                                                    const HtmCandidateOptions &options);
} // namespace cube
