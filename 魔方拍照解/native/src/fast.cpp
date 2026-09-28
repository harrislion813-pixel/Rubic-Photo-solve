#include "fast.hpp"

#include "pdb.hpp"
#include "solver.hpp"
#include "symmetry.hpp"
#include "tail.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <utility>
#include <vector>

namespace cube {
namespace {

constexpr std::array<int, 10> kPhase2Moves{0, 1, 2, 9, 10, 11, 4, 13, 7, 16};
constexpr std::uint32_t kPhase2JointEntries = 40320U * 24U;

struct Phase2Tables {
    explicit Phase2Tables(const CoordinateTables &tables) {
        corner_move.resize(40320U * kPhase2Moves.size());
        edge_move.resize(40320U * kPhase2Moves.size());
        for (std::uint32_t coordinate = 0; coordinate < 40320; ++coordinate) {
            const auto permutation = unrank_permutation(coordinate, 8);
            CubieCube edge_cube;
            std::copy(permutation.begin(), permutation.end(), edge_cube.ep.begin());
            for (std::size_t column = 0; column < kPhase2Moves.size(); ++column) {
                const int move = kPhase2Moves[column];
                corner_move[coordinate * kPhase2Moves.size() + column] =
                    tables.corner_move(static_cast<std::uint16_t>(coordinate), move);
                const auto next = edge_cube.apply_move(move);
                edge_move[coordinate * kPhase2Moves.size() + column] =
                    static_cast<std::uint16_t>(rank_permutation(std::span<const std::uint8_t>(next.ep.data(), 8)));
            }
        }
        for (std::uint32_t coordinate = 0; coordinate < 24; ++coordinate) {
            const auto permutation = unrank_permutation(coordinate, 4);
            CubieCube slice_cube;
            for (int position = 0; position < 4; ++position)
                slice_cube.ep[8 + position] = static_cast<std::uint8_t>(8 + permutation[position]);
            for (std::size_t column = 0; column < kPhase2Moves.size(); ++column) {
                const auto next = slice_cube.apply_move(kPhase2Moves[column]);
                std::array<std::uint8_t, 4> four{};
                for (int position = 0; position < 4; ++position)
                    four[position] = static_cast<std::uint8_t>(next.ep[8 + position] - 8);
                slice_move[coordinate * kPhase2Moves.size() + column] =
                    static_cast<std::uint8_t>(rank_permutation(four));
            }
        }
        corner_slice = build_joint_distances(corner_move);
        edge_slice = build_joint_distances(edge_move);
        for (auto value : corner_slice)
            corner_max = std::max(corner_max, static_cast<int>(value));
        for (auto value : edge_slice)
            edge_max = std::max(edge_max, static_cast<int>(value));
    }

    std::vector<std::uint8_t> build_joint_distances(const std::vector<std::uint16_t> &permutation_moves) const {
        std::vector<std::uint8_t> distances(kPhase2JointEntries, 255);
        std::vector<std::vector<std::uint32_t>> buckets(32);
        distances[0] = 0;
        buckets[0].push_back(0);
        std::uint32_t reached = 1;
        for (std::size_t depth = 0; depth < buckets.size(); ++depth) {
            for (std::size_t cursor = 0; cursor < buckets[depth].size(); ++cursor) {
                const auto coordinate = buckets[depth][cursor];
                if (distances[coordinate] != depth)
                    continue;
                const auto permutation = coordinate / 24U;
                const auto slice = coordinate % 24U;
                for (std::size_t column = 0; column < kPhase2Moves.size(); ++column) {
                    const auto next_permutation = permutation_moves[permutation * kPhase2Moves.size() + column];
                    const auto next_slice = slice_move[slice * kPhase2Moves.size() + column];
                    const auto next = static_cast<std::uint32_t>(next_permutation) * 24U + next_slice;
                    const auto next_depth =
                        depth + static_cast<std::size_t>(move_cost(kPhase2Moves[column], MoveMetric::QTM));
                    if (next_depth >= distances[next])
                        continue;
                    if (distances[next] == 255)
                        ++reached;
                    distances[next] = static_cast<std::uint8_t>(next_depth);
                    if (next_depth >= buckets.size())
                        buckets.resize(next_depth + 1);
                    buckets[next_depth].push_back(next);
                }
            }
        }
        if (reached != kPhase2JointEntries)
            throw std::runtime_error("QTM phase-2 weighted distance table is incomplete");
        return distances;
    }

    [[nodiscard]] int lower(std::uint16_t corner, std::uint16_t edge, std::uint8_t slice) const noexcept {
        return std::max(corner_slice[static_cast<std::uint32_t>(corner) * 24U + slice],
                        edge_slice[static_cast<std::uint32_t>(edge) * 24U + slice]);
    }

    std::vector<std::uint16_t> corner_move;
    std::vector<std::uint16_t> edge_move;
    std::array<std::uint8_t, 24U * kPhase2Moves.size()> slice_move{};
    std::vector<std::uint8_t> corner_slice;
    std::vector<std::uint8_t> edge_slice;
    int corner_max{};
    int edge_max{};
};

const Phase2Tables &phase2_tables(const CoordinateTables &tables) {
    static std::once_flag once;
    static std::unique_ptr<Phase2Tables> value;
    std::call_once(once, [&] { value = std::make_unique<Phase2Tables>(tables); });
    return *value;
}

std::vector<int> normalize_moves(const std::vector<int> &moves) {
    std::vector<int> result;
    result.reserve(moves.size());
    for (int move : moves) {
        if (result.empty() || result.back() / 3 != move / 3) {
            result.push_back(move);
            continue;
        }
        const int previous_power = result.back() % 3 + 1;
        const int power = move % 3 + 1;
        const int combined = (previous_power + power) % 4;
        result.pop_back();
        if (combined != 0)
            result.push_back((move / 3) * 3 + combined - 1);
    }
    return result;
}

class Search {
  public:
    Search(const CubieCube &cube, const CoordinateTables &tables, const Phase1PatternDatabase &phase1,
           const Phase2Tables &phase2, const FastCandidateOptions &options)
        : cube_(cube), tables_(tables), phase1_(phase1), phase2_(phase2), options_(options),
          deadline_(std::chrono::steady_clock::now() + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                                                           std::chrono::duration<double>(options.timeout_seconds))),
          best_cost_(options.incumbent_cost) {
        result_.phase1_max_distance = phase1.max_value();
        result_.phase2_max_distance = std::max(phase2.corner_max, phase2.edge_max);
    }

    FastCandidateResult run() {
        const int lower = phase1_.distance(twist_coord(cube_), flip_coord(cube_), slice_comb_coord(cube_));
        for (int cost = lower; cost <= options_.max_phase1_cost && !expired(); ++cost) {
            phase1_dfs(cube_, twist_coord(cube_), flip_coord(cube_), slice_comb_coord(cube_), cost, 6);
        }
        return result_;
    }

  private:
    bool expired() {
        if (expired_)
            return true;
        if (((result_.phase1_nodes + result_.phase2_nodes) & 1023U) != 0)
            return false;
        expired_ = (options_.cancel_requested && options_.cancel_requested->load(std::memory_order_relaxed)) ||
                   std::chrono::steady_clock::now() >= deadline_;
        result_.timed_out = expired_;
        return expired_;
    }

    void accept_candidate() {
        const auto normalized = improve_windows(normalize_moves(path_));
        const int cost = solution_cost(normalized, MoveMetric::QTM);
        if (cost >= best_cost_)
            return;
        auto verified = cube_;
        for (int move : normalized)
            verified = verified.apply_move(move);
        if (!verified.solved())
            throw std::runtime_error("native QTM candidate did not solve the original cube");
        best_cost_ = cost;
        result_.moves = normalized;
        result_.cost = cost;
        ++result_.improvements;
        if (options_.on_improved)
            options_.on_improved(result_.moves);
    }

    std::vector<int> improve_windows(std::vector<int> current) {
        const auto *tail = options_.local_tail;
        if (tail == nullptr || tail->metric() != MoveMetric::QTM)
            return current;
        int probes = 0;
        for (int pass = 0; pass < 8 && probes < 128; ++pass) {
            bool changed = false;
            for (std::size_t first = 0; first < current.size() && !changed && probes < 128; ++first) {
                CubieCube segment;
                int segment_cost = 0;
                for (std::size_t last = first; last < current.size() && probes < 128; ++last) {
                    segment_cost += move_cost(current[last], MoveMetric::QTM);
                    if (segment_cost > tail->depth())
                        break;
                    segment = segment.apply_move(current[last]);
                    if (segment_cost < 3)
                        continue;
                    ++probes;
                    const auto hit = tail->lookup(segment);
                    if (!hit.has_value() || hit->distance >= segment_cost)
                        continue;
                    const auto replacement = invert_moves(tail->solution_suffix(segment));
                    std::vector<int> candidate;
                    candidate.reserve(current.size() - (last - first + 1) + replacement.size());
                    candidate.insert(candidate.end(), current.begin(), current.begin() + first);
                    candidate.insert(candidate.end(), replacement.begin(), replacement.end());
                    candidate.insert(candidate.end(), current.begin() + last + 1, current.end());
                    candidate = normalize_moves(candidate);
                    if (solution_cost(candidate, MoveMetric::QTM) >= solution_cost(current, MoveMetric::QTM))
                        continue;
                    current = std::move(candidate);
                    ++result_.window_replacements;
                    changed = true;
                    break;
                }
            }
            if (!changed)
                break;
        }
        return current;
    }

    bool phase2_dfs(std::uint16_t corner, std::uint16_t edge, std::uint8_t slice, int remaining, int last_face) {
        ++result_.phase2_nodes;
        if (expired() || phase2_.lower(corner, edge, slice) > remaining)
            return false;
        if (corner == 0 && edge == 0 && slice == 0)
            return true;
        for (std::size_t column = 0; column < kPhase2Moves.size(); ++column) {
            const int move = kPhase2Moves[column];
            const int face = move / 3;
            if (should_skip_face(last_face, face))
                continue;
            const int next_remaining = remaining - move_cost(move, MoveMetric::QTM);
            if (next_remaining < 0)
                continue;
            const auto next_corner =
                phase2_.corner_move[static_cast<std::size_t>(corner) * kPhase2Moves.size() + column];
            const auto next_edge = phase2_.edge_move[static_cast<std::size_t>(edge) * kPhase2Moves.size() + column];
            const auto next_slice = phase2_.slice_move[static_cast<std::size_t>(slice) * kPhase2Moves.size() + column];
            if (phase2_.lower(next_corner, next_edge, next_slice) > next_remaining)
                continue;
            path_.push_back(move);
            if (phase2_dfs(next_corner, next_edge, next_slice, next_remaining, face))
                return true;
            path_.pop_back();
            if (expired_)
                return false;
        }
        return false;
    }

    void try_phase2(const CubieCube &cube) {
        const auto corner = corner_perm_coord(cube);
        const auto edge =
            static_cast<std::uint16_t>(rank_permutation(std::span<const std::uint8_t>(cube.ep.data(), 8)));
        std::array<std::uint8_t, 4> last{};
        for (int position = 0; position < 4; ++position)
            last[position] = static_cast<std::uint8_t>(cube.ep[8 + position] - 8);
        const auto slice = static_cast<std::uint8_t>(rank_permutation(last));
        const int lower = phase2_.lower(corner, edge, slice);
        const auto prefix_size = path_.size();
        const int prefix_cost = solution_cost(path_, MoveMetric::QTM);
        const int limit = std::min(options_.max_phase2_cost, best_cost_ - prefix_cost - 1);
        for (int cost = lower; cost <= limit && !expired_; ++cost) {
            if (phase2_dfs(corner, edge, slice, cost, 6)) {
                accept_candidate();
                path_.resize(prefix_size);
                break;
            }
        }
    }

    void phase1_dfs(const CubieCube &cube, std::uint16_t twist, std::uint16_t flip, std::uint16_t slice, int remaining,
                    int last_face) {
        ++result_.phase1_nodes;
        if (expired() || phase1_.distance(twist, flip, slice) > remaining)
            return;
        if (remaining == 0) {
            if (twist == 0 && flip == 0 && slice == slice_comb_coord(CubieCube{}))
                try_phase2(cube);
            return;
        }
        for (int move = 0; move < 18; ++move) {
            const int face = move / 3;
            if (should_skip_face(last_face, face))
                continue;
            const int next_remaining = remaining - move_cost(move, MoveMetric::QTM);
            if (next_remaining < 0)
                continue;
            const auto next_twist = tables_.twist_move(twist, move);
            const auto next_flip = tables_.flip_move(flip, move);
            const auto next_slice = tables_.slice_move(slice, move);
            if (phase1_.distance(next_twist, next_flip, next_slice) > next_remaining)
                continue;
            path_.push_back(move);
            phase1_dfs(cube.apply_move(move), next_twist, next_flip, next_slice, next_remaining, face);
            path_.pop_back();
            if (expired_)
                return;
        }
    }

    const CubieCube &cube_;
    const CoordinateTables &tables_;
    const Phase1PatternDatabase &phase1_;
    const Phase2Tables &phase2_;
    const FastCandidateOptions &options_;
    std::chrono::steady_clock::time_point deadline_;
    int best_cost_;
    bool expired_{false};
    std::vector<int> path_;
    FastCandidateResult result_;
};

} // namespace

FastCandidateResult find_fast_qtm_candidate(const CubieCube &cube, const CoordinateTables &tables,
                                            const Phase1PatternDatabase &phase1_pdb,
                                            const FastCandidateOptions &options) {
    if (options.metric != MoveMetric::QTM || phase1_pdb.metric() != MoveMetric::QTM || !phase1_pdb.complete())
        throw std::invalid_argument("native QTM candidate requires a complete QTM phase-1 PDB");
    if (options.timeout_seconds <= 0 || options.max_phase1_cost < 0 || options.max_phase2_cost < 0 ||
        options.incumbent_cost <= 0)
        throw std::invalid_argument("native QTM candidate options are invalid");
    const auto started = std::chrono::steady_clock::now();
    const auto deadline = started + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                                        std::chrono::duration<double>(options.timeout_seconds));
    const auto &phase2 = phase2_tables(tables);
    FastCandidateResult result;
    result.phase1_max_distance = phase1_pdb.max_value();
    result.phase2_max_distance = std::max(phase2.corner_max, phase2.edge_max);
    int best_cost = options.incumbent_cost;
    constexpr std::array<std::pair<int, bool>, 6> variants{
        {{-1, false}, {0, false}, {1, false}, {-1, true}, {0, true}, {1, true}}};
    for (std::size_t index = 0; index < variants.size(); ++index) {
        const auto now = std::chrono::steady_clock::now();
        if (now >= deadline ||
            (options.cancel_requested && options.cancel_requested->load(std::memory_order_relaxed))) {
            result.timed_out = true;
            break;
        }
        const auto [axis, inverse] = variants[index];
        CubieCube transformed = inverse ? cube.inverse() : cube;
        if (axis >= 0)
            transformed = conjugate_axis(transformed, axis);
        FastCandidateOptions variant = options;
        variant.incumbent_cost = best_cost;
        const double remaining = std::chrono::duration<double>(deadline - now).count();
        variant.timeout_seconds = index == 0 ? remaining * 0.4 : remaining / (variants.size() - index);
        variant.on_improved = [&](const std::vector<int> &path) {
            std::vector<int> mapped = path;
            if (axis >= 0) {
                std::array<int, 18> inverse_map{};
                for (int move = 0; move < 18; ++move)
                    inverse_map[axis_rotation_move_maps()[axis][move]] = move;
                for (int &move : mapped)
                    move = inverse_map[move];
            }
            if (inverse)
                mapped = invert_moves(mapped);
            mapped = normalize_moves(mapped);
            const int cost = solution_cost(mapped, MoveMetric::QTM);
            if (cost >= best_cost)
                return;
            CubieCube verified = cube;
            for (int move : mapped)
                verified = verified.apply_move(move);
            if (!verified.solved())
                throw std::runtime_error("transformed QTM candidate did not solve the original cube");
            best_cost = cost;
            result.moves = mapped;
            result.cost = cost;
            ++result.improvements;
            if (options.on_improved)
                options.on_improved(result.moves);
        };
        const auto part = Search(transformed, tables, phase1_pdb, phase2, variant).run();
        result.phase1_nodes += part.phase1_nodes;
        result.phase2_nodes += part.phase2_nodes;
        result.window_replacements += part.window_replacements;
    }
    result.timed_out |= std::chrono::steady_clock::now() >= deadline;
    return result;
}

} // namespace cube
