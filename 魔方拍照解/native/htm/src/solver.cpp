#include "solver.hpp"

#include "pdb.hpp"
#include "symmetry.hpp"
#include "tail.hpp"

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <bit>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <fstream>
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
constexpr std::uint64_t kSolvedEdges = 0xBA9876543210ULL;

std::uint64_t pack_edges(const CubieCube &cube) noexcept {
    std::uint64_t result = 0;
    for (int i = 0; i < 12; ++i)
        result |= static_cast<std::uint64_t>(cube.ep[i]) << (i * 4);
    return result;
}

std::uint64_t move_edges(std::uint64_t edges, int move) noexcept {
    struct Spec {
        std::uint64_t unchanged{0};
        std::array<int, 4> source{};
        std::array<int, 4> destination{};
    };
    static const auto specs = [] {
        std::array<Spec, 18> result{};
        for (int m = 0; m < 18; ++m) {
            int changed = 0;
            for (int i = 0; i < 12; ++i) {
                const int source = move_cubes()[m].ep[i];
                if (source == i)
                    result[m].unchanged |= 0xFULL << (i * 4);
                else {
                    result[m].source[changed] = source * 4;
                    result[m].destination[changed++] = i * 4;
                }
            }
        }
        return result;
    }();
    const auto &spec = specs[move];
    std::uint64_t result = edges & spec.unchanged;
    for (int i = 0; i < 4; ++i)
        result |= ((edges >> spec.source[i]) & 0xFULL) << spec.destination[i];
    return result;
}

bool solved(const CoordinateState &state) noexcept {
    return state.corner_perm == 0 && state.twist == 0 && state.flip == 0 && state.edges == kSolvedEdges;
}

void add_counters(SearchCounters &target, const SearchCounters &source) {
    target.generated += source.generated;
    target.small_queries += source.small_queries;
    target.phase1_queries += source.phase1_queries;
    target.corner_queries += source.corner_queries;
    target.edge_queries += source.edge_queries;
    for (int i = 0; i < 3; ++i)
        target.axis_rejects[i] += source.axis_rejects[i];
    target.equality_rejects += source.equality_rejects;
    target.corner_rejects += source.corner_rejects;
    target.edge_rejects += source.edge_rejects;
}

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

std::vector<std::uint8_t> build_pair_prune(int size_a, int size_b, int solved_a, int solved_b,
                                           const std::vector<std::uint16_t> &move_a,
                                           const std::vector<std::uint16_t> &move_b) {
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

std::vector<std::uint8_t> build_single_prune(int size, int solved, const std::vector<std::uint16_t> &moves) {
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
    bool operator==(const StateKey &) const = default;
};

StateKey state_key(const CubieCube &cube, int last_face) noexcept {
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

    [[nodiscard]] bool contains_at_least(const StateKey &key, std::uint8_t depth) const noexcept {
        std::size_t slot = static_cast<std::size_t>(mix_hash(key.low ^ std::rotl(key.high, 23))) & mask_;
        for (int probe = 0; probe < kProbeLimit; ++probe) {
            const Entry &entry = entries_[slot];
            const std::uint8_t stored_depth = static_cast<std::uint8_t>(entry.high_depth >> 56U);
            if (stored_depth == 0)
                return false;
            if (entry.low == key.low && (entry.high_depth & kHighMask) == key.high) {
                return stored_depth >= depth;
            }
            slot = (slot + 1) & mask_;
        }
        return false;
    }

    void store(const StateKey &key, std::uint8_t depth) noexcept {
        std::size_t slot = static_cast<std::size_t>(mix_hash(key.low ^ std::rotl(key.high, 23))) & mask_;
        std::size_t replacement = slot;
        std::uint8_t shallowest = 255;
        for (int probe = 0; probe < kProbeLimit; ++probe) {
            Entry &entry = entries_[slot];
            const std::uint8_t stored_depth = static_cast<std::uint8_t>(entry.high_depth >> 56U);
            if (stored_depth == 0 || (entry.low == key.low && (entry.high_depth & kHighMask) == key.high)) {
                if (stored_depth <= depth)
                    entry = Entry{key.low, key.high | (static_cast<std::uint64_t>(depth) << 56U)};
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
    const std::atomic<bool> *cancel_requested{nullptr};
    std::mutex counters_mutex;
    SearchCounters counters;
    std::vector<WorkerStatistics> workers;
    std::mutex solution_mutex;
    std::vector<int> solution;
};

struct WorkerContext {
    WorkerContext(std::size_t transposition_limit, bool use_transposition) {
        if (use_transposition)
            transposition = std::make_unique<TranspositionTable>(transposition_limit);
    }
    std::unique_ptr<TranspositionTable> transposition;
    std::uint64_t pending_nodes{0};
    std::uint64_t split_nodes{0};
    std::uint64_t transposition_hits{0};
    TailLookupCounters tail_counters;
    SearchCounters counters;
    WorkerStatistics statistics;
    int index{};
};

void publish(SearchControl &control, WorkerContext &worker) {
    worker.statistics.nodes += worker.pending_nodes;
    worker.statistics.generated += worker.counters.generated;
    control.nodes.fetch_add(std::exchange(worker.pending_nodes, 0), std::memory_order_relaxed);
    control.split_nodes.fetch_add(std::exchange(worker.split_nodes, 0), std::memory_order_relaxed);
    control.transposition_hits.fetch_add(std::exchange(worker.transposition_hits, 0), std::memory_order_relaxed);
    control.tail_queries.fetch_add(std::exchange(worker.tail_counters.queries, 0), std::memory_order_relaxed);
    control.tail_bloom_rejects.fetch_add(std::exchange(worker.tail_counters.bloom_rejects, 0),
                                         std::memory_order_relaxed);
    control.tail_exact_queries.fetch_add(std::exchange(worker.tail_counters.exact_queries, 0),
                                         std::memory_order_relaxed);
    control.tail_probes.fetch_add(std::exchange(worker.tail_counters.probes, 0), std::memory_order_relaxed);
    control.tail_hits.fetch_add(std::exchange(worker.tail_counters.hits, 0), std::memory_order_relaxed);
    std::lock_guard lock(control.counters_mutex);
    add_counters(control.counters, worker.counters);
    control.workers[worker.index] = worker.statistics;
    worker.counters = {};
}

bool check_stop(SearchControl &control, WorkerContext &worker) {
    if (control.cancel_requested != nullptr && control.cancel_requested->load(std::memory_order_relaxed))
        control.stop.store(true, std::memory_order_relaxed);
    if (control.stop.load(std::memory_order_relaxed))
        return true;
    if ((worker.pending_nodes & 1023U) == 0 && std::chrono::steady_clock::now() >= control.deadline) {
        control.timed_out.store(true, std::memory_order_relaxed);
        control.stop.store(true, std::memory_order_relaxed);
        return true;
    }
    if (worker.pending_nodes >= 4096)
        publish(control, worker);
    return false;
}

bool depth_first_search(const CoordinateTables &tables, const Phase1PatternDatabase *phase1_pdb,
                        const CornerPatternDatabase *corner_pdb, std::span<const EdgePatternDatabase *const> edge_pdbs,
                        const TailDatabase *tail_database, const CoordinateFeatures &features,
                        const SolverOptions &options, const CoordinateState &state, int depth_left, int last_face,
                        std::vector<int> &path, SearchControl &control, WorkerContext &worker,
                        bool heuristic_checked = false) {
    ++worker.pending_nodes;
    if (check_stop(control, worker))
        return false;
    if (!heuristic_checked &&
        tables.heuristic(state, phase1_pdb, corner_pdb, edge_pdbs, static_cast<std::uint8_t>(depth_left), features,
                         &worker.counters) > depth_left) {
        return false;
    }
    if (tail_database != nullptr && depth_left <= tail_database->depth()) {
        const CubieCube full_cube = tables.materialize(state);
        const auto hit = tail_database->lookup(full_cube, &worker.tail_counters);
        if (!hit.has_value() || hit->distance > depth_left)
            return false;
        std::vector<int> solution = path;
        const auto suffix = tail_database->solution_suffix(full_cube);
        solution.insert(solution.end(), suffix.begin(), suffix.end());
        std::lock_guard lock(control.solution_mutex);
        if (control.solution.empty())
            control.solution = std::move(solution);
        control.stop.store(true, std::memory_order_relaxed);
        return true;
    }
    if (solved(state)) {
        std::lock_guard lock(control.solution_mutex);
        if (control.solution.empty())
            control.solution = path;
        control.stop.store(true, std::memory_order_relaxed);
        return true;
    }
    if (depth_left == 0)
        return false;

    StateKey key{};
    if (worker.transposition != nullptr) {
        key = state_key(tables.materialize(state), last_face);
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
            if (should_skip_face(last_face, face))
                continue;
            CoordinateState child;
            const std::uint8_t child_heuristic =
                tables.expand(state, move, child, phase1_pdb, corner_pdb, edge_pdbs,
                              static_cast<std::uint8_t>(next_depth), features, worker.counters);
            if (child_heuristic > next_depth)
                continue;
            candidates.push_back(Candidate{std::move(child), move, face, child_heuristic});
        }
        std::stable_sort(candidates.begin(), candidates.end(), [](const Candidate &left, const Candidate &right) {
            return left.heuristic < right.heuristic;
        });
        for (const Candidate &candidate : candidates) {
            path.push_back(candidate.move);
            if (depth_first_search(tables, phase1_pdb, corner_pdb, edge_pdbs, tail_database, features, options,
                                   candidate.state, next_depth, candidate.face, path, control, worker, true)) {
                return true;
            }
            path.pop_back();
            if (control.stop.load(std::memory_order_relaxed))
                return false;
        }
        if (worker.transposition != nullptr) {
            worker.transposition->store(key, static_cast<std::uint8_t>(depth_left));
        }
        return false;
    }

    for (int move = 0; move < kMoveCount; ++move) {
        const int face = move / 3;
        if (should_skip_face(last_face, face))
            continue;
        CoordinateState child;
        const std::uint8_t child_heuristic =
            tables.expand(state, move, child, phase1_pdb, corner_pdb, edge_pdbs, static_cast<std::uint8_t>(next_depth),
                          features, worker.counters);
        if (child_heuristic > next_depth)
            continue;
        path.push_back(move);
        if (depth_first_search(tables, phase1_pdb, corner_pdb, edge_pdbs, tail_database, features, options, child,
                               next_depth, face, path, control, worker, true)) {
            return true;
        }
        path.pop_back();
        if (control.stop.load(std::memory_order_relaxed))
            return false;
    }

    if (worker.transposition != nullptr) {
        worker.transposition->store(key, static_cast<std::uint8_t>(depth_left));
    }
    return false;
}

std::vector<SearchTask> split_task(const CoordinateTables &tables, const Phase1PatternDatabase *phase1_pdb,
                                   const CornerPatternDatabase *corner_pdb,
                                   std::span<const EdgePatternDatabase *const> edge_pdbs,
                                   const CoordinateFeatures &features, const SearchTask &task, WorkerContext &worker) {
    std::vector<SearchTask> children;
    if (task.depth_left == 0)
        return children;
    const int next_depth = task.depth_left - 1;
    std::uint64_t generated_nodes = 0;
    children.reserve(15);
    for (int move = 0; move < kMoveCount; ++move) {
        const int face = move / 3;
        if (should_skip_face(task.last_face, face))
            continue;
        ++generated_nodes;
        CoordinateState child;
        if (tables.expand(task.state, move, child, phase1_pdb, corner_pdb, edge_pdbs,
                          static_cast<std::uint8_t>(next_depth), features, worker.counters) > next_depth)
            continue;
        SearchTask child_task{std::move(child), next_depth, face, task.path};
        child_task.path.push_back(move);
        children.push_back(std::move(child_task));
    }
    worker.split_nodes += generated_nodes;
    return children;
}

std::optional<std::vector<int>>
parallel_depth_search(const CoordinateTables &tables, const Phase1PatternDatabase *phase1_pdb,
                      const CornerPatternDatabase *corner_pdb, std::span<const EdgePatternDatabase *const> edge_pdbs,
                      const TailDatabase *tail_database, const CoordinateFeatures &features,
                      const CoordinateState &initial, int depth, const SolverOptions &options, int thread_count,
                      SearchControl &control, const std::function<void()> &snapshot = {}) {
    struct QueueState {
        std::mutex mutex;
        std::condition_variable condition;
        std::deque<SearchTask> tasks;
        std::size_t outstanding{1};
    } queue;
    queue.tasks.push_back(SearchTask{initial, depth, -1, {}});
    const std::size_t target_queue = static_cast<std::size_t>(thread_count) * 64;

    std::atomic<int> active_workers{thread_count};
    std::condition_variable finished_condition;
    std::mutex finished_mutex;
    control.workers.assign(thread_count, {});
    auto worker_function = [&](int index) {
        WorkerContext worker(options.transposition_limit_per_thread, options.use_transposition);
        worker.index = index;
        while (true) {
            if (check_stop(control, worker)) {
                queue.condition.notify_all();
                break;
            }
            SearchTask task;
            std::size_t queued_after_pop = 0;
            const auto wait_started = std::chrono::steady_clock::now();
            {
                std::unique_lock lock(queue.mutex);
                queue.condition.wait(lock, [&] {
                    return control.stop.load(std::memory_order_relaxed) || !queue.tasks.empty() ||
                           queue.outstanding == 0;
                });
                worker.statistics.idle_seconds +=
                    std::chrono::duration<double>(std::chrono::steady_clock::now() - wait_started).count();
                if (control.stop.load(std::memory_order_relaxed) || queue.outstanding == 0)
                    break;
                task = std::move(queue.tasks.front());
                queue.tasks.pop_front();
                queued_after_pop = queue.tasks.size();
            }
            const auto work_started = std::chrono::steady_clock::now();

            const int split_floor = tail_database != nullptr ? tail_database->depth() : 3;
            const bool should_split =
                task.depth_left > split_floor && task.path.size() < 7 && queued_after_pop < target_queue;
            if (should_split) {
                auto children = split_task(tables, phase1_pdb, corner_pdb, edge_pdbs, features, task, worker);
                {
                    std::lock_guard lock(queue.mutex);
                    queue.outstanding += children.size();
                    --queue.outstanding;
                    for (auto &child : children)
                        queue.tasks.push_back(std::move(child));
                }
                queue.condition.notify_all();
                worker.statistics.busy_seconds +=
                    std::chrono::duration<double>(std::chrono::steady_clock::now() - work_started).count();
                if (worker.split_nodes >= 4096)
                    publish(control, worker);
                continue;
            }

            std::vector<int> path = task.path;
            depth_first_search(tables, phase1_pdb, corner_pdb, edge_pdbs, tail_database, features, options, task.state,
                               task.depth_left, task.last_face, path, control, worker);
            {
                std::lock_guard lock(queue.mutex);
                --queue.outstanding;
            }
            queue.condition.notify_all();
            worker.statistics.busy_seconds +=
                std::chrono::duration<double>(std::chrono::steady_clock::now() - work_started).count();
        }
        publish(control, worker);
        active_workers.fetch_sub(1);
        finished_condition.notify_one();
    };

    std::vector<std::thread> workers;
    workers.reserve(thread_count);
    for (int i = 0; i < thread_count; ++i)
        workers.emplace_back(worker_function, i);
    while (active_workers.load() > 0) {
        std::unique_lock lock(finished_mutex);
        finished_condition.wait_for(lock, std::chrono::milliseconds(250), [&] { return active_workers.load() == 0; });
        if (active_workers.load() > 0 && snapshot)
            snapshot();
    }
    for (auto &worker : workers)
        worker.join();

    if (!control.solution.empty())
        return control.solution;
    return std::nullopt;
}

} // namespace

CoordinateTables::CoordinateTables() {
    const wchar_t *configured_cache = _wgetenv(L"CUBE_NATIVE_COORDINATE_CACHE");
    const std::filesystem::path cache = configured_cache ? configured_cache : L".cache/native/coordinates_htm_v1.bin";
    if (!cache.empty() && load_cache(cache))
        return;
    twist_move_ = build_move_table(kTwistCount, cube_from_twist, twist_coord);
    flip_move_ = build_move_table(kFlipCount, cube_from_flip, flip_coord);
    slice_move_ = build_move_table(kSliceCount, cube_from_slice_comb, slice_comb_coord);
    corner_move_ = build_move_table(kCornerPermCount, cube_from_corner_perm, corner_perm_coord);
    const int solved_slice = slice_comb_coord(CubieCube{});
    twist_slice_prune_ = build_pair_prune(kTwistCount, kSliceCount, 0, solved_slice, twist_move_, slice_move_);
    flip_slice_prune_ = build_pair_prune(kFlipCount, kSliceCount, 0, solved_slice, flip_move_, slice_move_);
    twist_flip_prune_ = build_pair_prune(kTwistCount, kFlipCount, 0, 0, twist_move_, flip_move_);
    corner_prune_ = build_single_prune(kCornerPermCount, 0, corner_move_);
    if (!cache.empty())
        save_cache(cache);
}

namespace {
constexpr std::uint64_t kCoordinateCacheVersion = 0x314D544843524F43ULL;
constexpr std::size_t kCoordinateCacheBytes =
    (kTwistCount + kFlipCount + kSliceCount + kCornerPermCount) * kMoveCount * sizeof(std::uint16_t) +
    kTwistCount * kSliceCount + kFlipCount * kSliceCount + kTwistCount * kFlipCount + kCornerPermCount;

std::uint64_t cache_checksum(const std::vector<std::uint8_t> &bytes) {
    std::uint64_t checksum = 1469598103934665603ULL;
    for (auto value : bytes) {
        checksum ^= value;
        checksum *= 1099511628211ULL;
    }
    return checksum;
}
} // namespace

bool CoordinateTables::load_cache(const std::filesystem::path &path) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input || input.tellg() != static_cast<std::streamoff>(24 + kCoordinateCacheBytes))
        return false;
    input.seekg(0);
    std::array<std::uint64_t, 3> header{};
    std::vector<std::uint8_t> data(kCoordinateCacheBytes);
    input.read(reinterpret_cast<char *>(header.data()), sizeof(header));
    input.read(reinterpret_cast<char *>(data.data()), static_cast<std::streamsize>(data.size()));
    if (!input || header[0] != kCoordinateCacheVersion || header[1] != 0x0102030405060708ULL ||
        header[2] != cache_checksum(data))
        return false;
    std::size_t offset = 0;
    auto read = [&](auto &values, std::size_t count) {
        values.resize(count);
        const auto bytes = count * sizeof(values[0]);
        std::memcpy(values.data(), data.data() + offset, bytes);
        offset += bytes;
    };
    read(twist_move_, kTwistCount * kMoveCount);
    read(flip_move_, kFlipCount * kMoveCount);
    read(slice_move_, kSliceCount * kMoveCount);
    read(corner_move_, kCornerPermCount * kMoveCount);
    read(twist_slice_prune_, kTwistCount * kSliceCount);
    read(flip_slice_prune_, kFlipCount * kSliceCount);
    read(twist_flip_prune_, kTwistCount * kFlipCount);
    read(corner_prune_, kCornerPermCount);
    return true;
}

void CoordinateTables::save_cache(const std::filesystem::path &path) const {
    // Cache failures are optional; the freshly generated tables remain authoritative.
    std::filesystem::path temporary;
    try {
        if (!path.parent_path().empty())
            std::filesystem::create_directories(path.parent_path());
        std::vector<std::uint8_t> data;
        data.reserve(kCoordinateCacheBytes);
        auto append = [&](const auto &values) {
            const auto *bytes = reinterpret_cast<const std::uint8_t *>(values.data());
            data.insert(data.end(), bytes, bytes + values.size() * sizeof(values[0]));
        };
        append(twist_move_);
        append(flip_move_);
        append(slice_move_);
        append(corner_move_);
        append(twist_slice_prune_);
        append(flip_slice_prune_);
        append(twist_flip_prune_);
        append(corner_prune_);
        const std::array<std::uint64_t, 3> header{kCoordinateCacheVersion, 0x0102030405060708ULL, cache_checksum(data)};
        temporary = path;
        temporary += "." + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) + ".tmp";
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        output.write(reinterpret_cast<const char *>(header.data()), sizeof(header));
        output.write(reinterpret_cast<const char *>(data.data()), static_cast<std::streamsize>(data.size()));
        output.close();
        if (!output)
            throw std::runtime_error("coordinate cache write failed");
        if (!MoveFileExW(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING))
            throw std::runtime_error("coordinate cache replace failed");
    } catch (const std::exception &) {
        std::error_code error;
        if (!temporary.empty())
            std::filesystem::remove(temporary, error);
    }
}

CoordinateState CoordinateTables::from_cube(const CubieCube &cube, const CoordinateFeatures &features) const noexcept {
    CoordinateState result{pack_edges(cube), twist_coord(cube), flip_coord(cube), slice_comb_coord(cube),
                           corner_perm_coord(cube)};
    if (features.edge_pattern_a)
        result.edge_pattern_a = edge_pattern_state(cube, 0);
    if (features.edge_pattern_b)
        result.edge_pattern_b = edge_pattern_state(cube, 6);
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

CubieCube CoordinateTables::materialize(const CoordinateState &state) const {
    CubieCube result = cube_from_corner_perm(state.corner_perm);
    result.co = cube_from_twist(state.twist).co;
    result.eo = cube_from_flip(state.flip).eo;
    for (int i = 0; i < 12; ++i)
        result.ep[i] = static_cast<std::uint8_t>((state.edges >> (i * 4)) & 0xFULL);
    return result;
}

CoordinateState CoordinateTables::moved(const CoordinateState &state, int move,
                                        const CoordinateFeatures &features) const noexcept {
    CoordinateState result{move_edges(state.edges, move), twist_move(state.twist, move), flip_move(state.flip, move),
                           slice_move(state.slice, move), corner_move(state.corner_perm, move)};
    if (features.edge_pattern_a)
        result.edge_pattern_a = move_edge_pattern(state.edge_pattern_a, move);
    if (features.edge_pattern_b)
        result.edge_pattern_b = move_edge_pattern(state.edge_pattern_b, move);
    if (features.axis_coordinates) {
        for (int axis = 0; axis < kAxisRotationCount; ++axis) {
            const int mapped = axis_rotation_move_maps()[axis][move];
            result.axis_twist[axis] = twist_move(state.axis_twist[axis], mapped);
            result.axis_flip[axis] = flip_move(state.axis_flip[axis], mapped);
            result.axis_slice[axis] = slice_move(state.axis_slice[axis], mapped);
        }
    }
    return result;
}

std::uint8_t CoordinateTables::evaluate(CoordinateState &state, const CoordinateState *parent, int move,
                                        const Phase1PatternDatabase *phase1_pdb,
                                        const CornerPatternDatabase *corner_pdb,
                                        std::span<const EdgePatternDatabase *const> edge_pdbs, std::uint8_t cutoff,
                                        const CoordinateFeatures &features, SearchCounters &counters) const noexcept {
    if (parent != nullptr) {
        state.twist = twist_move(parent->twist, move);
        state.flip = flip_move(parent->flip, move);
        state.slice = slice_move(parent->slice, move);
    }
    std::uint8_t result = 0;
    if (features.small_phase1 || phase1_pdb == nullptr) {
        counters.small_queries += 3;
        result = std::max({twist_slice_prune_[static_cast<std::size_t>(state.twist) * kSliceCount + state.slice],
                           flip_slice_prune_[static_cast<std::size_t>(state.flip) * kSliceCount + state.slice],
                           twist_flip_prune_[static_cast<std::size_t>(state.twist) * kFlipCount + state.flip]});
        if (result > cutoff) {
            ++counters.axis_rejects[0];
            return result;
        }
    }
    if (phase1_pdb != nullptr) {
        std::array<std::uint8_t, 3> axis_values{};
        ++counters.phase1_queries;
        axis_values[0] = phase1_pdb->distance(state.twist, state.flip, state.slice);
        result = std::max(result, axis_values[0]);
        if (result > cutoff) {
            ++counters.axis_rejects[0];
            return result;
        }
        for (int axis = 0; axis < kAxisRotationCount; ++axis) {
            if (parent != nullptr) {
                const int mapped = axis_rotation_move_maps()[axis][move];
                state.axis_twist[axis] = twist_move(parent->axis_twist[axis], mapped);
                state.axis_flip[axis] = flip_move(parent->axis_flip[axis], mapped);
                state.axis_slice[axis] = slice_move(parent->axis_slice[axis], mapped);
            }
            ++counters.phase1_queries;
            axis_values[axis + 1] =
                phase1_pdb->distance(state.axis_twist[axis], state.axis_flip[axis], state.axis_slice[axis]);
            result = std::max(result, axis_values[axis + 1]);
            if (result > cutoff) {
                ++counters.axis_rejects[axis + 1];
                return result;
            }
        }
        // Only independent subgroup bounds participate; the all-zero case must stay zero.
        if (features.strengthen_axes && axis_values[0] > 0 && axis_values[0] == axis_values[1] &&
            axis_values[1] == axis_values[2]) {
            result = std::max(result, static_cast<std::uint8_t>(axis_values[0] + 1));
            if (result > cutoff) {
                ++counters.equality_rejects;
                return result;
            }
        }
    }
    if (parent != nullptr)
        state.corner_perm = corner_move(parent->corner_perm, move);
    if (features.small_corner || corner_pdb == nullptr) {
        ++counters.small_queries;
        result = std::max(result, corner_prune_[state.corner_perm]);
        if (result > cutoff) {
            ++counters.corner_rejects;
            return result;
        }
    }
    if (corner_pdb != nullptr) {
        ++counters.corner_queries;
        result = std::max(
            result, corner_pdb->distance(static_cast<std::uint32_t>(state.corner_perm) * kTwistCount + state.twist));
        if (result > cutoff) {
            ++counters.corner_rejects;
            return result;
        }
    }
    if (parent != nullptr) {
        state.edges = move_edges(parent->edges, move);
        if (features.edge_pattern_a)
            state.edge_pattern_a = move_edge_pattern(parent->edge_pattern_a, move);
        if (features.edge_pattern_b)
            state.edge_pattern_b = move_edge_pattern(parent->edge_pattern_b, move);
    }
    std::optional<CubieCube> full_cube;
    for (std::size_t group = 0; group < edge_pdbs.size(); ++group) {
        const EdgePatternDatabase *database = edge_pdbs[group];
        if (database == nullptr)
            continue;
        std::uint32_t coordinate;
        if (group == 0)
            coordinate = edge_pattern_coord(state.edge_pattern_a);
        else if (group == 1)
            coordinate = edge_pattern_coord(state.edge_pattern_b);
        else {
            if (!full_cube)
                full_cube = materialize(state);
            coordinate =
                edge_pattern_coord(edge_pattern_state(*full_cube, edge_pattern_group(static_cast<int>(group))));
        }
        ++counters.edge_queries;
        result = std::max(result, database->distance(coordinate));
        if (result > cutoff) {
            ++counters.edge_rejects;
            return result;
        }
    }
    return result;
}

std::uint8_t CoordinateTables::heuristic(const CoordinateState &state, const Phase1PatternDatabase *phase1_pdb,
                                         const CornerPatternDatabase *corner_pdb,
                                         std::span<const EdgePatternDatabase *const> edge_pdbs, std::uint8_t cutoff,
                                         const CoordinateFeatures &features, SearchCounters *counters) const noexcept {
    CoordinateState copy = state;
    SearchCounters unused;
    return evaluate(copy, nullptr, 0, phase1_pdb, corner_pdb, edge_pdbs, cutoff, features,
                    counters ? *counters : unused);
}

std::uint8_t CoordinateTables::expand(const CoordinateState &parent, int move, CoordinateState &child,
                                      const Phase1PatternDatabase *phase1_pdb, const CornerPatternDatabase *corner_pdb,
                                      std::span<const EdgePatternDatabase *const> edge_pdbs, std::uint8_t cutoff,
                                      const CoordinateFeatures &features, SearchCounters &counters) const noexcept {
    ++counters.generated;
    if (features.staged_expansion)
        return evaluate(child, &parent, move, phase1_pdb, corner_pdb, edge_pdbs, cutoff, features, counters);
    child = moved(parent, move, features);
    return evaluate(child, nullptr, 0, phase1_pdb, corner_pdb, edge_pdbs, cutoff, features, counters);
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

void NativeOptimalSolver::load_corner_pdb(const std::filesystem::path &path) {
    corner_pdb_ = std::make_shared<CornerPatternDatabase>(path);
}

void NativeOptimalSolver::load_phase1_pdb(const std::filesystem::path &path) {
    phase1_pdb_ = std::make_shared<Phase1PatternDatabase>(path);
}

void NativeOptimalSolver::load_edge_pdb(int group, const std::filesystem::path &path) {
    if (group < 0 || group >= static_cast<int>(edge_pdbs_.size())) {
        throw std::invalid_argument("edge PDB group must be 0..7");
    }
    edge_pdbs_[group] = std::make_shared<EdgePatternDatabase>(path, group);
}

void NativeOptimalSolver::load_edge_pdbs(const std::filesystem::path &path_a, const std::filesystem::path &path_b) {
    load_edge_pdb(0, path_a);
    load_edge_pdb(1, path_b);
}

void NativeOptimalSolver::load_extra_edge_pdbs(const std::filesystem::path &path_c,
                                               const std::filesystem::path &path_d) {
    load_edge_pdb(2, path_c);
    load_edge_pdb(3, path_d);
}

void NativeOptimalSolver::load_tail_database(const std::filesystem::path &path) {
    tail_database_ = std::make_shared<TailDatabase>(path);
}

bool NativeOptimalSolver::has_corner_pdb() const noexcept { return static_cast<bool>(corner_pdb_); }

bool NativeOptimalSolver::has_phase1_pdb() const noexcept { return static_cast<bool>(phase1_pdb_); }

bool NativeOptimalSolver::has_edge_pdbs() const noexcept {
    return static_cast<bool>(edge_pdbs_[0]) && static_cast<bool>(edge_pdbs_[1]);
}

bool NativeOptimalSolver::has_extra_edge_pdbs() const noexcept { return edge_pdb_count() > 2; }

int NativeOptimalSolver::edge_pdb_count() const noexcept {
    return static_cast<int>(std::count_if(edge_pdbs_.begin(), edge_pdbs_.end(),
                                          [](const auto &database) { return static_cast<bool>(database); }));
}

bool NativeOptimalSolver::has_tail_database() const noexcept { return static_cast<bool>(tail_database_); }

NativeSolveResult NativeOptimalSolver::solve(const CubieCube &cube, const SolverOptions &options) const {
    if (options.max_depth < 0 || options.max_depth > 20)
        throw std::invalid_argument("max depth must be 0..20");
    if (!std::isfinite(options.timeout_seconds) || options.timeout_seconds < 0)
        throw std::invalid_argument("timeout must be finite and nonnegative (0 means unlimited)");
    const auto started = std::chrono::steady_clock::now();
    NativeSolveResult result;
    if (cube.solved()) {
        result.depth = 0;
        result.optimal = true;
        return result;
    }
    auto validate_incumbent = [&](const std::vector<int> &moves) {
        CubieCube candidate = cube;
        for (int move : moves) {
            if (move < 0 || move >= kMoveCount)
                throw std::invalid_argument("incumbent contains invalid move");
            candidate = candidate.apply_move(move);
        }
        if (!candidate.solved())
            throw std::invalid_argument("incumbent does not solve the cube");
    };
    std::vector<int> incumbent = options.incumbent_moves;
    if (!incumbent.empty())
        validate_incumbent(incumbent);
    std::array<const EdgePatternDatabase *, 8> edge_pdb_views{};
    for (std::size_t group = 0; group < edge_pdbs_.size(); ++group)
        edge_pdb_views[group] = edge_pdbs_[group].get();
    CoordinateFeatures features;
    features.axis_coordinates = phase1_pdb_ != nullptr;
    features.edge_pattern_a = edge_pdb_views[0] != nullptr;
    features.edge_pattern_b = edge_pdb_views[1] != nullptr;
    features.small_phase1 = !options.omit_covered_small_tables || !phase1_pdb_ || !phase1_pdb_->complete();
    features.small_corner = !options.omit_covered_small_tables || !corner_pdb_ || !corner_pdb_->complete();
    features.strengthen_axes = options.strengthen_axes;
    features.staged_expansion = options.staged_expansion;
    bool searching_inverse = options.inverse_direction;
    CoordinateState active_initial = tables_->from_cube(searching_inverse ? cube.inverse() : cube, features);
    const int lower_bound =
        tables_->heuristic(active_initial, phase1_pdb_.get(), corner_pdb_.get(), edge_pdb_views, 255, features);
    int effective_max = options.max_depth;
    if (!incumbent.empty())
        effective_max = std::min(effective_max, static_cast<int>(incumbent.size()) - 1);
    const bool probe_enabled =
        options.use_direction_probe && !searching_inverse && incumbent.size() >= 18 && effective_max >= 17;
    const int probe_depth = probe_enabled ? std::max(lower_bound, std::min(16, effective_max - 2)) : -1;
    bool direction_probed = false;
    int thread_count = std::clamp(
        options.threads > 0 ? options.threads : static_cast<int>(std::max(1U, std::thread::hardware_concurrency())), 1,
        64);
    SearchControl control;
    control.cancel_requested = options.cancel_requested;
    control.deadline = options.timeout_seconds == 0
                           ? std::chrono::steady_clock::time_point::max()
                           : started + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                                           std::chrono::duration<double>(options.timeout_seconds));
    int completed_depth = std::max(lower_bound - 1, options.completed_depth);
    auto cancelled = [&] {
        return options.cancel_requested && options.cancel_requested->load(std::memory_order_relaxed);
    };
    auto report = [&](int depth, std::uint64_t nodes_before, std::uint64_t split_before,
                      std::chrono::steady_clock::time_point iteration_started, bool found = false) {
        if (!options.progress_callback)
            return;
        NativeSearchProgress progress;
        progress.threads = thread_count;
        progress.lower_bound = lower_bound;
        progress.upper_bound = effective_max;
        progress.current_depth = depth;
        progress.completed_depth = completed_depth;
        progress.total_nodes = control.nodes.load(std::memory_order_relaxed);
        progress.total_split_nodes = control.split_nodes.load(std::memory_order_relaxed);
        progress.iteration_nodes = progress.total_nodes - nodes_before;
        progress.iteration_split_nodes = progress.total_split_nodes - split_before;
        progress.transposition_hits = control.transposition_hits.load(std::memory_order_relaxed);
        progress.tail_queries = control.tail_queries.load(std::memory_order_relaxed);
        progress.tail_bloom_rejects = control.tail_bloom_rejects.load(std::memory_order_relaxed);
        progress.tail_exact_queries = control.tail_exact_queries.load(std::memory_order_relaxed);
        progress.tail_probes = control.tail_probes.load(std::memory_order_relaxed);
        progress.tail_hits = control.tail_hits.load(std::memory_order_relaxed);
        progress.iteration_seconds =
            std::chrono::duration<double>(std::chrono::steady_clock::now() - iteration_started).count();
        progress.elapsed_seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        progress.found = found;
        progress.timed_out = control.timed_out.load(std::memory_order_relaxed);
        progress.cancelled = cancelled();
        {
            std::lock_guard lock(control.counters_mutex);
            progress.counters = control.counters;
            progress.workers = control.workers;
        }
        options.progress_callback(progress);
    };
    report(completed_depth + 1, 0, 0, started);
    for (int depth = completed_depth + 1; depth <= effective_max; ++depth) {
        if (options.thread_count_callback)
            thread_count = std::clamp(options.thread_count_callback(), 1, 64);
        if (options.incumbent_callback) {
            auto updated = options.incumbent_callback();
            if (!updated.empty() && (incumbent.empty() || updated.size() < incumbent.size())) {
                validate_incumbent(updated);
                incumbent = std::move(updated);
                effective_max = std::min(options.max_depth, static_cast<int>(incumbent.size()) - 1);
                if (depth > effective_max)
                    break;
            }
        }
        const auto iteration_started = std::chrono::steady_clock::now();
        const auto nodes_before = control.nodes.load(std::memory_order_relaxed);
        const auto split_before = control.split_nodes.load(std::memory_order_relaxed);
        control.stop.store(false);
        control.timed_out.store(false);
        control.solution.clear();
        auto snapshot = [&] { report(depth, nodes_before, split_before, iteration_started); };
        auto solution =
            parallel_depth_search(*tables_, phase1_pdb_.get(), corner_pdb_.get(), edge_pdb_views, tail_database_.get(),
                                  features, active_initial, depth, options, thread_count, control, snapshot);
        const auto primary_nodes = control.nodes.load() - nodes_before;
        if (!solution && !control.timed_out.load() && !cancelled() && !direction_probed && depth == probe_depth) {
            direction_probed = true;
            const auto inverse_initial = tables_->from_cube(cube.inverse(), features);
            const int inverse_lower = tables_->heuristic(inverse_initial, phase1_pdb_.get(), corner_pdb_.get(),
                                                         edge_pdb_views, 255, features);
            const auto inverse_before = control.nodes.load();
            control.stop.store(false);
            if (inverse_lower <= depth) {
                auto inverse_solution = parallel_depth_search(
                    *tables_, phase1_pdb_.get(), corner_pdb_.get(), edge_pdb_views, tail_database_.get(), features,
                    inverse_initial, depth, options, thread_count, control, snapshot);
                if (inverse_solution)
                    solution = invert_moves(*inverse_solution);
                else if (control.nodes.load() - inverse_before < primary_nodes) {
                    active_initial = inverse_initial;
                    searching_inverse = true;
                }
            } else {
                active_initial = inverse_initial;
                searching_inverse = true;
            }
        } else if (solution && searching_inverse) {
            solution = invert_moves(*solution);
        }
        const bool stopped = control.timed_out.load() || cancelled();
        if (!solution && !stopped)
            completed_depth = depth;
        report(depth, nodes_before, split_before, iteration_started, solution.has_value());
        if (solution) {
            result.moves = *solution;
            result.depth = static_cast<int>(result.moves.size());
            result.optimal = true;
            break;
        }
        if (stopped) {
            result.cancelled = cancelled();
            result.timed_out = control.timed_out.load();
            break;
        }
    }
    if (result.depth < 0 && !incumbent.empty()) {
        if (!result.timed_out && !result.cancelled && completed_depth < static_cast<int>(incumbent.size()) - 1)
            throw std::runtime_error("no solution found within max depth");
        result.moves = incumbent;
        result.depth = static_cast<int>(incumbent.size());
        result.optimal = !result.timed_out && !result.cancelled && completed_depth >= result.depth - 1;
    }
    if (result.depth < 0 && !result.timed_out && !result.cancelled)
        throw std::runtime_error("no solution found within max depth");
    result.completed_depth = completed_depth;
    result.nodes = control.nodes.load();
    result.split_nodes = control.split_nodes.load();
    result.transposition_hits = control.transposition_hits.load();
    result.tail_queries = control.tail_queries.load();
    result.tail_bloom_rejects = control.tail_bloom_rejects.load();
    result.tail_exact_queries = control.tail_exact_queries.load();
    result.tail_probes = control.tail_probes.load();
    result.tail_hits = control.tail_hits.load();
    result.counters = control.counters;
    result.workers = control.workers;
    result.inverse_direction = searching_inverse;
    result.elapsed_seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    return result;
}

} // namespace cube
