#include "tail.hpp"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <system_error>
#include <thread>
#include <vector>

namespace cube {
namespace {

constexpr std::array<char, 8> kMagic{'R', 'C', 'T', 'A', 'I', 'L', '1', '\0'};
constexpr std::uint32_t kLegacyVersion = 2;
constexpr std::uint32_t kCompactVersion = 3;
constexpr std::uint32_t kBloomVersion = 4;
constexpr std::uint8_t kEmpty = 255;
constexpr std::uint32_t kEmptyMetadata = static_cast<std::uint32_t>(kEmpty) << 16U;
constexpr std::uint32_t kBusyMetadata = 254U << 16U;
constexpr std::uint64_t kParallelChecksumMarker = 0x5441494C50415231ULL;
constexpr std::uint64_t kBloomChecksumMarker = 0x5441494C424C4D31ULL;
constexpr int kBloomHashes = 7;
constexpr std::uint64_t kBloomWordsPerBlock = 8;

#pragma pack(push, 1)
struct TailHeader {
    std::array<char, 8> magic{};
    std::uint32_t version{};
    std::uint32_t header_size{};
    std::uint32_t metric{};
    std::uint32_t depth{};
    std::uint64_t slot_count{};
    std::uint64_t state_count{};
    std::array<std::uint64_t, 3> reserved{};
};

struct LegacyTailEntry {
    std::uint64_t key_low{};
    std::uint16_t key_high{};
    std::uint8_t distance{kEmpty};
    std::uint8_t move_to_goal{kEmpty};
    std::uint32_t reserved{};
};
#pragma pack(pop)

static_assert(sizeof(TailHeader) == 64);
static_assert(sizeof(LegacyTailEntry) == 16);

struct PackedKey {
    std::uint64_t low{};
    std::uint16_t high{};
    bool operator==(const PackedKey &) const = default;
};

std::runtime_error windows_error(std::string_view operation) {
    return std::runtime_error(std::string(operation) + " failed with Windows error " + std::to_string(GetLastError()));
}

std::uint64_t checksum_bytes(const std::uint8_t *data, std::uint64_t size,
                             std::uint64_t checksum = 1469598103934665603ULL) noexcept {
    for (std::uint64_t index = 0; index < size; ++index) {
        checksum ^= data[index];
        checksum *= 1099511628211ULL;
    }
    return checksum;
}

std::uint64_t mix_checksum(std::uint64_t value) noexcept {
    value ^= value >> 30U;
    value *= 0xBF58476D1CE4E5B9ULL;
    value ^= value >> 27U;
    value *= 0x94D049BB133111EBULL;
    return value ^ (value >> 31U);
}

std::uint64_t checksum_bytes_parallel(const std::uint8_t *data, std::uint64_t size) {
    constexpr std::uint64_t chunk_bytes = 4ULL << 20U;
    const std::size_t chunk_count = static_cast<std::size_t>((size + chunk_bytes - 1) / chunk_bytes);
    if (chunk_count == 0)
        return checksum_bytes(data, size);
    std::vector<std::uint64_t> hashes(chunk_count);
    std::atomic<std::size_t> cursor{0};
    const int thread_count = std::clamp(static_cast<int>(std::thread::hardware_concurrency()), 1, 32);
    std::vector<std::thread> workers;
    workers.reserve(thread_count);
    for (int thread = 0; thread < thread_count; ++thread) {
        workers.emplace_back([&] {
            while (true) {
                const std::size_t chunk = cursor.fetch_add(1, std::memory_order_relaxed);
                if (chunk >= chunk_count)
                    break;
                const std::uint64_t begin = static_cast<std::uint64_t>(chunk) * chunk_bytes;
                const std::uint64_t length = std::min(chunk_bytes, size - begin);
                hashes[chunk] = checksum_bytes(data + begin, length);
            }
        });
    }
    for (auto &worker : workers)
        worker.join();

    std::uint64_t result = 0xCBF29CE484222325ULL ^ size;
    for (std::size_t chunk = 0; chunk < hashes.size(); ++chunk) {
        result = mix_checksum(result ^ hashes[chunk] ^ (static_cast<std::uint64_t>(chunk) * 0x9E3779B97F4A7C15ULL));
    }
    return result;
}

void normalize_empty_keys(std::uint64_t *keys, const std::uint32_t *metadata, std::uint64_t slot_count, int threads) {
    std::vector<std::thread> workers;
    workers.reserve(threads);
    for (int thread = 0; thread < threads; ++thread) {
        workers.emplace_back([&, thread] {
            const std::uint64_t begin = slot_count * thread / threads;
            const std::uint64_t end = slot_count * (thread + 1) / threads;
            for (std::uint64_t slot = begin; slot < end; ++slot) {
                if (((metadata[slot] >> 16U) & 0xFFU) == kEmpty)
                    keys[slot] = 0;
            }
        });
    }
    for (auto &worker : workers)
        worker.join();
}

void write_bytes(std::ofstream &output, const void *data, std::uint64_t size) {
    constexpr std::uint64_t chunk_bytes = 64ULL << 20U;
    const auto *cursor = static_cast<const char *>(data);
    while (size > 0) {
        const std::uint64_t length = std::min(chunk_bytes, size);
        output.write(cursor, static_cast<std::streamsize>(length));
        if (!output)
            throw std::runtime_error("failed while writing tail database");
        cursor += length;
        size -= length;
    }
}

PackedKey pack_cube(const CubieCube &cube) noexcept {
    const std::uint64_t corner = corner_pattern_coord(cube);
    const std::uint64_t edges = rank_permutation(cube.ep);
    const std::uint64_t flip = flip_coord(cube);
    return PackedKey{
        corner | (edges << 27U) | ((flip & 0xFFU) << 56U),
        static_cast<std::uint16_t>(flip >> 8U),
    };
}

std::uint64_t hash_key(PackedKey key) noexcept {
    std::uint64_t value = key.low ^ (static_cast<std::uint64_t>(key.high) * 0x9E3779B97F4A7C15ULL);
    value ^= value >> 30U;
    value *= 0xBF58476D1CE4E5B9ULL;
    value ^= value >> 27U;
    value *= 0x94D049BB133111EBULL;
    return value ^ (value >> 31U);
}

std::uint64_t bloom_word_count(std::uint64_t slot_count) noexcept { return slot_count / 16U; }

void bloom_locations(PackedKey key, std::uint64_t word_count, std::array<std::uint64_t, kBloomHashes> &words,
                     std::array<std::uint64_t, kBloomHashes> &masks) noexcept {
    const std::uint64_t block_count = word_count / kBloomWordsPerBlock;
    const std::uint64_t hash = hash_key(key);
    const std::uint64_t block = hash & (block_count - 1U);
    std::uint64_t seed = mix_checksum(hash ^ (static_cast<std::uint64_t>(key.high) << 48U));
    for (int index = 0; index < kBloomHashes; ++index) {
        seed = mix_checksum(seed + 0x9E3779B97F4A7C15ULL + static_cast<std::uint64_t>(index));
        const std::uint64_t bit = seed & 511U;
        words[index] = block * kBloomWordsPerBlock + bit / 64U;
        masks[index] = 1ULL << (bit % 64U);
    }
}

bool bloom_maybe_contains(const std::uint64_t *bloom, std::uint64_t word_count, PackedKey key) noexcept {
    std::array<std::uint64_t, kBloomHashes> words{};
    std::array<std::uint64_t, kBloomHashes> masks{};
    bloom_locations(key, word_count, words, masks);
    for (int index = 0; index < kBloomHashes; ++index) {
        if ((bloom[words[index]] & masks[index]) == 0)
            return false;
    }
    return true;
}

std::unique_ptr<std::uint64_t[]> build_bloom_filter(const std::uint64_t *keys, const std::uint32_t *metadata,
                                                    std::uint64_t slot_count, int threads) {
    const std::uint64_t word_count = bloom_word_count(slot_count);
    auto bloom = std::make_unique_for_overwrite<std::uint64_t[]>(word_count);
    std::vector<std::thread> initializers;
    initializers.reserve(threads);
    for (int thread = 0; thread < threads; ++thread) {
        initializers.emplace_back([&, thread] {
            const std::uint64_t begin = word_count * thread / threads;
            const std::uint64_t end = word_count * (thread + 1) / threads;
            std::fill(bloom.get() + begin, bloom.get() + end, 0);
        });
    }
    for (auto &initializer : initializers)
        initializer.join();

    std::atomic<std::uint64_t> cursor{0};
    std::vector<std::thread> workers;
    workers.reserve(threads);
    for (int thread = 0; thread < threads; ++thread) {
        workers.emplace_back([&] {
            std::array<std::uint64_t, kBloomHashes> words{};
            std::array<std::uint64_t, kBloomHashes> masks{};
            while (true) {
                const std::uint64_t begin = cursor.fetch_add(4096, std::memory_order_relaxed);
                if (begin >= slot_count)
                    break;
                const std::uint64_t end = std::min(slot_count, begin + 4096);
                for (std::uint64_t slot = begin; slot < end; ++slot) {
                    const std::uint32_t value = metadata[slot];
                    if (((value >> 16U) & 0xFFU) == kEmpty)
                        continue;
                    const PackedKey key{keys[slot], static_cast<std::uint16_t>(value & 0xFFFFU)};
                    bloom_locations(key, word_count, words, masks);
                    for (int index = 0; index < kBloomHashes; ++index) {
                        std::atomic_ref<std::uint64_t> word(bloom[words[index]]);
                        word.fetch_or(masks[index], std::memory_order_relaxed);
                    }
                }
            }
        });
    }
    for (auto &worker : workers)
        worker.join();
    return bloom;
}

std::uint8_t inverse_move(int move) noexcept {
    const int power = move % 3;
    return static_cast<std::uint8_t>((move / 3) * 3 + (power == 0 ? 2 : power == 2 ? 0 : 1));
}

std::uint64_t slots_for_depth(int depth) {
    if (depth <= 2)
        return 1ULL << 12U;
    if (depth == 3)
        return 1ULL << 15U;
    if (depth == 4)
        return 1ULL << 20U;
    if (depth == 5)
        return 1ULL << 23U;
    if (depth <= 6)
        return 1ULL << 24U;
    return 1ULL << 28U;
}

void require_tail_build_memory(int depth) {
    if (depth < 7)
        return;
    MEMORYSTATUSEX status{};
    status.dwLength = sizeof(status);
    if (!GlobalMemoryStatusEx(&status))
        throw windows_error("GlobalMemoryStatusEx");
    constexpr std::uint64_t minimum_available = 10ULL << 30U;
    if (status.ullAvailPhys < minimum_available) {
        throw std::runtime_error(
            "building a depth-7 tail database requires at least 10 GiB of available physical memory");
    }
}

std::uint8_t metadata_distance(std::uint32_t metadata) noexcept {
    return static_cast<std::uint8_t>((metadata >> 16U) & 0xFFU);
}

std::uint8_t metadata_move(std::uint32_t metadata) noexcept { return static_cast<std::uint8_t>(metadata >> 24U); }

std::uint16_t metadata_key_high(std::uint32_t metadata) noexcept {
    return static_cast<std::uint16_t>(metadata & 0xFFFFU);
}

std::uint32_t pack_metadata(PackedKey key, std::uint8_t distance, std::uint8_t move_to_goal) noexcept {
    return static_cast<std::uint32_t>(key.high) | (static_cast<std::uint32_t>(distance) << 16U) |
           (static_cast<std::uint32_t>(move_to_goal) << 24U);
}

std::uint64_t find_compact_slot(const std::uint64_t *keys, const std::uint32_t *metadata, std::uint64_t slot_count,
                                PackedKey key) noexcept {
    const std::uint64_t mask = slot_count - 1;
    std::uint64_t index = hash_key(key) & mask;
    while (true) {
        const std::uint32_t value = metadata[index];
        if (metadata_distance(value) == kEmpty || (keys[index] == key.low && metadata_key_high(value) == key.high)) {
            return index;
        }
        index = (index + 1) & mask;
    }
}

bool insert_compact_concurrent(std::uint64_t *keys, std::uint32_t *metadata, std::uint64_t slot_count, PackedKey key,
                               std::uint8_t distance, std::uint8_t move_to_goal) noexcept {
    const std::uint64_t mask = slot_count - 1;
    std::uint64_t index = hash_key(key) & mask;
    while (true) {
        std::atomic_ref<std::uint32_t> slot(metadata[index]);
        std::uint32_t value = slot.load(std::memory_order_acquire);
        if (value == kEmptyMetadata) {
            if (slot.compare_exchange_strong(value, kBusyMetadata, std::memory_order_acq_rel,
                                             std::memory_order_acquire)) {
                keys[index] = key.low;
                slot.store(pack_metadata(key, distance, move_to_goal), std::memory_order_release);
                return true;
            }
            continue;
        }
        if (value == kBusyMetadata) {
            std::this_thread::yield();
            continue;
        }
        if (keys[index] == key.low && metadata_key_high(value) == key.high)
            return false;
        index = (index + 1) & mask;
    }
}

const LegacyTailEntry *find_legacy_slot(const LegacyTailEntry *entries, std::uint64_t mask, PackedKey key) noexcept {
    std::uint64_t index = hash_key(key) & mask;
    while (true) {
        const LegacyTailEntry &entry = entries[index];
        if (entry.distance == kEmpty)
            return nullptr;
        if (entry.key_low == key.low && entry.key_high == key.high)
            return &entry;
        index = (index + 1) & mask;
    }
}

std::optional<TailHit> find_compact_entry(const std::uint64_t *keys, const std::uint32_t *metadata, std::uint64_t mask,
                                          PackedKey key, TailLookupCounters *counters) noexcept {
    std::uint64_t index = hash_key(key) & mask;
    while (true) {
        if (counters != nullptr)
            ++counters->probes;
        const std::uint32_t value = metadata[index];
        if (metadata_distance(value) == kEmpty)
            return std::nullopt;
        if (keys[index] == key.low && metadata_key_high(value) == key.high) {
            return TailHit{metadata_distance(value), metadata_move(value)};
        }
        index = (index + 1) & mask;
    }
}

bool valid_existing_file(const std::filesystem::path &path, int requested_depth) {
    try {
        TailDatabase existing(path);
        return existing.format_version() >= kCompactVersion && existing.depth() >= requested_depth;
    } catch (...) {
        return false;
    }
}

} // namespace

TailDatabase::TailDatabase(const std::filesystem::path &path) {
    const auto absolute = std::filesystem::absolute(path);
    HANDLE file = CreateFileW(absolute.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE)
        throw windows_error("CreateFileW");
    file_ = file;

    LARGE_INTEGER size{};
    if (!GetFileSizeEx(file, &size) || size.QuadPart < static_cast<LONGLONG>(sizeof(TailHeader))) {
        CloseHandle(file);
        file_ = nullptr;
        throw std::runtime_error("tail database is truncated");
    }
    HANDLE mapping = CreateFileMappingW(file, nullptr, PAGE_READONLY, 0, 0, nullptr);
    if (mapping == nullptr) {
        CloseHandle(file);
        file_ = nullptr;
        throw windows_error("CreateFileMappingW");
    }
    mapping_ = mapping;
    view_ = static_cast<const std::uint8_t *>(MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0));
    if (view_ == nullptr) {
        CloseHandle(mapping);
        CloseHandle(file);
        mapping_ = nullptr;
        file_ = nullptr;
        throw windows_error("MapViewOfFile");
    }

    const auto *header = reinterpret_cast<const TailHeader *>(view_);
    const bool legacy = header->version == kLegacyVersion;
    const bool compact = header->version == kCompactVersion;
    const bool bloom_format = header->version == kBloomVersion;
    const std::uint64_t entry_bytes = legacy ? sizeof(LegacyTailEntry) : 12U;
    const std::uint64_t bloom_bytes = bloom_format ? bloom_word_count(header->slot_count) * sizeof(std::uint64_t) : 0;
    const std::uint64_t data_bytes = header->slot_count * entry_bytes + bloom_bytes;
    bool checksum_valid = false;
    if (size.QuadPart == static_cast<LONGLONG>(sizeof(TailHeader) + data_bytes)) {
        if (bloom_format && header->reserved[2] == kBloomChecksumMarker) {
            const auto *keys = view_ + sizeof(TailHeader);
            const auto *metadata = keys + header->slot_count * sizeof(std::uint64_t);
            const auto *bloom = metadata + header->slot_count * sizeof(std::uint32_t);
            const std::uint64_t metadata_checksum =
                checksum_bytes_parallel(metadata, header->slot_count * sizeof(std::uint32_t));
            const std::uint64_t bloom_checksum = checksum_bytes_parallel(bloom, bloom_bytes);
            checksum_valid =
                header->reserved[0] == checksum_bytes_parallel(keys, header->slot_count * sizeof(std::uint64_t)) &&
                header->reserved[1] == mix_checksum(metadata_checksum ^ std::rotl(bloom_checksum, 17));
        } else if (compact && header->reserved[2] == kParallelChecksumMarker) {
            const auto *keys = view_ + sizeof(TailHeader);
            const auto *metadata = keys + header->slot_count * sizeof(std::uint64_t);
            checksum_valid =
                header->reserved[0] == checksum_bytes_parallel(keys, header->slot_count * sizeof(std::uint64_t)) &&
                header->reserved[1] == checksum_bytes_parallel(metadata, header->slot_count * sizeof(std::uint32_t));
        } else {
            checksum_valid = header->reserved[0] == checksum_bytes(view_ + sizeof(TailHeader), data_bytes);
        }
    }
    const bool valid = header->magic == kMagic && (legacy || compact || bloom_format) &&
                       header->header_size == sizeof(TailHeader) && header->metric == 1 && header->depth <= 7 &&
                       header->slot_count > 0 && (header->slot_count & (header->slot_count - 1)) == 0 &&
                       size.QuadPart == static_cast<LONGLONG>(sizeof(TailHeader) + data_bytes) && checksum_valid;
    if (!valid) {
        UnmapViewOfFile(view_);
        CloseHandle(mapping);
        CloseHandle(file);
        view_ = nullptr;
        mapping_ = nullptr;
        file_ = nullptr;
        throw std::runtime_error("tail database header is invalid or incompatible");
    }
    entries_ = view_ + sizeof(TailHeader);
    slot_count_ = header->slot_count;
    mask_ = slot_count_ - 1;
    version_ = header->version;
    depth_ = static_cast<int>(header->depth);
    if (bloom_format) {
        const auto *keys = static_cast<const std::uint64_t *>(entries_);
        const auto *metadata = reinterpret_cast<const std::uint32_t *>(keys + slot_count_);
        bloom_ = reinterpret_cast<const std::uint64_t *>(metadata + slot_count_);
        bloom_word_count_ = bloom_word_count(slot_count_);
    }
}

TailDatabase::~TailDatabase() {
    if (view_ != nullptr)
        UnmapViewOfFile(view_);
    if (mapping_ != nullptr)
        CloseHandle(static_cast<HANDLE>(mapping_));
    if (file_ != nullptr)
        CloseHandle(static_cast<HANDLE>(file_));
}

int TailDatabase::depth() const noexcept { return depth_; }

std::uint32_t TailDatabase::format_version() const noexcept { return version_; }

std::optional<TailHit> TailDatabase::lookup(const CubieCube &cube, TailLookupCounters *counters) const noexcept {
    if (counters != nullptr)
        ++counters->queries;
    const PackedKey key = pack_cube(cube);
    if (version_ == kBloomVersion && !bloom_maybe_contains(bloom_, bloom_word_count_, key)) {
        if (counters != nullptr)
            ++counters->bloom_rejects;
        return std::nullopt;
    }
    if (counters != nullptr)
        ++counters->exact_queries;
    if (version_ == kCompactVersion || version_ == kBloomVersion) {
        const auto *keys = static_cast<const std::uint64_t *>(entries_);
        const auto *metadata = reinterpret_cast<const std::uint32_t *>(keys + slot_count_);
        auto result = find_compact_entry(keys, metadata, mask_, key, counters);
        if (result.has_value() && counters != nullptr)
            ++counters->hits;
        return result;
    }
    const auto *entry = find_legacy_slot(static_cast<const LegacyTailEntry *>(entries_), mask_, key);
    if (entry == nullptr)
        return std::nullopt;
    if (counters != nullptr)
        ++counters->hits;
    return TailHit{entry->distance, entry->move_to_goal};
}

std::vector<int> TailDatabase::solution_suffix(CubieCube cube) const {
    std::vector<int> result;
    result.reserve(depth_);
    while (!cube.solved()) {
        const auto hit = lookup(cube);
        if (!hit.has_value() || hit->move_to_goal >= 18) {
            throw std::runtime_error("tail database chain is incomplete");
        }
        result.push_back(hit->move_to_goal);
        cube = cube.apply_move(hit->move_to_goal);
    }
    return result;
}

void build_tail_database(const std::filesystem::path &path, int depth, int threads, bool force) {
    if (depth < 0 || depth > 7)
        throw std::invalid_argument("tail database depth must be 0..7");
    if (!force && std::filesystem::exists(path) && valid_existing_file(path, depth))
        return;
    std::filesystem::create_directories(path.parent_path());
    require_tail_build_memory(depth);
    threads = std::clamp(threads > 0 ? threads : static_cast<int>(std::thread::hardware_concurrency()), 1, 64);

    const std::uint64_t slot_count = slots_for_depth(depth);
    auto keys = std::make_unique_for_overwrite<std::uint64_t[]>(slot_count);
    auto metadata = std::make_unique_for_overwrite<std::uint32_t[]>(slot_count);
    {
        std::vector<std::thread> initializers;
        initializers.reserve(threads);
        for (int thread = 0; thread < threads; ++thread) {
            initializers.emplace_back([&, thread] {
                const std::uint64_t begin = slot_count * thread / threads;
                const std::uint64_t end = slot_count * (thread + 1) / threads;
                std::fill(metadata.get() + begin, metadata.get() + end, kEmptyMetadata);
            });
        }
        for (auto &initializer : initializers)
            initializer.join();
    }
    std::vector<CubieCube> frontier{CubieCube{}};
    {
        const PackedKey solved = pack_cube(CubieCube{});
        const std::uint64_t slot = find_compact_slot(keys.get(), metadata.get(), slot_count, solved);
        keys[slot] = solved.low;
        metadata[slot] = pack_metadata(solved, 0, kEmpty);
    }
    std::uint64_t state_count = 1;
    std::vector<std::vector<CubieCube>> frontier_shards;

    for (int current_depth = 0; current_depth < depth; ++current_depth) {
        const bool final_layer = current_depth + 1 == depth;
        std::vector<CubieCube> next;
        std::uint64_t next_count = 0;
        const bool parallel_layer = threads > 1 && (!frontier_shards.empty() || frontier.size() >= 1024);
        if (parallel_layer) {
            std::atomic<std::size_t> cursor{0};
            std::vector<std::uint64_t> local_counts(threads, 0);
            std::vector<std::vector<CubieCube>> local_next(threads);
            std::vector<std::thread> workers;
            workers.reserve(threads);
            for (int thread = 0; thread < threads; ++thread) {
                workers.emplace_back([&, thread] {
                    std::uint64_t local_count = 0;
                    auto &output = local_next[thread];
                    if (!final_layer) {
                        const std::size_t input_size =
                            frontier_shards.empty() ? frontier.size() : frontier_shards[thread].size() * threads;
                        output.reserve(input_size * 12 / threads + 1024);
                    }
                    auto expand_state = [&](const CubieCube &state) {
                        for (int move = 0; move < 18; ++move) {
                            const CubieCube child = state.apply_move(move);
                            const PackedKey key = pack_cube(child);
                            if (insert_compact_concurrent(keys.get(), metadata.get(), slot_count, key,
                                                          static_cast<std::uint8_t>(current_depth + 1),
                                                          inverse_move(move))) {
                                ++local_count;
                                if (!final_layer)
                                    output.push_back(child);
                            }
                        }
                    };
                    if (!frontier_shards.empty()) {
                        for (const CubieCube &state : frontier_shards[thread])
                            expand_state(state);
                    } else {
                        while (true) {
                            const std::size_t begin = cursor.fetch_add(1024, std::memory_order_relaxed);
                            if (begin >= frontier.size())
                                break;
                            const std::size_t end = std::min(frontier.size(), begin + 1024);
                            for (std::size_t item = begin; item < end; ++item)
                                expand_state(frontier[item]);
                        }
                    }
                    local_counts[thread] = local_count;
                });
            }
            for (auto &worker : workers)
                worker.join();
            for (const std::uint64_t count : local_counts)
                next_count += count;
            if (!final_layer) {
                if (current_depth + 2 == depth) {
                    frontier_shards = std::move(local_next);
                } else {
                    next.reserve(static_cast<std::size_t>(next_count));
                    for (auto &output : local_next) {
                        next.insert(next.end(), std::make_move_iterator(output.begin()),
                                    std::make_move_iterator(output.end()));
                    }
                }
            }
        } else {
            if (!final_layer)
                next.reserve(frontier.size() * 12);
            for (const CubieCube &state : frontier) {
                for (int move = 0; move < 18; ++move) {
                    CubieCube child = state.apply_move(move);
                    const PackedKey key = pack_cube(child);
                    const std::uint64_t slot = find_compact_slot(keys.get(), metadata.get(), slot_count, key);
                    if (metadata_distance(metadata[slot]) != kEmpty)
                        continue;
                    keys[slot] = key.low;
                    metadata[slot] =
                        pack_metadata(key, static_cast<std::uint8_t>(current_depth + 1), inverse_move(move));
                    ++next_count;
                    if (!final_layer)
                        next.push_back(std::move(child));
                }
            }
        }
        frontier = std::move(next);
        if (final_layer)
            frontier_shards.clear();
        state_count += next_count;
        if (state_count * 10 >= slot_count * 7) {
            throw std::runtime_error("tail database hash table exceeded 70% load");
        }
        std::cerr << "tail-db depth=" << current_depth + 1 << " frontier=" << next_count << " states=" << state_count
                  << "\n";
    }

    normalize_empty_keys(keys.get(), metadata.get(), slot_count, threads);
    auto bloom = build_bloom_filter(keys.get(), metadata.get(), slot_count, threads);
    const std::uint64_t bloom_words = bloom_word_count(slot_count);

    TailHeader header;
    header.magic = kMagic;
    header.version = kBloomVersion;
    header.header_size = sizeof(TailHeader);
    header.metric = 1;
    header.depth = depth;
    header.slot_count = slot_count;
    header.state_count = state_count;
    header.reserved[0] =
        checksum_bytes_parallel(reinterpret_cast<const std::uint8_t *>(keys.get()), slot_count * sizeof(keys[0]));
    const std::uint64_t metadata_checksum = checksum_bytes_parallel(
        reinterpret_cast<const std::uint8_t *>(metadata.get()), slot_count * sizeof(metadata[0]));
    const std::uint64_t bloom_checksum =
        checksum_bytes_parallel(reinterpret_cast<const std::uint8_t *>(bloom.get()), bloom_words * sizeof(bloom[0]));
    header.reserved[1] = mix_checksum(metadata_checksum ^ std::rotl(bloom_checksum, 17));
    header.reserved[2] = kBloomChecksumMarker;

    const std::filesystem::path temporary = path.string() + ".tmp";
    {
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        if (!output)
            throw std::runtime_error("cannot create tail database temporary file");
        write_bytes(output, &header, sizeof(header));
        write_bytes(output, keys.get(), slot_count * sizeof(keys[0]));
        write_bytes(output, metadata.get(), slot_count * sizeof(metadata[0]));
        write_bytes(output, bloom.get(), bloom_words * sizeof(bloom[0]));
        output.flush();
        if (!output)
            throw std::runtime_error("failed while writing tail database");
    }
    std::error_code error;
    std::filesystem::remove(path, error);
    error.clear();
    std::filesystem::rename(temporary, path, error);
    if (error)
        throw std::runtime_error("cannot atomically publish tail database: " + error.message());
    std::cerr << "tail-db complete depth=" << depth << " states=" << state_count << " slots=" << slot_count
              << " file=" << path.string() << "\n";
}

} // namespace cube
