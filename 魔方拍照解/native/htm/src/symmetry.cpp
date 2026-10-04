#include "symmetry.hpp"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

namespace cube {
namespace {

using Vector = std::array<std::int8_t, 3>;
using Sticker = std::pair<Vector, Vector>;

constexpr std::array<char, 6> kFaces{'U', 'R', 'F', 'D', 'L', 'B'};
constexpr std::array<Vector, 6> kFaceNormals{{
    {{0, 1, 0}},
    {{1, 0, 0}},
    {{0, 0, 1}},
    {{0, -1, 0}},
    {{-1, 0, 0}},
    {{0, 0, -1}},
}};
constexpr std::array<std::array<int, 2>, 12> kEdgeFacelets{{
    {{5, 10}},
    {{7, 19}},
    {{3, 37}},
    {{1, 46}},
    {{32, 16}},
    {{28, 25}},
    {{30, 43}},
    {{34, 52}},
    {{23, 12}},
    {{21, 41}},
    {{50, 39}},
    {{48, 14}},
}};

int face_for_normal(const Vector &normal) {
    const auto found = std::find(kFaceNormals.begin(), kFaceNormals.end(), normal);
    if (found == kFaceNormals.end())
        throw std::runtime_error("invalid transformed face normal");
    return static_cast<int>(found - kFaceNormals.begin());
}

std::array<Sticker, 54> sticker_geometry() {
    std::array<Sticker, 54> result{};
    const auto set = [&](int index, Vector position, Vector normal) { result[index] = {position, normal}; };
    for (int row = 0; row < 3; ++row) {
        for (int column = 0; column < 3; ++column) {
            set(row * 3 + column, {static_cast<std::int8_t>(column - 1), 1, static_cast<std::int8_t>(row - 1)},
                {0, 1, 0});
            set(9 + row * 3 + column, {1, static_cast<std::int8_t>(1 - row), static_cast<std::int8_t>(1 - column)},
                {1, 0, 0});
            set(18 + row * 3 + column, {static_cast<std::int8_t>(column - 1), static_cast<std::int8_t>(1 - row), 1},
                {0, 0, 1});
            set(27 + row * 3 + column, {static_cast<std::int8_t>(column - 1), -1, static_cast<std::int8_t>(1 - row)},
                {0, -1, 0});
            set(36 + row * 3 + column, {-1, static_cast<std::int8_t>(1 - row), static_cast<std::int8_t>(column - 1)},
                {-1, 0, 0});
            set(45 + row * 3 + column, {static_cast<std::int8_t>(1 - column), static_cast<std::int8_t>(1 - row), -1},
                {0, 0, -1});
        }
    }
    return result;
}

std::uint32_t sticker_key(const Sticker &sticker) noexcept {
    std::uint32_t key = 0;
    for (std::int8_t component : sticker.first)
        key = key * 3U + static_cast<std::uint32_t>(component + 1);
    for (std::int8_t component : sticker.second)
        key = key * 3U + static_cast<std::uint32_t>(component + 1);
    return key;
}

CubieCube conjugate_axis_impl(const CubieCube &cube, int axis_rotation) {
    const auto transform = [axis_rotation](const Vector &vector) {
        const auto [x, y, z] = vector;
        if (axis_rotation == 0)
            return Vector{x, static_cast<std::int8_t>(-z), y};
        return Vector{static_cast<std::int8_t>(-y), x, z};
    };
    const auto geometry = sticker_geometry();
    std::unordered_map<std::uint32_t, int> sticker_indices;
    sticker_indices.reserve(54);
    for (int index = 0; index < 54; ++index)
        sticker_indices.emplace(sticker_key(geometry[index]), index);

    const std::string old_facelets = to_facelets(cube);
    std::string new_facelets(54, '?');
    std::array<char, 256> color_map{};
    for (int face = 0; face < 6; ++face) {
        color_map[static_cast<unsigned char>(kFaces[face])] = kFaces[face_for_normal(transform(kFaceNormals[face]))];
    }
    for (int old_index = 0; old_index < 54; ++old_index) {
        const Sticker transformed{transform(geometry[old_index].first), transform(geometry[old_index].second)};
        new_facelets[sticker_indices.at(sticker_key(transformed))] =
            color_map[static_cast<unsigned char>(old_facelets[old_index])];
    }
    return from_facelets(new_facelets);
}

} // namespace

CubieCube conjugate_axis(const CubieCube &cube, int axis_rotation) {
    if (axis_rotation < 0 || axis_rotation >= kAxisRotationCount) {
        throw std::out_of_range("axis rotation must be 0..1");
    }
    return conjugate_axis_impl(cube, axis_rotation);
}

const std::array<std::array<std::uint8_t, 18>, kAxisRotationCount> &axis_rotation_move_maps() {
    static const auto maps = [] {
        std::array<std::array<std::uint8_t, 18>, kAxisRotationCount> result{};
        for (int axis = 0; axis < kAxisRotationCount; ++axis) {
            for (int move = 0; move < 18; ++move) {
                const CubieCube transformed = conjugate_axis_impl(move_cubes()[move], axis);
                const auto found = std::find(move_cubes().begin(), move_cubes().end(), transformed);
                if (found == move_cubes().end())
                    throw std::runtime_error("axis rotation did not map a move to a move");
                result[axis][move] = static_cast<std::uint8_t>(found - move_cubes().begin());
            }
        }
        return result;
    }();
    return maps;
}

Phase1Symmetry::Phase1Symmetry() {
    const Matrix identity{{{1, 0, 0}, {0, 1, 0}, {0, 0, 1}}};
    const Matrix front_half_turn{{{-1, 0, 0}, {0, -1, 0}, {0, 0, 1}}};
    const Matrix up_quarter_turn{{{0, 0, 1}, {0, 1, 0}, {-1, 0, 0}}};
    const Matrix left_right_reflection{{{-1, 0, 0}, {0, 1, 0}, {0, 0, 1}}};

    const auto multiply = [](const Matrix &left, const Matrix &right) {
        Matrix result{};
        for (int row = 0; row < 3; ++row) {
            for (int column = 0; column < 3; ++column) {
                int value = 0;
                for (int inner = 0; inner < 3; ++inner) {
                    value += left.value[row][inner] * right.value[inner][column];
                }
                result.value[row][column] = static_cast<std::int8_t>(value);
            }
        }
        return result;
    };
    const auto transform = [](const Matrix &matrix, const Vector &vector) {
        Vector result{};
        for (int row = 0; row < 3; ++row) {
            int value = 0;
            for (int column = 0; column < 3; ++column)
                value += matrix.value[row][column] * vector[column];
            result[row] = static_cast<std::int8_t>(value);
        }
        return result;
    };

    matrices_.push_back(identity);
    const std::array<Matrix, 3> generators{front_half_turn, up_quarter_turn, left_right_reflection};
    for (std::size_t cursor = 0; cursor < matrices_.size(); ++cursor) {
        for (const Matrix &generator : generators) {
            const Matrix candidate = multiply(generator, matrices_[cursor]);
            if (std::find(matrices_.begin(), matrices_.end(), candidate) == matrices_.end()) {
                matrices_.push_back(candidate);
            }
        }
    }
    if (matrices_.size() != kPhase1SymmetryCount) {
        throw std::runtime_error("phase-1 symmetry generators did not produce 16 elements");
    }

    const auto geometry = sticker_geometry();
    std::unordered_map<std::uint32_t, int> sticker_indices;
    sticker_indices.reserve(54);
    for (int index = 0; index < 54; ++index)
        sticker_indices.emplace(sticker_key(geometry[index]), index);

    for (int symmetry = 0; symmetry < kPhase1SymmetryCount; ++symmetry) {
        for (int old_position = 0; old_position < 12; ++old_position) {
            const Sticker transformed{
                transform(matrices_[symmetry], geometry[kEdgeFacelets[old_position][0]].first),
                transform(matrices_[symmetry], geometry[kEdgeFacelets[old_position][0]].second),
            };
            const int new_facelet = sticker_indices.at(sticker_key(transformed));
            bool found = false;
            for (int new_position = 0; new_position < 12 && !found; ++new_position) {
                for (int slot = 0; slot < 2; ++slot) {
                    if (kEdgeFacelets[new_position][slot] != new_facelet)
                        continue;
                    edge_position_[symmetry][old_position] = static_cast<std::uint8_t>(new_position);
                    edge_frame_[symmetry][old_position] = static_cast<std::uint8_t>(slot);
                    found = true;
                    break;
                }
            }
            if (!found)
                throw std::runtime_error("transformed edge sticker is not an edge");
        }
    }

    const auto conjugate_with_matrix = [&](const CubieCube &cube, const Matrix &matrix) {
        const std::string old_facelets = to_facelets(cube);
        std::string new_facelets(54, '?');
        std::array<char, 256> color_map{};
        for (int face = 0; face < 6; ++face) {
            color_map[static_cast<unsigned char>(kFaces[face])] =
                kFaces[face_for_normal(transform(matrix, kFaceNormals[face]))];
        }
        for (int old_index = 0; old_index < 54; ++old_index) {
            const Sticker transformed{
                transform(matrix, geometry[old_index].first),
                transform(matrix, geometry[old_index].second),
            };
            const auto found = sticker_indices.find(sticker_key(transformed));
            if (found == sticker_indices.end())
                throw std::runtime_error("transformed sticker is not on the cube");
            new_facelets[found->second] = color_map[static_cast<unsigned char>(old_facelets[old_index])];
        }
        return from_facelets(new_facelets);
    };

    const wchar_t *configured = _wgetenv(L"CUBE_HTM_SYMMETRY_CACHE");
    const wchar_t *coordinate_cache = _wgetenv(L"CUBE_NATIVE_COORDINATE_CACHE");
    const std::filesystem::path cache =
        configured ? std::filesystem::path(configured)
        : coordinate_cache && *coordinate_cache
            ? std::filesystem::path(coordinate_cache).parent_path() / L"phase1_symmetry_htm_v1.bin"
            : std::filesystem::path(L".cache/htm/phase1_symmetry_htm_v1.bin");
    cache_loaded_ = !cache.empty() && load_cache(cache);
    if (!cache_loaded_) {
        representatives_.clear();
        // Cache each 54-facelet permutation as a transformed cubie operation by using
        // the matrix routine while the small coordinate conjugation tables are built.
        twist_conjugates_.resize(2187U * kPhase1SymmetryCount);
        for (std::uint16_t coordinate = 0; coordinate < 2187; ++coordinate) {
            const CubieCube cube = cube_from_twist(coordinate);
            for (int symmetry = 0; symmetry < kPhase1SymmetryCount; ++symmetry) {
                twist_conjugates_[static_cast<std::size_t>(coordinate) * kPhase1SymmetryCount + symmetry] =
                    twist_coord(conjugate_with_matrix(cube, matrices_[symmetry]));
            }
        }

        flip_conjugates_.resize(2048U * kPhase1SymmetryCount);
        for (std::uint16_t coordinate = 0; coordinate < 2048; ++coordinate) {
            const CubieCube cube = cube_from_flip(coordinate);
            for (int symmetry = 0; symmetry < kPhase1SymmetryCount; ++symmetry) {
                flip_conjugates_[static_cast<std::size_t>(coordinate) * kPhase1SymmetryCount + symmetry] =
                    flip_coord(conjugate_with_matrix(cube, matrices_[symmetry]));
            }
        }

        slice_conjugates_.resize(495U * kPhase1SymmetryCount);
        for (std::uint16_t coordinate = 0; coordinate < 495; ++coordinate) {
            CubieCube cube = cube_from_slice_comb(coordinate);
            if (permutation_parity(cube.ep) != 0)
                std::swap(cube.cp[0], cube.cp[1]);
            for (int symmetry = 0; symmetry < kPhase1SymmetryCount; ++symmetry) {
                slice_conjugates_[static_cast<std::size_t>(coordinate) * kPhase1SymmetryCount + symmetry] =
                    slice_comb_coord(conjugate_with_matrix(cube, matrices_[symmetry]));
            }
        }

        const auto conjugate_flip_slice_cube = [&](const CubieCube &cube, int symmetry) {
            CubieCube transformed;
            for (int old_position = 0; old_position < 12; ++old_position) {
                const int old_edge = cube.ep[old_position];
                const int new_position = edge_position_[symmetry][old_position];
                transformed.ep[new_position] = edge_position_[symmetry][old_edge];
                transformed.eo[new_position] = static_cast<std::uint8_t>(
                    cube.eo[old_position] ^ edge_frame_[symmetry][old_position] ^ edge_frame_[symmetry][old_edge]);
            }
            return static_cast<std::uint32_t>(flip_coord(transformed)) * 495U + slice_comb_coord(transformed);
        };

        static_assert((static_cast<std::uint64_t>(kFlipSliceClassCount - 1) * 2187U << 4U) + 15U <=
                      std::numeric_limits<std::uint32_t>::max());
        raw_to_packed_.assign(kFlipSliceRawCount, std::numeric_limits<std::uint32_t>::max());
        representatives_.reserve(kFlipSliceClassCount);
        for (std::uint32_t raw = 0; raw < kFlipSliceRawCount; ++raw) {
            CubieCube raw_cube = cube_from_slice_comb(static_cast<std::uint16_t>(raw % 495U));
            const CubieCube flip_cube = cube_from_flip(static_cast<std::uint16_t>(raw / 495U));
            raw_cube.eo = flip_cube.eo;
            std::uint32_t representative_raw = raw;
            std::uint8_t symmetry_to_rep = 0;
            for (int symmetry = 1; symmetry < kPhase1SymmetryCount; ++symmetry) {
                const std::uint32_t transformed = conjugate_flip_slice_cube(raw_cube, symmetry);
                if (transformed < representative_raw) {
                    representative_raw = transformed;
                    symmetry_to_rep = static_cast<std::uint8_t>(symmetry);
                }
            }
            if (representative_raw == raw) {
                raw_to_packed_[raw] = (static_cast<std::uint32_t>(representatives_.size()) * 2187U) << 4U;
                representatives_.push_back(raw);
            } else {
                if (raw_to_packed_[representative_raw] == std::numeric_limits<std::uint32_t>::max()) {
                    throw std::runtime_error("phase-1 symmetry representative ordering is inconsistent");
                }
                raw_to_packed_[raw] = raw_to_packed_[representative_raw] & ~15U;
            }
            raw_to_packed_[raw] |= symmetry_to_rep;
        }
        if (representatives_.size() != kFlipSliceClassCount) {
            throw std::runtime_error("phase-1 symmetry class count mismatch: got " +
                                     std::to_string(representatives_.size()));
        }
        if (!cache.empty())
            save_cache(cache);
    }

    // A projected symmetry table is useful for pruning only if it agrees with
    // conjugation of complete legal cubes. Exercise every symmetry on a stable
    // pseudo-random walk so convention errors fail at load time, not in search.
    CubieCube probe;
    std::uint32_t random = 0x6D2B79F5U;
    for (int sample = 0; sample < 128; ++sample) {
        random = random * 1664525U + 1013904223U;
        probe = probe.apply_move(static_cast<int>(random % 18U));
        const std::uint16_t probe_twist = twist_coord(probe);
        const std::uint32_t probe_raw = static_cast<std::uint32_t>(flip_coord(probe)) * 495U + slice_comb_coord(probe);
        for (int symmetry = 0; symmetry < kPhase1SymmetryCount; ++symmetry) {
            const CubieCube transformed = conjugate_with_matrix(probe, matrices_[symmetry]);
            const std::uint32_t transformed_raw =
                static_cast<std::uint32_t>(flip_coord(transformed)) * 495U + slice_comb_coord(transformed);
            if (twist_coord(transformed) != twist_conjugate(probe_twist, symmetry) ||
                transformed_raw != flip_slice_conjugate(probe_raw, symmetry)) {
                throw std::runtime_error("projected phase-1 symmetry table failed full-cube validation");
            }
        }
    }
}

namespace {
constexpr std::uint64_t kSymmetryCacheVersion = 0x314D544859534850ULL;
constexpr std::size_t kSymmetryCacheBytes = (2187U + 2048U + 495U) * 16U * sizeof(std::uint16_t) +
                                            (kFlipSliceRawCount + kFlipSliceClassCount) * sizeof(std::uint32_t);

std::uint64_t symmetry_checksum(const std::vector<std::uint8_t> &data) {
    std::uint64_t result = 1469598103934665603ULL;
    for (auto value : data) {
        result ^= value;
        result *= 1099511628211ULL;
    }
    return result;
}
} // namespace

bool Phase1Symmetry::load_cache(const std::filesystem::path &path) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    std::array<std::uint64_t, 10> header{};
    if (!input || input.tellg() != static_cast<std::streamoff>(sizeof(header) + kSymmetryCacheBytes))
        return false;
    input.seekg(0);
    std::vector<std::uint8_t> data(kSymmetryCacheBytes);
    input.read(reinterpret_cast<char *>(header.data()), sizeof(header));
    input.read(reinterpret_cast<char *>(data.data()), static_cast<std::streamsize>(data.size()));
    const std::array<std::uint64_t, 10> expected{
        kSymmetryCacheVersion, 0x0102030405060708ULL,  1, 2187, 2048, 495, kFlipSliceRawCount, kFlipSliceClassCount,
        kPhase1SymmetryCount,  symmetry_checksum(data)};
    if (!input || header != expected)
        return false;
    std::size_t offset = 0;
    auto read = [&](auto &values, std::size_t count) {
        values.resize(count);
        const auto bytes = count * sizeof(values[0]);
        std::memcpy(values.data(), data.data() + offset, bytes);
        offset += bytes;
    };
    read(twist_conjugates_, 2187U * 16U);
    read(flip_conjugates_, 2048U * 16U);
    read(slice_conjugates_, 495U * 16U);
    read(raw_to_packed_, kFlipSliceRawCount);
    read(representatives_, kFlipSliceClassCount);
    for (std::uint32_t raw = 0; raw < kFlipSliceRawCount; ++raw) {
        const auto base = raw_to_packed_[raw] >> 4U;
        if (base % 2187U != 0 || base / 2187U >= kFlipSliceClassCount || representatives_[base / 2187U] > raw)
            return false;
    }
    for (std::uint32_t i = 0; i < kFlipSliceClassCount; ++i) {
        const auto raw = representatives_[i];
        if (raw >= kFlipSliceRawCount || (i && raw <= representatives_[i - 1]) ||
            raw_to_packed_[raw] != (i * 2187U << 4U))
            return false;
    }
    if (!std::all_of(twist_conjugates_.begin(), twist_conjugates_.end(), [](auto v) { return v < 2187; }) ||
        !std::all_of(flip_conjugates_.begin(), flip_conjugates_.end(), [](auto v) { return v < 2048; }) ||
        !std::all_of(slice_conjugates_.begin(), slice_conjugates_.end(), [](auto v) { return v < 495; }))
        return false;
    CubieCube probe;
    std::uint32_t random = 0x6D2B79F5U;
    for (int sample = 0; sample < 128; ++sample) {
        random = random * 1664525U + 1013904223U;
        probe = probe.apply_move(static_cast<int>(random % 18U));
        const auto raw = static_cast<std::uint32_t>(flip_coord(probe)) * 495U + slice_comb_coord(probe);
        for (int s = 0; s < 16; ++s) {
            const auto transformed = conjugate(probe, s);
            if (twist_coord(transformed) != twist_conjugate(twist_coord(probe), s) ||
                static_cast<std::uint32_t>(flip_coord(transformed)) * 495U + slice_comb_coord(transformed) !=
                    flip_slice_conjugate(raw, s))
                return false;
        }
        if (flip_slice_conjugate(raw, symmetry_to_representative(raw)) != representative(class_index(raw)))
            return false;
    }
    return true;
}

void Phase1Symmetry::save_cache(const std::filesystem::path &path) const {
    std::filesystem::path temporary;
    try {
        if (!path.parent_path().empty())
            std::filesystem::create_directories(path.parent_path());
        std::vector<std::uint8_t> data;
        data.reserve(kSymmetryCacheBytes);
        auto append = [&](const auto &values) {
            const auto *bytes = reinterpret_cast<const std::uint8_t *>(values.data());
            data.insert(data.end(), bytes, bytes + values.size() * sizeof(values[0]));
        };
        append(twist_conjugates_);
        append(flip_conjugates_);
        append(slice_conjugates_);
        append(raw_to_packed_);
        append(representatives_);
        const std::array<std::uint64_t, 10> header{
            kSymmetryCacheVersion, 0x0102030405060708ULL,  1, 2187, 2048, 495, kFlipSliceRawCount, kFlipSliceClassCount,
            kPhase1SymmetryCount,  symmetry_checksum(data)};
        temporary = path;
        temporary +=
            L"." + std::to_wstring(GetCurrentProcessId()) + L"." + std::to_wstring(GetCurrentThreadId()) + L".tmp";
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        output.write(reinterpret_cast<const char *>(header.data()), sizeof(header));
        output.write(reinterpret_cast<const char *>(data.data()), static_cast<std::streamsize>(data.size()));
        output.close();
        if (!output ||
            !MoveFileExW(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
            throw std::runtime_error("could not publish optional HTM symmetry cache");
    } catch (...) {
        if (!temporary.empty()) {
            std::error_code ignored;
            std::filesystem::remove(temporary, ignored);
        }
    }
}

CubieCube Phase1Symmetry::conjugate(const CubieCube &cube, int symmetry) const {
    if (symmetry < 0 || symmetry >= kPhase1SymmetryCount)
        throw std::out_of_range("symmetry must be 0..15");

    const auto geometry = sticker_geometry();
    std::unordered_map<std::uint32_t, int> sticker_indices;
    sticker_indices.reserve(54);
    for (int index = 0; index < 54; ++index)
        sticker_indices.emplace(sticker_key(geometry[index]), index);
    const auto transform = [](const Matrix &matrix, const Vector &vector) {
        Vector result{};
        for (int row = 0; row < 3; ++row) {
            int value = 0;
            for (int column = 0; column < 3; ++column)
                value += matrix.value[row][column] * vector[column];
            result[row] = static_cast<std::int8_t>(value);
        }
        return result;
    };
    const Matrix &matrix = matrices_[symmetry];
    const std::string old_facelets = to_facelets(cube);
    std::string new_facelets(54, '?');
    std::array<char, 256> color_map{};
    for (int face = 0; face < 6; ++face) {
        color_map[static_cast<unsigned char>(kFaces[face])] =
            kFaces[face_for_normal(transform(matrix, kFaceNormals[face]))];
    }
    for (int old_index = 0; old_index < 54; ++old_index) {
        const Sticker transformed{
            transform(matrix, geometry[old_index].first),
            transform(matrix, geometry[old_index].second),
        };
        new_facelets[sticker_indices.at(sticker_key(transformed))] =
            color_map[static_cast<unsigned char>(old_facelets[old_index])];
    }
    return from_facelets(new_facelets);
}

std::uint16_t Phase1Symmetry::twist_conjugate(std::uint16_t twist, int symmetry) const noexcept {
    return twist_conjugates_[static_cast<std::size_t>(twist) * kPhase1SymmetryCount + symmetry];
}

std::uint16_t Phase1Symmetry::flip_conjugate(std::uint16_t flip, int symmetry) const noexcept {
    return flip_conjugates_[static_cast<std::size_t>(flip) * kPhase1SymmetryCount + symmetry];
}

std::uint16_t Phase1Symmetry::slice_conjugate(std::uint16_t slice, int symmetry) const noexcept {
    return slice_conjugates_[static_cast<std::size_t>(slice) * kPhase1SymmetryCount + symmetry];
}

std::uint32_t Phase1Symmetry::flip_slice_conjugate(std::uint32_t raw, int symmetry) const noexcept {
    CubieCube cube = cube_from_slice_comb(static_cast<std::uint16_t>(raw % 495U));
    cube.eo = cube_from_flip(static_cast<std::uint16_t>(raw / 495U)).eo;
    CubieCube transformed;
    for (int old_position = 0; old_position < 12; ++old_position) {
        const int old_edge = cube.ep[old_position];
        const int new_position = edge_position_[symmetry][old_position];
        transformed.ep[new_position] = edge_position_[symmetry][old_edge];
        transformed.eo[new_position] = static_cast<std::uint8_t>(
            cube.eo[old_position] ^ edge_frame_[symmetry][old_position] ^ edge_frame_[symmetry][old_edge]);
    }
    return static_cast<std::uint32_t>(flip_coord(transformed)) * 495U + slice_comb_coord(transformed);
}

std::uint32_t Phase1Symmetry::class_count() const noexcept {
    return static_cast<std::uint32_t>(representatives_.size());
}

std::uint32_t Phase1Symmetry::class_index(std::uint32_t raw) const noexcept {
    return (raw_to_packed_[raw] >> 4U) / 2187U;
}

std::uint8_t Phase1Symmetry::symmetry_to_representative(std::uint32_t raw) const noexcept {
    return static_cast<std::uint8_t>(raw_to_packed_[raw] & 15U);
}

std::uint32_t Phase1Symmetry::representative(std::uint32_t class_index_value) const noexcept {
    return representatives_[class_index_value];
}

std::uint32_t Phase1Symmetry::canonical_index(std::uint16_t twist, std::uint16_t flip,
                                              std::uint16_t slice) const noexcept {
    const std::uint32_t raw = static_cast<std::uint32_t>(flip) * 495U + slice;
    const std::uint32_t packed = raw_to_packed_[raw];
    return (packed >> 4U) + twist_conjugate(twist, static_cast<int>(packed & 15U));
}

const std::vector<std::uint16_t> &Phase1Symmetry::twist_table() const noexcept { return twist_conjugates_; }
const std::vector<std::uint32_t> &Phase1Symmetry::raw_to_packed_table() const noexcept { return raw_to_packed_; }
const std::vector<std::uint32_t> &Phase1Symmetry::representatives() const noexcept { return representatives_; }

} // namespace cube
