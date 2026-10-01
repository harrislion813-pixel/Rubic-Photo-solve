#pragma once

#include "metric.hpp"
#include "strong_coords.hpp"

#include <array>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <span>

namespace cube {

class CoordinateTables;
class LoaderControl;
inline constexpr std::uint64_t kStrongPatternEntries = 788ULL * 2048ULL * 2187ULL;

struct StrongVerification {
    std::uint64_t entries{};
    std::array<std::uint64_t, 255> distance_histogram{};
};

enum class StrongValidationMode { Legacy, Fused, Split };

struct StrongChunkValidation {
    std::uint64_t checksum{1469598103934665603ULL};
    std::uint8_t maximum{};
    bool valid{true};
    double checksum_seconds{};
    double nibble_seconds{};
};

[[nodiscard]] StrongChunkValidation validate_strong_chunk(std::span<const std::uint8_t> bytes,
                                                          std::uint8_t coverage_depth, StrongValidationMode mode);

class StrongPatternDatabase {
  public:
    explicit StrongPatternDatabase(const std::filesystem::path &path, LoaderControl *loader = nullptr,
                                   StrongValidationMode mode = StrongValidationMode::Legacy);
    ~StrongPatternDatabase();
    StrongPatternDatabase(const StrongPatternDatabase &) = delete;
    StrongPatternDatabase &operator=(const StrongPatternDatabase &) = delete;

    [[nodiscard]] std::uint8_t distance(std::uint16_t twist, std::uint16_t flip, std::uint16_t sorted,
                                        bool affine = true) const noexcept;
    [[nodiscard]] std::uint64_t prepare_index(std::uint16_t twist, std::uint16_t flip, std::uint16_t sorted,
                                              bool affine = true) const noexcept;
    [[nodiscard]] std::uint8_t load_distance(std::uint64_t index) const noexcept;
    void prefetch(std::uint64_t index) const noexcept;
    [[nodiscard]] std::uint16_t sorted_move(std::uint16_t sorted, int move) const noexcept;
    [[nodiscard]] bool complete() const noexcept;
    [[nodiscard]] int coverage_depth() const noexcept;
    [[nodiscard]] std::uint8_t max_distance() const noexcept;
    [[nodiscard]] bool packed() const noexcept;
    [[nodiscard]] double symmetry_initialization_seconds() const noexcept;
    [[nodiscard]] double verification_seconds() const noexcept;
    [[nodiscard]] double mapping_seconds() const noexcept;
    [[nodiscard]] double checksum_worker_seconds() const noexcept;
    [[nodiscard]] double nibble_worker_seconds() const noexcept;
    [[nodiscard]] std::uint8_t raw_distance(std::uint64_t index) const noexcept;
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
    bool packed_{};
    double symmetry_initialization_seconds_{};
    double verification_seconds_{};
    double mapping_seconds_{};
    double checksum_worker_seconds_{};
    double nibble_worker_seconds_{};
};

[[nodiscard]] StrongVerification convert_strong_pattern_database_to_nibble(const std::filesystem::path &source,
                                                                           const std::filesystem::path &target);

void build_strong_pattern_database(const std::filesystem::path &path, const CoordinateTables &tables, int threads = 8,
                                   int coverage_depth = 254, bool resume = false, double memory_limit_gib = 12.0);

} // namespace cube
