#pragma once

#include "metric.hpp"
#include "strong_coords.hpp"

#include <array>
#include <cstdint>
#include <filesystem>
#include <memory>

namespace cube {

class CoordinateTables;
inline constexpr std::uint64_t kStrongPatternEntries = 788ULL * 2048ULL * 2187ULL;

struct StrongVerification {
    std::uint64_t entries{};
    std::array<std::uint64_t, 255> distance_histogram{};
};

class StrongPatternDatabase {
  public:
    explicit StrongPatternDatabase(const std::filesystem::path &path);
    ~StrongPatternDatabase();
    StrongPatternDatabase(const StrongPatternDatabase &) = delete;
    StrongPatternDatabase &operator=(const StrongPatternDatabase &) = delete;

    [[nodiscard]] std::uint8_t distance(std::uint16_t twist, std::uint16_t flip, std::uint16_t sorted) const noexcept;
    [[nodiscard]] std::uint16_t sorted_move(std::uint16_t sorted, int move) const noexcept;
    [[nodiscard]] bool complete() const noexcept;
    [[nodiscard]] int coverage_depth() const noexcept;
    [[nodiscard]] std::uint8_t max_distance() const noexcept;
    [[nodiscard]] StrongVerification verify_all(const CoordinateTables &tables, int threads = 8) const;

  private:
    void *file_{nullptr};
    void *mapping_{nullptr};
    const std::uint8_t *view_{nullptr};
    const std::uint8_t *data_{nullptr};
    std::shared_ptr<SortedSliceSymmetry> symmetry_;
    int coverage_depth_{};
    std::uint8_t max_distance_{};
    bool complete_{};
};

void build_strong_pattern_database(const std::filesystem::path &path, const CoordinateTables &tables, int threads = 8,
                                   int coverage_depth = 254, bool resume = false, double memory_limit_gib = 12.0);

} // namespace cube
