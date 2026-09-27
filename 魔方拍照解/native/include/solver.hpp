#pragma once

#include "cube.hpp"

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

enum class MoveMetric { HTM, QTM };
[[nodiscard]] MoveMetric parse_metric(const std::string &value);
[[nodiscard]] const char *metric_name(MoveMetric metric) noexcept;
[[nodiscard]] int move_cost(int move, MoveMetric metric);
[[nodiscard]] int solution_cost(std::span<const int> moves, MoveMetric metric);
[[nodiscard]] int default_max_depth(MoveMetric metric) noexcept;

class CornerPatternDatabase;
class EdgePatternDatabase;
class Phase1PatternDatabase;
class TailDatabase;

struct CoordinateState {
    std::uint64_t edges{};
    std::uint16_t twist{};
    std::uint16_t flip{};
    std::uint16_t slice{};
    std::uint16_t corner_perm{};
    EdgePatternState edge_pattern_a{};
    EdgePatternState edge_pattern_b{};
    std::array<std::uint16_t, 2> axis_twist{};
    std::array<std::uint16_t, 2> axis_flip{};
    std::array<std::uint16_t, 2> axis_slice{};
};

struct CoordinateFeatures {
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
    std::array<std::uint64_t, 3> axis_rejects{};
    std::uint64_t equality_rejects{};
    std::uint64_t corner_rejects{};
    std::uint64_t edge_rejects{};
};

struct WorkerStatistics {
    std::uint64_t nodes{};
    std::uint64_t generated{};
    double busy_seconds{};
    double idle_seconds{};
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
    bool strengthen_axes{true};
    bool omit_covered_small_tables{true};
    bool staged_expansion{true};
    bool inverse_direction{false};
    int completed_depth{-1}; // Only supplied by the service's verified proof cache.
    const std::atomic<bool> *cancel_requested{nullptr};
    std::vector<int> incumbent_moves;
    std::function<std::vector<int>()> incumbent_callback;
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
    int completed_depth{-1};
    SearchCounters counters;
    std::vector<WorkerStatistics> workers;
};

class NativeOptimalSolver {
  public:
    explicit NativeOptimalSolver(std::shared_ptr<CoordinateTables> tables = {});

    void load_corner_pdb(const std::filesystem::path &path);
    void load_phase1_pdb(const std::filesystem::path &path);
    void load_edge_pdb(int group, const std::filesystem::path &path);
    void load_edge_pdbs(const std::filesystem::path &path_a, const std::filesystem::path &path_b);
    void load_extra_edge_pdbs(const std::filesystem::path &path_c, const std::filesystem::path &path_d);
    void load_tail_database(const std::filesystem::path &path);
    [[nodiscard]] bool has_corner_pdb() const noexcept;
    [[nodiscard]] bool has_phase1_pdb() const noexcept;
    [[nodiscard]] bool has_edge_pdbs() const noexcept;
    [[nodiscard]] bool has_extra_edge_pdbs() const noexcept;
    [[nodiscard]] int edge_pdb_count() const noexcept;
    [[nodiscard]] bool has_tail_database() const noexcept;
    [[nodiscard]] NativeSolveResult solve(const CubieCube &cube, const SolverOptions &options) const;

  private:
    std::shared_ptr<CoordinateTables> tables_;
    std::shared_ptr<Phase1PatternDatabase> phase1_pdb_;
    std::shared_ptr<CornerPatternDatabase> corner_pdb_;
    std::array<std::shared_ptr<EdgePatternDatabase>, 8> edge_pdbs_{};
    std::shared_ptr<TailDatabase> tail_database_;
};

} // namespace cube
