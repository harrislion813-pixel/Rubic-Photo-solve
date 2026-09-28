#pragma once

#include "cube.hpp"
#include "metric.hpp"

#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <vector>

namespace cube {

class CornerPatternDatabase;
class EdgePatternDatabase;
class Phase1PatternDatabase;
class TailDatabase;
class StrongPatternDatabase;

struct CoordinateState {
    std::uint64_t edges{};
    std::uint16_t twist{};
    std::uint16_t flip{};
    std::uint16_t slice{};
    std::uint16_t corner_perm{};
    std::uint16_t sorted_slice{};
    EdgePatternState edge_pattern_a{};
    EdgePatternState edge_pattern_b{};
    std::array<std::uint16_t, 2> axis_twist{};
    std::array<std::uint16_t, 2> axis_flip{};
    std::array<std::uint16_t, 2> axis_slice{};
    std::array<std::uint16_t, 2> axis_sorted_slice{};
};

struct CoordinateFeatures {
    MoveMetric metric{MoveMetric::HTM};
    const StrongPatternDatabase *strong_pdb{nullptr};
    bool axis_coordinates{true};
    bool edge_pattern_a{true};
    bool edge_pattern_b{true};
    bool small_phase1{true};
    bool small_corner{true};
    bool strengthen_axes{true};
    bool staged_expansion{true};
};

struct SearchCounters {
    std::uint64_t generated{};
    std::uint64_t small_queries{};
    std::uint64_t phase1_queries{};
    std::uint64_t corner_queries{};
    std::uint64_t edge_queries{};
    std::uint64_t strong_queries{};
    std::uint64_t tt_keys{};
    std::uint64_t tt_lookups{};
    std::uint64_t tt_stores{};
    std::array<std::uint64_t, 3> axis_rejects{};
    std::uint64_t equality_rejects{};
    std::uint64_t corner_rejects{};
    std::uint64_t edge_rejects{};
    std::uint64_t strong_rejects{};
};

struct WorkerStatistics {
    std::uint64_t nodes{};
    std::uint64_t generated{};
    double busy_seconds{};
    double idle_seconds{};
    std::uint64_t tasks{};
    double longest_task_seconds{};
    double queue_lock_wait_seconds{};
};

class CoordinateTables {
  public:
    CoordinateTables();

    [[nodiscard]] CoordinateState from_cube(const CubieCube &cube,
                                            const CoordinateFeatures &features = {}) const noexcept;
    [[nodiscard]] CoordinateState moved(const CoordinateState &state, int move,
                                        const CoordinateFeatures &features = {}) const noexcept;
    [[nodiscard]] std::uint8_t heuristic(const CoordinateState &state,
                                         const Phase1PatternDatabase *phase1_pdb = nullptr,
                                         const CornerPatternDatabase *corner_pdb = nullptr,
                                         std::span<const EdgePatternDatabase *const> edge_pdbs = {},
                                         std::uint8_t cutoff = 255, const CoordinateFeatures &features = {},
                                         SearchCounters *counters = nullptr) const noexcept;
    [[nodiscard]] std::uint8_t expand(const CoordinateState &parent, int move, CoordinateState &child,
                                      const Phase1PatternDatabase *phase1_pdb, const CornerPatternDatabase *corner_pdb,
                                      std::span<const EdgePatternDatabase *const> edge_pdbs, std::uint8_t cutoff,
                                      const CoordinateFeatures &features, SearchCounters &counters) const noexcept;
    [[nodiscard]] CubieCube materialize(const CoordinateState &state) const;

    [[nodiscard]] std::uint16_t corner_move(std::uint16_t coordinate, int move) const noexcept;
    [[nodiscard]] std::uint16_t twist_move(std::uint16_t coordinate, int move) const noexcept;
    [[nodiscard]] std::uint16_t flip_move(std::uint16_t coordinate, int move) const noexcept;
    [[nodiscard]] std::uint16_t slice_move(std::uint16_t coordinate, int move) const noexcept;

  private:
    std::vector<std::uint16_t> twist_move_;
    std::vector<std::uint16_t> flip_move_;
    std::vector<std::uint16_t> slice_move_;
    std::vector<std::uint16_t> corner_move_;
    std::vector<std::uint8_t> twist_slice_prune_;
    std::vector<std::uint8_t> flip_slice_prune_;
    std::vector<std::uint8_t> twist_flip_prune_;
    std::vector<std::uint8_t> corner_prune_;
    std::vector<std::uint8_t> qtm_twist_slice_prune_;
    std::vector<std::uint8_t> qtm_flip_slice_prune_;
    std::vector<std::uint8_t> qtm_twist_flip_prune_;
    std::vector<std::uint8_t> qtm_corner_prune_;
    [[nodiscard]] bool load_cache(const std::filesystem::path &path);
    void save_cache(const std::filesystem::path &path) const;
    [[nodiscard]] std::uint8_t evaluate(CoordinateState &state, const CoordinateState *parent, int move,
                                        const Phase1PatternDatabase *phase1_pdb,
                                        const CornerPatternDatabase *corner_pdb,
                                        std::span<const EdgePatternDatabase *const> edge_pdbs, std::uint8_t cutoff,
                                        const CoordinateFeatures &features, SearchCounters &counters) const noexcept;
};

struct NativeSearchProgress {
    MoveMetric metric{MoveMetric::HTM};
    int lower_bound{};
    int upper_bound{};
    int current_depth{};
    int completed_depth{};
    std::uint64_t iteration_nodes{};
    std::uint64_t iteration_split_nodes{};
    std::uint64_t total_nodes{};
    std::uint64_t total_split_nodes{};
    std::uint64_t transposition_hits{};
    std::uint64_t tail_queries{};
    std::uint64_t tail_bloom_rejects{};
    std::uint64_t tail_exact_queries{};
    std::uint64_t tail_probes{};
    std::uint64_t tail_hits{};
    double iteration_seconds{};
    double elapsed_seconds{};
    bool found{};
    bool timed_out{};
    bool cancelled{};
    SearchCounters counters;
    std::vector<WorkerStatistics> workers;
};

struct SolverOptions {
    MoveMetric metric{MoveMetric::HTM};
    int max_depth{-1}; // Unspecified: resolve to the selected metric's full search bound.
    double timeout_seconds{180.0};
    int threads{0};
    std::size_t transposition_limit_per_thread{500'000};
    bool use_transposition{false};
    bool use_direction_probe{true};
    bool use_qtm_parity{true};
    bool strengthen_axes{true};
    bool omit_covered_small_tables{true};
    bool staged_expansion{true};
    bool inverse_direction{false};
    bool use_native_candidate{true};
    bool adaptive_split{true};
    bool selective_transposition{true};
    std::array<std::uint8_t, 18> move_costs{};
    int completed_depth{-1}; // Only supplied by the service's verified proof cache.
    const std::atomic<bool> *cancel_requested{nullptr};
    std::vector<int> incumbent_moves;
    std::function<std::vector<int>()> incumbent_callback;
    std::function<void(const std::vector<int> &)> candidate_callback;
    std::function<void(const NativeSearchProgress &)> progress_callback;
};

struct NativeSolveResult {
    MoveMetric metric{MoveMetric::HTM};
    std::vector<int> moves;
    int depth{-1};
    bool optimal{false};
    bool timed_out{false};
    bool cancelled{false};
    bool inverse_direction{false};
    double elapsed_seconds{0.0};
    std::uint64_t nodes{0};
    std::uint64_t split_nodes{0};
    std::uint64_t transposition_hits{0};
    std::uint64_t tail_queries{0};
    std::uint64_t tail_bloom_rejects{0};
    std::uint64_t tail_exact_queries{0};
    std::uint64_t tail_probes{0};
    std::uint64_t tail_hits{0};
    std::uint64_t candidate_phase1_nodes{0};
    std::uint64_t candidate_phase2_nodes{0};
    int candidate_improvements{0};
    int candidate_window_replacements{0};
    double first_candidate_seconds{-1.0};
    int completed_depth{-1};
    SearchCounters counters;
    std::vector<WorkerStatistics> workers;
};

class NativeOptimalSolver {
  public:
    explicit NativeOptimalSolver(std::shared_ptr<CoordinateTables> tables = {});

    void load_corner_pdb(const std::filesystem::path &path, std::optional<MoveMetric> expected = std::nullopt);
    void load_phase1_pdb(const std::filesystem::path &path, std::optional<MoveMetric> expected = std::nullopt);
    void load_edge_pdb(int group, const std::filesystem::path &path,
                       std::optional<MoveMetric> expected = std::nullopt);
    void load_edge_pdbs(const std::filesystem::path &path_a, const std::filesystem::path &path_b);
    void load_extra_edge_pdbs(const std::filesystem::path &path_c, const std::filesystem::path &path_d);
    void load_tail_database(const std::filesystem::path &path, MoveMetric expected_metric = MoveMetric::HTM);
    void load_strong_pdb(const std::filesystem::path &path);
    [[nodiscard]] bool has_corner_pdb(MoveMetric metric = MoveMetric::HTM) const noexcept;
    [[nodiscard]] bool has_phase1_pdb(MoveMetric metric = MoveMetric::HTM) const noexcept;
    [[nodiscard]] bool has_edge_pdbs(MoveMetric metric = MoveMetric::HTM) const noexcept;
    [[nodiscard]] bool has_extra_edge_pdbs(MoveMetric metric = MoveMetric::HTM) const noexcept;
    [[nodiscard]] int edge_pdb_count(MoveMetric metric = MoveMetric::HTM) const noexcept;
    [[nodiscard]] bool has_tail_database(MoveMetric metric = MoveMetric::HTM) const noexcept;
    [[nodiscard]] int tail_database_depth(MoveMetric metric = MoveMetric::HTM) const noexcept;
    [[nodiscard]] bool has_strong_pdb(MoveMetric metric = MoveMetric::QTM) const noexcept;
    [[nodiscard]] MoveMetric corner_pdb_metric(MoveMetric metric) const noexcept;
    [[nodiscard]] MoveMetric phase1_pdb_metric(MoveMetric metric) const noexcept;
    [[nodiscard]] bool corner_pdb_complete(MoveMetric metric) const noexcept;
    [[nodiscard]] bool phase1_pdb_complete(MoveMetric metric) const noexcept;
    [[nodiscard]] NativeSolveResult solve(const CubieCube &cube, const SolverOptions &options) const;

  private:
    std::shared_ptr<CoordinateTables> tables_;
    std::array<std::shared_ptr<Phase1PatternDatabase>, 2> phase1_pdbs_{};
    std::array<std::shared_ptr<CornerPatternDatabase>, 2> corner_pdbs_{};
    std::array<std::array<std::shared_ptr<EdgePatternDatabase>, 8>, 2> edge_pdbs_{};
    std::array<std::shared_ptr<TailDatabase>, 2> tail_databases_{};
    std::shared_ptr<StrongPatternDatabase> strong_pdb_;
};

} // namespace cube
