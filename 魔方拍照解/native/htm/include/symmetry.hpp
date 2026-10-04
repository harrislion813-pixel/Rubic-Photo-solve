#pragma once

#include "cube.hpp"

#include <array>
#include <cstdint>
#include <filesystem>
#include <vector>

namespace cube {

inline constexpr std::uint32_t kFlipSliceRawCount = 2048U * 495U;
inline constexpr std::uint32_t kFlipSliceClassCount = 64'430U;
inline constexpr int kPhase1SymmetryCount = 16;
inline constexpr int kAxisRotationCount = 2;

[[nodiscard]] CubieCube conjugate_axis(const CubieCube &cube, int axis_rotation);
[[nodiscard]] const std::array<std::array<std::uint8_t, 18>, kAxisRotationCount> &axis_rotation_move_maps();

class Phase1Symmetry {
  public:
    Phase1Symmetry();

    [[nodiscard]] CubieCube conjugate(const CubieCube &cube, int symmetry) const;
    [[nodiscard]] std::uint16_t twist_conjugate(std::uint16_t twist, int symmetry) const noexcept;
    [[nodiscard]] std::uint16_t flip_conjugate(std::uint16_t flip, int symmetry) const noexcept;
    [[nodiscard]] std::uint16_t slice_conjugate(std::uint16_t slice, int symmetry) const noexcept;
    [[nodiscard]] std::uint32_t flip_slice_conjugate(std::uint32_t raw, int symmetry) const noexcept;

    [[nodiscard]] std::uint32_t class_count() const noexcept;
    [[nodiscard]] std::uint32_t class_index(std::uint32_t raw) const noexcept;
    [[nodiscard]] std::uint8_t symmetry_to_representative(std::uint32_t raw) const noexcept;
    [[nodiscard]] std::uint32_t representative(std::uint32_t class_index) const noexcept;
    [[nodiscard]] std::uint32_t canonical_index(std::uint16_t twist, std::uint16_t flip,
                                                std::uint16_t slice) const noexcept;

    [[nodiscard]] const std::vector<std::uint16_t> &twist_table() const noexcept;
    [[nodiscard]] const std::vector<std::uint32_t> &raw_to_packed_table() const noexcept;
    [[nodiscard]] const std::vector<std::uint32_t> &representatives() const noexcept;
    [[nodiscard]] bool cache_loaded() const noexcept { return cache_loaded_; }

  private:
    struct Matrix {
        std::int8_t value[3][3]{};
        bool operator==(const Matrix &) const = default;
    };

    std::vector<Matrix> matrices_;
    std::array<std::array<std::uint8_t, 12>, kPhase1SymmetryCount> edge_position_{};
    std::array<std::array<std::uint8_t, 12>, kPhase1SymmetryCount> edge_frame_{};
    std::vector<std::uint16_t> twist_conjugates_;
    std::vector<std::uint16_t> flip_conjugates_;
    std::vector<std::uint16_t> slice_conjugates_;
    // Upper bits: class * 2187; low four bits: symmetry to that representative.
    std::vector<std::uint32_t> raw_to_packed_;
    std::vector<std::uint32_t> representatives_;
    bool cache_loaded_{false};
    [[nodiscard]] bool load_cache(const std::filesystem::path &path);
    void save_cache(const std::filesystem::path &path) const;
};

} // namespace cube
