#include "solver.hpp"

#include "fast.hpp"
#include "pdb.hpp"
#include "strong_coords.hpp"
#include "strong_pdb.hpp"
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
#include <cctype>
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

MoveMetric parse_metric(const std::string &value) {
    std::string normalized = value;
    std::transform(normalized.begin(), normalized.end(), normalized.begin(),
                   [](unsigned char character) { return static_cast<char>(std::toupper(character)); });
    if (normalized == "HTM")
        return MoveMetric::HTM;
    if (normalized == "QTM")
        return MoveMetric::QTM;
    throw std::invalid_argument("metric must be HTM or QTM");
}

const char *metric_name(MoveMetric metric) noexcept { return metric == MoveMetric::QTM ? "QTM" : "HTM"; }

int move_cost(int move, MoveMetric metric) {
    if (move < 0 || move >= 18)
        throw std::invalid_argument("invalid move index");
    return metric == MoveMetric::QTM && move % 3 == 1 ? 2 : 1;
}

int solution_cost(std::span<const int> moves, MoveMetric metric) {
    int cost = 0;
    for (int move : moves)
        cost += move_cost(move, metric);
    return cost;
}

int default_max_depth(MoveMetric metric) noexcept { return metric == MoveMetric::QTM ? 26 : 20; }

namespace {

constexpr int kMoveCount = 18;
constexpr int kTwistCount = 2187;
constexpr int kFlipCount = 2048;
constexpr int kSliceCount = 495;
constexpr int kCornerPermCount = 40320;
constexpr int kMoveOrderingMinRemaining = 12;
constexpr std::uint8_t kUnknown = 255;
constexpr std::uint64_t kSolvedEdges = 0xBA9876543210ULL;

constexpr std::size_t metric_slot(MoveMetric metric) noexcept { return metric == MoveMetric::QTM ? 1U : 0U; }

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
    target.strong_queries += source.strong_queries;
    target.strong_prefetches += source.strong_prefetches;
    target.slice_updates += source.slice_updates;
    target.slice_updates_skipped += source.slice_updates_skipped;
    target.tt_keys += source.tt_keys;
    target.tt_lookups += source.tt_lookups;
    target.tt_stores += source.tt_stores;
    for (int i = 0; i < 3; ++i)
        target.axis_rejects[i] += source.axis_rejects[i];
    target.equality_rejects += source.equality_rejects;
    target.strong_equality_rejects += source.strong_equality_rejects;
    target.dual_queries += source.dual_queries;
    target.dual_rejects += source.dual_rejects;
    target.bpmx_rejects += source.bpmx_rejects;
    target.corner_rejects += source.corner_rejects;
    target.edge_rejects += source.edge_rejects;
    target.strong_rejects += source.strong_rejects;
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
                                           const std::vector<std::uint16_t> &move_b,
                                           MoveMetric metric = MoveMetric::HTM) {
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
            if (metric == MoveMetric::QTM && move % 3 == 1)
                continue;
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

std::vector<std::uint8_t> build_single_prune(int size, int solved, const std::vector<std::uint16_t> &moves,
                                             MoveMetric metric = MoveMetric::HTM) {
    std::vector<std::uint8_t> table(size, kUnknown);
    table[solved] = 0;
    std::deque<std::uint32_t> queue{static_cast<std::uint32_t>(solved)};
    while (!queue.empty()) {
        const std::uint32_t coordinate = queue.front();
        queue.pop_front();
        const std::uint8_t next_depth = static_cast<std::uint8_t>(table[coordinate] + 1);
        for (int move = 0; move < kMoveCount; ++move) {
            if (metric == MoveMetric::QTM && move % 3 == 1)
                continue;
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

    void clear() noexcept { std::fill(entries_.begin(), entries_.end(), Entry{}); }

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
    std::uint8_t heuristic{};
    std::vector<int> path;
};

struct SearchControl {
    std::atomic<bool> stop{false};
    std::atomic<bool> timed_out{false};
    std::atomic<bool> shortened_by_candidate{false};
    std::atomic<double> proof_worker_return_seconds{-1.0};
    std::chrono::steady_clock::time_point started_at;
    const std::atomic<int> *candidate_cost{nullptr};
    int current_depth{};
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
    std::vector<int> path;
    int index{};

    void reset_for_layer() {
        pending_nodes = 0;
        split_nodes = 0;
        transposition_hits = 0;
        tail_counters = {};
        counters = {};
        statistics = {};
        path.clear();
        if (transposition)
            transposition->clear();
    }
};

class PersistentWorkerPool {
  public:
    PersistentWorkerPool(int count, const SolverOptions &options) {
        contexts_.reserve(count);
        for (int index = 0; index < count; ++index) {
            const auto memory_bounded_entries =
                std::min<std::size_t>(options.transposition_limit_per_thread, (512ULL << 20U) / (32ULL * count));
            auto context = std::make_unique<WorkerContext>(memory_bounded_entries, options.use_transposition);
            context->index = index;
            context->path.reserve(32);
            contexts_.push_back(std::move(context));
        }
        for (int index = 0; index < count; ++index) {
            threads_.emplace_back([this, index] {
                std::uint64_t observed_generation = 0;
                bool ran_this_generation = false;
                while (true) {
                    std::function<void(int)> task;
                    {
                        std::unique_lock lock(mutex_);
                        work_ready_.wait(lock, [&] {
                            return closing_ || generation_ != observed_generation ||
                                   (!ran_this_generation && index < active_count_);
                        });
                        if (closing_)
                            return;
                        if (generation_ != observed_generation) {
                            observed_generation = generation_;
                            ran_this_generation = false;
                        }
                        if (index >= active_count_ || ran_this_generation)
                            continue;
                        ran_this_generation = true;
                        task = task_;
                    }
                    task(index);
                    {
                        std::lock_guard lock(mutex_);
                        ++finished_;
                    }
                    work_finished_.notify_one();
                }
            });
        }
    }

    PersistentWorkerPool(const PersistentWorkerPool &) = delete;
    PersistentWorkerPool &operator=(const PersistentWorkerPool &) = delete;

    ~PersistentWorkerPool() {
        {
            std::lock_guard lock(mutex_);
            closing_ = true;
        }
        work_ready_.notify_all();
        for (auto &thread : threads_)
            thread.join();
    }

    WorkerContext &context(int index) noexcept { return *contexts_[index]; }
    int capacity() const noexcept { return static_cast<int>(contexts_.size()); }

    int active_count() {
        std::lock_guard lock(mutex_);
        return active_count_;
    }

    bool activate_one() {
        {
            std::lock_guard lock(mutex_);
            if (active_count_ >= capacity() || !task_)
                return false;
            ++active_count_;
        }
        work_ready_.notify_all();
        return true;
    }

    void run(const std::function<void(int)> &task, int active_count, const std::function<void()> &snapshot) {
        {
            std::lock_guard lock(mutex_);
            task_ = task;
            active_count_ = active_count;
            finished_ = 0;
            ++generation_;
        }
        work_ready_.notify_all();
        std::unique_lock lock(mutex_);
        while (finished_ < active_count_) {
            if (work_finished_.wait_for(lock, std::chrono::milliseconds(250),
                                        [&] { return finished_ == active_count_; }))
                break;
            lock.unlock();
            if (snapshot)
                snapshot();
            lock.lock();
        }
        task_ = {};
    }

  private:
    std::mutex mutex_;
    std::condition_variable work_ready_;
    std::condition_variable work_finished_;
    std::vector<std::unique_ptr<WorkerContext>> contexts_;
    std::vector<std::thread> threads_;
    std::function<void(int)> task_;
    std::uint64_t generation_{0};
    int active_count_{0};
    int finished_{0};
    bool closing_{false};
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
    if ((worker.pending_nodes & 1023U) == 0 && control.candidate_cost != nullptr &&
        control.candidate_cost->load(std::memory_order_relaxed) <= control.current_depth) {
        control.shortened_by_candidate.store(true, std::memory_order_relaxed);
        control.stop.store(true, std::memory_order_relaxed);
        return true;
    }
    if ((worker.pending_nodes & 1023U) == 0 && std::chrono::steady_clock::now() >= control.deadline) {
        control.timed_out.store(true, std::memory_order_relaxed);
        control.stop.store(true, std::memory_order_relaxed);
        return true;
    }
    if (worker.pending_nodes >= 4096)
        publish(control, worker);
    return false;
}

int dual_bound(const CoordinateTables &tables, const CoordinateState &state, const Phase1PatternDatabase *phase1_pdb,
               const CornerPatternDatabase *corner_pdb, const CoordinateFeatures &features) noexcept {
    // Cubie reconstruction uses stack arrays only. Inversion changes the side
    // on which moves act, so inverse coordinates are extracted afresh rather
    // than updated with the forward right-multiplication tables.
    const CubieCube inverse = tables.materialize(state).inverse();
    const auto twist = twist_coord(inverse);
    const auto flip = flip_coord(inverse);
    int bound = 0;
    if (phase1_pdb)
        bound = std::max<int>(bound, phase1_pdb->distance(twist, flip, slice_comb_coord(inverse)));
    if (corner_pdb)
        bound = std::max<int>(
            bound, corner_pdb->distance(static_cast<std::uint32_t>(corner_perm_coord(inverse)) * kTwistCount + twist));
    if (features.strong_pdb)
        bound = std::max<int>(bound, features.strong_pdb->distance(twist, flip, sorted_slice_coord(inverse),
                                                                   features.affine_coordinates));
    return bound;
}

int maybe_dual_bound(const CoordinateTables &tables, const CoordinateState &state, int bound, int remaining,
                     const Phase1PatternDatabase *phase1_pdb, const CornerPatternDatabase *corner_pdb,
                     const CoordinateFeatures &features, const SolverOptions &options,
                     SearchCounters &counters) noexcept {
    if (features.metric != MoveMetric::QTM || options.dual_policy == DualPolicy::Off ||
        options.dual_policy == DualPolicy::Root ||
        (options.dual_policy == DualPolicy::Selective && remaining - bound > 2))
        return bound;
    ++counters.dual_queries;
    bound = std::max(bound, dual_bound(tables, state, phase1_pdb, corner_pdb, features));
    if (bound > remaining)
        ++counters.dual_rejects;
    return bound;
}

bool depth_first_search(const CoordinateTables &tables, const Phase1PatternDatabase *phase1_pdb,
                        const CornerPatternDatabase *corner_pdb, std::span<const EdgePatternDatabase *const> edge_pdbs,
                        const TailDatabase *tail_database, const CoordinateFeatures &features,
                        const SolverOptions &options, const CoordinateState &state, int depth_left, int last_face,
                        std::vector<int> &path, SearchControl &control, WorkerContext &worker,
                        int known_heuristic = -1) {
    ++worker.pending_nodes;
    if (check_stop(control, worker))
        return false;
    int propagated_heuristic =
        known_heuristic >= 0 ? known_heuristic
                             : tables.heuristic(state, phase1_pdb, corner_pdb, edge_pdbs,
                                                static_cast<std::uint8_t>(depth_left), features, &worker.counters);
    if (propagated_heuristic > depth_left) {
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
    const bool tt_active =
        worker.transposition != nullptr &&
        (!options.selective_transposition ||
         (depth_left >= 10 && tables.heuristic(state, phase1_pdb, corner_pdb, edge_pdbs,
                                               static_cast<std::uint8_t>(depth_left - 2), features, &worker.counters) +
                                      2 <=
                                  depth_left));
    if (tt_active) {
        ++worker.counters.tt_keys;
        key = state_key(tables.materialize(state), last_face);
        ++worker.counters.tt_lookups;
        if (worker.transposition->contains_at_least(key, static_cast<std::uint8_t>(depth_left))) {
            ++worker.transposition_hits;
            return false;
        }
    }

    if (depth_left >= kMoveOrderingMinRemaining) {
        struct Candidate {
            CoordinateState state;
            int move{};
            int face{};
            int remaining{};
            std::uint8_t heuristic{};
        };
        std::array<Candidate, 18> candidates{};
        std::size_t candidate_count = 0;
        for (int move = 0; move < kMoveCount; ++move) {
            const int face = move / 3;
            if (should_skip_face(last_face, face))
                continue;
            const int next_depth = depth_left - options.move_costs[move];
            if (next_depth < 0)
                continue;
            CoordinateState child;
            int child_heuristic = tables.expand(state, move, child, phase1_pdb, corner_pdb, edge_pdbs,
                                                static_cast<std::uint8_t>(next_depth), features, worker.counters);
            if (child_heuristic <= next_depth)
                child_heuristic = maybe_dual_bound(tables, child, child_heuristic, next_depth, phase1_pdb, corner_pdb,
                                                   features, options, worker.counters);
            if (options.bpmx) {
                propagated_heuristic = std::max(propagated_heuristic, child_heuristic - options.move_costs[move]);
                if (propagated_heuristic > depth_left) {
                    ++worker.counters.bpmx_rejects;
                    return false;
                }
                child_heuristic = std::max<int>(child_heuristic, propagated_heuristic - options.move_costs[move]);
            }
            if (child_heuristic > next_depth)
                continue;
            candidates[candidate_count++] =
                Candidate{std::move(child), move, face, next_depth, static_cast<std::uint8_t>(child_heuristic)};
        }
        std::stable_sort(candidates.begin(), candidates.begin() + candidate_count,
                         [&](const Candidate &left, const Candidate &right) {
                             return left.heuristic + options.move_costs[left.move] <
                                    right.heuristic + options.move_costs[right.move];
                         });
        for (std::size_t candidate_index = 0; candidate_index < candidate_count; ++candidate_index) {
            const Candidate &candidate = candidates[candidate_index];
            path.push_back(candidate.move);
            if (depth_first_search(tables, phase1_pdb, corner_pdb, edge_pdbs, tail_database, features, options,
                                   candidate.state, candidate.remaining, candidate.face, path, control, worker,
                                   candidate.heuristic)) {
                return true;
            }
            path.pop_back();
            if (control.stop.load(std::memory_order_relaxed))
                return false;
        }
        if (tt_active) {
            ++worker.counters.tt_stores;
            worker.transposition->store(key, static_cast<std::uint8_t>(depth_left));
        }
        return false;
    }

    for (int move = 0; move < kMoveCount; ++move) {
        const int face = move / 3;
        if (should_skip_face(last_face, face))
            continue;
        const int next_depth = depth_left - options.move_costs[move];
        if (next_depth < 0)
            continue;
        CoordinateState child;
        int child_heuristic = tables.expand(state, move, child, phase1_pdb, corner_pdb, edge_pdbs,
                                            static_cast<std::uint8_t>(next_depth), features, worker.counters);
        if (child_heuristic <= next_depth)
            child_heuristic = maybe_dual_bound(tables, child, child_heuristic, next_depth, phase1_pdb, corner_pdb,
                                               features, options, worker.counters);
        if (options.bpmx) {
            propagated_heuristic = std::max(propagated_heuristic, child_heuristic - options.move_costs[move]);
            if (propagated_heuristic > depth_left) {
                ++worker.counters.bpmx_rejects;
                return false;
            }
            child_heuristic = std::max<int>(child_heuristic, propagated_heuristic - options.move_costs[move]);
        }
        if (child_heuristic > next_depth)
            continue;
        path.push_back(move);
        if (depth_first_search(tables, phase1_pdb, corner_pdb, edge_pdbs, tail_database, features, options, child,
                               next_depth, face, path, control, worker, child_heuristic)) {
            return true;
        }
        path.pop_back();
        if (control.stop.load(std::memory_order_relaxed))
            return false;
    }

    if (tt_active) {
        ++worker.counters.tt_stores;
        worker.transposition->store(key, static_cast<std::uint8_t>(depth_left));
    }
    return false;
}

std::vector<SearchTask> split_task(const CoordinateTables &tables, const Phase1PatternDatabase *phase1_pdb,
                                   const CornerPatternDatabase *corner_pdb,
                                   std::span<const EdgePatternDatabase *const> edge_pdbs,
                                   const CoordinateFeatures &features, const SolverOptions &options,
                                   const SearchTask &task, WorkerContext &worker) {
    std::vector<SearchTask> children;
    if (task.depth_left == 0)
        return children;
    std::uint64_t generated_nodes = 0;
    int propagated_heuristic = task.heuristic;
    children.reserve(18);
    for (int move = 0; move < kMoveCount; ++move) {
        const int face = move / 3;
        if (should_skip_face(task.last_face, face))
            continue;
        const int next_depth = task.depth_left - options.move_costs[move];
        if (next_depth < 0)
            continue;
        ++generated_nodes;
        CoordinateState child;
        int child_heuristic = tables.expand(task.state, move, child, phase1_pdb, corner_pdb, edge_pdbs,
                                            static_cast<std::uint8_t>(next_depth), features, worker.counters);
        if (child_heuristic <= next_depth)
            child_heuristic = maybe_dual_bound(tables, child, child_heuristic, next_depth, phase1_pdb, corner_pdb,
                                               features, options, worker.counters);
        if (options.bpmx) {
            propagated_heuristic = std::max(propagated_heuristic, child_heuristic - options.move_costs[move]);
            if (propagated_heuristic > task.depth_left) {
                ++worker.counters.bpmx_rejects;
                children.clear();
                break;
            }
            child_heuristic = std::max<int>(child_heuristic, propagated_heuristic - options.move_costs[move]);
        }
        if (child_heuristic > next_depth)
            continue;
        SearchTask child_task{std::move(child), next_depth, face, static_cast<std::uint8_t>(child_heuristic),
                              task.path};
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
                      SearchControl &control, PersistentWorkerPool &pool, const std::function<void()> &snapshot = {},
                      const std::atomic<bool> *candidate_done = nullptr) {
    struct QueueState {
        std::mutex mutex;
        std::condition_variable condition;
        std::deque<SearchTask> tasks;
        std::size_t outstanding{1};
    } queue;
    const auto root_heuristic = tables.heuristic(initial, phase1_pdb, corner_pdb, edge_pdbs, 255, features);
    queue.tasks.push_back(SearchTask{initial, depth, -1, root_heuristic, {}});
    const std::size_t target_queue = static_cast<std::size_t>(thread_count) * 64;

    control.workers.assign(static_cast<std::size_t>(pool.capacity()), {});
    auto worker_function = [&](int index) {
        WorkerContext &worker = pool.context(index);
        worker.reset_for_layer();
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
                worker.statistics.queue_lock_wait_seconds +=
                    std::chrono::duration<double>(std::chrono::steady_clock::now() - wait_started).count();
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
            ++worker.statistics.tasks;
            const auto work_started = std::chrono::steady_clock::now();

            const int split_floor = tail_database != nullptr ? tail_database->depth() : 3;
            const int slack = task.depth_left - task.heuristic;
            const bool should_split =
                options.adaptive_split
                    ? task.depth_left > split_floor + (options.metric == MoveMetric::QTM ? 1 : 0) &&
                          task.path.size() < 9 && queued_after_pop < target_queue &&
                          (queued_after_pop < static_cast<std::size_t>(thread_count * 2) || slack >= 3)
                    : task.depth_left > split_floor && task.path.size() < 7 && queued_after_pop < target_queue;
            if (should_split) {
                auto children = split_task(tables, phase1_pdb, corner_pdb, edge_pdbs, features, options, task, worker);
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
                worker.statistics.longest_task_seconds =
                    std::max(worker.statistics.longest_task_seconds,
                             std::chrono::duration<double>(std::chrono::steady_clock::now() - work_started).count());
                if (worker.split_nodes >= 4096)
                    publish(control, worker);
                continue;
            }

            auto &path = worker.path;
            path.assign(task.path.begin(), task.path.end());
            depth_first_search(tables, phase1_pdb, corner_pdb, edge_pdbs, tail_database, features, options, task.state,
                               task.depth_left, task.last_face, path, control, worker);
            {
                std::lock_guard lock(queue.mutex);
                --queue.outstanding;
            }
            queue.condition.notify_all();
            worker.statistics.busy_seconds +=
                std::chrono::duration<double>(std::chrono::steady_clock::now() - work_started).count();
            worker.statistics.longest_task_seconds =
                std::max(worker.statistics.longest_task_seconds,
                         std::chrono::duration<double>(std::chrono::steady_clock::now() - work_started).count());
        }
        publish(control, worker);
    };
    bool candidate_quota_returned = false;
    pool.run(worker_function, thread_count, [&] {
        const int candidate = candidate_done && !candidate_done->load(std::memory_order_acquire);
        const int loading = options.loader_threads_callback ? options.loader_threads_callback() : 0;
        const int target = std::max(1, pool.capacity() - candidate - loading);
        while (pool.active_count() < target && pool.activate_one()) {
        }
        if (!candidate && candidate_done && !candidate_quota_returned) {
            candidate_quota_returned = true;
            control.proof_worker_return_seconds.store(
                std::chrono::duration<double>(std::chrono::steady_clock::now() - control.started_at).count(),
                std::memory_order_relaxed);
        }
        if (options.thread_activity_callback)
            options.thread_activity_callback(loading, candidate, pool.active_count());
        if (snapshot)
            snapshot();
    });

    if (!control.solution.empty())
        return control.solution;
    return std::nullopt;
}

struct DirectionProbeSample {
    std::uint64_t generated{};
    std::uint64_t rejected{};
    bool complete{true};
    bool found{};
};

DirectionProbeSample sample_direction(const CoordinateTables &tables, const CoordinateState &initial,
                                      const Phase1PatternDatabase *phase1_pdb, const CornerPatternDatabase *corner_pdb,
                                      std::span<const EdgePatternDatabase *const> edge_pdbs,
                                      const CoordinateFeatures &features, const SolverOptions &options, int depth,
                                      std::uint64_t node_limit, std::chrono::steady_clock::time_point deadline) {
    DirectionProbeSample sample;
    SearchCounters counters;
    const auto walk = [&](const auto &self, const CoordinateState &state, int remaining, int last_face) -> bool {
        if (sample.generated >= node_limit ||
            ((sample.generated & 255ULL) == 0 && std::chrono::steady_clock::now() >= deadline)) {
            sample.complete = false;
            return false;
        }
        if (solved(state)) {
            sample.found = true;
            sample.complete = false;
            return false;
        }
        if (remaining == 0)
            return true;
        for (int move = 0; move < kMoveCount; ++move) {
            const int face = move / 3;
            if (should_skip_face(last_face, face))
                continue;
            const int next = remaining - options.move_costs[move];
            if (next < 0)
                continue;
            CoordinateState child;
            const auto bound = tables.expand(state, move, child, phase1_pdb, corner_pdb, edge_pdbs,
                                             static_cast<std::uint8_t>(next), features, counters);
            ++sample.generated;
            if (bound > next) {
                ++sample.rejected;
                continue;
            }
            if (!self(self, child, next, face))
                return false;
        }
        return true;
    };
    walk(walk, initial, depth, -1);
    return sample;
}

} // namespace

CoordinateTables::CoordinateTables() {
    const wchar_t *configured_cache = _wgetenv(L"CUBE_NATIVE_COORDINATE_CACHE");
    const std::filesystem::path cache = configured_cache ? configured_cache : L".cache/native/coordinates_dual_v2.bin";
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
    qtm_twist_slice_prune_ =
        build_pair_prune(kTwistCount, kSliceCount, 0, solved_slice, twist_move_, slice_move_, MoveMetric::QTM);
    qtm_flip_slice_prune_ =
        build_pair_prune(kFlipCount, kSliceCount, 0, solved_slice, flip_move_, slice_move_, MoveMetric::QTM);
    qtm_twist_flip_prune_ = build_pair_prune(kTwistCount, kFlipCount, 0, 0, twist_move_, flip_move_, MoveMetric::QTM);
    qtm_corner_prune_ = build_single_prune(kCornerPermCount, 0, corner_move_, MoveMetric::QTM);
    if (!cache.empty())
        save_cache(cache);
}

namespace {
constexpr std::uint64_t kCoordinateCacheVersion = 0x324C415543524F43ULL;
constexpr std::size_t kCoordinateCacheBytes =
    (kTwistCount + kFlipCount + kSliceCount + kCornerPermCount) * kMoveCount * sizeof(std::uint16_t) +
    2 * (kTwistCount * kSliceCount + kFlipCount * kSliceCount + kTwistCount * kFlipCount + kCornerPermCount);

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
    read(qtm_twist_slice_prune_, kTwistCount * kSliceCount);
    read(qtm_flip_slice_prune_, kFlipCount * kSliceCount);
    read(qtm_twist_flip_prune_, kTwistCount * kFlipCount);
    read(qtm_corner_prune_, kCornerPermCount);
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
        append(qtm_twist_slice_prune_);
        append(qtm_flip_slice_prune_);
        append(qtm_twist_flip_prune_);
        append(qtm_corner_prune_);
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
    if (features.strong_pdb)
        result.sorted_slice = sorted_slice_coord(cube);
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
            if (features.strong_pdb)
                result.axis_sorted_slice[axis] = sorted_slice_coord(rotated);
        }
    }
    return result;
}

CubieCube CoordinateTables::materialize(const CoordinateState &state) const noexcept {
    CubieCube result;
    std::uint16_t rank = state.corner_perm;
    std::array<std::uint8_t, 8> digits{};
    std::array<std::uint8_t, 8> available{0, 1, 2, 3, 4, 5, 6, 7};
    for (int index = 7; index >= 0; --index) {
        const int base = 8 - index;
        digits[index] = static_cast<std::uint8_t>(rank % base);
        rank = static_cast<std::uint16_t>(rank / base);
    }
    for (int index = 0; index < 8; ++index) {
        const int digit = digits[index];
        result.cp[index] = available[digit];
        for (int cursor = digit; cursor < 7 - index; ++cursor)
            available[cursor] = available[cursor + 1];
    }
    result.co = cube_from_twist(state.twist).co;
    result.eo = cube_from_flip(state.flip).eo;
    for (int i = 0; i < 12; ++i)
        result.ep[i] = static_cast<std::uint8_t>((state.edges >> (i * 4)) & 0xFULL);
    return result;
}

CoordinateState CoordinateTables::moved(const CoordinateState &state, int move,
                                        const CoordinateFeatures &features) const noexcept {
    CoordinateState result{move_edges(state.edges, move), twist_move(state.twist, move), flip_move(state.flip, move),
                           features.maintain_slice ? slice_move(state.slice, move) : std::uint16_t{0},
                           corner_move(state.corner_perm, move)};
    if (features.strong_pdb)
        result.sorted_slice = features.strong_pdb->sorted_move(state.sorted_slice, move);
    if (features.edge_pattern_a)
        result.edge_pattern_a = move_edge_pattern(state.edge_pattern_a, move);
    if (features.edge_pattern_b)
        result.edge_pattern_b = move_edge_pattern(state.edge_pattern_b, move);
    if (features.axis_coordinates) {
        for (int axis = 0; axis < kAxisRotationCount; ++axis) {
            const int mapped = axis_rotation_move_maps()[axis][move];
            result.axis_twist[axis] = twist_move(state.axis_twist[axis], mapped);
            result.axis_flip[axis] = flip_move(state.axis_flip[axis], mapped);
            if (features.maintain_slice)
                result.axis_slice[axis] = slice_move(state.axis_slice[axis], mapped);
            if (features.strong_pdb)
                result.axis_sorted_slice[axis] =
                    features.strong_pdb->sorted_move(state.axis_sorted_slice[axis], mapped);
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
        if (features.maintain_slice) {
            state.slice = slice_move(parent->slice, move);
            ++counters.slice_updates;
        } else
            ++counters.slice_updates_skipped;
    }
    std::uint8_t result = 0;
    const auto &twist_slice = features.metric == MoveMetric::QTM ? qtm_twist_slice_prune_ : twist_slice_prune_;
    const auto &flip_slice = features.metric == MoveMetric::QTM ? qtm_flip_slice_prune_ : flip_slice_prune_;
    const auto &twist_flip = features.metric == MoveMetric::QTM ? qtm_twist_flip_prune_ : twist_flip_prune_;
    const auto &corner = features.metric == MoveMetric::QTM ? qtm_corner_prune_ : corner_prune_;
    if (features.small_phase1 || phase1_pdb == nullptr) {
        counters.small_queries += 3;
        result = std::max({twist_slice[static_cast<std::size_t>(state.twist) * kSliceCount + state.slice],
                           flip_slice[static_cast<std::size_t>(state.flip) * kSliceCount + state.slice],
                           twist_flip[static_cast<std::size_t>(state.twist) * kFlipCount + state.flip]});
        if (result > cutoff) {
            ++counters.axis_rejects[0];
            return result;
        }
    }
    const bool alternative_order = features.strong_pdb != nullptr && features.query_order != PdbQueryOrder::Legacy;
    if (alternative_order) {
        std::array<std::uint8_t, 3> phase_values{};
        std::array<std::uint8_t, 3> strong_values{};
        std::array<bool, 2> axis_ready{};
        const auto ensure_axis = [&](int axis) {
            if (axis == 0 || parent == nullptr || axis_ready[axis - 1])
                return;
            const int mapped = axis_rotation_move_maps()[axis - 1][move];
            state.axis_twist[axis - 1] = twist_move(parent->axis_twist[axis - 1], mapped);
            state.axis_flip[axis - 1] = flip_move(parent->axis_flip[axis - 1], mapped);
            if (features.maintain_slice) {
                state.axis_slice[axis - 1] = slice_move(parent->axis_slice[axis - 1], mapped);
                ++counters.slice_updates;
            } else
                ++counters.slice_updates_skipped;
            axis_ready[axis - 1] = true;
        };
        const auto query_phase = [&](int axis) {
            ensure_axis(axis);
            ++counters.phase1_queries;
            phase_values[axis] = axis == 0 ? phase1_pdb->distance(state.twist, state.flip, state.slice)
                                           : phase1_pdb->distance(state.axis_twist[axis - 1], state.axis_flip[axis - 1],
                                                                  state.axis_slice[axis - 1]);
            result = std::max(result, phase_values[axis]);
            if (result > cutoff) {
                ++counters.axis_rejects[axis];
                return false;
            }
            return true;
        };
        const auto query_strong = [&](int axis) {
            ensure_axis(axis);
            if (parent != nullptr) {
                if (axis == 0)
                    state.sorted_slice = features.strong_pdb->sorted_move(parent->sorted_slice, move);
                else {
                    const int mapped = axis_rotation_move_maps()[axis - 1][move];
                    state.axis_sorted_slice[axis - 1] =
                        features.strong_pdb->sorted_move(parent->axis_sorted_slice[axis - 1], mapped);
                }
            }
            ++counters.strong_queries;
            if (features.prefetch_strong) {
                const auto index = axis == 0
                                       ? features.strong_pdb->prepare_index(state.twist, state.flip, state.sorted_slice,
                                                                            features.affine_coordinates)
                                       : features.strong_pdb->prepare_index(
                                             state.axis_twist[axis - 1], state.axis_flip[axis - 1],
                                             state.axis_sorted_slice[axis - 1], features.affine_coordinates);
                features.strong_pdb->prefetch(index);
                ++counters.strong_prefetches;
                strong_values[axis] = features.strong_pdb->load_distance(index);
            } else
                strong_values[axis] =
                    axis == 0
                        ? features.strong_pdb->distance(state.twist, state.flip, state.sorted_slice,
                                                        features.affine_coordinates)
                        : features.strong_pdb->distance(state.axis_twist[axis - 1], state.axis_flip[axis - 1],
                                                        state.axis_sorted_slice[axis - 1], features.affine_coordinates);
            result = std::max(result, strong_values[axis]);
            if (result > cutoff) {
                ++counters.strong_rejects;
                return false;
            }
            return true;
        };
        const bool skip_phase = features.query_order == PdbQueryOrder::StrongFirst && features.strong_pdb->complete();
        if (features.query_order == PdbQueryOrder::Interleaved) {
            for (int axis = 0; axis < 3; ++axis) {
                if (phase1_pdb && !query_phase(axis))
                    return result;
                if (!query_strong(axis))
                    return result;
            }
        } else {
            for (int axis = 0; axis < 3; ++axis)
                if (!query_strong(axis))
                    return result;
            if (phase1_pdb && !skip_phase)
                for (int axis = 0; axis < 3; ++axis)
                    if (!query_phase(axis))
                        return result;
        }
        if (phase1_pdb && !skip_phase && features.strengthen_axes &&
            (features.metric != MoveMetric::QTM || features.qtm_phase1_axis_rule) && phase_values[0] > 0 &&
            phase_values[0] == phase_values[1] && phase_values[1] == phase_values[2]) {
            result = std::max(result, static_cast<std::uint8_t>(phase_values[0] + 1));
            if (result > cutoff) {
                ++counters.equality_rejects;
                return result;
            }
        }
        if (features.metric == MoveMetric::QTM && features.strengthen_axes && features.qtm_strong_axis_rule &&
            strong_values[0] > 0 && strong_values[0] == strong_values[1] && strong_values[1] == strong_values[2]) {
            result = std::max(result, static_cast<std::uint8_t>(strong_values[0] + 1));
            if (result > cutoff) {
                ++counters.strong_equality_rejects;
                return result;
            }
        }
        if (parent != nullptr)
            state.corner_perm = corner_move(parent->corner_perm, move);
        if (features.small_corner || corner_pdb == nullptr) {
            ++counters.small_queries;
            result = std::max(result, corner[state.corner_perm]);
            if (result > cutoff) {
                ++counters.corner_rejects;
                return result;
            }
        }
        if (corner_pdb != nullptr) {
            ++counters.corner_queries;
            result = std::max(result, corner_pdb->distance(static_cast<std::uint32_t>(state.corner_perm) * kTwistCount +
                                                           state.twist));
            if (result > cutoff) {
                ++counters.corner_rejects;
                return result;
            }
        }
    }
    if (!alternative_order) {
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
            // Expand a QTM solution into unit quarter turns. Just before its last
            // turn, one axis projection is already at its abstract goal: that
            // last face turn belongs to the corresponding goal subgroup. Thus a
            // solution of cost L gives at least one axis bound <= L-1. If all
            // three bounds equal n>0, the full cost is at least n+1.
            if (features.strengthen_axes && (features.metric != MoveMetric::QTM || features.qtm_phase1_axis_rule) &&
                axis_values[0] > 0 && axis_values[0] == axis_values[1] && axis_values[1] == axis_values[2]) {
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
            result = std::max(result, corner[state.corner_perm]);
            if (result > cutoff) {
                ++counters.corner_rejects;
                return result;
            }
        }
        if (corner_pdb != nullptr) {
            ++counters.corner_queries;
            result = std::max(result, corner_pdb->distance(static_cast<std::uint32_t>(state.corner_perm) * kTwistCount +
                                                           state.twist));
            if (result > cutoff) {
                ++counters.corner_rejects;
                return result;
            }
        }
        if (features.strong_pdb != nullptr) {
            if (parent != nullptr) {
                state.sorted_slice = features.strong_pdb->sorted_move(parent->sorted_slice, move);
            }
            std::array<std::uint64_t, 3> prefetched_indices{};
            if (features.prefetch_strong) {
                for (int axis = 0; axis < kAxisRotationCount; ++axis) {
                    if (parent != nullptr) {
                        const int mapped = axis_rotation_move_maps()[axis][move];
                        if (phase1_pdb == nullptr) {
                            state.axis_twist[axis] = twist_move(parent->axis_twist[axis], mapped);
                            state.axis_flip[axis] = flip_move(parent->axis_flip[axis], mapped);
                            state.axis_slice[axis] = slice_move(parent->axis_slice[axis], mapped);
                        }
                        state.axis_sorted_slice[axis] =
                            features.strong_pdb->sorted_move(parent->axis_sorted_slice[axis], mapped);
                    }
                }
                prefetched_indices[0] = features.strong_pdb->prepare_index(state.twist, state.flip, state.sorted_slice,
                                                                           features.affine_coordinates);
                for (int axis = 0; axis < kAxisRotationCount; ++axis)
                    prefetched_indices[axis + 1] =
                        features.strong_pdb->prepare_index(state.axis_twist[axis], state.axis_flip[axis],
                                                           state.axis_sorted_slice[axis], features.affine_coordinates);
                for (const auto index : prefetched_indices) {
                    features.strong_pdb->prefetch(index);
                    ++counters.strong_prefetches;
                }
            }
            std::array<std::uint8_t, 3> strong_axis_values{};
            ++counters.strong_queries;
            strong_axis_values[0] = features.prefetch_strong
                                        ? features.strong_pdb->load_distance(prefetched_indices[0])
                                        : features.strong_pdb->distance(state.twist, state.flip, state.sorted_slice,
                                                                        features.affine_coordinates);
            result = std::max(result, strong_axis_values[0]);
            if (result > cutoff) {
                ++counters.strong_rejects;
                return result;
            }
            for (int axis = 0; axis < kAxisRotationCount; ++axis) {
                if (parent != nullptr && !features.prefetch_strong) {
                    const int mapped = axis_rotation_move_maps()[axis][move];
                    if (phase1_pdb == nullptr) {
                        state.axis_twist[axis] = twist_move(parent->axis_twist[axis], mapped);
                        state.axis_flip[axis] = flip_move(parent->axis_flip[axis], mapped);
                        state.axis_slice[axis] = slice_move(parent->axis_slice[axis], mapped);
                    }
                    state.axis_sorted_slice[axis] =
                        features.strong_pdb->sorted_move(parent->axis_sorted_slice[axis], mapped);
                }
                ++counters.strong_queries;
                strong_axis_values[axis + 1] =
                    features.prefetch_strong
                        ? features.strong_pdb->load_distance(prefetched_indices[axis + 1])
                        : features.strong_pdb->distance(state.axis_twist[axis], state.axis_flip[axis],
                                                        state.axis_sorted_slice[axis], features.affine_coordinates);
                result = std::max(result, strong_axis_values[axis + 1]);
                if (result > cutoff) {
                    ++counters.strong_rejects;
                    return result;
                }
            }
            // The sorted-slice target for an axis consists of the four edges in
            // the plane perpendicular to it, including their order. From the
            // solved cube, a quarter turn about that axis leaves this target,
            // twist and flip at their goals. Apply the last-turn argument above;
            // arbitrary forward right moves need not preserve the projection.
            if (features.metric == MoveMetric::QTM && features.strengthen_axes && features.qtm_strong_axis_rule &&
                strong_axis_values[0] > 0 && strong_axis_values[0] == strong_axis_values[1] &&
                strong_axis_values[1] == strong_axis_values[2]) {
                result = std::max(result, static_cast<std::uint8_t>(strong_axis_values[0] + 1));
                if (result > cutoff) {
                    ++counters.strong_equality_rejects;
                    return result;
                }
            }
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

void NativeOptimalSolver::load_corner_pdb(const std::filesystem::path &path, std::optional<MoveMetric> expected) {
    auto database = std::make_shared<CornerPatternDatabase>(path);
    if (expected && database->metric() != *expected)
        throw std::invalid_argument("corner PDB metric does not match its asset flag");
    corner_pdbs_[metric_slot(database->metric())] = std::move(database);
}

void NativeOptimalSolver::load_phase1_pdb(const std::filesystem::path &path, std::optional<MoveMetric> expected) {
    auto database = std::make_shared<Phase1PatternDatabase>(path);
    if (expected && database->metric() != *expected)
        throw std::invalid_argument("phase-1 PDB metric does not match its asset flag");
    phase1_pdbs_[metric_slot(database->metric())] = std::move(database);
}

void NativeOptimalSolver::load_edge_pdb(int group, const std::filesystem::path &path,
                                        std::optional<MoveMetric> expected) {
    if (group < 0 || group >= static_cast<int>(edge_pdbs_[0].size())) {
        throw std::invalid_argument("edge PDB group must be 0..7");
    }
    auto database = std::make_shared<EdgePatternDatabase>(path, group);
    if (expected && database->metric() != *expected)
        throw std::invalid_argument("edge PDB metric does not match its asset flag");
    edge_pdbs_[metric_slot(database->metric())][group] = std::move(database);
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

void NativeOptimalSolver::load_tail_database(const std::filesystem::path &path, MoveMetric expected_metric,
                                             LoaderControl *loader) {
    auto database = std::make_shared<TailDatabase>(path, loader);
    if (database->metric() != expected_metric)
        throw std::invalid_argument("tail database metric does not match its asset flag");
    tail_databases_[metric_slot(database->metric())] = std::move(database);
}

void NativeOptimalSolver::load_strong_pdb(const std::filesystem::path &path, LoaderControl *loader) {
    strong_pdb_ = std::make_shared<StrongPatternDatabase>(path, loader);
}

bool NativeOptimalSolver::has_corner_pdb(MoveMetric metric) const noexcept {
    return static_cast<bool>(corner_pdbs_[metric_slot(metric)]) || static_cast<bool>(corner_pdbs_[0]);
}

bool NativeOptimalSolver::has_phase1_pdb(MoveMetric metric) const noexcept {
    return static_cast<bool>(phase1_pdbs_[metric_slot(metric)]) || static_cast<bool>(phase1_pdbs_[0]);
}

bool NativeOptimalSolver::has_edge_pdbs(MoveMetric metric) const noexcept {
    return (edge_pdbs_[metric_slot(metric)][0] || edge_pdbs_[0][0]) &&
           (edge_pdbs_[metric_slot(metric)][1] || edge_pdbs_[0][1]);
}

bool NativeOptimalSolver::has_extra_edge_pdbs(MoveMetric metric) const noexcept { return edge_pdb_count(metric) > 2; }

int NativeOptimalSolver::edge_pdb_count(MoveMetric metric) const noexcept {
    int count = 0;
    for (std::size_t group = 0; group < edge_pdbs_[0].size(); ++group)
        count += static_cast<bool>(edge_pdbs_[metric_slot(metric)][group] || edge_pdbs_[0][group]);
    return count;
}

bool NativeOptimalSolver::has_tail_database(MoveMetric metric) const noexcept {
    return static_cast<bool>(tail_databases_[metric_slot(metric)]);
}

int NativeOptimalSolver::tail_database_depth(MoveMetric metric) const noexcept {
    const auto &tail = tail_databases_[metric_slot(metric)];
    return tail ? tail->depth() : 0;
}

bool NativeOptimalSolver::has_strong_pdb(MoveMetric metric) const noexcept {
    return metric == MoveMetric::QTM && static_cast<bool>(strong_pdb_);
}

MoveMetric NativeOptimalSolver::corner_pdb_metric(MoveMetric metric) const noexcept {
    return corner_pdbs_[metric_slot(metric)] ? metric : MoveMetric::HTM;
}

MoveMetric NativeOptimalSolver::phase1_pdb_metric(MoveMetric metric) const noexcept {
    return phase1_pdbs_[metric_slot(metric)] ? metric : MoveMetric::HTM;
}

bool NativeOptimalSolver::corner_pdb_complete(MoveMetric metric) const noexcept {
    const auto &own = corner_pdbs_[metric_slot(metric)];
    const auto &fallback = corner_pdbs_[0];
    return own ? own->complete() : fallback && fallback->complete();
}

bool NativeOptimalSolver::phase1_pdb_complete(MoveMetric metric) const noexcept {
    const auto &own = phase1_pdbs_[metric_slot(metric)];
    const auto &fallback = phase1_pdbs_[0];
    return own ? own->complete() : fallback && fallback->complete();
}

const CoordinateTables &NativeOptimalSolver::coordinate_tables() const noexcept { return *tables_; }
double NativeOptimalSolver::strong_symmetry_initialization_seconds() const noexcept {
    return strong_pdb_ ? strong_pdb_->symmetry_initialization_seconds() : 0.0;
}
double NativeOptimalSolver::strong_verification_seconds() const noexcept {
    return strong_pdb_ ? strong_pdb_->verification_seconds() : 0.0;
}

NativeSolveResult NativeOptimalSolver::solve(const CubieCube &cube, const SolverOptions &requested_options) const {
    SolverOptions options = requested_options;
    for (int move = 0; move < kMoveCount; ++move)
        options.move_costs[move] = static_cast<std::uint8_t>(move_cost(move, options.metric));
    if (options.max_depth == -1)
        options.max_depth = default_max_depth(options.metric);
    if (options.max_depth < 0 || options.max_depth > default_max_depth(options.metric))
        throw std::invalid_argument("max depth must be 0.." + std::to_string(default_max_depth(options.metric)));
    if (!std::isfinite(options.timeout_seconds) || options.timeout_seconds < 0)
        throw std::invalid_argument("timeout must be finite and nonnegative (0 means unlimited)");
    const auto started = std::chrono::steady_clock::now();
    NativeSolveResult result;
    result.metric = options.metric;
    const auto slot = metric_slot(options.metric);
    const Phase1PatternDatabase *active_phase1 = (phase1_pdbs_[slot] ? phase1_pdbs_[slot] : phase1_pdbs_[0]).get();
    const CornerPatternDatabase *active_corner = (corner_pdbs_[slot] ? corner_pdbs_[slot] : corner_pdbs_[0]).get();
    const TailDatabase *active_tail = tail_databases_[slot].get();
    const StrongPatternDatabase *active_strong = options.metric == MoveMetric::QTM ? strong_pdb_.get() : nullptr;
    std::shared_ptr<const NativeOptimalSolver> active_asset_snapshot;
    if (options.asset_adopted_callback)
        options.asset_adopted_callback(*this, -1, 0.0, options.timeout_seconds, 0);
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
    for (std::size_t group = 0; group < edge_pdbs_[0].size(); ++group)
        edge_pdb_views[group] = (edge_pdbs_[slot][group] ? edge_pdbs_[slot][group] : edge_pdbs_[0][group]).get();
    CoordinateFeatures features;
    features.metric = options.metric;
    features.strong_pdb = active_strong;
    features.affine_coordinates = options.affine_coordinates;
    features.query_order = options.query_order;
    features.prefetch_strong = options.prefetch_strong;
    features.axis_coordinates = active_phase1 != nullptr || active_strong != nullptr;
    features.edge_pattern_a = edge_pdb_views[0] != nullptr;
    features.edge_pattern_b = edge_pdb_views[1] != nullptr;
    features.small_phase1 = !options.omit_covered_small_tables || !active_phase1 || !active_phase1->complete() ||
                            (options.metric == MoveMetric::QTM && active_phase1->metric() == MoveMetric::HTM);
    features.small_corner = !options.omit_covered_small_tables || !active_corner || !active_corner->complete() ||
                            (options.metric == MoveMetric::QTM && active_corner->metric() == MoveMetric::HTM);
    features.strengthen_axes = options.strengthen_axes;
    features.qtm_phase1_axis_rule = options.qtm_phase1_axis_rule;
    features.qtm_strong_axis_rule = options.qtm_strong_axis_rule;
    features.staged_expansion = options.staged_expansion;
    const auto update_slice_requirement = [&] {
        features.maintain_slice = !(options.omit_strong_slice && options.metric == MoveMetric::QTM && active_strong &&
                                    active_strong->complete() && features.query_order == PdbQueryOrder::StrongFirst &&
                                    !features.small_phase1 && active_phase1);
    };
    update_slice_requirement();
    bool searching_inverse = options.inverse_direction;
    CoordinateState forward_initial = tables_->from_cube(cube, features);
    std::optional<CoordinateState> inverse_initial;
    if (options.metric == MoveMetric::QTM || searching_inverse)
        inverse_initial = tables_->from_cube(cube.inverse(), features);
    CoordinateState active_initial = searching_inverse ? *inverse_initial : forward_initial;
    int forward_lower_bound =
        tables_->heuristic(forward_initial, active_phase1, active_corner, edge_pdb_views, 255, features);
    int inverse_lower_bound = inverse_initial ? tables_->heuristic(*inverse_initial, active_phase1, active_corner,
                                                                   edge_pdb_views, 255, features)
                                              : forward_lower_bound;
    result.direction_forward_lower_bound = forward_lower_bound;
    result.direction_inverse_lower_bound = inverse_lower_bound;
    int lower_bound = std::max(forward_lower_bound, inverse_lower_bound);
    // Each quarter turn is an odd corner permutation and costs one QTM unit;
    // a half turn is even and costs two. Hence solution cost parity is fixed.
    const bool parity_search = options.metric == MoveMetric::QTM && options.use_qtm_parity;
    const int root_parity = parity_search ? permutation_parity(cube.cp) : 0;
    if (parity_search)
        lower_bound += (lower_bound ^ root_parity) & 1;
    int effective_max = options.max_depth;
    if (!incumbent.empty())
        effective_max = std::min(effective_max, solution_cost(incumbent, options.metric) - 1);
    if (options.use_direction_probe && options.direction_policy == DirectionPolicy::Bounded && !searching_inverse &&
        inverse_initial && inverse_lower_bound > forward_lower_bound) {
        active_initial = *inverse_initial;
        searching_inverse = true;
    }
    if (options.use_direction_probe && options.direction_policy == DirectionPolicy::Bounded && !searching_inverse &&
        inverse_initial && lower_bound <= effective_max) {
        int sample_depth = std::min(effective_max, std::max(lower_bound, 17));
        if (parity_search && ((sample_depth ^ root_parity) & 1))
            --sample_depth;
        const double budget_seconds =
            options.timeout_seconds == 0 ? 0.1 : std::min(0.1, options.timeout_seconds * 0.01);
        if (sample_depth >= lower_bound && budget_seconds >= 0.005) {
            const auto probe_started = std::chrono::steady_clock::now();
            const auto half_budget = std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                std::chrono::duration<double>(budget_seconds * 0.5));
            const auto forward_probe =
                sample_direction(*tables_, forward_initial, active_phase1, active_corner, edge_pdb_views, features,
                                 options, sample_depth, 50'000, probe_started + half_budget);
            const auto inverse_probe_started = std::chrono::steady_clock::now();
            const auto inverse_probe =
                sample_direction(*tables_, *inverse_initial, active_phase1, active_corner, edge_pdb_views, features,
                                 options, sample_depth, 50'000, inverse_probe_started + half_budget);
            result.direction_probe_forward_generated = forward_probe.generated;
            result.direction_probe_inverse_generated = inverse_probe.generated;
            result.direction_probe_forward_rejected = forward_probe.rejected;
            result.direction_probe_inverse_rejected = inverse_probe.rejected;
            result.direction_probe_seconds =
                std::chrono::duration<double>(std::chrono::steady_clock::now() - probe_started).count();
            bool choose_inverse = false;
            if (inverse_probe.found != forward_probe.found)
                choose_inverse = inverse_probe.found;
            else if (inverse_probe.complete != forward_probe.complete)
                choose_inverse = inverse_probe.complete;
            else if (inverse_probe.complete && forward_probe.complete)
                choose_inverse = inverse_probe.generated < forward_probe.generated;
            else if (std::min(forward_probe.generated, inverse_probe.generated) >= 1000) {
                const double forward_reject_rate =
                    static_cast<double>(forward_probe.rejected) / forward_probe.generated;
                const double inverse_reject_rate =
                    static_cast<double>(inverse_probe.rejected) / inverse_probe.generated;
                choose_inverse = inverse_reject_rate > forward_reject_rate + 0.02;
            }
            if (choose_inverse) {
                active_initial = *inverse_initial;
                searching_inverse = true;
            }
        }
    }
    const bool probe_enabled = options.use_direction_probe && options.direction_policy == DirectionPolicy::Legacy &&
                               !searching_inverse && solution_cost(incumbent, options.metric) >= 18 &&
                               effective_max >= 17;
    const int probe_depth = probe_enabled ? std::max(lower_bound, std::min(16, effective_max - 2)) : -1;
    bool direction_probed = false;
    const int thread_count = std::clamp(
        options.threads > 0 ? options.threads : static_cast<int>(std::max(1U, std::thread::hardware_concurrency())), 1,
        64);
    PersistentWorkerPool pool(thread_count, options);
    std::mutex candidate_mutex;
    std::vector<int> native_candidate;
    std::atomic<int> best_candidate_cost{incumbent.empty() ? 100 : solution_cost(incumbent, options.metric)};
    FastCandidateResult candidate_result;
    std::atomic<bool> candidate_done{true};
    std::atomic<double> candidate_done_seconds{-1.0};
    std::atomic<bool> candidate_cancel{false};
    std::jthread candidate_thread;
    const bool can_generate_candidate = options.metric == MoveMetric::QTM && options.use_native_candidate &&
                                        active_phase1 != nullptr && active_phase1->metric() == MoveMetric::QTM &&
                                        active_phase1->complete();
    if (can_generate_candidate) {
        candidate_done.store(false, std::memory_order_relaxed);
        auto run_candidate = [&] {
            try {
                FastCandidateOptions candidate_options;
                candidate_options.timeout_seconds =
                    thread_count == 1
                        ? (options.timeout_seconds == 0 ? 0.5
                                                        : std::min(0.5, std::max(0.05, options.timeout_seconds * 0.1)))
                        : (options.timeout_seconds == 0 ? 3.0
                                                        : std::min(3.0, std::max(0.05, options.timeout_seconds * 0.6)));
                candidate_options.incumbent_cost = incumbent.empty() ? 100 : solution_cost(incumbent, MoveMetric::QTM);
                candidate_options.cancel_requested = &candidate_cancel;
                candidate_options.local_tail = active_tail;
                candidate_options.on_improved = [&](const std::vector<int> &moves) {
                    CubieCube verified = cube;
                    for (int move : moves)
                        verified = verified.apply_move(move);
                    if (!verified.solved())
                        return;
                    const int cost = solution_cost(moves, MoveMetric::QTM);
                    {
                        std::lock_guard lock(candidate_mutex);
                        native_candidate = moves;
                    }
                    best_candidate_cost.store(std::min(best_candidate_cost.load(std::memory_order_relaxed), cost),
                                              std::memory_order_relaxed);
                    if (result.first_candidate_seconds < 0)
                        result.first_candidate_seconds =
                            std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
                    if (options.candidate_callback)
                        options.candidate_callback(moves);
                };
                candidate_result = find_fast_qtm_candidate(cube, *tables_, *active_phase1, candidate_options);
            } catch (const std::exception &) {
                // Candidate generation is opportunistic; exact proof remains authoritative.
            }
            candidate_done_seconds.store(
                std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count(),
                std::memory_order_relaxed);
            candidate_done.store(true, std::memory_order_release);
        };
        if (thread_count == 1)
            run_candidate(); // A bounded pre-proof slice keeps the total thread quota at one.
        else
            candidate_thread = std::jthread(run_candidate);
    }
    auto candidate_snapshot = [&] {
        std::lock_guard lock(candidate_mutex);
        return native_candidate;
    };
    SearchControl control;
    control.started_at = started;
    control.candidate_cost = &best_candidate_cost;
    control.cancel_requested = options.cancel_requested;
    control.deadline = options.timeout_seconds == 0
                           ? std::chrono::steady_clock::time_point::max()
                           : started + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                                           std::chrono::duration<double>(options.timeout_seconds));
    int completed_depth = std::max(lower_bound - 1, options.completed_depth);
    if (parity_search && completed_depth >= lower_bound && ((completed_depth ^ root_parity) & 1) == 0)
        ++completed_depth; // The next cost has the impossible parity too.
    auto cancelled = [&] {
        return options.cancel_requested && options.cancel_requested->load(std::memory_order_relaxed);
    };
    auto report = [&](int depth, std::uint64_t nodes_before, std::uint64_t split_before,
                      std::chrono::steady_clock::time_point iteration_started, bool found = false) {
        if (!options.progress_callback)
            return;
        NativeSearchProgress progress;
        progress.metric = options.metric;
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
    int first_depth = completed_depth + 1;
    if (parity_search)
        first_depth += (first_depth ^ root_parity) & 1;
    report(first_depth, 0, 0, started);
    double interrupted_layer_seconds = 0.0;
    for (int depth = first_depth; depth <= effective_max; depth += parity_search ? 2 : 1) {
        if (options.asset_snapshot_callback) {
            auto next_snapshot = options.asset_snapshot_callback();
            if (next_snapshot && next_snapshot.get() != active_asset_snapshot.get()) {
                active_asset_snapshot = std::move(next_snapshot);
                active_tail = active_asset_snapshot->tail_databases_[slot].get();
                active_strong = options.metric == MoveMetric::QTM ? active_asset_snapshot->strong_pdb_.get() : nullptr;
                features.strong_pdb = active_strong;
                features.axis_coordinates = active_phase1 != nullptr || active_strong != nullptr;
                update_slice_requirement();
                forward_initial = tables_->from_cube(cube, features);
                inverse_initial = tables_->from_cube(cube.inverse(), features);
                active_initial = searching_inverse ? *inverse_initial : forward_initial;
                forward_lower_bound =
                    tables_->heuristic(forward_initial, active_phase1, active_corner, edge_pdb_views, 255, features);
                inverse_lower_bound =
                    tables_->heuristic(*inverse_initial, active_phase1, active_corner, edge_pdb_views, 255, features);
                result.direction_forward_lower_bound = forward_lower_bound;
                result.direction_inverse_lower_bound = inverse_lower_bound;
                lower_bound = std::max(forward_lower_bound, inverse_lower_bound);
                if (parity_search)
                    lower_bound += (lower_bound ^ root_parity) & 1;
                completed_depth = std::max(completed_depth, lower_bound - 1);
                if (depth < lower_bound)
                    depth = lower_bound;
                if (options.asset_adopted_callback)
                    options.asset_adopted_callback(
                        *active_asset_snapshot, depth, interrupted_layer_seconds,
                        options.timeout_seconds == 0
                            ? -1.0
                            : std::max(0.0, std::chrono::duration<double>(control.deadline -
                                                                          std::chrono::steady_clock::now())
                                                .count()),
                        control.counters.generated);
                interrupted_layer_seconds = 0.0;
            }
        }
        if (depth > effective_max)
            break;
        {
            auto updated = options.incumbent_callback ? options.incumbent_callback() : std::vector<int>{};
            auto generated = candidate_snapshot();
            if (!generated.empty() &&
                (updated.empty() || solution_cost(generated, options.metric) < solution_cost(updated, options.metric)))
                updated = std::move(generated);
            if (!updated.empty() && (incumbent.empty() || solution_cost(updated, options.metric) <
                                                              solution_cost(incumbent, options.metric))) {
                validate_incumbent(updated);
                incumbent = std::move(updated);
                best_candidate_cost.store(solution_cost(incumbent, options.metric), std::memory_order_relaxed);
                effective_max = std::min(options.max_depth, solution_cost(incumbent, options.metric) - 1);
                if (depth > effective_max)
                    break;
            }
        }
        const auto iteration_started = std::chrono::steady_clock::now();
        const auto nodes_before = control.nodes.load(std::memory_order_relaxed);
        const auto split_before = control.split_nodes.load(std::memory_order_relaxed);
        control.stop.store(false);
        control.timed_out.store(false);
        control.shortened_by_candidate.store(false);
        control.current_depth = depth;
        control.solution.clear();
        bool upgrade_requested = false;
        const auto generated_before = control.counters.generated;
        std::chrono::steady_clock::time_point upgrade_requested_at;
        auto snapshot = [&] {
            if (options.strong_upgrade_restart && result.strong_upgrade_restarts == 0 && !active_strong &&
                !cancelled() && std::chrono::steady_clock::now() + std::chrono::milliseconds(500) < control.deadline &&
                options.asset_snapshot_callback) {
                const auto next = options.asset_snapshot_callback();
                if (next && next->has_strong_pdb() &&
                    std::chrono::steady_clock::now() - iteration_started > std::chrono::milliseconds(100)) {
                    if (!upgrade_requested)
                        upgrade_requested_at = std::chrono::steady_clock::now();
                    upgrade_requested = true;
                    control.stop.store(true, std::memory_order_relaxed);
                }
            }
            if (options.incumbent_callback) {
                auto updated = options.incumbent_callback();
                if (!updated.empty() && (incumbent.empty() || solution_cost(updated, options.metric) <
                                                                  solution_cost(incumbent, options.metric))) {
                    validate_incumbent(updated);
                    incumbent = std::move(updated);
                    const int cost = solution_cost(incumbent, options.metric);
                    best_candidate_cost.store(std::min(best_candidate_cost.load(std::memory_order_relaxed), cost),
                                              std::memory_order_relaxed);
                    effective_max = std::min(effective_max, cost - 1);
                }
            }
            report(depth, nodes_before, split_before, iteration_started);
        };
        const int loader_threads = options.loader_threads_callback ? options.loader_threads_callback() : 0;
        const int candidate_threads = !candidate_done.load(std::memory_order_acquire);
        const int proof_threads = std::max(1, thread_count - candidate_threads - loader_threads);
        if (options.thread_activity_callback)
            options.thread_activity_callback(loader_threads, candidate_threads, proof_threads);
        auto solution = parallel_depth_search(*tables_, active_phase1, active_corner, edge_pdb_views, active_tail,
                                              features, active_initial, depth, options, proof_threads, control, pool,
                                              snapshot, candidate_threads ? &candidate_done : nullptr);
        if (upgrade_requested && !solution && !cancelled() && !control.timed_out.load()) {
            interrupted_layer_seconds =
                std::chrono::duration<double>(std::chrono::steady_clock::now() - iteration_started).count();
            ++result.strong_upgrade_restarts;
            const auto discarded = control.counters.generated - generated_before;
            const double stop_seconds =
                std::chrono::duration<double>(std::chrono::steady_clock::now() - upgrade_requested_at).count();
            result.upgrade_discarded_generated += discarded;
            result.upgrade_stop_seconds += stop_seconds;
            report(depth, nodes_before, split_before, iteration_started);
            if (options.upgrade_callback)
                options.upgrade_callback(depth, discarded, stop_seconds);
            depth -= parity_search ? 2 : 1;
            continue; // This interrupted layer contributes no coverage certificate.
        }
        const auto primary_nodes = control.nodes.load() - nodes_before;
        if (!solution && !control.timed_out.load() && !cancelled() && !direction_probed && depth == probe_depth) {
            direction_probed = true;
            const auto inverse_initial = tables_->from_cube(cube.inverse(), features);
            const int inverse_lower =
                tables_->heuristic(inverse_initial, active_phase1, active_corner, edge_pdb_views, 255, features);
            const auto inverse_before = control.nodes.load();
            control.stop.store(false);
            if (inverse_lower <= depth) {
                auto inverse_solution =
                    parallel_depth_search(*tables_, active_phase1, active_corner, edge_pdb_views, active_tail, features,
                                          inverse_initial, depth, options, proof_threads, control, pool, snapshot);
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
        const bool shortened = control.shortened_by_candidate.load(std::memory_order_relaxed);
        if (!solution && !stopped && !shortened)
            completed_depth = depth + (parity_search ? 1 : 0);
        report(depth, nodes_before, split_before, iteration_started, solution.has_value());
        if (solution) {
            result.moves = *solution;
            result.depth = solution_cost(result.moves, options.metric);
            result.optimal = true;
            break;
        }
        if (stopped) {
            result.cancelled = cancelled();
            result.timed_out = control.timed_out.load();
            break;
        }
        if (shortened)
            break;
    }
    candidate_cancel.store(true, std::memory_order_relaxed);
    if (candidate_thread.joinable())
        candidate_thread.join();
    result.candidate_phase1_nodes = candidate_result.phase1_nodes;
    result.candidate_phase2_nodes = candidate_result.phase2_nodes;
    result.candidate_improvements = candidate_result.improvements;
    result.candidate_window_replacements = candidate_result.window_replacements;
    result.candidate_worker_done_seconds = candidate_done_seconds.load(std::memory_order_relaxed);
    result.proof_worker_return_seconds = control.proof_worker_return_seconds.load(std::memory_order_relaxed);
    auto final_candidate = candidate_snapshot();
    if (!final_candidate.empty() && (incumbent.empty() || solution_cost(final_candidate, options.metric) <
                                                              solution_cost(incumbent, options.metric)))
        incumbent = std::move(final_candidate);
    if (result.depth < 0 && !incumbent.empty()) {
        result.moves = incumbent;
        result.depth = solution_cost(incumbent, options.metric);
        result.optimal = completed_depth >= result.depth - 1;
        if (result.optimal) {
            result.timed_out = false;
            result.cancelled = false;
        }
    }
    if (result.depth >= 0) {
        CubieCube verified = cube;
        for (int move : result.moves)
            verified = verified.apply_move(move);
        if (!verified.solved() || solution_cost(result.moves, options.metric) != result.depth)
            throw std::runtime_error("search returned an invalid solution or metric cost");
    }
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
    result.asset_snapshot = active_asset_snapshot;
    result.elapsed_seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    return result;
}

} // namespace cube
