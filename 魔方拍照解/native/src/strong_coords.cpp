#include "strong_coords.hpp"

#include <algorithm>
#include <array>
#include <limits>
#include <stdexcept>

namespace cube {

std::uint16_t sorted_slice_coord(const CubieCube &cube) noexcept {
    std::array<std::uint8_t, 4> order{};
    int selected = 0;
    for (int position = 0; position < 12; ++position)
        if (cube.ep[position] >= 8)
            order[selected++] = static_cast<std::uint8_t>(cube.ep[position] - 8);
    return static_cast<std::uint16_t>(slice_comb_coord(cube) * 24U + rank_permutation(order));
}

CubieCube cube_from_sorted_slice(std::uint16_t coordinate) {
    if (coordinate >= kSortedSliceCount)
        throw std::invalid_argument("sorted slice coordinate out of range");
    CubieCube cube = cube_from_slice_comb(static_cast<std::uint16_t>(coordinate / 24U));
    const auto order = unrank_permutation(coordinate % 24U, 4);
    int selected = 0;
    for (int position = 0; position < 12; ++position)
        if (cube.ep[position] >= 8)
            cube.ep[position] = static_cast<std::uint8_t>(8 + order[selected++]);
    return cube;
}

SortedSliceSymmetry::SortedSliceSymmetry() {
    moves_.resize(static_cast<std::size_t>(kSortedSliceCount) * 18U);
    conjugates_.resize(static_cast<std::size_t>(kSortedSliceCount) * kPhase1SymmetryCount);
    for (std::uint16_t raw = 0; raw < kSortedSliceCount; ++raw) {
        const auto cube = cube_from_sorted_slice(raw);
        for (int move = 0; move < 18; ++move)
            moves_[static_cast<std::size_t>(raw) * 18U + move] = sorted_slice_coord(cube.apply_move(move));
        for (int symmetry = 0; symmetry < kPhase1SymmetryCount; ++symmetry)
            conjugates_[static_cast<std::size_t>(raw) * kPhase1SymmetryCount + symmetry] =
                sorted_slice_coord(phase1_.conjugate_edges(cube, symmetry));
    }
    raw_to_class_.resize(kSortedSliceCount, std::numeric_limits<std::uint16_t>::max());
    raw_to_symmetry_.resize(kSortedSliceCount);
    for (std::uint16_t raw = 0; raw < kSortedSliceCount; ++raw) {
        std::uint16_t representative_raw = raw;
        std::uint8_t symmetry_to_rep = 0;
        for (int symmetry = 1; symmetry < kPhase1SymmetryCount; ++symmetry) {
            const auto transformed = conjugate(raw, symmetry);
            if (transformed < representative_raw) {
                representative_raw = transformed;
                symmetry_to_rep = static_cast<std::uint8_t>(symmetry);
            }
        }
        if (representative_raw == raw) {
            raw_to_class_[raw] = static_cast<std::uint16_t>(representatives_.size());
            representatives_.push_back(raw);
        } else {
            if (raw_to_class_[representative_raw] == std::numeric_limits<std::uint16_t>::max())
                throw std::runtime_error("sorted slice symmetry representative ordering is inconsistent");
            raw_to_class_[raw] = raw_to_class_[representative_raw];
        }
        raw_to_symmetry_[raw] = symmetry_to_rep;
    }
    stabilizers_.resize(representatives_.size(), 1U);
    for (std::size_t class_index = 0; class_index < representatives_.size(); ++class_index)
        for (int symmetry = 1; symmetry < kPhase1SymmetryCount; ++symmetry)
            if (conjugate(representatives_[class_index], symmetry) == representatives_[class_index])
                stabilizers_[class_index] |= static_cast<std::uint16_t>(1U << symmetry);

    // Check the joint slice/flip projection against full legal cubies, not only
    // against synthetic coordinates with arbitrary other edge assignments.
    CubieCube probe;
    std::uint32_t random = 0xA83149C5U;
    for (int sample = 0; sample < 128; ++sample) {
        random = random * 1664525U + 1013904223U;
        probe = probe.apply_move(static_cast<int>(random % 18U));
        const auto sorted = sorted_slice_coord(probe);
        const auto flip = flip_coord(probe);
        for (int move = 0; move < 18; ++move)
            if (sorted_slice_coord(probe.apply_move(move)) != moved(sorted, move))
                throw std::runtime_error("sorted slice move differs from full cubie transition");
        for (int symmetry = 0; symmetry < kPhase1SymmetryCount; ++symmetry) {
            const auto full = phase1_.conjugate(probe, symmetry);
            if (sorted_slice_coord(full) != conjugate(sorted, symmetry) ||
                flip_coord(full) != flip_conjugate(flip, sorted, symmetry))
                throw std::runtime_error("sorted slice/flip symmetry differs from full cubie conjugation");
        }
    }
}

std::uint16_t SortedSliceSymmetry::moved(std::uint16_t sorted, int move) const noexcept {
    return moves_[static_cast<std::size_t>(sorted) * 18U + move];
}

std::uint16_t SortedSliceSymmetry::conjugate(std::uint16_t sorted, int symmetry) const noexcept {
    return conjugates_[static_cast<std::size_t>(sorted) * kPhase1SymmetryCount + symmetry];
}

std::uint16_t SortedSliceSymmetry::class_index(std::uint16_t sorted) const noexcept {
    return raw_to_class_[sorted];
}

std::uint8_t SortedSliceSymmetry::symmetry_to_representative(std::uint16_t sorted) const noexcept {
    return raw_to_symmetry_[sorted];
}

std::uint16_t SortedSliceSymmetry::representative(std::uint16_t class_index) const noexcept {
    return representatives_[class_index];
}

std::uint16_t SortedSliceSymmetry::stabilizer_mask(std::uint16_t class_index) const noexcept {
    return stabilizers_[class_index];
}

std::uint16_t SortedSliceSymmetry::flip_conjugate(std::uint16_t flip, std::uint16_t sorted,
                                                  int symmetry) const noexcept {
    auto cube = cube_from_sorted_slice(sorted);
    cube.eo = cube_from_flip(flip).eo;
    return flip_coord(phase1_.conjugate_edges(cube, symmetry));
}

std::uint64_t SortedSliceSymmetry::canonical_index(std::uint16_t twist, std::uint16_t flip,
                                                    std::uint16_t sorted) const noexcept {
    const auto symmetry = symmetry_to_representative(sorted);
    const auto canonical_flip = flip_conjugate(flip, sorted, symmetry);
    const auto canonical_twist = phase1_.twist_conjugate(twist, symmetry);
    return (static_cast<std::uint64_t>(class_index(sorted)) * 2048U + canonical_flip) * 2187U + canonical_twist;
}

std::uint16_t SortedSliceSymmetry::class_count() const noexcept {
    return static_cast<std::uint16_t>(representatives_.size());
}

const Phase1Symmetry &SortedSliceSymmetry::phase1() const noexcept { return phase1_; }

} // namespace cube
