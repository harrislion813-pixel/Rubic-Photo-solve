#include "tail.hpp"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string_view>
#include <system_error>
#include <vector>

namespace cube {
namespace {

constexpr std::array<char, 8> kMagic{'R', 'C', 'T', 'A', 'I', 'L', '1', '\0'};
constexpr std::uint32_t kVersion = 2;
constexpr std::uint8_t kEmpty = 255;

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

struct TailEntry {
    std::uint64_t key_low{};
    std::uint16_t key_high{};
    std::uint8_t distance{kEmpty};
    std::uint8_t move_to_goal{kEmpty};
    std::uint32_t reserved{};
};
#pragma pack(pop)

static_assert(sizeof(TailHeader) == 64);
static_assert(sizeof(TailEntry) == 16);

struct PackedKey {
    std::uint64_t low{};
    std::uint16_t high{};
    bool operator==(const PackedKey&) const = default;
};

std::runtime_error windows_error(std::string_view operation) {
    return std::runtime_error(std::string(operation) + " failed with Windows error " + std::to_string(GetLastError()));
}

std::uint64_t checksum_bytes(const std::uint8_t* data, std::uint64_t size) noexcept {
    std::uint64_t checksum = 1469598103934665603ULL;
    for (std::uint64_t index = 0; index < size; ++index) {
        checksum ^= data[index];
        checksum *= 1099511628211ULL;
    }
    return checksum;
}

PackedKey pack_cube(const CubieCube& cube) noexcept {
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

std::uint8_t inverse_move(int move) noexcept {
    const int power = move % 3;
    return static_cast<std::uint8_t>((move / 3) * 3 + (power == 0 ? 2 : power == 2 ? 0 : 1));
}

std::uint64_t slots_for_depth(int depth) {
    if (depth <= 2) return 1ULL << 12U;
    if (depth == 3) return 1ULL << 15U;
    if (depth == 4) return 1ULL << 20U;
    if (depth == 5) return 1ULL << 23U;
    return 1ULL << 24U;
}

TailEntry* find_slot(std::vector<TailEntry>& entries, PackedKey key) noexcept {
    const std::uint64_t mask = entries.size() - 1;
    std::uint64_t index = hash_key(key) & mask;
    while (true) {
        TailEntry& entry = entries[index];
        if (entry.distance == kEmpty || (entry.key_low == key.low && entry.key_high == key.high)) return &entry;
        index = (index + 1) & mask;
    }
}

const TailEntry* find_slot(const TailEntry* entries, std::uint64_t mask, PackedKey key) noexcept {
    std::uint64_t index = hash_key(key) & mask;
    while (true) {
        const TailEntry& entry = entries[index];
        if (entry.distance == kEmpty) return nullptr;
        if (entry.key_low == key.low && entry.key_high == key.high) return &entry;
        index = (index + 1) & mask;
    }
}

bool valid_existing_file(const std::filesystem::path& path, int requested_depth) {
    try {
        TailDatabase existing(path);
        return existing.depth() >= requested_depth;
    } catch (...) {
        return false;
    }
}

}  // namespace

TailDatabase::TailDatabase(const std::filesystem::path& path) {
    const auto absolute = std::filesystem::absolute(path);
    HANDLE file = CreateFileW(
        absolute.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) throw windows_error("CreateFileW");
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
    view_ = static_cast<const std::uint8_t*>(MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0));
    if (view_ == nullptr) {
        CloseHandle(mapping);
        CloseHandle(file);
        mapping_ = nullptr;
        file_ = nullptr;
        throw windows_error("MapViewOfFile");
    }

    const auto* header = reinterpret_cast<const TailHeader*>(view_);
    const bool valid =
        header->magic == kMagic && header->version == kVersion && header->header_size == sizeof(TailHeader) &&
        header->metric == 1 && header->depth <= 6 && header->slot_count > 0 &&
        (header->slot_count & (header->slot_count - 1)) == 0 &&
        size.QuadPart == static_cast<LONGLONG>(sizeof(TailHeader) + header->slot_count * sizeof(TailEntry)) &&
        header->reserved[0] == checksum_bytes(
            view_ + sizeof(TailHeader), header->slot_count * sizeof(TailEntry));
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
    depth_ = static_cast<int>(header->depth);
}

TailDatabase::~TailDatabase() {
    if (view_ != nullptr) UnmapViewOfFile(view_);
    if (mapping_ != nullptr) CloseHandle(static_cast<HANDLE>(mapping_));
    if (file_ != nullptr) CloseHandle(static_cast<HANDLE>(file_));
}

int TailDatabase::depth() const noexcept { return depth_; }

std::optional<TailHit> TailDatabase::lookup(const CubieCube& cube) const noexcept {
    const auto* entry = find_slot(static_cast<const TailEntry*>(entries_), mask_, pack_cube(cube));
    if (entry == nullptr) return std::nullopt;
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

void build_tail_database(const std::filesystem::path& path, int depth, bool force) {
    if (depth < 0 || depth > 6) throw std::invalid_argument("tail database depth must be 0..6");
    if (!force && std::filesystem::exists(path) && valid_existing_file(path, depth)) return;
    std::filesystem::create_directories(path.parent_path());

    const std::uint64_t slot_count = slots_for_depth(depth);
    std::vector<TailEntry> entries(slot_count);
    std::vector<CubieCube> frontier{CubieCube{}};
    {
        TailEntry* solved = find_slot(entries, pack_cube(CubieCube{}));
        solved->key_low = pack_cube(CubieCube{}).low;
        solved->key_high = pack_cube(CubieCube{}).high;
        solved->distance = 0;
        solved->move_to_goal = kEmpty;
    }
    std::uint64_t state_count = 1;

    for (int current_depth = 0; current_depth < depth; ++current_depth) {
        std::vector<CubieCube> next;
        next.reserve(frontier.size() * 12);
        for (const CubieCube& state : frontier) {
            for (int move = 0; move < 18; ++move) {
                CubieCube child = state.apply_move(move);
                const PackedKey key = pack_cube(child);
                TailEntry* entry = find_slot(entries, key);
                if (entry->distance != kEmpty) continue;
                entry->key_low = key.low;
                entry->key_high = key.high;
                entry->distance = static_cast<std::uint8_t>(current_depth + 1);
                entry->move_to_goal = inverse_move(move);
                next.push_back(std::move(child));
            }
        }
        frontier = std::move(next);
        state_count += frontier.size();
        if (state_count * 10 >= slot_count * 7) {
            throw std::runtime_error("tail database hash table exceeded 70% load");
        }
        std::cerr << "tail-db depth=" << current_depth + 1 << " frontier=" << frontier.size()
                  << " states=" << state_count << "\n";
    }

    TailHeader header;
    header.magic = kMagic;
    header.version = kVersion;
    header.header_size = sizeof(TailHeader);
    header.metric = 1;
    header.depth = depth;
    header.slot_count = slot_count;
    header.state_count = state_count;
    header.reserved[0] = checksum_bytes(
        reinterpret_cast<const std::uint8_t*>(entries.data()), entries.size() * sizeof(TailEntry));

    const std::filesystem::path temporary = path.string() + ".tmp";
    {
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        if (!output) throw std::runtime_error("cannot create tail database temporary file");
        output.write(reinterpret_cast<const char*>(&header), sizeof(header));
        output.write(
            reinterpret_cast<const char*>(entries.data()),
            static_cast<std::streamsize>(entries.size() * sizeof(TailEntry)));
        output.flush();
        if (!output) throw std::runtime_error("failed while writing tail database");
    }
    std::error_code error;
    std::filesystem::remove(path, error);
    error.clear();
    std::filesystem::rename(temporary, path, error);
    if (error) throw std::runtime_error("cannot atomically publish tail database: " + error.message());
    std::cerr << "tail-db complete depth=" << depth << " states=" << state_count
              << " slots=" << slot_count << " file=" << path.string() << "\n";
}

}  // namespace cube
