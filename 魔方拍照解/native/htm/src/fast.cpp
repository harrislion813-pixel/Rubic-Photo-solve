#include "fast.hpp"
#include "solver.hpp"
#include "symmetry.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <memory>
#include <mutex>
#include <stdexcept>

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

namespace cube {
namespace {
// Ascending HTM action order matches the Python candidate's phase-2 traversal.
constexpr std::array<int, 10> kPhase2Moves{0, 1, 2, 4, 7, 9, 10, 11, 13, 16};
constexpr std::uint32_t kJointCount = 40320U * 24U;
constexpr std::size_t kCacheBytes = 40320U * 10U * 2U + 24U * 10U + 2U * kJointCount;
constexpr std::uint64_t kCacheVersion = 0x314D544832504843ULL;

std::uint64_t checksum(const std::vector<std::uint8_t> &data) {
    std::uint64_t value = 1469598103934665603ULL;
    for (auto byte : data)
        value = (value ^ byte) * 1099511628211ULL;
    return value;
}

struct Phase2Tables {
    std::vector<std::uint16_t> edge_move;
    std::array<std::uint8_t, 240> slice_move{};
    std::vector<std::uint8_t> corner_slice;
    std::vector<std::uint8_t> edge_slice;

    explicit Phase2Tables(const CoordinateTables &tables) {
        const auto *configured = _wgetenv(L"CUBE_HTM_PHASE2_CACHE");
        const auto *coordinates = _wgetenv(L"CUBE_NATIVE_COORDINATE_CACHE");
        const auto path = configured ? std::filesystem::path(configured)
                          : coordinates && *coordinates
                              ? std::filesystem::path(coordinates).parent_path() / L"phase2_htm_v1.bin"
                              : std::filesystem::path(L".cache/htm/phase2_htm_v1.bin");
        if (!path.empty() && load(path))
            return;
        edge_move.resize(40320U * 10U);
        for (std::uint32_t coordinate = 0; coordinate < 40320; ++coordinate) {
            const auto permutation = unrank_permutation(coordinate, 8);
            CubieCube state;
            std::copy(permutation.begin(), permutation.end(), state.ep.begin());
            for (std::size_t col = 0; col < 10; ++col) {
                const auto next = state.apply_move(kPhase2Moves[col]);
                edge_move[coordinate * 10U + col] =
                    static_cast<std::uint16_t>(rank_permutation(std::span<const std::uint8_t>(next.ep.data(), 8)));
            }
        }
        for (std::uint32_t coordinate = 0; coordinate < 24; ++coordinate) {
            const auto permutation = unrank_permutation(coordinate, 4);
            CubieCube state;
            for (int pos = 0; pos < 4; ++pos)
                state.ep[8 + pos] = static_cast<std::uint8_t>(8 + permutation[pos]);
            for (std::size_t col = 0; col < 10; ++col) {
                const auto next = state.apply_move(kPhase2Moves[col]);
                std::array<std::uint8_t, 4> slice{};
                for (int pos = 0; pos < 4; ++pos)
                    slice[pos] = static_cast<std::uint8_t>(next.ep[8 + pos] - 8);
                slice_move[coordinate * 10U + col] = static_cast<std::uint8_t>(rank_permutation(slice));
            }
        }
        auto build = [&](bool corners) {
            std::vector<std::uint8_t> distances(kJointCount, 255);
            std::vector<std::uint32_t> queue;
            queue.reserve(kJointCount);
            queue.push_back(0);
            distances[0] = 0;
            for (std::size_t cursor = 0; cursor < queue.size(); ++cursor) {
                const auto index = queue[cursor];
                for (std::size_t col = 0; col < 10; ++col) {
                    const auto permutation =
                        corners ? tables.corner_move(static_cast<std::uint16_t>(index / 24U), kPhase2Moves[col])
                                : edge_move[(index / 24U) * 10U + col];
                    const auto next = permutation * 24U + slice_move[(index % 24U) * 10U + col];
                    if (distances[next] != 255)
                        continue;
                    // Every HTM move, including a half turn, costs exactly one.
                    distances[next] = static_cast<std::uint8_t>(distances[index] + 1);
                    queue.push_back(next);
                }
            }
            if (queue.size() != kJointCount)
                throw std::runtime_error("HTM phase-2 distance table is incomplete");
            return distances;
        };
        corner_slice = build(true);
        edge_slice = build(false);
        if (!path.empty())
            save(path);
    }

    bool load(const std::filesystem::path &path) {
        std::ifstream input(path, std::ios::binary | std::ios::ate);
        std::array<std::uint64_t, 7> header{};
        if (!input || input.tellg() != static_cast<std::streamoff>(sizeof(header) + kCacheBytes))
            return false;
        input.seekg(0);
        std::vector<std::uint8_t> data(kCacheBytes);
        input.read(reinterpret_cast<char *>(header.data()), sizeof(header));
        input.read(reinterpret_cast<char *>(data.data()), data.size());
        const std::array<std::uint64_t, 7> expected{kCacheVersion, 0x0102030405060708ULL, 1, 40320, 24, 10,
                                                    checksum(data)};
        if (!input || header != expected)
            return false;
        edge_move.resize(40320U * 10U);
        corner_slice.resize(kJointCount);
        edge_slice.resize(kJointCount);
        std::size_t offset = 0;
        auto read = [&](auto &values) {
            const auto bytes = values.size() * sizeof(values[0]);
            std::memcpy(values.data(), data.data() + offset, bytes);
            offset += bytes;
        };
        read(edge_move);
        read(slice_move);
        read(corner_slice);
        read(edge_slice);
        return corner_slice[0] == 0 && edge_slice[0] == 0 &&
               std::all_of(edge_move.begin(), edge_move.end(), [](auto v) { return v < 40320; }) &&
               std::all_of(slice_move.begin(), slice_move.end(), [](auto v) { return v < 24; }) &&
               std::all_of(corner_slice.begin(), corner_slice.end(), [](auto v) { return v <= 14; }) &&
               std::all_of(edge_slice.begin(), edge_slice.end(), [](auto v) { return v <= 14; });
    }

    void save(const std::filesystem::path &path) const {
        auto temporary = path;
        temporary += L"." + std::to_wstring(GetCurrentProcessId()) + L".tmp";
        try {
            if (!path.parent_path().empty())
                std::filesystem::create_directories(path.parent_path());
            std::vector<std::uint8_t> data;
            data.reserve(kCacheBytes);
            auto append = [&](const auto &values) {
                const auto *bytes = reinterpret_cast<const std::uint8_t *>(values.data());
                data.insert(data.end(), bytes, bytes + values.size() * sizeof(values[0]));
            };
            append(edge_move);
            append(slice_move);
            append(corner_slice);
            append(edge_slice);
            const std::array<std::uint64_t, 7> header{kCacheVersion, 0x0102030405060708ULL, 1, 40320, 24, 10,
                                                      checksum(data)};
            std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
            output.write(reinterpret_cast<const char *>(header.data()), sizeof(header));
            output.write(reinterpret_cast<const char *>(data.data()), data.size());
            output.close();
            if (!output ||
                !MoveFileExW(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
                throw std::runtime_error("HTM candidate cache publish failed");
        } catch (...) {
            std::error_code ignored;
            std::filesystem::remove(temporary, ignored);
        }
    }

    int lower(std::uint16_t corner, std::uint16_t edge, std::uint8_t slice) const {
        return std::max(corner_slice[corner * 24U + slice], edge_slice[edge * 24U + slice]);
    }
};

const Phase2Tables &phase2_tables(const CoordinateTables &tables) {
    static std::once_flag once;
    static std::unique_ptr<Phase2Tables> value;
    std::call_once(once, [&] { value = std::make_unique<Phase2Tables>(tables); });
    return *value;
}

class CandidateSearch {
  public:
    CandidateSearch(const CoordinateTables &tables, const Phase2Tables &phase2, const HtmCandidateOptions &options,
                    std::chrono::steady_clock::time_point deadline, int best,
                    std::function<void(const std::vector<int> &)> accept)
        : tables_(tables), phase2_(phase2), options_(options), deadline_(deadline), best_(best),
          accept_(std::move(accept)) {}

    void run(const CubieCube &state) {
        CoordinateFeatures features;
        features.axis_coordinates = features.edge_pattern_a = features.edge_pattern_b = false;
        const auto initial = tables_.from_cube(state, features);
        const auto lower = tables_.phase1_lower(initial.twist, initial.flip, initial.slice);
        int first_depth = -1;
        for (int depth = lower; depth <= options_.max_phase1_depth && !stopped(); ++depth) {
            if (phase1(initial, depth, -1, false)) {
                first_depth = depth;
                break;
            }
        }
        if (first_depth < 0)
            return;
        for (int depth = first_depth; depth <= options_.max_phase1_depth && !stopped(); ++depth)
            phase1(initial, depth, -1, true);
    }

    std::uint64_t phase1_nodes{};
    std::uint64_t phase2_nodes{};

  private:
    bool stopped() {
        if (stopped_)
            return true;
        if (((phase1_nodes + phase2_nodes) & 255U) == 0)
            stopped_ = (options_.cancel_requested && options_.cancel_requested->load(std::memory_order_relaxed)) ||
                       std::chrono::steady_clock::now() >= deadline_;
        return stopped_;
    }

    bool phase2(std::uint16_t cp, std::uint16_t ep, std::uint8_t slice, int remaining, int last_face) {
        ++phase2_nodes;
        if (stopped() || phase2_.lower(cp, ep, slice) > remaining)
            return false;
        if (cp == 0 && ep == 0 && slice == 0)
            return true;
        if (remaining == 0)
            return false;
        for (std::size_t col = 0; col < 10; ++col) {
            const int move = kPhase2Moves[col];
            if (should_skip_face(last_face, move / 3))
                continue;
            const auto next_cp = tables_.corner_move(cp, move);
            const auto next_ep = phase2_.edge_move[ep * 10U + col];
            const auto next_slice = phase2_.slice_move[slice * 10U + col];
            if (phase2_.lower(next_cp, next_ep, next_slice) >= remaining)
                continue;
            path_.push_back(move);
            if (phase2(next_cp, next_ep, next_slice, remaining - 1, move / 3))
                return true;
            path_.pop_back();
            if (stopped_)
                return false;
        }
        return false;
    }

    bool try_phase2(const CoordinateState &state, int last_face) {
        std::array<std::uint8_t, 8> edges{};
        std::array<std::uint8_t, 4> slice{};
        for (int i = 0; i < 8; ++i)
            edges[i] = static_cast<std::uint8_t>((state.edges >> (4 * i)) & 15U);
        for (int i = 0; i < 4; ++i)
            slice[i] = static_cast<std::uint8_t>(((state.edges >> (4 * (i + 8))) & 15U) - 8U);
        const auto ep = static_cast<std::uint16_t>(rank_permutation(edges));
        const auto sp = static_cast<std::uint8_t>(rank_permutation(slice));
        const auto prefix = path_.size();
        const int limit = std::min(options_.max_phase2_depth, best_ - static_cast<int>(prefix) - 1);
        for (int depth = phase2_.lower(state.corner_perm, ep, sp); depth <= limit && !stopped(); ++depth) {
            if (phase2(state.corner_perm, ep, sp, depth, last_face)) {
                best_ = static_cast<int>(path_.size());
                accept_(path_);
                path_.resize(prefix);
                return true;
            }
        }
        return false;
    }

    bool phase1(const CoordinateState &state, int remaining, int last_face, bool improve) {
        ++phase1_nodes;
        if (stopped())
            return false;
        if (remaining == 0)
            return state.twist == 0 && state.flip == 0 && state.slice == slice_comb_coord(CubieCube{}) &&
                   try_phase2(state, last_face);
        struct Child {
            int move;
            int lower;
        };
        std::vector<Child> children;
        children.reserve(15);
        for (int move = 0; move < 18; ++move) {
            if (should_skip_face(last_face, move / 3))
                continue;
            const auto twist = tables_.twist_move(state.twist, move);
            const auto flip = tables_.flip_move(state.flip, move);
            const auto slice = tables_.slice_move(state.slice, move);
            const auto lower = tables_.phase1_lower(twist, flip, slice);
            if (lower < remaining)
                children.push_back({move, lower});
        }
        if (improve)
            std::stable_sort(children.begin(), children.end(),
                             [](const auto &a, const auto &b) { return a.lower < b.lower; });
        CoordinateFeatures features;
        features.axis_coordinates = features.edge_pattern_a = features.edge_pattern_b = false;
        for (const auto &next : children) {
            const auto child = tables_.moved(state, next.move, features);
            path_.push_back(next.move);
            const auto found = phase1(child, remaining - 1, next.move / 3, improve);
            path_.pop_back();
            if (found && !improve)
                return true;
            if (stopped_)
                return false;
        }
        return false;
    }

    const CoordinateTables &tables_;
    const Phase2Tables &phase2_;
    const HtmCandidateOptions &options_;
    std::chrono::steady_clock::time_point deadline_;
    int best_;
    bool stopped_{};
    std::vector<int> path_;
    std::function<void(const std::vector<int> &)> accept_;
};
} // namespace

void prepare_htm_candidate_tables(const CoordinateTables &tables) { (void)phase2_tables(tables); }

HtmCandidateResult find_htm_candidate(const CubieCube &cube, const CoordinateTables &tables,
                                      const HtmCandidateOptions &options) {
    if (!std::isfinite(options.timeout_seconds) || options.timeout_seconds <= 0 ||
        (options.directions != 1 && options.directions != 6) || options.max_phase1_depth < 0 ||
        options.max_phase1_depth > 12 || options.max_phase2_depth < 0 || options.max_phase2_depth > 18)
        throw std::invalid_argument("invalid native HTM candidate budget or directions");
    const auto started = std::chrono::steady_clock::now();
    const auto deadline = started + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                                        std::chrono::duration<double>(options.timeout_seconds));
    HtmCandidateResult result;
    if (cube.solved()) {
        result.solution_found = true;
        return result;
    }
    const auto &phase2 = phase2_tables(tables);
    for (int direction = 0; direction < options.directions; ++direction) {
        const auto now = std::chrono::steady_clock::now();
        if (now >= deadline || (options.cancel_requested && options.cancel_requested->load(std::memory_order_relaxed)))
            break;
        const bool inverse = direction >= 3;
        const int axis = direction % 3 - 1;
        const auto original = inverse ? cube.inverse() : cube;
        const auto oriented = axis < 0 ? original : conjugate_axis(original, axis);
        const auto local_deadline = now + (deadline - now) / (options.directions - direction);
        CandidateSearch search(
            tables, phase2, options, local_deadline, result.moves.empty() ? 100 : static_cast<int>(result.moves.size()),
            [&](const auto &path) {
                std::vector<int> mapped = path;
                if (axis >= 0) {
                    const auto &mapping = axis_rotation_move_maps()[axis];
                    for (auto &move : mapped)
                        move = static_cast<int>(std::find(mapping.begin(), mapping.end(), move) - mapping.begin());
                }
                if (inverse)
                    mapped = invert_moves(mapped);
                auto verified = cube;
                for (int move : mapped)
                    verified = verified.apply_move(move);
                if (!verified.solved())
                    throw std::runtime_error("native HTM candidate failed independent direction replay");
                if (std::chrono::steady_clock::now() >= deadline ||
                    (options.cancel_requested && options.cancel_requested->load(std::memory_order_relaxed)))
                    return;
                if (!result.moves.empty() && mapped.size() >= result.moves.size())
                    return;
                result.moves = std::move(mapped);
                result.solution_found = true;
                ++result.improvements;
                if (options.on_improved)
                    options.on_improved(
                        result.moves, std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count(),
                        direction);
            });
        search.run(oriented);
        result.phase1_nodes += search.phase1_nodes;
        result.phase2_nodes += search.phase2_nodes;
    }
    result.cancelled = options.cancel_requested && options.cancel_requested->load(std::memory_order_relaxed);
    result.elapsed_seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    return result;
}
} // namespace cube
