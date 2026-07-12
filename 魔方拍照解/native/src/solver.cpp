#include "solver.hpp"

#include "pdb.hpp"
#include "symmetry.hpp"
#include "tail.hpp"

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <bit>
#include <iostream>
#include <limits>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <thread>
#include <utility>

namespace cube {
namespace {

constexpr int kMoveCount = 18;
constexpr int kTwistCount = 2187;
constexpr int kFlipCount = 2048;
constexpr int kSliceCount = 495;
constexpr int kCornerPermCount = 40320;
constexpr int kMoveOrderingMinRemaining = 12;
constexpr std::uint8_t kUnknown = 255;

template <typename Setter, typename Getter>
std::vector<std::uint16_t> build_move_table(int size, Setter setter, Getter getter) {
    std::vector<std::uint16_t> table(static_cast<std::size_t>(size) * kMoveCount);
    for (int coordinate = 0; coordinate < size; ++coordinate) {
        const CubieCube cube = setter(static_cast<std::uint16_t>(coordinate));
        for (int move = 0; move < kMoveCount; ++move) {
            table[static_cast<std::size_t>(coordinate) * kMoveCount + move] = getter(cube.apply_move(move));
        }
    }
    return table;
}

std::vector<std::uint8_t> build_pair_prune(
    int size_a,
    int size_b,
    int solved_a,
    int solved_b,
    const std::vector<std::uint16_t>& move_a,
    const std::vector<std::uint16_t>& move_b) {
    std::vector<std::uint8_t> table(static_cast<std::size_t>(size_a) * size_b, kUnknown);
    const auto start = static_cast<std::uint32_t>(solved_a * size_b + solved_b);
    table[start] = 0;
    std::deque<std::uint32_t> queue{start};
    while (!queue.empty()) {
        const std::uint32_t index = queue.front();
        queue.pop_front();
        const int a = index / size_b;
        const int b = index % size_b;
        const std::uint8_t next_depth = static_cast<std::uint8_t>(table[index] + 1);
        for (int move = 0; move < kMoveCount; ++move) {
            const int next_a = move_a[static_cast<std::size_t>(a) * kMoveCount + move];
            const int next_b = move_b[static_cast<std::size_t>(b) * kMoveCount + move];
            const auto next_index = static_cast<std::uint32_t>(next_a * size_b + next_b);
            if (table[next_index] == kUnknown) {
                table[next_index] = next_depth;
                queue.push_back(next_index);
            }
        }
    }
    return table;
}

std::vector<std::uint8_t> build_single_prune(
    int size,
    int solved,
    const std::vector<std::uint16_t>& moves) {
    std::vector<std::uint8_t> table(size, kUnknown);
    table[solved] = 0;
    std::deque<std::uint32_t> queue{static_cast<std::uint32_t>(solved)};
    while (!queue.empty()) {
        const std::uint32_t coordinate = queue.front();
        queue.pop_front();
        const std::uint8_t next_depth = static_cast<std::uint8_t>(table[coordinate] + 1);
        for (int move = 0; move < kMoveCount; ++move) {
            const auto next = moves[static_cast<std::size_t>(coordinate) * kMoveCount + move];
            if (table[next] == kUnknown) {
                table[next] = next_depth;
                queue.push_back(next);
            }
        }
    }
    return table;
}

struct StateKey {
    std::uint64_t low{};
    std::uint64_t high{};
    bool operator==(const StateKey&) const = default;
};

StateKey state_key(const CubieCube& cube, int last_face) noexcept {
    StateKey key;
    for (int index = 0; index < 12; ++index) {
        key.low |= static_cast<std::uint64_t>(cube.ep[index]) << (index * 4);
    }
    for (int index = 0; index < 11; ++index) {
        key.low |= static_cast<std::uint64_t>(cube.eo[index]) << (48 + index);
    }
    for (int index = 0; index < 8; ++index) {
        key.high |= static_cast<std::uint64_t>(cube.cp[index]) << (index * 3);
        key.high |= static_cast<std::uint64_t>(cube.co[index]) << (24 + index * 2);
    }
    key.high |= static_cast<std::uint64_t>(last_face + 1) << 40U;
    return key;
}

std::uint64_t mix_hash(std::uint64_t value) noexcept {
    value ^= value >> 30U;
    value *= 0xBF58476D1CE4E5B9ULL;
    value ^= value >> 27U;
    value *= 0x94D049BB133111EBULL;
    return value ^ (value >> 31U);
}

class TranspositionTable {
public:
    explicit TranspositionTable(std::size_t requested_entries) {
        const std::size_t target = std::max<std::size_t>(1024, requested_entries * 2);
        const std::size_t capacity = std::bit_ceil(target);
        entries_.resize(capacity);
        mask_ = capacity - 1;
    }

    [[nodiscard]] bool contains_at_least(const StateKey& key, std::uint8_t depth) const noexcept {
        std::size_t slot = static_cast<std::size_t>(mix_hash(key.low ^ std::rotl(key.high, 23))) & mask_;
        for (int probe = 0; probe < kProbeLimit; ++probe) {
            const Entry& entry = entries_[slot];
            const std::uint8_t stored_depth = static_cast<std::uint8_t>(entry.high_depth >> 56U);
            if (stored_depth == 0) return false;
            if (entry.low == key.low && (entry.high_depth & kHighMask) == key.high) {
                return stored_depth >= depth;
            }
            slot = (slot + 1) & mask_;
        }
        return false;
    }

    void store(const StateKey& key, std::uint8_t depth) noexcept {
        std::size_t slot = static_cast<std::size_t>(mix_hash(key.low ^ std::rotl(key.high, 23))) & mask_;
        std::size_t replacement = slot;
        std::uint8_t shallowest = 255;
        for (int probe = 0; probe < kProbeLimit; ++probe) {
            Entry& entry = entries_[slot];
            const std::uint8_t stored_depth = static_cast<std::uint8_t>(entry.high_depth >> 56U);
            if (stored_depth == 0 || (entry.low == key.low && (entry.high_depth & kHighMask) == key.high)) {
                if (stored_depth <= depth) entry = Entry{key.low, key.high | (static_cast<std::uint64_t>(depth) << 56U)};
                return;
            }
            if (stored_depth < shallowest) {
                shallowest = stored_depth;
                replacement = slot;
            }
            slot = (slot + 1) & mask_;
        }
        if (depth >= shallowest) {
            entries_[replacement] = Entry{key.low, key.high | (static_cast<std::uint64_t>(depth) << 56U)};
        }
    }

private:
    struct Entry {
        std::uint64_t low{};
        std::uint64_t high_depth{};
    };
    static constexpr int kProbeLimit = 12;
    static constexpr std::uint64_t kHighMask = (1ULL << 56U) - 1U;
    std::vector<Entry> entries_;
    std::size_t mask_{};
};

struct SearchTask {
    CoordinateState state;
    int depth_left{};
    int last_face{-1};
    std::vector<int> path;
};

struct SearchControl {
    std::atomic<bool> stop{false};
    std::atomic<bool> timed_out{false};
    std::atomic<std::uint64_t> nodes{0};
    std::atomic<std::uint64_t> split_nodes{0};
    std::atomic<std::uint64_t> transposition_hits{0};
    std::atomic<std::uint64_t> tail_queries{0};
    std::atomic<std::uint64_t> tail_bloom_rejects{0};
    std::atomic<std::uint64_t> tail_exact_queries{0};
    std::atomic<std::uint64_t> tail_probes{0};
    std::atomic<std::uint64_t> tail_hits{0};
    std::chrono::steady_clock::time_point deadline;
    std::mutex solution_mutex;
    std::vector<int> solution;
};

struct WorkerContext {
    WorkerContext(std::size_t transposition_limit, bool use_transposition) {
        if (use_transposition) transposition = std::make_unique<TranspositionTable>(transposition_limit);
    }
    std::unique_ptr<TranspositionTable> transposition;
    std::uint64_t pending_nodes{0};
    std::uint64_t split_nodes{0};
    std::uint64_t transposition_hits{0};
    TailLookupCounters tail_counters;
};

bool check_stop(SearchControl& control, WorkerContext& worker) {
    if (control.stop.load(std::memory_order_relaxed)) return true;
    if ((worker.pending_nodes & 1023U) == 0 && std::chrono::steady_clock::now() >= control.deadline) {
        control.timed_out.store(true, std::memory_order_relaxed);
        control.stop.store(true, std::memory_order_relaxed);
        return true;
    }
    return false;
}

bool depth_first_search(
    const CoordinateTables& tables,
    const Phase1PatternDatabase* phase1_pdb,
    const CornerPatternDatabase* corner_pdb,
    std::span<const EdgePatternDatabase* const> edge_pdbs,
    const TailDatabase* tail_database,
    const CoordinateFeatures& features,
    const SolverOptions& options,
    const CoordinateState& state,
    int depth_left,
    int last_face,
    std::vector<int>& path,
    SearchControl& control,
    WorkerContext& worker,
    bool heuristic_checked = false) {
    ++worker.pending_nodes;
    if (check_stop(control, worker)) return false;
    if (!heuristic_checked &&
        tables.heuristic(state, phase1_pdb, corner_pdb, edge_pdbs, static_cast<std::uint8_t>(depth_left)) > depth_left) {
        return false;
    }
    if (tail_database != nullptr && depth_left <= tail_database->depth()) {
        const auto hit = tail_database->lookup(*state.cube, &worker.tail_counters);
        if (!hit.has_value() || hit->distance > depth_left) return false;
        std::vector<int> solution = path;
        const auto suffix = tail_database->solution_suffix(*state.cube);
        solution.insert(solution.end(), suffix.begin(), suffix.end());
        std::lock_guard lock(control.solution_mutex);
        if (control.solution.empty()) control.solution = std::move(solution);
        control.stop.store(true, std::memory_order_relaxed);
        return true;
    }
    if (state.cube->solved()) {
        std::lock_guard lock(control.solution_mutex);
        if (control.solution.empty()) control.solution = path;
        control.stop.store(true, std::memory_order_relaxed);
        return true;
    }
    if (depth_left == 0) return false;

    StateKey key{};
    if (worker.transposition != nullptr) {
        key = state_key(*state.cube, last_face);
        if (worker.transposition->contains_at_least(key, static_cast<std::uint8_t>(depth_left))) {
            ++worker.transposition_hits;
            return false;
        }
    }

    const int next_depth = depth_left - 1;
    if (depth_left >= kMoveOrderingMinRemaining) {
        struct Candidate {
            CoordinateState state;
            int move{};
            int face{};
            std::uint8_t heuristic{};
        };
        std::vector<Candidate> candidates;
        candidates.reserve(15);
        for (int move = 0; move < kMoveCount; ++move) {
            const int face = move / 3;
            if (should_skip_face(last_face, face)) continue;
            CoordinateState child = tables.moved(state, move, features);
            const std::uint8_t child_heuristic = tables.heuristic(
                child, phase1_pdb, corner_pdb, edge_pdbs, static_cast<std::uint8_t>(next_depth));
            if (child_heuristic > next_depth) continue;
            if (!features.full_cube_for_heuristic) child.cube = state.cube->apply_move(move);
            candidates.push_back(Candidate{std::move(child), move, face, child_heuristic});
        }
        std::stable_sort(candidates.begin(), candidates.end(), [](const Candidate& left, const Candidate& right) {
            return left.heuristic < right.heuristic;
        });
        for (const Candidate& candidate : candidates) {
            path.push_back(candidate.move);
            if (depth_first_search(
                    tables,
                    phase1_pdb,
                    corner_pdb,
                    edge_pdbs,
                    tail_database,
                    features,
                    options,
                    candidate.state,
                    next_depth,
                    candidate.face,
                    path,
                    control,
                    worker,
                    true)) {
                return true;
            }
            path.pop_back();
            if (control.stop.load(std::memory_order_relaxed)) return false;
        }
        if (worker.transposition != nullptr) {
            worker.transposition->store(key, static_cast<std::uint8_t>(depth_left));
        }
        return false;
    }

    for (int move = 0; move < kMoveCount; ++move) {
        const int face = move / 3;
        if (should_skip_face(last_face, face)) continue;
        CoordinateState child = tables.moved(state, move, features);
        const std::uint8_t child_heuristic = tables.heuristic(
            child, phase1_pdb, corner_pdb, edge_pdbs, static_cast<std::uint8_t>(next_depth));
        if (child_heuristic > next_depth) continue;
        if (!features.full_cube_for_heuristic) child.cube = state.cube->apply_move(move);
        path.push_back(move);
        if (depth_first_search(
                tables,
                phase1_pdb,
                corner_pdb,
                edge_pdbs,
                tail_database,
                features,
                options,
                child,
                next_depth,
                face,
                path,
                control,
                worker,
                true)) {
            return true;
        }
        path.pop_back();
        if (control.stop.load(std::memory_order_relaxed)) return false;
    }

    if (worker.transposition != nullptr) {
        worker.transposition->store(key, static_cast<std::uint8_t>(depth_left));
    }
    return false;
}

std::vector<SearchTask> split_task(
    const CoordinateTables& tables,
    const Phase1PatternDatabase* phase1_pdb,
    const CornerPatternDatabase* corner_pdb,
    std::span<const EdgePatternDatabase* const> edge_pdbs,
    const CoordinateFeatures& features,
    const SearchTask& task,
    std::uint64_t& split_nodes) {
    std::vector<SearchTask> children;
    if (task.depth_left == 0) return children;
    const int next_depth = task.depth_left - 1;
    std::uint64_t generated_nodes = 0;
    children.reserve(15);
    for (int move = 0; move < kMoveCount; ++move) {
        const int face = move / 3;
        if (should_skip_face(task.last_face, face)) continue;
        ++generated_nodes;
        CoordinateState child = tables.moved(task.state, move, features);
        if (tables.heuristic(child, phase1_pdb, corner_pdb, edge_pdbs, static_cast<std::uint8_t>(next_depth)) > next_depth) continue;
        if (!features.full_cube_for_heuristic) child.cube = task.state.cube->apply_move(move);
        SearchTask child_task{std::move(child), next_depth, face, task.path};
        child_task.path.push_back(move);
        children.push_back(std::move(child_task));
    }
    split_nodes += generated_nodes;
    return children;
}

std::optional<std::vector<int>> parallel_depth_search(
    const CoordinateTables& tables,
    const Phase1PatternDatabase* phase1_pdb,
    const CornerPatternDatabase* corner_pdb,
    std::span<const EdgePatternDatabase* const> edge_pdbs,
    const TailDatabase* tail_database,
    const CoordinateFeatures& features,
    const CoordinateState& initial,
    int depth,
    const SolverOptions& options,
    int thread_count,
    SearchControl& control) {
    struct QueueState {
        std::mutex mutex;
        std::condition_variable condition;
        std::deque<SearchTask> tasks;
        std::size_t outstanding{1};
    } queue;
    queue.tasks.push_back(SearchTask{initial, depth, -1, {}});
    const std::size_t target_queue = static_cast<std::size_t>(thread_count) * 64;

    auto worker_function = [&] {
        WorkerContext worker(options.transposition_limit_per_thread, options.use_transposition);
        while (true) {
            SearchTask task;
            std::size_t queued_after_pop = 0;
            {
                std::unique_lock lock(queue.mutex);
                queue.condition.wait(lock, [&] {
                    return control.stop.load(std::memory_order_relaxed) || !queue.tasks.empty() || queue.outstanding == 0;
                });
                if (control.stop.load(std::memory_order_relaxed) || queue.outstanding == 0) break;
                task = std::move(queue.tasks.front());
                queue.tasks.pop_front();
                queued_after_pop = queue.tasks.size();
            }

            const int split_floor = tail_database != nullptr ? tail_database->depth() : 3;
            const bool should_split =
                task.depth_left > split_floor && task.path.size() < 7 && queued_after_pop < target_queue;
            if (should_split) {
                auto children = split_task(
                    tables, phase1_pdb, corner_pdb, edge_pdbs, features, task, worker.split_nodes);
                {
                    std::lock_guard lock(queue.mutex);
                    queue.outstanding += children.size();
                    --queue.outstanding;
                    for (auto& child : children) queue.tasks.push_back(std::move(child));
                }
                queue.condition.notify_all();
                continue;
            }

            std::vector<int> path = task.path;
            depth_first_search(
                tables,
                phase1_pdb,
                corner_pdb,
                edge_pdbs,
                tail_database,
                features,
                options,
                task.state,
                task.depth_left,
                task.last_face,
                path,
                control,
                worker);
            {
                std::lock_guard lock(queue.mutex);
                --queue.outstanding;
            }
            queue.condition.notify_all();
        }
        control.nodes.fetch_add(worker.pending_nodes, std::memory_order_relaxed);
        control.split_nodes.fetch_add(worker.split_nodes, std::memory_order_relaxed);
        control.transposition_hits.fetch_add(worker.transposition_hits, std::memory_order_relaxed);
        control.tail_queries.fetch_add(worker.tail_counters.queries, std::memory_order_relaxed);
        control.tail_bloom_rejects.fetch_add(worker.tail_counters.bloom_rejects, std::memory_order_relaxed);
        control.tail_exact_queries.fetch_add(worker.tail_counters.exact_queries, std::memory_order_relaxed);
        control.tail_probes.fetch_add(worker.tail_counters.probes, std::memory_order_relaxed);
        control.tail_hits.fetch_add(worker.tail_counters.hits, std::memory_order_relaxed);
    };

    std::vector<std::thread> workers;
    workers.reserve(thread_count);
    for (int i = 0; i < thread_count; ++i) workers.emplace_back(worker_function);
    for (auto& worker : workers) worker.join();

    if (!control.solution.empty()) return control.solution;
    return std::nullopt;
}

}  // namespace

CoordinateTables::CoordinateTables() {
    twist_move_ = build_move_table(kTwistCount, cube_from_twist, twist_coord);
    flip_move_ = build_move_table(kFlipCount, cube_from_flip, flip_coord);
    slice_move_ = build_move_table(kSliceCount, cube_from_slice_comb, slice_comb_coord);
    corner_move_ = build_move_table(kCornerPermCount, cube_from_corner_perm, corner_perm_coord);
    const int solved_slice = slice_comb_coord(CubieCube{});
    twist_slice_prune_ = build_pair_prune(
        kTwistCount, kSliceCount, 0, solved_slice, twist_move_, slice_move_);
    flip_slice_prune_ = build_pair_prune(
        kFlipCount, kSliceCount, 0, solved_slice, flip_move_, slice_move_);
    twist_flip_prune_ = build_pair_prune(
        kTwistCount, kFlipCount, 0, 0, twist_move_, flip_move_);
    corner_prune_ = build_single_prune(kCornerPermCount, 0, corner_move_);
}

CoordinateState CoordinateTables::from_cube(
    const CubieCube& cube,
    const CoordinateFeatures& features) const noexcept {
    CoordinateState result{
        cube,
        twist_coord(cube),
        flip_coord(cube),
        slice_comb_coord(cube),
        corner_perm_coord(cube),
    };
    if (features.edge_pattern_a) result.edge_pattern_a = edge_pattern_state(cube, 0);
    if (features.edge_pattern_b) result.edge_pattern_b = edge_pattern_state(cube, 6);
    if (features.axis_coordinates) {
        for (int axis = 0; axis < kAxisRotationCount; ++axis) {
            const CubieCube rotated = conjugate_axis(cube, axis);
            result.axis_twist[axis] = twist_coord(rotated);
            result.axis_flip[axis] = flip_coord(rotated);
            result.axis_slice[axis] = slice_comb_coord(rotated);
        }
    }
    return result;
}

CoordinateState CoordinateTables::moved(
    const CoordinateState& state,
    int move,
    const CoordinateFeatures& features) const noexcept {
    CoordinateState result{
        features.full_cube_for_heuristic
            ? std::optional<CubieCube>{state.cube->apply_move(move)}
            : std::nullopt,
        twist_move_[static_cast<std::size_t>(state.twist) * kMoveCount + move],
        flip_move_[static_cast<std::size_t>(state.flip) * kMoveCount + move],
        slice_move_[static_cast<std::size_t>(state.slice) * kMoveCount + move],
        corner_move_[static_cast<std::size_t>(state.corner_perm) * kMoveCount + move],
    };
    if (features.edge_pattern_a) result.edge_pattern_a = move_edge_pattern(state.edge_pattern_a, move);
    if (features.edge_pattern_b) result.edge_pattern_b = move_edge_pattern(state.edge_pattern_b, move);
    if (features.axis_coordinates) {
        const auto& axis_moves = axis_rotation_move_maps();
        for (int axis = 0; axis < kAxisRotationCount; ++axis) {
            const int rotated_move = axis_moves[axis][move];
            result.axis_twist[axis] = twist_move_[static_cast<std::size_t>(state.axis_twist[axis]) * kMoveCount + rotated_move];
            result.axis_flip[axis] = flip_move_[static_cast<std::size_t>(state.axis_flip[axis]) * kMoveCount + rotated_move];
            result.axis_slice[axis] = slice_move_[static_cast<std::size_t>(state.axis_slice[axis]) * kMoveCount + rotated_move];
        }
    }
    return result;
}

std::uint8_t CoordinateTables::heuristic(
    const CoordinateState& state,
    const Phase1PatternDatabase* phase1_pdb,
    const CornerPatternDatabase* corner_pdb,
    std::span<const EdgePatternDatabase* const> edge_pdbs,
    std::uint8_t cutoff) const noexcept {
    std::uint8_t result = corner_prune_[state.corner_perm];
    result = std::max(result, twist_slice_prune_[static_cast<std::size_t>(state.twist) * kSliceCount + state.slice]);
    result = std::max(result, flip_slice_prune_[static_cast<std::size_t>(state.flip) * kSliceCount + state.slice]);
    result = std::max(result, twist_flip_prune_[static_cast<std::size_t>(state.twist) * kFlipCount + state.flip]);
    if (result > cutoff) return result;
    if (phase1_pdb != nullptr) {
        result = std::max(result, phase1_pdb->distance(state.twist, state.flip, state.slice));
        if (result > cutoff) return result;
        for (int axis = 0; axis < kAxisRotationCount; ++axis) {
            result = std::max(result, phase1_pdb->distance(
                state.axis_twist[axis], state.axis_flip[axis], state.axis_slice[axis]));
            if (result > cutoff) return result;
        }
    }
    if (corner_pdb != nullptr) {
        result = std::max(result, corner_pdb->distance(
            static_cast<std::uint32_t>(state.corner_perm) * kTwistCount + state.twist));
        if (result > cutoff) return result;
    }
    for (std::size_t group = 0; group < edge_pdbs.size(); ++group) {
        const EdgePatternDatabase* database = edge_pdbs[group];
        if (database == nullptr) continue;
        std::uint32_t coordinate = 0;
        if (group == 0) coordinate = edge_pattern_coord(state.edge_pattern_a);
        else if (group == 1) coordinate = edge_pattern_coord(state.edge_pattern_b);
        else coordinate = edge_pattern_coord(edge_pattern_state(*state.cube, edge_pattern_group(static_cast<int>(group))));
        result = std::max(result, database->distance(coordinate));
        if (result > cutoff) return result;
    }
    return result;
}

std::uint16_t CoordinateTables::corner_move(std::uint16_t coordinate, int move) const noexcept {
    return corner_move_[static_cast<std::size_t>(coordinate) * kMoveCount + move];
}

std::uint16_t CoordinateTables::twist_move(std::uint16_t coordinate, int move) const noexcept {
    return twist_move_[static_cast<std::size_t>(coordinate) * kMoveCount + move];
}

std::uint16_t CoordinateTables::flip_move(std::uint16_t coordinate, int move) const noexcept {
    return flip_move_[static_cast<std::size_t>(coordinate) * kMoveCount + move];
}

std::uint16_t CoordinateTables::slice_move(std::uint16_t coordinate, int move) const noexcept {
    return slice_move_[static_cast<std::size_t>(coordinate) * kMoveCount + move];
}

NativeOptimalSolver::NativeOptimalSolver(std::shared_ptr<CoordinateTables> tables)
    : tables_(tables ? std::move(tables) : std::make_shared<CoordinateTables>()) {}

void NativeOptimalSolver::load_corner_pdb(const std::filesystem::path& path) {
    corner_pdb_ = std::make_shared<CornerPatternDatabase>(path);
}

void NativeOptimalSolver::load_phase1_pdb(const std::filesystem::path& path) {
    phase1_pdb_ = std::make_shared<Phase1PatternDatabase>(path);
}

void NativeOptimalSolver::load_edge_pdb(int group, const std::filesystem::path& path) {
    if (group < 0 || group >= static_cast<int>(edge_pdbs_.size())) {
        throw std::invalid_argument("edge PDB group must be 0..7");
    }
    edge_pdbs_[group] = std::make_shared<EdgePatternDatabase>(path, group);
}

void NativeOptimalSolver::load_edge_pdbs(
    const std::filesystem::path& path_a,
    const std::filesystem::path& path_b) {
    load_edge_pdb(0, path_a);
    load_edge_pdb(1, path_b);
}

void NativeOptimalSolver::load_extra_edge_pdbs(
    const std::filesystem::path& path_c,
    const std::filesystem::path& path_d) {
    load_edge_pdb(2, path_c);
    load_edge_pdb(3, path_d);
}

void NativeOptimalSolver::load_tail_database(const std::filesystem::path& path) {
    tail_database_ = std::make_shared<TailDatabase>(path);
}

bool NativeOptimalSolver::has_corner_pdb() const noexcept { return static_cast<bool>(corner_pdb_); }

bool NativeOptimalSolver::has_phase1_pdb() const noexcept { return static_cast<bool>(phase1_pdb_); }

bool NativeOptimalSolver::has_edge_pdbs() const noexcept {
    return static_cast<bool>(edge_pdbs_[0]) && static_cast<bool>(edge_pdbs_[1]);
}

bool NativeOptimalSolver::has_extra_edge_pdbs() const noexcept {
    return edge_pdb_count() > 2;
}

int NativeOptimalSolver::edge_pdb_count() const noexcept {
    return static_cast<int>(std::count_if(
        edge_pdbs_.begin(), edge_pdbs_.end(), [](const auto& database) { return static_cast<bool>(database); }));
}

bool NativeOptimalSolver::has_tail_database() const noexcept { return static_cast<bool>(tail_database_); }

NativeSolveResult NativeOptimalSolver::solve(const CubieCube& cube, const SolverOptions& options) const {
    if (options.max_depth < 0 || options.max_depth > 20) throw std::invalid_argument("max depth must be 0..20");
    if (!(options.timeout_seconds > 0.0)) throw std::invalid_argument("timeout must be positive");
    const auto started = std::chrono::steady_clock::now();
    if (cube.solved()) {
        NativeSolveResult solved;
        solved.depth = 0;
        solved.optimal = true;
        return solved;
    }

    if (!options.incumbent_moves.empty()) {
        CubieCube candidate = cube;
        for (int move : options.incumbent_moves) {
            if (move < 0 || move >= kMoveCount) throw std::invalid_argument("incumbent contains invalid move");
            candidate = candidate.apply_move(move);
        }
        if (!candidate.solved()) throw std::invalid_argument("incumbent does not solve the cube");
    }

    std::array<const EdgePatternDatabase*, 8> edge_pdb_views{};
    for (std::size_t group = 0; group < edge_pdbs_.size(); ++group) {
        edge_pdb_views[group] = edge_pdbs_[group].get();
    }
    const CoordinateFeatures features{
        phase1_pdb_ != nullptr,
        edge_pdb_views[0] != nullptr,
        edge_pdb_views[1] != nullptr,
        std::any_of(edge_pdb_views.begin() + 2, edge_pdb_views.end(), [](const auto* database) {
            return database != nullptr;
        }),
    };
    CoordinateState active_initial = tables_->from_cube(cube, features);
    const int lower_bound = tables_->heuristic(
        active_initial, phase1_pdb_.get(), corner_pdb_.get(), edge_pdb_views);
    int effective_max = options.max_depth;
    if (!options.incumbent_moves.empty()) {
        effective_max = std::min(effective_max, static_cast<int>(options.incumbent_moves.size()) - 1);
    }
    const bool direction_probe_enabled =
        options.use_direction_probe && options.incumbent_moves.size() >= 18 && effective_max >= 17;
    const int direction_probe_depth = direction_probe_enabled
        ? std::max(lower_bound, std::min(16, effective_max - 2))
        : -1;
    std::optional<CoordinateState> inverse_initial;
    int inverse_lower_bound = 0;
    if (direction_probe_enabled && direction_probe_depth < effective_max) {
        inverse_initial = tables_->from_cube(cube.inverse(), features);
        inverse_lower_bound = tables_->heuristic(
            *inverse_initial, phase1_pdb_.get(), corner_pdb_.get(), edge_pdb_views);
    }
    bool searching_inverse = false;
    bool direction_probed = false;
    const unsigned hardware_threads = std::max(1U, std::thread::hardware_concurrency());
    const int thread_count = std::clamp(options.threads > 0 ? options.threads : static_cast<int>(hardware_threads), 1, 64);

    NativeSolveResult result;
    SearchControl control;
    control.deadline = started + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
        std::chrono::duration<double>(options.timeout_seconds));

    if (options.progress_callback) {
        options.progress_callback(NativeSearchProgress{
            lower_bound,
            effective_max,
            lower_bound,
            lower_bound - 1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0.0,
            0.0,
            false,
            false,
        });
    }

    for (int depth = lower_bound; depth <= effective_max; ++depth) {
        const auto iteration_started = std::chrono::steady_clock::now();
        const std::uint64_t nodes_before = control.nodes.load(std::memory_order_relaxed);
        const std::uint64_t split_nodes_before = control.split_nodes.load(std::memory_order_relaxed);
        const std::uint64_t hits_before = control.transposition_hits.load(std::memory_order_relaxed);
        const TailLookupCounters tail_before{
            control.tail_queries.load(std::memory_order_relaxed),
            control.tail_bloom_rejects.load(std::memory_order_relaxed),
            control.tail_exact_queries.load(std::memory_order_relaxed),
            control.tail_probes.load(std::memory_order_relaxed),
            control.tail_hits.load(std::memory_order_relaxed),
        };
        control.stop.store(false, std::memory_order_relaxed);
        control.timed_out.store(false, std::memory_order_relaxed);
        control.solution.clear();
        auto solution = parallel_depth_search(
            *tables_,
            phase1_pdb_.get(),
            corner_pdb_.get(),
            edge_pdb_views,
            tail_database_.get(),
            features,
            active_initial,
            depth,
            options,
            thread_count,
            control);
        const std::uint64_t primary_iteration_nodes =
            control.nodes.load(std::memory_order_relaxed) - nodes_before;
        if (!solution.has_value() && !control.timed_out.load(std::memory_order_relaxed) &&
            !direction_probed && inverse_initial.has_value() && depth == direction_probe_depth) {
            direction_probed = true;
            SearchControl inverse_control;
            inverse_control.deadline = control.deadline;
            std::optional<std::vector<int>> inverse_solution;
            if (inverse_lower_bound <= depth) {
                inverse_solution = parallel_depth_search(
                    *tables_,
                    phase1_pdb_.get(),
                    corner_pdb_.get(),
                    edge_pdb_views,
                    tail_database_.get(),
                    features,
                    *inverse_initial,
                    depth,
                    options,
                    thread_count,
                    inverse_control);
            }
            const std::uint64_t inverse_nodes = inverse_control.nodes.load(std::memory_order_relaxed);
            control.nodes.fetch_add(inverse_nodes, std::memory_order_relaxed);
            control.split_nodes.fetch_add(
                inverse_control.split_nodes.load(std::memory_order_relaxed), std::memory_order_relaxed);
            control.transposition_hits.fetch_add(
                inverse_control.transposition_hits.load(std::memory_order_relaxed), std::memory_order_relaxed);
            control.tail_queries.fetch_add(
                inverse_control.tail_queries.load(std::memory_order_relaxed), std::memory_order_relaxed);
            control.tail_bloom_rejects.fetch_add(
                inverse_control.tail_bloom_rejects.load(std::memory_order_relaxed), std::memory_order_relaxed);
            control.tail_exact_queries.fetch_add(
                inverse_control.tail_exact_queries.load(std::memory_order_relaxed), std::memory_order_relaxed);
            control.tail_probes.fetch_add(
                inverse_control.tail_probes.load(std::memory_order_relaxed), std::memory_order_relaxed);
            control.tail_hits.fetch_add(
                inverse_control.tail_hits.load(std::memory_order_relaxed), std::memory_order_relaxed);
            if (inverse_control.timed_out.load(std::memory_order_relaxed)) {
                control.timed_out.store(true, std::memory_order_relaxed);
            } else if (inverse_solution.has_value()) {
                solution = invert_moves(*inverse_solution);
            } else if (inverse_nodes < primary_iteration_nodes) {
                active_initial = *inverse_initial;
                searching_inverse = true;
            }
        }
        if (solution.has_value() && searching_inverse) {
            solution = invert_moves(*solution);
        }
        const std::uint64_t iteration_nodes = control.nodes.load(std::memory_order_relaxed) - nodes_before;
        const std::uint64_t iteration_split_nodes =
            control.split_nodes.load(std::memory_order_relaxed) - split_nodes_before;
        const std::uint64_t iteration_hits =
            control.transposition_hits.load(std::memory_order_relaxed) - hits_before;
        const TailLookupCounters iteration_tail{
            control.tail_queries.load(std::memory_order_relaxed) - tail_before.queries,
            control.tail_bloom_rejects.load(std::memory_order_relaxed) - tail_before.bloom_rejects,
            control.tail_exact_queries.load(std::memory_order_relaxed) - tail_before.exact_queries,
            control.tail_probes.load(std::memory_order_relaxed) - tail_before.probes,
            control.tail_hits.load(std::memory_order_relaxed) - tail_before.hits,
        };
        const double iteration_seconds = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - iteration_started).count();
        const bool timed_out = control.timed_out.load(std::memory_order_relaxed);
        const int completed_depth = solution.has_value() || timed_out ? depth - 1 : depth;
        if (options.progress_callback) {
            options.progress_callback(NativeSearchProgress{
                lower_bound,
                effective_max,
                depth,
                completed_depth,
                iteration_nodes,
                iteration_split_nodes,
                control.nodes.load(std::memory_order_relaxed),
                control.split_nodes.load(std::memory_order_relaxed),
                iteration_hits,
                iteration_tail.queries,
                iteration_tail.bloom_rejects,
                iteration_tail.exact_queries,
                iteration_tail.probes,
                iteration_tail.hits,
                iteration_seconds,
                std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count(),
                solution.has_value(),
                timed_out,
            });
        } else {
            std::cerr << "ida depth=" << depth << " nodes=" << iteration_nodes
                      << " split_nodes=" << iteration_split_nodes
                      << " tt_hits=" << iteration_hits
                      << " elapsed=" << iteration_seconds << "s"
                      << " found=" << solution.has_value() << "\n";
        }
        if (solution.has_value()) {
            result.moves = *solution;
            result.depth = static_cast<int>(result.moves.size());
            result.optimal = true;
            break;
        }
        if (timed_out) {
            result.timed_out = true;
            break;
        }
    }

    if (result.depth < 0 && !result.timed_out && !options.incumbent_moves.empty() &&
        options.max_depth >= static_cast<int>(options.incumbent_moves.size()) - 1) {
        result.moves = options.incumbent_moves;
        result.depth = static_cast<int>(result.moves.size());
        result.optimal = true;
    } else if (result.depth < 0 && result.timed_out && !options.incumbent_moves.empty()) {
        result.moves = options.incumbent_moves;
        result.depth = static_cast<int>(result.moves.size());
    } else if (result.depth < 0 && !result.timed_out) {
        throw std::runtime_error("no solution found within max depth");
    }

    result.nodes = control.nodes.load(std::memory_order_relaxed);
    result.split_nodes = control.split_nodes.load(std::memory_order_relaxed);
    result.transposition_hits = control.transposition_hits.load(std::memory_order_relaxed);
    result.tail_queries = control.tail_queries.load(std::memory_order_relaxed);
    result.tail_bloom_rejects = control.tail_bloom_rejects.load(std::memory_order_relaxed);
    result.tail_exact_queries = control.tail_exact_queries.load(std::memory_order_relaxed);
    result.tail_probes = control.tail_probes.load(std::memory_order_relaxed);
    result.tail_hits = control.tail_hits.load(std::memory_order_relaxed);
    result.inverse_direction = searching_inverse;
    result.elapsed_seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    return result;
}

}  // namespace cube
