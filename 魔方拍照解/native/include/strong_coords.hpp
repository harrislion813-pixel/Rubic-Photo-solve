#pragma once

#include "cube.hpp"
#include "symmetry.hpp"

#include <cstdint>
#include <vector>

namespace cube {

inline constexpr std::uint16_t kSortedSliceCount = 495U * 24U;

[[nodiscard]] std::uint16_t sorted_slice_coord(const CubieCube &cube) noexcept;
[[nodiscard]] CubieCube cube_from_sorted_slice(std::uint16_t coordinate);

class SortedSliceSymmetry {
  public:
    SortedSliceSymmetry();

    [[nodiscard]] std::uint16_t moved(std::uint16_t sorted, int move) const noexcept;
    [[nodiscard]] std::uint16_t conjugate(std::uint16_t sorted, int symmetry) const noexcept;
    [[nodiscard]] std::uint16_t class_index(std::uint16_t sorted) const noexcept;
    [[nodiscard]] std::uint8_t symmetry_to_representative(std::uint16_t sorted) const noexcept;
    [[nodiscard]] std::uint16_t representative(std::uint16_t class_index) const noexcept;
    [[nodiscard]] std::uint16_t stabilizer_mask(std::uint16_t class_index) const noexcept;
    [[nodiscard]] std::uint16_t flip_conjugate(std::uint16_t flip, std::uint16_t sorted, int symmetry) const noexcept;
    [[nodiscard]] std::uint64_t canonical_index(std::uint16_t twist, std::uint16_t flip,
                                                std::uint16_t sorted) const noexcept;
    [[nodiscard]] std::uint64_t canonical_index_reference(std::uint16_t twist, std::uint16_t flip,
                                                          std::uint16_t sorted) const noexcept;
    [[nodiscard]] std::uint16_t class_count() const noexcept;
    [[nodiscard]] const Phase1Symmetry &phase1() const noexcept;

  private:
    Phase1Symmetry phase1_;
    std::vector<std::uint16_t> moves_;
    std::vector<std::uint16_t> conjugates_;
    std::vector<std::uint16_t> raw_to_class_;
    std::vector<std::uint8_t> raw_to_symmetry_;
    std::vector<std::uint16_t> representatives_;
    std::vector<std::uint16_t> stabilizers_;
    std::vector<std::uint16_t> representative_flip_offsets_;
    std::vector<std::uint64_t> class_bases_;
};

} // namespace cube
