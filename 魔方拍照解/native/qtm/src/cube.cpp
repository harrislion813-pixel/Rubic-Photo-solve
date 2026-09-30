#include "cube.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cctype>
#include <limits>
#include <numeric>
#include <stdexcept>

namespace cube {
namespace {

constexpr std::array<std::array<int, 3>, 8> kCornerFacelets{{
    {{8, 9, 20}},
    {{6, 18, 38}},
    {{0, 36, 47}},
    {{2, 45, 11}},
    {{29, 26, 15}},
    {{27, 44, 24}},
    {{33, 53, 42}},
    {{35, 17, 51}},
}};
constexpr std::array<std::array<char, 3>, 8> kCornerColors{{
    {{'U', 'R', 'F'}},
    {{'U', 'F', 'L'}},
    {{'U', 'L', 'B'}},
    {{'U', 'B', 'R'}},
    {{'D', 'F', 'R'}},
    {{'D', 'L', 'F'}},
    {{'D', 'B', 'L'}},
    {{'D', 'R', 'B'}},
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
constexpr std::array<std::array<char, 2>, 12> kEdgeColors{{
    {{'U', 'R'}},
    {{'U', 'F'}},
    {{'U', 'L'}},
    {{'U', 'B'}},
    {{'D', 'R'}},
    {{'D', 'F'}},
    {{'D', 'L'}},
    {{'D', 'B'}},
    {{'F', 'R'}},
    {{'F', 'L'}},
    {{'B', 'L'}},
    {{'B', 'R'}},
}};
constexpr std::string_view kSolvedFacelets = "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB";

constexpr int binomial(int n, int k) noexcept {
    if (k < 0 || k > n)
        return 0;
    if (k == 0 || k == n)
        return 1;
    int value = 1;
    for (int i = 1; i <= k; ++i)
        value = value * (n - k + i) / i;
    return value;
}

constexpr CubieCube make_cube(std::array<std::uint8_t, 8> cp, std::array<std::uint8_t, 8> co,
                              std::array<std::uint8_t, 12> ep, std::array<std::uint8_t, 12> eo) {
    return CubieCube{cp, co, ep, eo};
}

constexpr std::array<CubieCube, 6> kQuarterTurns{{
    make_cube({3, 0, 1, 2, 4, 5, 6, 7}, {0, 0, 0, 0, 0, 0, 0, 0}, {3, 0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11},
              {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}),
    make_cube({4, 1, 2, 0, 7, 5, 6, 3}, {2, 0, 0, 1, 1, 0, 0, 2}, {8, 1, 2, 3, 11, 5, 6, 7, 4, 9, 10, 0},
              {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}),
    make_cube({1, 5, 2, 3, 0, 4, 6, 7}, {1, 2, 0, 0, 2, 1, 0, 0}, {0, 9, 2, 3, 4, 8, 6, 7, 1, 5, 10, 11},
              {0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0}),
    make_cube({0, 1, 2, 3, 5, 6, 7, 4}, {0, 0, 0, 0, 0, 0, 0, 0}, {0, 1, 2, 3, 5, 6, 7, 4, 8, 9, 10, 11},
              {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}),
    make_cube({0, 2, 6, 3, 4, 1, 5, 7}, {0, 1, 2, 0, 0, 2, 1, 0}, {0, 1, 10, 3, 4, 5, 9, 7, 8, 2, 6, 11},
              {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}),
    make_cube({0, 1, 3, 7, 4, 5, 2, 6}, {0, 0, 1, 2, 0, 0, 2, 1}, {0, 1, 2, 11, 4, 5, 6, 10, 8, 9, 3, 7},
              {0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1}),
}};

} // namespace

CubieCube CubieCube::moved(const CubieCube &move) const noexcept {
    CubieCube result;
    for (int i = 0; i < 8; ++i) {
        result.cp[i] = cp[move.cp[i]];
        result.co[i] = static_cast<std::uint8_t>((co[move.cp[i]] + move.co[i]) % 3);
    }
    for (int i = 0; i < 12; ++i) {
        result.ep[i] = ep[move.ep[i]];
        result.eo[i] = static_cast<std::uint8_t>((eo[move.ep[i]] + move.eo[i]) % 2);
    }
    return result;
}

CubieCube CubieCube::apply_move(int move_index_value) const noexcept { return moved(move_cubes()[move_index_value]); }

CubieCube CubieCube::inverse() const noexcept {
    CubieCube result;
    for (int position = 0; position < 8; ++position) {
        const int cubie = cp[position];
        result.cp[cubie] = static_cast<std::uint8_t>(position);
        result.co[cubie] = static_cast<std::uint8_t>((3 - co[position]) % 3);
    }
    for (int position = 0; position < 12; ++position) {
        const int cubie = ep[position];
        result.ep[cubie] = static_cast<std::uint8_t>(position);
        result.eo[cubie] = eo[position];
    }
    return result;
}

bool CubieCube::solved() const noexcept { return *this == CubieCube{}; }

const std::array<CubieCube, 18> &move_cubes() {
    static const auto moves = [] {
        std::array<CubieCube, 18> result{};
        for (int face = 0; face < 6; ++face) {
            CubieCube current;
            for (int power = 0; power < 3; ++power) {
                current = current.moved(kQuarterTurns[face]);
                result[face * 3 + power] = current;
            }
        }
        return result;
    }();
    return moves;
}

int move_index(std::string_view move) noexcept {
    for (int i = 0; i < static_cast<int>(kMoveNames.size()); ++i) {
        if (kMoveNames[i] == move)
            return i;
    }
    return -1;
}

int inverse_move_index(int move) noexcept {
    const int turn = move % 3;
    return turn == 0 ? move + 2 : turn == 2 ? move - 2 : move;
}

std::vector<int> invert_moves(std::span<const int> moves) {
    std::vector<int> result;
    result.reserve(moves.size());
    for (auto move = moves.rbegin(); move != moves.rend(); ++move) {
        result.push_back(inverse_move_index(*move));
    }
    return result;
}

std::string clean_facelets(std::string_view facelets) {
    std::string compact;
    compact.reserve(54);
    for (char value : facelets) {
        const char ch = static_cast<char>(std::toupper(static_cast<unsigned char>(value)));
        if (std::string_view("URFDLB").find(ch) != std::string_view::npos)
            compact.push_back(ch);
    }
    if (compact.size() != 54)
        throw std::invalid_argument("expected 54 facelets in URFDLB order");
    for (char face : std::string_view("URFDLB")) {
        if (std::count(compact.begin(), compact.end(), face) != 9) {
            throw std::invalid_argument("each face label must occur exactly 9 times");
        }
    }
    constexpr std::array<int, 6> centers{4, 13, 22, 31, 40, 49};
    for (int i = 0; i < 6; ++i) {
        if (compact[centers[i]] != std::string_view("URFDLB")[i]) {
            throw std::invalid_argument("face centers must be fixed in URFDLB order");
        }
    }
    return compact;
}

CubieCube from_facelets(std::string_view facelets) {
    const std::string f = clean_facelets(facelets);
    CubieCube cube;
    cube.cp.fill(255);
    cube.co.fill(255);
    cube.ep.fill(255);
    cube.eo.fill(255);

    for (int position = 0; position < 8; ++position) {
        int orientation = -1;
        for (int candidate = 0; candidate < 3; ++candidate) {
            const char color = f[kCornerFacelets[position][candidate]];
            if (color == 'U' || color == 'D') {
                orientation = candidate;
                break;
            }
        }
        if (orientation < 0)
            throw std::invalid_argument("corner is missing a U/D sticker");
        const char color1 = f[kCornerFacelets[position][(orientation + 1) % 3]];
        const char color2 = f[kCornerFacelets[position][(orientation + 2) % 3]];
        for (int cubie = 0; cubie < 8; ++cubie) {
            if (kCornerColors[cubie][1] == color1 && kCornerColors[cubie][2] == color2) {
                cube.cp[position] = static_cast<std::uint8_t>(cubie);
                cube.co[position] = static_cast<std::uint8_t>(orientation);
                break;
            }
        }
        if (cube.cp[position] == 255)
            throw std::invalid_argument("unrecognized corner color combination");
    }

    for (int position = 0; position < 12; ++position) {
        const char color0 = f[kEdgeFacelets[position][0]];
        const char color1 = f[kEdgeFacelets[position][1]];
        for (int cubie = 0; cubie < 12; ++cubie) {
            if (kEdgeColors[cubie][0] == color0 && kEdgeColors[cubie][1] == color1) {
                cube.ep[position] = static_cast<std::uint8_t>(cubie);
                cube.eo[position] = 0;
                break;
            }
            if (kEdgeColors[cubie][0] == color1 && kEdgeColors[cubie][1] == color0) {
                cube.ep[position] = static_cast<std::uint8_t>(cubie);
                cube.eo[position] = 1;
                break;
            }
        }
        if (cube.ep[position] == 255)
            throw std::invalid_argument("unrecognized edge color combination");
    }
    validate_cube(cube);
    return cube;
}

std::string to_facelets(const CubieCube &cube) {
    std::string result{kSolvedFacelets};
    for (int position = 0; position < 8; ++position) {
        const int cubie = cube.cp[position];
        const int orientation = cube.co[position];
        for (int n = 0; n < 3; ++n) {
            result[kCornerFacelets[position][(n + orientation) % 3]] = kCornerColors[cubie][n];
        }
    }
    for (int position = 0; position < 12; ++position) {
        const int cubie = cube.ep[position];
        const int orientation = cube.eo[position];
        for (int n = 0; n < 2; ++n) {
            result[kEdgeFacelets[position][(n + orientation) % 2]] = kEdgeColors[cubie][n];
        }
    }
    return result;
}

void validate_cube(const CubieCube &cube) {
    auto corners = cube.cp;
    auto edges = cube.ep;
    std::sort(corners.begin(), corners.end());
    std::sort(edges.begin(), edges.end());
    if (corners != std::array<std::uint8_t, 8>{0, 1, 2, 3, 4, 5, 6, 7}) {
        throw std::invalid_argument("corner set is incomplete or duplicated");
    }
    if (edges != std::array<std::uint8_t, 12>{0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}) {
        throw std::invalid_argument("edge set is incomplete or duplicated");
    }
    const int corner_orientation = std::accumulate(cube.co.begin(), cube.co.end(), 0);
    const int edge_orientation = std::accumulate(cube.eo.begin(), cube.eo.end(), 0);
    if (corner_orientation % 3 != 0)
        throw std::invalid_argument("illegal corner orientation");
    if (edge_orientation % 2 != 0)
        throw std::invalid_argument("illegal edge orientation");
    if (permutation_parity(cube.cp) != permutation_parity(cube.ep)) {
        throw std::invalid_argument("corner and edge permutation parity differ");
    }
}

std::uint16_t twist_coord(const CubieCube &cube) noexcept {
    std::uint16_t coordinate = 0;
    for (int i = 0; i < 7; ++i)
        coordinate = static_cast<std::uint16_t>(coordinate * 3 + cube.co[i]);
    return coordinate;
}

std::uint16_t flip_coord(const CubieCube &cube) noexcept {
    std::uint16_t coordinate = 0;
    for (int i = 0; i < 11; ++i)
        coordinate = static_cast<std::uint16_t>(coordinate * 2 + cube.eo[i]);
    return coordinate;
}

std::uint16_t corner_perm_coord(const CubieCube &cube) noexcept {
    return static_cast<std::uint16_t>(rank_permutation(cube.cp));
}

std::uint16_t slice_comb_coord(const CubieCube &cube) noexcept {
    std::array<int, 4> positions{};
    int count = 0;
    for (int position = 0; position < 12; ++position) {
        if (cube.ep[position] >= 8)
            positions[count++] = position;
    }

    int rank = 0;
    int previous = -1;
    for (int index = 0; index < 4; ++index) {
        for (int candidate = previous + 1; candidate < positions[index]; ++candidate) {
            rank += binomial(12 - candidate - 1, 4 - index - 1);
        }
        previous = positions[index];
    }
    return static_cast<std::uint16_t>(rank);
}

std::uint32_t corner_pattern_coord(const CubieCube &cube) noexcept {
    return static_cast<std::uint32_t>(corner_perm_coord(cube)) * 2187U + twist_coord(cube);
}

std::uint32_t rank_permutation(std::span<const std::uint8_t> permutation) noexcept {
    std::uint32_t rank = 0;
    std::uint32_t available = permutation.size() >= 32 ? std::numeric_limits<std::uint32_t>::max()
                                                       : (1U << static_cast<unsigned>(permutation.size())) - 1U;
    for (std::size_t i = 0; i < permutation.size(); ++i) {
        const std::uint32_t value_bit = 1U << permutation[i];
        const std::uint32_t smaller = std::popcount(available & (value_bit - 1U));
        rank = rank * static_cast<std::uint32_t>(permutation.size() - i) + smaller;
        available &= ~value_bit;
    }
    return rank;
}

std::vector<std::uint8_t> unrank_permutation(std::uint32_t rank, int size) {
    std::vector<std::uint8_t> digits(size);
    for (int index = size - 1; index >= 0; --index) {
        const int base = size - index;
        digits[index] = static_cast<std::uint8_t>(rank % base);
        rank /= base;
    }
    std::vector<std::uint8_t> items(size);
    std::iota(items.begin(), items.end(), 0);
    std::vector<std::uint8_t> permutation;
    permutation.reserve(size);
    for (std::uint8_t digit : digits) {
        permutation.push_back(items[digit]);
        items.erase(items.begin() + digit);
    }
    return permutation;
}

CubieCube cube_from_twist(std::uint16_t coordinate) noexcept {
    CubieCube cube;
    int total = 0;
    for (int index = 6; index >= 0; --index) {
        cube.co[index] = coordinate % 3;
        total += cube.co[index];
        coordinate /= 3;
    }
    cube.co[7] = static_cast<std::uint8_t>((3 - total % 3) % 3);
    return cube;
}

CubieCube cube_from_flip(std::uint16_t coordinate) noexcept {
    CubieCube cube;
    int total = 0;
    for (int index = 10; index >= 0; --index) {
        cube.eo[index] = coordinate % 2;
        total += cube.eo[index];
        coordinate /= 2;
    }
    cube.eo[11] = static_cast<std::uint8_t>(total % 2);
    return cube;
}

CubieCube cube_from_corner_perm(std::uint16_t coordinate) {
    CubieCube cube;
    const auto permutation = unrank_permutation(coordinate, 8);
    std::copy(permutation.begin(), permutation.end(), cube.cp.begin());
    return cube;
}

CubieCube cube_from_slice_comb(std::uint16_t coordinate) {
    if (coordinate >= 495)
        throw std::invalid_argument("slice combination coordinate out of range");
    std::array<int, 4> selected{};
    int remaining_rank = coordinate;
    int previous = -1;
    for (int index = 0; index < 4; ++index) {
        for (int candidate = previous + 1; candidate < 12; ++candidate) {
            const int block = binomial(12 - candidate - 1, 4 - index - 1);
            if (remaining_rank < block) {
                selected[index] = candidate;
                previous = candidate;
                break;
            }
            remaining_rank -= block;
        }
    }

    CubieCube cube;
    int slice_edge = 8;
    int normal_edge = 0;
    for (int position = 0; position < 12; ++position) {
        if (std::find(selected.begin(), selected.end(), position) != selected.end()) {
            cube.ep[position] = static_cast<std::uint8_t>(slice_edge++);
        } else {
            cube.ep[position] = static_cast<std::uint8_t>(normal_edge++);
        }
    }
    return cube;
}

EdgePatternState edge_pattern_state(const CubieCube &cube, int first_edge) noexcept {
    std::array<std::uint8_t, 6> selected{};
    for (int index = 0; index < 6; ++index)
        selected[index] = static_cast<std::uint8_t>(first_edge + index);
    return edge_pattern_state(cube, selected);
}

const std::array<std::uint8_t, 6> &edge_pattern_group(int group) {
    static constexpr std::array<std::array<std::uint8_t, 6>, 8> groups{{
        {{0, 1, 2, 3, 4, 5}},
        {{6, 7, 8, 9, 10, 11}},
        {{0, 2, 4, 6, 8, 10}},
        {{1, 3, 5, 7, 9, 11}},
        {{0, 2, 4, 8, 9, 11}},
        {{1, 3, 5, 6, 7, 10}},
        {{0, 2, 6, 8, 9, 10}},
        {{1, 3, 4, 5, 7, 11}},
    }};
    if (group < 0 || group >= static_cast<int>(groups.size())) {
        throw std::invalid_argument("edge pattern group must be 0..7");
    }
    return groups[group];
}

EdgePatternState edge_pattern_state(const CubieCube &cube, std::span<const std::uint8_t, 6> selected_edges) noexcept {
    EdgePatternState state;
    for (int position = 0; position < 12; ++position) {
        const int edge = cube.ep[position];
        for (int local = 0; local < 6; ++local) {
            if (edge != selected_edges[local])
                continue;
            state.positions[local] = static_cast<std::uint8_t>(position);
            state.orientations |= static_cast<std::uint8_t>(cube.eo[position] << local);
            break;
        }
    }
    return state;
}

std::uint32_t edge_pattern_coord(const EdgePatternState &state) noexcept {
    std::uint32_t rank = 0;
    std::uint16_t available = 0x0FFF;
    for (int index = 0; index < 6; ++index) {
        const std::uint16_t below = static_cast<std::uint16_t>((1U << state.positions[index]) - 1U);
        const std::uint32_t digit = std::popcount(static_cast<unsigned>(available & below));
        rank = rank * static_cast<std::uint32_t>(12 - index) + digit;
        available &= static_cast<std::uint16_t>(~(1U << state.positions[index]));
    }
    return rank * 64U + state.orientations;
}

EdgePatternState edge_pattern_from_coord(std::uint32_t coordinate) {
    EdgePatternState state;
    state.orientations = static_cast<std::uint8_t>(coordinate & 63U);
    std::uint32_t rank = coordinate >> 6U;
    std::array<std::uint8_t, 6> digits{};
    for (int index = 5; index >= 0; --index) {
        const std::uint32_t base = static_cast<std::uint32_t>(12 - index);
        digits[index] = static_cast<std::uint8_t>(rank % base);
        rank /= base;
    }
    std::vector<std::uint8_t> available(12);
    std::iota(available.begin(), available.end(), 0);
    for (int index = 0; index < 6; ++index) {
        state.positions[index] = available[digits[index]];
        available.erase(available.begin() + digits[index]);
    }
    return state;
}

EdgePatternState move_edge_pattern(const EdgePatternState &state, int move) noexcept {
    EdgePatternState result;
    const CubieCube &move_cube = move_cubes()[move];
    std::array<std::uint8_t, 12> source_to_destination{};
    for (int destination = 0; destination < 12; ++destination) {
        source_to_destination[move_cube.ep[destination]] = static_cast<std::uint8_t>(destination);
    }
    for (int edge = 0; edge < 6; ++edge) {
        const int source = state.positions[edge];
        const int destination = source_to_destination[source];
        const int orientation = ((state.orientations >> edge) & 1U) ^ move_cube.eo[destination];
        result.positions[edge] = static_cast<std::uint8_t>(destination);
        result.orientations |= static_cast<std::uint8_t>(orientation << edge);
    }
    return result;
}

int permutation_parity(std::span<const std::uint8_t> permutation) noexcept {
    int parity = 0;
    for (std::size_t i = 0; i < permutation.size(); ++i) {
        for (std::size_t j = i + 1; j < permutation.size(); ++j)
            parity ^= permutation[i] > permutation[j];
    }
    return parity;
}

bool should_skip_face(int last_face, int face) noexcept {
    if (last_face < 0)
        return false;
    if (last_face == face)
        return true;
    constexpr std::array<int, 6> opposite{3, 4, 5, 0, 1, 2};
    return opposite[last_face] == face && last_face > face;
}

} // namespace cube
