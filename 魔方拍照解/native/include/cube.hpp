#pragma once

#include <array>
#include <cstdint>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace cube {

inline constexpr std::array<std::string_view, 6> kFaceNames{"U", "R", "F", "D", "L", "B"};
inline constexpr std::array<std::string_view, 18> kMoveNames{
    "U", "U2", "U'", "R", "R2", "R'", "F", "F2", "F'",
    "D", "D2", "D'", "L", "L2", "L'", "B", "B2", "B'",
};

struct CubieCube {
    std::array<std::uint8_t, 8> cp{0, 1, 2, 3, 4, 5, 6, 7};
    std::array<std::uint8_t, 8> co{};
    std::array<std::uint8_t, 12> ep{0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11};
    std::array<std::uint8_t, 12> eo{};

    [[nodiscard]] CubieCube moved(const CubieCube& move) const noexcept;
    [[nodiscard]] CubieCube apply_move(int move_index) const noexcept;
    [[nodiscard]] CubieCube inverse() const noexcept;
    [[nodiscard]] bool solved() const noexcept;
    auto operator<=>(const CubieCube&) const = default;
};

struct EdgePatternState {
    std::array<std::uint8_t, 6> positions{};
    std::uint8_t orientations{};
    auto operator<=>(const EdgePatternState&) const = default;
};

[[nodiscard]] const std::array<CubieCube, 18>& move_cubes();
[[nodiscard]] int move_index(std::string_view move) noexcept;
[[nodiscard]] int inverse_move_index(int move) noexcept;
[[nodiscard]] std::vector<int> invert_moves(std::span<const int> moves);
[[nodiscard]] std::string clean_facelets(std::string_view facelets);
[[nodiscard]] CubieCube from_facelets(std::string_view facelets);
[[nodiscard]] std::string to_facelets(const CubieCube& cube);
void validate_cube(const CubieCube& cube);

[[nodiscard]] std::uint16_t twist_coord(const CubieCube& cube) noexcept;
[[nodiscard]] std::uint16_t flip_coord(const CubieCube& cube) noexcept;
[[nodiscard]] std::uint16_t corner_perm_coord(const CubieCube& cube) noexcept;
[[nodiscard]] std::uint16_t slice_comb_coord(const CubieCube& cube) noexcept;
[[nodiscard]] std::uint32_t corner_pattern_coord(const CubieCube& cube) noexcept;

[[nodiscard]] std::uint32_t rank_permutation(std::span<const std::uint8_t> permutation) noexcept;
[[nodiscard]] std::vector<std::uint8_t> unrank_permutation(std::uint32_t rank, int size);
[[nodiscard]] CubieCube cube_from_twist(std::uint16_t coordinate) noexcept;
[[nodiscard]] CubieCube cube_from_flip(std::uint16_t coordinate) noexcept;
[[nodiscard]] CubieCube cube_from_corner_perm(std::uint16_t coordinate);
[[nodiscard]] CubieCube cube_from_slice_comb(std::uint16_t coordinate);
[[nodiscard]] EdgePatternState edge_pattern_state(const CubieCube& cube, int first_edge) noexcept;
[[nodiscard]] EdgePatternState edge_pattern_state(
    const CubieCube& cube,
    std::span<const std::uint8_t, 6> selected_edges) noexcept;
[[nodiscard]] const std::array<std::uint8_t, 6>& edge_pattern_group(int group);
[[nodiscard]] EdgePatternState edge_pattern_from_coord(std::uint32_t coordinate);
[[nodiscard]] EdgePatternState move_edge_pattern(const EdgePatternState& state, int move) noexcept;
[[nodiscard]] std::uint32_t edge_pattern_coord(const EdgePatternState& state) noexcept;
[[nodiscard]] int permutation_parity(std::span<const std::uint8_t> permutation) noexcept;
[[nodiscard]] bool should_skip_face(int last_face, int face) noexcept;

}  // namespace cube
