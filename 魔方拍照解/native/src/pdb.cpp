#include "pdb.hpp"

#include "solver.hpp"
#include "symmetry.hpp"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <thread>
#include <vector>

namespace cube {
namespace {

constexpr std::array<char, 8> kMagic{'R', 'C', 'P', 'D', 'B', '0', '1', '\0'};
constexpr std::uint32_t kVersion = 2;
constexpr std::uint32_t kMetricHtm = 1;
constexpr std::uint32_t kPatternCorners = 1;
constexpr std::uint32_t kPatternEdgesA = 2;
constexpr std::uint32_t kPatternPhase1Symmetry = 10;
constexpr std::uint32_t kCompleteFlag = 1;
constexpr std::uint32_t kChecksumFlag = 2;

#pragma pack(push, 1)
struct PdbHeader {
    std::array<char, 8> magic{};
    std::uint32_t version{};
    std::uint32_t header_size{};
    std::uint32_t metric{};
    std::uint32_t pattern{};
    std::uint32_t bits_per_entry{};
    std::uint32_t max_value{};
    std::uint32_t flags{};
    std::uint64_t entry_count{};
    std::uint64_t data_bytes{};
    std::array<std::uint64_t, 2> reserved{};
};
#pragma pack(pop)

static_assert(sizeof(PdbHeader) == 68);

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

bool valid_existing_file(const std::filesystem::path& path, int requested_depth) {
    try {
        CornerPatternDatabase existing(path);
        return existing.complete() || existing.max_value() >= requested_depth + 1;
    } catch (...) {
        return false;
    }
}

bool valid_existing_edge_file(const std::filesystem::path& path, int group, int requested_depth) {
    try {
        EdgePatternDatabase existing(path, group);
        return existing.complete() || existing.max_value() >= requested_depth + 1;
    } catch (...) {
        return false;
    }
}

bool valid_existing_phase1_file(const std::filesystem::path& path, int requested_depth) {
    try {
        Phase1PatternDatabase existing(path);
        return existing.complete() || existing.max_value() >= requested_depth + 1;
    } catch (...) {
        return false;
    }
}

}  // namespace

Phase1PatternDatabase::Phase1PatternDatabase(const std::filesystem::path& path) {
    const auto absolute = std::filesystem::absolute(path);
    HANDLE file = CreateFileW(
        absolute.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) throw windows_error("CreateFileW");
    file_ = file;

    LARGE_INTEGER size{};
    if (!GetFileSizeEx(file, &size) || size.QuadPart < static_cast<LONGLONG>(sizeof(PdbHeader))) {
        CloseHandle(file);
        file_ = nullptr;
        throw std::runtime_error("phase-1 PDB is truncated");
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

    const auto* header = reinterpret_cast<const PdbHeader*>(view_);
    const bool valid =
        header->magic == kMagic && header->version == kVersion && header->header_size == sizeof(PdbHeader) &&
        header->metric == kMetricHtm && header->pattern == kPatternPhase1Symmetry && header->bits_per_entry == 4 &&
        header->entry_count == kPhase1PatternEntries &&
        header->data_bytes == (kPhase1PatternEntries + 1) / 2 &&
        size.QuadPart == static_cast<LONGLONG>(header->header_size + header->data_bytes) &&
        header->max_value <= 15 && (header->flags & kChecksumFlag) != 0 &&
        header->reserved[0] == checksum_bytes(view_ + header->header_size, header->data_bytes);
    if (!valid) {
        UnmapViewOfFile(view_);
        CloseHandle(mapping);
        CloseHandle(file);
        view_ = nullptr;
        mapping_ = nullptr;
        file_ = nullptr;
        throw std::runtime_error("phase-1 PDB header is invalid or incompatible");
    }
    data_ = view_ + header->header_size;
    max_value_ = static_cast<std::uint8_t>(header->max_value);
    complete_ = (header->flags & kCompleteFlag) != 0;
    try {
        symmetry_ = std::make_shared<Phase1Symmetry>();
    } catch (...) {
        UnmapViewOfFile(view_);
        CloseHandle(mapping);
        CloseHandle(file);
        view_ = nullptr;
        mapping_ = nullptr;
        file_ = nullptr;
        throw;
    }
}

Phase1PatternDatabase::~Phase1PatternDatabase() {
    if (view_ != nullptr) UnmapViewOfFile(view_);
    if (mapping_ != nullptr) CloseHandle(static_cast<HANDLE>(mapping_));
    if (file_ != nullptr) CloseHandle(static_cast<HANDLE>(file_));
}

std::uint8_t Phase1PatternDatabase::distance(
    std::uint16_t twist,
    std::uint16_t flip,
    std::uint16_t slice) const noexcept {
    const std::uint32_t coordinate = symmetry_->canonical_index(twist, flip, slice);
    const std::uint8_t packed = data_[coordinate >> 1U];
    return coordinate & 1U ? static_cast<std::uint8_t>(packed >> 4U)
                           : static_cast<std::uint8_t>(packed & 0x0FU);
}

bool Phase1PatternDatabase::complete() const noexcept { return complete_; }

std::uint8_t Phase1PatternDatabase::max_value() const noexcept { return max_value_; }

CornerPatternDatabase::CornerPatternDatabase(const std::filesystem::path& path) {
    const auto absolute = std::filesystem::absolute(path);
    HANDLE file = CreateFileW(
        absolute.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) throw windows_error("CreateFileW");
    file_ = file;

    LARGE_INTEGER size{};
    if (!GetFileSizeEx(file, &size) || size.QuadPart < static_cast<LONGLONG>(sizeof(PdbHeader))) {
        CloseHandle(file);
        file_ = nullptr;
        throw std::runtime_error("corner PDB is truncated");
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

    const auto* header = reinterpret_cast<const PdbHeader*>(view_);
    const bool valid =
        header->magic == kMagic && header->version == kVersion && header->header_size == sizeof(PdbHeader) &&
        header->metric == kMetricHtm && header->pattern == kPatternCorners && header->bits_per_entry == 4 &&
        header->entry_count == kCornerPatternEntries &&
        header->data_bytes == (kCornerPatternEntries + 1) / 2 &&
        size.QuadPart == static_cast<LONGLONG>(header->header_size + header->data_bytes) &&
        header->max_value <= 15 && (header->flags & kChecksumFlag) != 0 &&
        header->reserved[0] == checksum_bytes(view_ + header->header_size, header->data_bytes);
    if (!valid) {
        UnmapViewOfFile(view_);
        CloseHandle(mapping);
        CloseHandle(file);
        view_ = nullptr;
        mapping_ = nullptr;
        file_ = nullptr;
        throw std::runtime_error("corner PDB header is invalid or incompatible");
    }
    data_ = view_ + header->header_size;
    max_value_ = static_cast<std::uint8_t>(header->max_value);
    complete_ = (header->flags & kCompleteFlag) != 0;
}

CornerPatternDatabase::~CornerPatternDatabase() {
    if (view_ != nullptr) UnmapViewOfFile(view_);
    if (mapping_ != nullptr) CloseHandle(static_cast<HANDLE>(mapping_));
    if (file_ != nullptr) CloseHandle(static_cast<HANDLE>(file_));
}

std::uint8_t CornerPatternDatabase::distance(std::uint32_t coordinate) const noexcept {
    const std::uint8_t packed = data_[coordinate >> 1U];
    return coordinate & 1U ? static_cast<std::uint8_t>(packed >> 4U)
                           : static_cast<std::uint8_t>(packed & 0x0FU);
}

bool CornerPatternDatabase::complete() const noexcept { return complete_; }

std::uint8_t CornerPatternDatabase::max_value() const noexcept { return max_value_; }

EdgePatternDatabase::EdgePatternDatabase(const std::filesystem::path& path, int group) {
    if (group < 0 || group > 7) throw std::invalid_argument("edge pattern group must be 0..7");
    const auto absolute = std::filesystem::absolute(path);
    HANDLE file = CreateFileW(
        absolute.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) throw windows_error("CreateFileW");
    file_ = file;

    LARGE_INTEGER size{};
    if (!GetFileSizeEx(file, &size) || size.QuadPart < static_cast<LONGLONG>(sizeof(PdbHeader))) {
        CloseHandle(file);
        file_ = nullptr;
        throw std::runtime_error("edge PDB is truncated");
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

    const auto* header = reinterpret_cast<const PdbHeader*>(view_);
    const std::uint32_t expected_pattern = kPatternEdgesA + static_cast<std::uint32_t>(group);
    const bool valid =
        header->magic == kMagic && header->version == kVersion && header->header_size == sizeof(PdbHeader) &&
        header->metric == kMetricHtm && header->pattern == expected_pattern && header->bits_per_entry == 4 &&
        header->entry_count == kEdgePatternEntries &&
        header->data_bytes == (kEdgePatternEntries + 1) / 2 &&
        size.QuadPart == static_cast<LONGLONG>(header->header_size + header->data_bytes) &&
        header->max_value <= 15 && (header->flags & kChecksumFlag) != 0 &&
        header->reserved[0] == checksum_bytes(view_ + header->header_size, header->data_bytes);
    if (!valid) {
        UnmapViewOfFile(view_);
        CloseHandle(mapping);
        CloseHandle(file);
        view_ = nullptr;
        mapping_ = nullptr;
        file_ = nullptr;
        throw std::runtime_error("edge PDB header is invalid or incompatible");
    }
    data_ = view_ + header->header_size;
    max_value_ = static_cast<std::uint8_t>(header->max_value);
    complete_ = (header->flags & kCompleteFlag) != 0;
}

EdgePatternDatabase::~EdgePatternDatabase() {
    if (view_ != nullptr) UnmapViewOfFile(view_);
    if (mapping_ != nullptr) CloseHandle(static_cast<HANDLE>(mapping_));
    if (file_ != nullptr) CloseHandle(static_cast<HANDLE>(file_));
}

std::uint8_t EdgePatternDatabase::distance(std::uint32_t coordinate) const noexcept {
    const std::uint8_t packed = data_[coordinate >> 1U];
    return coordinate & 1U ? static_cast<std::uint8_t>(packed >> 4U)
                           : static_cast<std::uint8_t>(packed & 0x0FU);
}

bool EdgePatternDatabase::complete() const noexcept { return complete_; }

std::uint8_t EdgePatternDatabase::max_value() const noexcept { return max_value_; }

void build_corner_pattern_database(
    const std::filesystem::path& path,
    const CoordinateTables& tables,
    int threads,
    int coverage_depth,
    bool force) {
    if (coverage_depth < 0 || coverage_depth > 11) {
        throw std::invalid_argument("corner PDB coverage depth must be 0..11");
    }
    if (!force && std::filesystem::exists(path) && valid_existing_file(path, coverage_depth)) return;
    threads = std::clamp(threads > 0 ? threads : static_cast<int>(std::thread::hardware_concurrency()), 1, 64);
    std::filesystem::create_directories(path.parent_path());

    const auto started = std::chrono::steady_clock::now();
    auto distances = std::make_unique<std::atomic<std::uint8_t>[]>(kCornerPatternEntries);
    {
        std::vector<std::thread> initializers;
        for (int thread = 0; thread < threads; ++thread) {
            initializers.emplace_back([&, thread] {
                const std::uint64_t begin = kCornerPatternEntries * thread / threads;
                const std::uint64_t end = kCornerPatternEntries * (thread + 1) / threads;
                for (std::uint64_t index = begin; index < end; ++index) {
                    distances[index].store(255, std::memory_order_relaxed);
                }
            });
        }
        for (auto& initializer : initializers) initializer.join();
    }
    distances[0].store(0, std::memory_order_relaxed);
    std::vector<std::uint32_t> frontier{0};
    std::uint64_t discovered = 1;
    int depth = 0;

    while (!frontier.empty() && depth < coverage_depth) {
        std::atomic<std::size_t> cursor{0};
        std::vector<std::vector<std::uint32_t>> local_next(threads);
        std::vector<std::thread> workers;
        workers.reserve(threads);
        for (int thread = 0; thread < threads; ++thread) {
            workers.emplace_back([&, thread] {
                auto& output = local_next[thread];
                output.reserve(frontier.size() / threads + 1024);
                while (true) {
                    const std::size_t begin = cursor.fetch_add(4096, std::memory_order_relaxed);
                    if (begin >= frontier.size()) break;
                    const std::size_t end = std::min(frontier.size(), begin + 4096);
                    for (std::size_t item = begin; item < end; ++item) {
                        const std::uint32_t coordinate = frontier[item];
                        const std::uint16_t corner_perm = coordinate / 2187U;
                        const std::uint16_t twist = coordinate % 2187U;
                        for (int move = 0; move < 18; ++move) {
                            const std::uint32_t next =
                                static_cast<std::uint32_t>(tables.corner_move(corner_perm, move)) * 2187U +
                                tables.twist_move(twist, move);
                            std::uint8_t expected = 255;
                            if (distances[next].compare_exchange_strong(
                                    expected,
                                    static_cast<std::uint8_t>(depth + 1),
                                    std::memory_order_relaxed)) {
                                output.push_back(next);
                            }
                        }
                    }
                }
            });
        }
        for (auto& worker : workers) worker.join();

        std::size_t next_size = 0;
        for (const auto& values : local_next) next_size += values.size();
        std::vector<std::uint32_t> next;
        next.reserve(next_size);
        for (auto& values : local_next) {
            next.insert(next.end(), std::make_move_iterator(values.begin()), std::make_move_iterator(values.end()));
        }
        frontier = std::move(next);
        discovered += frontier.size();
        ++depth;
        const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        std::cerr << "corner-pdb depth=" << depth << " frontier=" << frontier.size()
                  << " discovered=" << discovered << " elapsed=" << elapsed << "s\n";
    }

    const bool complete = discovered == kCornerPatternEntries;
    const std::uint8_t unknown_value = static_cast<std::uint8_t>(std::min(15, depth + 1));
    std::vector<std::uint8_t> packed((kCornerPatternEntries + 1) / 2, 0);
    std::atomic<std::uint64_t> unknown_count{0};
    {
        std::vector<std::thread> packers;
        for (int thread = 0; thread < threads; ++thread) {
            packers.emplace_back([&, thread] {
                const std::uint64_t begin_byte = packed.size() * thread / threads;
                const std::uint64_t end_byte = packed.size() * (thread + 1) / threads;
                std::uint64_t local_unknown = 0;
                for (std::uint64_t byte_index = begin_byte; byte_index < end_byte; ++byte_index) {
                    const std::uint64_t first = byte_index * 2;
                    std::uint8_t low = distances[first].load(std::memory_order_relaxed);
                    std::uint8_t high = first + 1 < kCornerPatternEntries
                        ? distances[first + 1].load(std::memory_order_relaxed)
                        : 0;
                    if (low == 255) {
                        low = unknown_value;
                        ++local_unknown;
                    }
                    if (high == 255) {
                        high = unknown_value;
                        ++local_unknown;
                    }
                    packed[byte_index] = static_cast<std::uint8_t>((high << 4U) | low);
                }
                unknown_count.fetch_add(local_unknown, std::memory_order_relaxed);
            });
        }
        for (auto& packer : packers) packer.join();
    }

    PdbHeader header;
    header.magic = kMagic;
    header.version = kVersion;
    header.header_size = sizeof(PdbHeader);
    header.metric = kMetricHtm;
    header.pattern = kPatternCorners;
    header.bits_per_entry = 4;
    header.max_value = complete ? static_cast<std::uint32_t>(depth) : unknown_value;
    header.flags = (complete ? kCompleteFlag : 0) | kChecksumFlag;
    header.entry_count = kCornerPatternEntries;
    header.data_bytes = packed.size();
    header.reserved[0] = checksum_bytes(packed.data(), packed.size());

    const std::filesystem::path temporary = path.string() + ".tmp";
    {
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        if (!output) throw std::runtime_error("cannot create corner PDB temporary file");
        output.write(reinterpret_cast<const char*>(&header), sizeof(header));
        output.write(reinterpret_cast<const char*>(packed.data()), static_cast<std::streamsize>(packed.size()));
        output.flush();
        if (!output) throw std::runtime_error("failed while writing corner PDB");
    }
    std::error_code error;
    std::filesystem::remove(path, error);
    error.clear();
    std::filesystem::rename(temporary, path, error);
    if (error) throw std::runtime_error("cannot atomically publish corner PDB: " + error.message());
    std::cerr << "corner-pdb complete=" << complete << " unknown=" << unknown_count.load()
              << " file=" << path.string() << "\n";
}

void build_edge_pattern_database(
    const std::filesystem::path& path,
    int group,
    int threads,
    int coverage_depth,
    bool force) {
    if (group < 0 || group > 7) throw std::invalid_argument("edge pattern group must be 0..7");
    if (coverage_depth < 0 || coverage_depth > 10) {
        throw std::invalid_argument("edge PDB coverage depth must be 0..10");
    }
    if (!force && std::filesystem::exists(path) && valid_existing_edge_file(path, group, coverage_depth)) return;
    threads = std::clamp(threads > 0 ? threads : static_cast<int>(std::thread::hardware_concurrency()), 1, 64);
    std::filesystem::create_directories(path.parent_path());

    const auto started = std::chrono::steady_clock::now();
    auto distances = std::make_unique<std::atomic<std::uint8_t>[]>(kEdgePatternEntries);
    {
        std::vector<std::thread> initializers;
        for (int thread = 0; thread < threads; ++thread) {
            initializers.emplace_back([&, thread] {
                const std::uint64_t begin = kEdgePatternEntries * thread / threads;
                const std::uint64_t end = kEdgePatternEntries * (thread + 1) / threads;
                for (std::uint64_t index = begin; index < end; ++index) {
                    distances[index].store(255, std::memory_order_relaxed);
                }
            });
        }
        for (auto& initializer : initializers) initializer.join();
    }
    const EdgePatternState solved_pattern = edge_pattern_state(CubieCube{}, edge_pattern_group(group));
    const std::uint32_t solved_coordinate = edge_pattern_coord(solved_pattern);
    distances[solved_coordinate].store(0, std::memory_order_relaxed);
    std::vector<std::uint32_t> frontier{solved_coordinate};
    std::uint64_t discovered = 1;
    int depth = 0;

    while (!frontier.empty() && depth < coverage_depth) {
        std::atomic<std::size_t> cursor{0};
        std::vector<std::vector<std::uint32_t>> local_next(threads);
        std::vector<std::thread> workers;
        workers.reserve(threads);
        for (int thread = 0; thread < threads; ++thread) {
            workers.emplace_back([&, thread] {
                auto& output = local_next[thread];
                output.reserve(frontier.size() / threads + 1024);
                while (true) {
                    const std::size_t begin = cursor.fetch_add(2048, std::memory_order_relaxed);
                    if (begin >= frontier.size()) break;
                    const std::size_t end = std::min(frontier.size(), begin + 2048);
                    for (std::size_t item = begin; item < end; ++item) {
                        const EdgePatternState state = edge_pattern_from_coord(frontier[item]);
                        for (int move = 0; move < 18; ++move) {
                            const std::uint32_t next = edge_pattern_coord(move_edge_pattern(state, move));
                            std::uint8_t expected = 255;
                            if (distances[next].compare_exchange_strong(
                                    expected,
                                    static_cast<std::uint8_t>(depth + 1),
                                    std::memory_order_relaxed)) {
                                output.push_back(next);
                            }
                        }
                    }
                }
            });
        }
        for (auto& worker : workers) worker.join();

        std::size_t next_size = 0;
        for (const auto& values : local_next) next_size += values.size();
        std::vector<std::uint32_t> next;
        next.reserve(next_size);
        for (auto& values : local_next) {
            next.insert(next.end(), std::make_move_iterator(values.begin()), std::make_move_iterator(values.end()));
        }
        frontier = std::move(next);
        discovered += frontier.size();
        ++depth;
        const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        std::cerr << "edge-pdb-" << group << " depth=" << depth << " frontier=" << frontier.size()
                  << " discovered=" << discovered << " elapsed=" << elapsed << "s\n";
    }

    const bool complete = discovered == kEdgePatternEntries;
    const std::uint8_t unknown_value = static_cast<std::uint8_t>(std::min(15, depth + 1));
    std::vector<std::uint8_t> packed((kEdgePatternEntries + 1) / 2, 0);
    std::atomic<std::uint64_t> unknown_count{0};
    {
        std::vector<std::thread> packers;
        for (int thread = 0; thread < threads; ++thread) {
            packers.emplace_back([&, thread] {
                const std::uint64_t begin_byte = packed.size() * thread / threads;
                const std::uint64_t end_byte = packed.size() * (thread + 1) / threads;
                std::uint64_t local_unknown = 0;
                for (std::uint64_t byte_index = begin_byte; byte_index < end_byte; ++byte_index) {
                    const std::uint64_t first = byte_index * 2;
                    std::uint8_t low = distances[first].load(std::memory_order_relaxed);
                    std::uint8_t high = first + 1 < kEdgePatternEntries
                        ? distances[first + 1].load(std::memory_order_relaxed)
                        : 0;
                    if (low == 255) {
                        low = unknown_value;
                        ++local_unknown;
                    }
                    if (high == 255) {
                        high = unknown_value;
                        ++local_unknown;
                    }
                    packed[byte_index] = static_cast<std::uint8_t>((high << 4U) | low);
                }
                unknown_count.fetch_add(local_unknown, std::memory_order_relaxed);
            });
        }
        for (auto& packer : packers) packer.join();
    }

    PdbHeader header;
    header.magic = kMagic;
    header.version = kVersion;
    header.header_size = sizeof(PdbHeader);
    header.metric = kMetricHtm;
    header.pattern = kPatternEdgesA + static_cast<std::uint32_t>(group);
    header.bits_per_entry = 4;
    header.max_value = complete ? static_cast<std::uint32_t>(depth) : unknown_value;
    header.flags = (complete ? kCompleteFlag : 0) | kChecksumFlag;
    header.entry_count = kEdgePatternEntries;
    header.data_bytes = packed.size();
    header.reserved[0] = checksum_bytes(packed.data(), packed.size());

    const std::filesystem::path temporary = path.string() + ".tmp";
    {
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        if (!output) throw std::runtime_error("cannot create edge PDB temporary file");
        output.write(reinterpret_cast<const char*>(&header), sizeof(header));
        output.write(reinterpret_cast<const char*>(packed.data()), static_cast<std::streamsize>(packed.size()));
        output.flush();
        if (!output) throw std::runtime_error("failed while writing edge PDB");
    }
    std::error_code error;
    std::filesystem::remove(path, error);
    error.clear();
    std::filesystem::rename(temporary, path, error);
    if (error) throw std::runtime_error("cannot atomically publish edge PDB: " + error.message());
    std::cerr << "edge-pdb-" << group << " complete=" << complete << " unknown=" << unknown_count.load()
              << " file=" << path.string() << "\n";
}

void build_phase1_pattern_database(
    const std::filesystem::path& path,
    const CoordinateTables& tables,
    int threads,
    int coverage_depth,
    bool force) {
    if (coverage_depth < 0 || coverage_depth > 12) {
        throw std::invalid_argument("phase-1 PDB coverage depth must be 0..12");
    }
    if (!force && std::filesystem::exists(path) && valid_existing_phase1_file(path, coverage_depth)) return;
    threads = std::clamp(threads > 0 ? threads : static_cast<int>(std::thread::hardware_concurrency()), 1, 64);
    std::filesystem::create_directories(path.parent_path());

    const auto started = std::chrono::steady_clock::now();
    Phase1Symmetry symmetry;
    if (symmetry.class_count() != kFlipSliceClassCount) {
        throw std::runtime_error("phase-1 symmetry class count changed unexpectedly");
    }

    // For a canonical raw representative, a move produces another raw state.
    // Record both its class and the symmetry that returns it to that class's
    // representative. This turns the BFS hot loop into indexed table reads.
    constexpr std::size_t move_count = 18;
    const std::size_t class_move_count = static_cast<std::size_t>(kFlipSliceClassCount) * move_count;
    std::vector<std::uint32_t> next_class(class_move_count);
    std::vector<std::uint8_t> next_symmetry(class_move_count);
    std::vector<std::uint16_t> stabilizer_masks(kFlipSliceClassCount, 1U);
    for (std::uint32_t class_index = 0; class_index < kFlipSliceClassCount; ++class_index) {
        const std::uint32_t raw = symmetry.representative(class_index);
        const std::uint16_t flip = static_cast<std::uint16_t>(raw / 495U);
        const std::uint16_t slice = static_cast<std::uint16_t>(raw % 495U);
        for (int move = 0; move < 18; ++move) {
            const std::uint32_t moved_raw =
                static_cast<std::uint32_t>(tables.flip_move(flip, move)) * 495U + tables.slice_move(slice, move);
            const std::size_t table_index = static_cast<std::size_t>(class_index) * move_count + move;
            next_class[table_index] = symmetry.class_index(moved_raw);
            next_symmetry[table_index] = symmetry.symmetry_to_representative(moved_raw);
        }
        for (int symmetry_index = 1; symmetry_index < kPhase1SymmetryCount; ++symmetry_index) {
            if (symmetry.flip_slice_conjugate(raw, symmetry_index) == raw) {
                stabilizer_masks[class_index] |= static_cast<std::uint16_t>(1U << symmetry_index);
            }
        }
    }

    auto distances = std::make_unique<std::atomic<std::uint8_t>[]>(kPhase1PatternEntries);
    {
        std::vector<std::thread> initializers;
        for (int thread = 0; thread < threads; ++thread) {
            initializers.emplace_back([&, thread] {
                const std::uint64_t begin = kPhase1PatternEntries * thread / threads;
                const std::uint64_t end = kPhase1PatternEntries * (thread + 1) / threads;
                for (std::uint64_t index = begin; index < end; ++index) {
                    distances[index].store(255, std::memory_order_relaxed);
                }
            });
        }
        for (auto& initializer : initializers) initializer.join();
    }

    const std::uint16_t solved_slice = slice_comb_coord(CubieCube{});
    const std::uint32_t solved_coordinate = symmetry.canonical_index(0, 0, solved_slice);
    distances[solved_coordinate].store(0, std::memory_order_relaxed);
    std::vector<std::uint32_t> frontier{solved_coordinate};
    std::uint64_t discovered = 1;
    int depth = 0;

    while (!frontier.empty() && depth < coverage_depth) {
        std::atomic<std::size_t> cursor{0};
        std::vector<std::vector<std::uint32_t>> local_next(threads);
        std::vector<std::thread> workers;
        workers.reserve(threads);
        for (int thread = 0; thread < threads; ++thread) {
            workers.emplace_back([&, thread] {
                auto& output = local_next[thread];
                output.reserve(frontier.size() / threads + 1024);
                while (true) {
                    const std::size_t begin = cursor.fetch_add(4096, std::memory_order_relaxed);
                    if (begin >= frontier.size()) break;
                    const std::size_t end = std::min(frontier.size(), begin + 4096);
                    for (std::size_t item = begin; item < end; ++item) {
                        const std::uint32_t coordinate = frontier[item];
                        const std::uint32_t class_index = coordinate / 2187U;
                        const std::uint16_t twist = static_cast<std::uint16_t>(coordinate % 2187U);
                        const std::size_t class_move_base = static_cast<std::size_t>(class_index) * move_count;
                        for (int move = 0; move < 18; ++move) {
                            const std::size_t table_index = class_move_base + move;
                            const std::uint16_t moved_twist = tables.twist_move(twist, move);
                            const std::uint16_t canonical_twist =
                                symmetry.twist_conjugate(moved_twist, next_symmetry[table_index]);
                            const std::uint32_t child_class = next_class[table_index];
                            std::uint16_t stabilizers = stabilizer_masks[child_class];
                            while (stabilizers != 0) {
                                const int stabilizer = std::countr_zero(stabilizers);
                                stabilizers &= static_cast<std::uint16_t>(stabilizers - 1U);
                                const std::uint16_t equivalent_twist =
                                    symmetry.twist_conjugate(canonical_twist, stabilizer);
                                const std::uint32_t next = child_class * 2187U + equivalent_twist;
                                std::uint8_t expected = 255;
                                if (distances[next].compare_exchange_strong(
                                        expected,
                                        static_cast<std::uint8_t>(depth + 1),
                                        std::memory_order_relaxed)) {
                                    output.push_back(next);
                                }
                            }
                        }
                    }
                }
            });
        }
        for (auto& worker : workers) worker.join();

        std::size_t next_size = 0;
        for (const auto& values : local_next) next_size += values.size();
        std::vector<std::uint32_t> next;
        next.reserve(next_size);
        for (auto& values : local_next) {
            next.insert(next.end(), std::make_move_iterator(values.begin()), std::make_move_iterator(values.end()));
        }
        frontier = std::move(next);
        discovered += frontier.size();
        ++depth;
        const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        std::cerr << "phase1-pdb depth=" << depth << " frontier=" << frontier.size()
                  << " discovered=" << discovered << " elapsed=" << elapsed << "s\n";
    }

    const bool complete = discovered == kPhase1PatternEntries;
    const std::uint8_t unknown_value = static_cast<std::uint8_t>(std::min(15, depth + 1));
    std::vector<std::uint8_t> packed((kPhase1PatternEntries + 1) / 2, 0);
    std::atomic<std::uint64_t> unknown_count{0};
    {
        std::vector<std::thread> packers;
        for (int thread = 0; thread < threads; ++thread) {
            packers.emplace_back([&, thread] {
                const std::uint64_t begin_byte = packed.size() * thread / threads;
                const std::uint64_t end_byte = packed.size() * (thread + 1) / threads;
                std::uint64_t local_unknown = 0;
                for (std::uint64_t byte_index = begin_byte; byte_index < end_byte; ++byte_index) {
                    const std::uint64_t first = byte_index * 2;
                    std::uint8_t low = distances[first].load(std::memory_order_relaxed);
                    std::uint8_t high = first + 1 < kPhase1PatternEntries
                        ? distances[first + 1].load(std::memory_order_relaxed)
                        : 0;
                    if (low == 255) {
                        low = unknown_value;
                        ++local_unknown;
                    }
                    if (high == 255) {
                        high = unknown_value;
                        ++local_unknown;
                    }
                    packed[byte_index] = static_cast<std::uint8_t>((high << 4U) | low);
                }
                unknown_count.fetch_add(local_unknown, std::memory_order_relaxed);
            });
        }
        for (auto& packer : packers) packer.join();
    }

    PdbHeader header;
    header.magic = kMagic;
    header.version = kVersion;
    header.header_size = sizeof(PdbHeader);
    header.metric = kMetricHtm;
    header.pattern = kPatternPhase1Symmetry;
    header.bits_per_entry = 4;
    header.max_value = complete ? static_cast<std::uint32_t>(depth) : unknown_value;
    header.flags = (complete ? kCompleteFlag : 0) | kChecksumFlag;
    header.entry_count = kPhase1PatternEntries;
    header.data_bytes = packed.size();
    header.reserved[0] = checksum_bytes(packed.data(), packed.size());

    const std::filesystem::path temporary = path.string() + ".tmp";
    {
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        if (!output) throw std::runtime_error("cannot create phase-1 PDB temporary file");
        output.write(reinterpret_cast<const char*>(&header), sizeof(header));
        output.write(reinterpret_cast<const char*>(packed.data()), static_cast<std::streamsize>(packed.size()));
        output.flush();
        if (!output) throw std::runtime_error("failed while writing phase-1 PDB");
    }
    std::error_code error;
    std::filesystem::remove(path, error);
    error.clear();
    std::filesystem::rename(temporary, path, error);
    if (error) throw std::runtime_error("cannot atomically publish phase-1 PDB: " + error.message());
    std::cerr << "phase1-pdb complete=" << complete << " unknown=" << unknown_count.load()
              << " file=" << path.string() << "\n";
}

}  // namespace cube
