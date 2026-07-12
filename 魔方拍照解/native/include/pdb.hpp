#pragma once

#include <cstdint>
#include <filesystem>
#include <memory>

namespace cube {

class CoordinateTables;
class Phase1Symmetry;

inline constexpr std::uint64_t kCornerPatternEntries = 88'179'840ULL;
inline constexpr std::uint64_t kEdgePatternEntries = 42'577'920ULL;
inline constexpr std::uint64_t kPhase1PatternEntries = 64'430ULL * 2'187ULL;

class Phase1PatternDatabase {
  public:
    explicit Phase1PatternDatabase(const std::filesystem::path &path);
    ~Phase1PatternDatabase();

    Phase1PatternDatabase(const Phase1PatternDatabase &) = delete;
    Phase1PatternDatabase &operator=(const Phase1PatternDatabase &) = delete;

    [[nodiscard]] std::uint8_t distance(std::uint16_t twist, std::uint16_t flip, std::uint16_t slice) const noexcept;
    [[nodiscard]] bool complete() const noexcept;
    [[nodiscard]] std::uint8_t max_value() const noexcept;

  private:
    void *file_{nullptr};
    void *mapping_{nullptr};
    const std::uint8_t *view_{nullptr};
    const std::uint8_t *data_{nullptr};
    std::shared_ptr<Phase1Symmetry> symmetry_;
    std::uint8_t max_value_{0};
    bool complete_{false};
};

class CornerPatternDatabase {
  public:
    explicit CornerPatternDatabase(const std::filesystem::path &path);
    ~CornerPatternDatabase();

    CornerPatternDatabase(const CornerPatternDatabase &) = delete;
    CornerPatternDatabase &operator=(const CornerPatternDatabase &) = delete;

    [[nodiscard]] std::uint8_t distance(std::uint32_t coordinate) const noexcept;
    [[nodiscard]] bool complete() const noexcept;
    [[nodiscard]] std::uint8_t max_value() const noexcept;

  private:
    void *file_{nullptr};
    void *mapping_{nullptr};
    const std::uint8_t *view_{nullptr};
    const std::uint8_t *data_{nullptr};
    std::uint8_t max_value_{0};
    bool complete_{false};
};

class EdgePatternDatabase {
  public:
    EdgePatternDatabase(const std::filesystem::path &path, int group);
    ~EdgePatternDatabase();

    EdgePatternDatabase(const EdgePatternDatabase &) = delete;
    EdgePatternDatabase &operator=(const EdgePatternDatabase &) = delete;

    [[nodiscard]] std::uint8_t distance(std::uint32_t coordinate) const noexcept;
    [[nodiscard]] bool complete() const noexcept;
    [[nodiscard]] std::uint8_t max_value() const noexcept;

  private:
    void *file_{nullptr};
    void *mapping_{nullptr};
    const std::uint8_t *view_{nullptr};
    const std::uint8_t *data_{nullptr};
    std::uint8_t max_value_{0};
    bool complete_{false};
};

void build_corner_pattern_database(const std::filesystem::path &path, const CoordinateTables &tables, int threads,
                                   int coverage_depth = 11, bool force = false);

void build_edge_pattern_database(const std::filesystem::path &path, int group, int threads, int coverage_depth = 10,
                                 bool force = false);

void build_phase1_pattern_database(const std::filesystem::path &path, const CoordinateTables &tables, int threads,
                                   int coverage_depth = 12, bool force = false);

} // namespace cube
