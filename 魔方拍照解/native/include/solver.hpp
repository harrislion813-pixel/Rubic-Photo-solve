#pragma once

#include "cube.hpp"

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

struct CoordinateState {
    std::optional<CubieCube> cube;
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
    bool full_cube_for_heuristic{true};
};

class CoordinateTables {
public:
    CoordinateTables();

    [[nodiscard]] CoordinateState from_cube(
        const CubieCube& cube,
        const CoordinateFeatures& features = {}) const noexcept;
    [[nodiscard]] CoordinateState moved(
        const CoordinateState& state,
        int move,
        const CoordinateFeatures& features = {}) const noexcept;
    [[nodiscard]] std::uint8_t heuristic(
        const CoordinateState& state,
        const Phase1PatternDatabase* phase1_pdb = nullptr,
        const CornerPatternDatabase* corner_pdb = nullptr,
        std::span<const EdgePatternDatabase* const> edge_pdbs = {},
        std::uint8_t cutoff = 255) const noexcept;

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
};

struct NativeSearchProgress {
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
};

struct SolverOptions {
    int max_depth{20};
    double timeout_seconds{180.0};
    int threads{0};
    std::size_t transposition_limit_per_thread{500'000};
    bool use_transposition{false};
    bool use_direction_probe{true};
    std::vector<int> incumbent_moves;
    std::function<void(const NativeSearchProgress&)> progress_callback;
};

struct NativeSolveResult {
    std::vector<int> moves;
    int depth{-1};
    bool optimal{false};
    bool timed_out{false};
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
};

class NativeOptimalSolver {
public:
    explicit NativeOptimalSolver(std::shared_ptr<CoordinateTables> tables = {});

    void load_corner_pdb(const std::filesystem::path& path);
    void load_phase1_pdb(const std::filesystem::path& path);
    void load_edge_pdb(int group, const std::filesystem::path& path);
    void load_edge_pdbs(const std::filesystem::path& path_a, const std::filesystem::path& path_b);
    void load_extra_edge_pdbs(const std::filesystem::path& path_c, const std::filesystem::path& path_d);
    void load_tail_database(const std::filesystem::path& path);
    [[nodiscard]] bool has_corner_pdb() const noexcept;
    [[nodiscard]] bool has_phase1_pdb() const noexcept;
    [[nodiscard]] bool has_edge_pdbs() const noexcept;
    [[nodiscard]] bool has_extra_edge_pdbs() const noexcept;
    [[nodiscard]] int edge_pdb_count() const noexcept;
    [[nodiscard]] bool has_tail_database() const noexcept;
    [[nodiscard]] NativeSolveResult solve(const CubieCube& cube, const SolverOptions& options) const;

private:
    std::shared_ptr<CoordinateTables> tables_;
    std::shared_ptr<Phase1PatternDatabase> phase1_pdb_;
    std::shared_ptr<CornerPatternDatabase> corner_pdb_;
    std::array<std::shared_ptr<EdgePatternDatabase>, 8> edge_pdbs_{};
    std::shared_ptr<TailDatabase> tail_database_;
};

}  // namespace cube
