#pragma once

#include "cube.hpp"
#include "fast.hpp"
#include "metric.hpp"
#include "strong_pdb.hpp"

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
class NativeOptimalSolver;
class LoaderControl;

enum class DirectionPolicy { Off, Legacy, Bounded };
enum class DualPolicy { Off, Root, Selective, All };
enum class PdbQueryOrder { Legacy, Interleaved, StrongFirst };
enum class QtmExpansionKernel { Generic, FullStrong };

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
    bool affine_coordinates{true};
    PdbQueryOrder query_order{PdbQueryOrder::StrongFirst};
    bool prefetch_strong{false};
    bool maintain_slice{true};
    bool axis_coordinates{true};
    bool edge_pattern_a{true};
    bool edge_pattern_b{true};
    bool small_phase1{true};
    bool small_corner{true};
    bool strengthen_axes{true};
    bool qtm_phase1_axis_rule{true};
    bool qtm_strong_axis_rule{true};
    bool staged_expansion{true};
};

struct SearchCounters {
    std::uint64_t generated{};
    std::uint64_t full_strong_expansions{};
    std::uint64_t small_queries{};
    std::uint64_t phase1_queries{};
    std::uint64_t corner_queries{};
    std::uint64_t edge_queries{};
    std::uint64_t strong_queries{};
    std::uint64_t strong_prefetches{};
    std::uint64_t slice_updates{};
    std::uint64_t slice_updates_skipped{};
    std::uint64_t tt_keys{};
    std::uint64_t tt_lookups{};
    std::uint64_t tt_stores{};
    std::array<std::uint64_t, 3> axis_rejects{};
    std::uint64_t equality_rejects{};
    std::uint64_t strong_equality_rejects{};
    std::uint64_t dual_queries{};
    std::uint64_t dual_rejects{};
    std::uint64_t bpmx_rejects{};
    std::uint64_t corner_rejects{};
    std::uint64_t edge_rejects{};
    std::uint64_t strong_rejects{};
    bool operator==(const SearchCounters &) const = default;
};

// Check once at a search-layer boundary. Ineligible snapshots retain the generic path.
[[nodiscard]] bool full_qtm_strong_eligible(const CoordinateFeatures &features, const Phase1PatternDatabase *phase1_pdb,
                                            const CornerPatternDatabase *corner_pdb,
                                            std::span<const EdgePatternDatabase *const> edge_pdbs = {}) noexcept;

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
    // The caller must hold the immutable snapshot accepted by full_qtm_strong_eligible.
    [[nodiscard]] std::uint8_t expand_full_qtm_strong(const CoordinateState &parent, int move, CoordinateState &child,
                                                      const CornerPatternDatabase *corner_pdb,
                                                      const StrongPatternDatabase *strong_pdb, std::uint8_t cutoff,
                                                      SearchCounters &counters) const noexcept;
    [[nodiscard]] std::uint8_t heuristic_full_qtm_strong(const CoordinateState &state,
                                                         const CornerPatternDatabase *corner_pdb,
                                                         const StrongPatternDatabase *strong_pdb, std::uint8_t cutoff,
                                                         SearchCounters *counters = nullptr) const noexcept;
    [[nodiscard]] CubieCube materialize(const CoordinateState &state) const noexcept;

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
    [[nodiscard]] std::uint8_t evaluate_full_qtm_strong(CoordinateState &state, const CoordinateState *parent, int move,
                                                        const CornerPatternDatabase *corner_pdb,
                                                        const StrongPatternDatabase *strong_pdb, std::uint8_t cutoff,
                                                        SearchCounters &counters) const noexcept;
};

struct NativeSearchProgress {
    MoveMetric metric{MoveMetric::HTM};
    const char *phase{"proving"};
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
    DirectionPolicy direction_policy{DirectionPolicy::Bounded};
    DualPolicy dual_policy{DualPolicy::Off};
    bool bpmx{false};
    bool use_qtm_parity{true};
    bool strengthen_axes{true};
    bool qtm_phase1_axis_rule{true};
    bool qtm_strong_axis_rule{true};
    bool omit_covered_small_tables{true};
    bool staged_expansion{true};
    bool affine_coordinates{true};
    PdbQueryOrder query_order{PdbQueryOrder::StrongFirst};
    // The same-tree gain did not clear every default-request regression gate.
    QtmExpansionKernel qtm_expansion{QtmExpansionKernel::Generic};
    bool prefetch_strong{false};
    bool omit_strong_slice{false};
    bool strong_upgrade_restart{false};
    bool strong_first_proof{false};
    double base_proof_window_seconds{0.3};
    bool inverse_direction{false};
    bool use_native_candidate{true};
    CandidateSchedule candidate_schedule{CandidateSchedule::Legacy};
    bool late_tail_improvement{false};
    bool adaptive_split{true};
    bool selective_transposition{true};
    std::array<std::uint8_t, 18> move_costs{};
    int completed_depth{-1}; // Only supplied by the service's verified proof cache.
    const std::atomic<bool> *cancel_requested{nullptr};
    std::vector<int> incumbent_moves;
    std::function<std::vector<int>()> incumbent_callback;
    std::function<std::shared_ptr<const NativeOptimalSolver>()> asset_snapshot_callback;
    std::function<void(const NativeOptimalSolver &, int, double, double, std::uint64_t)> asset_adopted_callback;
    std::function<int()> loader_threads_callback;
    std::function<bool()> strong_loading_callback;
    std::function<void(int, int, int)> thread_activity_callback;
    std::function<void(int, std::uint64_t, double)> upgrade_callback;
    std::function<void(const std::vector<int> &)> candidate_callback;
    std::function<void(const CandidateDirectionStatistics &)> candidate_direction_callback;
    std::function<void(const FastCandidateResult &)> late_tail_callback;
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
    int direction_forward_lower_bound{};
    int direction_inverse_lower_bound{};
    std::uint64_t direction_probe_forward_generated{};
    std::uint64_t direction_probe_inverse_generated{};
    std::uint64_t direction_probe_forward_rejected{};
    std::uint64_t direction_probe_inverse_rejected{};
    double direction_probe_seconds{};
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
    std::array<CandidateDirectionStatistics, 6> candidate_directions;
    double candidate_budget_seconds{};
    double candidate_elapsed_seconds{};
    int late_tail_attempts{};
    int late_tail_improvements{};
    int late_tail_window_replacements{};
    double late_tail_seconds{};
    double late_tail_budget_seconds{};
    double first_candidate_seconds{-1.0};
    double candidate_worker_done_seconds{-1.0};
    double proof_worker_return_seconds{-1.0};
    int completed_depth{-1};
    int strong_upgrade_restarts{};
    std::uint64_t upgrade_discarded_generated{};
    double upgrade_stop_seconds{};
    double base_proof_seconds{};
    double base_last_used_seconds{-1.0};
    double strong_wait_seconds{};
    int base_window_yields{};
    std::uint64_t base_window_discarded_generated{};
    SearchCounters counters;
    std::vector<WorkerStatistics> workers;
    std::shared_ptr<const NativeOptimalSolver> asset_snapshot;
};

class NativeOptimalSolver {
  public:
    explicit NativeOptimalSolver(std::shared_ptr<CoordinateTables> tables = {});

    void load_corner_pdb(const std::filesystem::path &path, std::optional<MoveMetric> expected = std::nullopt);
    void load_phase1_pdb(const std::filesystem::path &path, std::optional<MoveMetric> expected = std::nullopt);
    void load_edge_pdb(int group, const std::filesystem::path &path, std::optional<MoveMetric> expected = std::nullopt);
    void load_edge_pdbs(const std::filesystem::path &path_a, const std::filesystem::path &path_b);
    void load_extra_edge_pdbs(const std::filesystem::path &path_c, const std::filesystem::path &path_d);
    void load_tail_database(const std::filesystem::path &path, MoveMetric expected_metric = MoveMetric::HTM,
                            LoaderControl *loader = nullptr);
    void load_strong_pdb(const std::filesystem::path &path, LoaderControl *loader = nullptr,
                         StrongValidationMode mode = StrongValidationMode::Legacy);
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
    [[nodiscard]] const CoordinateTables &coordinate_tables() const noexcept;
    [[nodiscard]] double strong_symmetry_initialization_seconds() const noexcept;
    [[nodiscard]] double strong_verification_seconds() const noexcept;
    [[nodiscard]] double strong_mapping_seconds() const noexcept;
    [[nodiscard]] double strong_checksum_worker_seconds() const noexcept;
    [[nodiscard]] double strong_nibble_worker_seconds() const noexcept;
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
