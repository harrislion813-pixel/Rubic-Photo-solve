#include "strong_pdb.hpp"
#include "loader.hpp"

#include "paths.hpp"
#include "solver.hpp"

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <thread>
#include <tuple>
#include <vector>

namespace cube {
namespace {

constexpr std::array<char, 8> kMagic{'R', 'C', 'P', 'D', 'B', '0', '1', '\0'};
constexpr std::uint32_t kVersion = 3;
constexpr std::uint32_t kNibbleVersion = 4;
constexpr std::uint32_t kMetricQtm = 2;
constexpr std::uint32_t kPatternStrong = 11;
constexpr std::uint32_t kCoordinateVersion = 2;
constexpr std::uint32_t kBuilderVersion = 1;
constexpr std::uint32_t kCompleteFlag = 1;
constexpr std::uint32_t kChecksumFlag = 2;
constexpr std::array<int, 12> kQuarterMoves{0, 2, 3, 5, 6, 8, 9, 11, 12, 14, 15, 17};
constexpr std::uint64_t kClassStride = 2048ULL * 2187ULL;
constexpr std::uint64_t kWordCount = (kStrongPatternEntries + 63ULL) / 64ULL;
constexpr std::uint64_t kNibbleDataBytes = kStrongPatternEntries / 2ULL;
constexpr std::uint64_t kNibbleChunkBytes = 64ULL * 1024ULL * 1024ULL;
constexpr std::uint64_t kNibbleChunkCount = (kNibbleDataBytes + kNibbleChunkBytes - 1ULL) / kNibbleChunkBytes;
static_assert(sizeof(std::atomic<std::uint8_t>) == 1);

#pragma pack(push, 1)
struct StrongHeader {
    std::array<char, 8> magic{};
    std::uint32_t version{};
    std::uint32_t header_size{};
    std::uint32_t metric{};
    std::uint32_t pattern{};
    std::uint32_t coordinate_version{};
    std::uint32_t bits_per_entry{};
    std::uint32_t coverage_depth{};
    std::uint32_t max_distance{};
    std::uint32_t flags{};
    std::uint32_t builder_version{};
    std::uint64_t entry_count{};
    std::uint64_t data_bytes{};
    std::uint64_t unknown_count{};
    std::uint64_t checksum{};
};
#pragma pack(pop)
static_assert(sizeof(StrongHeader) == 80);

std::runtime_error windows_error(const char *operation) {
    return std::runtime_error(std::string(operation) + " failed with Windows error " + std::to_string(GetLastError()));
}

std::uint64_t checksum_bytes(const std::uint8_t *data, std::uint64_t size) noexcept {
    std::uint64_t checksum = 1469598103934665603ULL;
    for (std::uint64_t index = 0; index < size; ++index)
        checksum = (checksum ^ data[index]) * 1099511628211ULL;
    return checksum;
}

bool valid_header(const StrongHeader &header, std::uint64_t file_bytes) noexcept {
    return header.magic == kMagic && header.version == kVersion && header.header_size == sizeof(StrongHeader) &&
           header.metric == kMetricQtm && header.pattern == kPatternStrong &&
           header.coordinate_version == kCoordinateVersion && header.builder_version == kBuilderVersion &&
           header.bits_per_entry == 8 && header.entry_count == kStrongPatternEntries &&
           header.data_bytes == kStrongPatternEntries && file_bytes == sizeof(StrongHeader) + kStrongPatternEntries &&
           header.coverage_depth < 255 && header.max_distance <= header.coverage_depth &&
           header.unknown_count <= kStrongPatternEntries &&
           ((header.flags & kCompleteFlag) != 0) == (header.unknown_count == 0) && (header.flags & kChecksumFlag) != 0;
}

bool valid_nibble_header(const StrongHeader &header, std::uint64_t file_bytes) noexcept {
    return header.magic == kMagic && header.version == kNibbleVersion &&
           header.header_size == sizeof(StrongHeader) + kNibbleChunkCount * sizeof(std::uint64_t) &&
           header.metric == kMetricQtm && header.pattern == kPatternStrong &&
           header.coordinate_version == kCoordinateVersion && header.builder_version == kBuilderVersion &&
           header.bits_per_entry == 4 && header.entry_count == kStrongPatternEntries &&
           header.data_bytes == kNibbleDataBytes && file_bytes == header.header_size + header.data_bytes &&
           header.coverage_depth < 15 && header.max_distance <= 14 && header.max_distance <= header.coverage_depth &&
           header.unknown_count == 0 &&
           (header.flags & (kCompleteFlag | kChecksumFlag)) == (kCompleteFlag | kChecksumFlag);
}

StrongHeader make_header(int depth, std::uint64_t discovered, const std::uint8_t *data) {
    StrongHeader header;
    header.magic = kMagic;
    header.version = kVersion;
    header.header_size = sizeof(header);
    header.metric = kMetricQtm;
    header.pattern = kPatternStrong;
    header.coordinate_version = kCoordinateVersion;
    header.bits_per_entry = 8;
    header.coverage_depth = static_cast<std::uint32_t>(depth);
    header.max_distance = static_cast<std::uint32_t>(depth);
    header.flags = (discovered == kStrongPatternEntries ? kCompleteFlag : 0) | kChecksumFlag;
    header.builder_version = kBuilderVersion;
    header.entry_count = kStrongPatternEntries;
    header.data_bytes = kStrongPatternEntries;
    header.unknown_count = kStrongPatternEntries - discovered;
    header.checksum = checksum_bytes(data, kStrongPatternEntries);
    return header;
}

struct Stabilizer {
    std::uint8_t symmetry{};
    std::vector<std::uint16_t> flip;
};

struct StrongTransitions {
    explicit StrongTransitions(const SortedSliceSymmetry &symmetry, const CoordinateTables &tables) {
        const std::size_t move_slots = static_cast<std::size_t>(symmetry.class_count()) * kQuarterMoves.size();
        next_class.resize(move_slots);
        next_flip.resize(move_slots * 2048U);
        next_twist.resize(move_slots * 2187U);
        stabilizers.resize(symmetry.class_count());
        for (std::uint16_t class_index = 0; class_index < symmetry.class_count(); ++class_index) {
            const auto representative = symmetry.representative(class_index);
            const auto base_cube = cube_from_sorted_slice(representative);
            for (std::size_t quarter = 0; quarter < kQuarterMoves.size(); ++quarter) {
                const int move = kQuarterMoves[quarter];
                const std::size_t slot = static_cast<std::size_t>(class_index) * kQuarterMoves.size() + quarter;
                const auto moved_sorted = symmetry.moved(representative, move);
                const auto mapping = symmetry.symmetry_to_representative(moved_sorted);
                next_class[slot] = symmetry.class_index(moved_sorted);
                for (std::uint16_t flip = 0; flip < 2048; ++flip) {
                    auto source = base_cube;
                    source.eo = cube_from_flip(flip).eo;
                    const auto moved = source.apply_move(move);
                    const auto canonical = symmetry.phase1().conjugate_edges(moved, mapping);
                    next_flip[slot * 2048U + flip] = flip_coord(canonical);
                }
                for (std::uint16_t twist = 0; twist < 2187; ++twist)
                    next_twist[slot * 2187U + twist] =
                        symmetry.phase1().twist_conjugate(tables.twist_move(twist, move), mapping);
            }
            auto mask = symmetry.stabilizer_mask(class_index);
            mask &= static_cast<std::uint16_t>(mask - 1U); // The identity slot is emitted directly.
            while (mask != 0) {
                const int sym = std::countr_zero(mask);
                mask &= static_cast<std::uint16_t>(mask - 1U);
                Stabilizer stabilizer;
                stabilizer.symmetry = static_cast<std::uint8_t>(sym);
                stabilizer.flip.resize(2048);
                for (std::uint16_t flip = 0; flip < 2048; ++flip)
                    stabilizer.flip[flip] = symmetry.flip_conjugate(flip, representative, sym);
                stabilizers[class_index].push_back(std::move(stabilizer));
            }
        }
    }

    std::vector<std::uint16_t> next_class;
    std::vector<std::uint16_t> next_flip;
    std::vector<std::uint16_t> next_twist;
    std::vector<std::vector<Stabilizer>> stabilizers;
};

} // namespace

StrongChunkValidation validate_strong_chunk(std::span<const std::uint8_t> bytes, std::uint8_t coverage_depth,
                                            StrongValidationMode mode) {
    StrongChunkValidation result;
    const auto started = std::chrono::steady_clock::now();
    if (mode == StrongValidationMode::Split) {
        result.checksum = checksum_bytes(bytes.data(), bytes.size());
        const auto nibble_started = std::chrono::steady_clock::now();
        result.checksum_seconds = std::chrono::duration<double>(nibble_started - started).count();
        std::uint8_t maximum = 0;
        for (const auto value : bytes)
            maximum =
                std::max({maximum, static_cast<std::uint8_t>(value & 15U), static_cast<std::uint8_t>(value >> 4U)});
        result.maximum = maximum;
        result.valid = maximum < 15 && maximum <= coverage_depth;
        result.nibble_seconds =
            std::chrono::duration<double>(std::chrono::steady_clock::now() - nibble_started).count();
    } else {
        static constexpr auto maxima = [] {
            std::array<std::uint8_t, 256> values{};
            for (std::size_t value = 0; value < values.size(); ++value)
                values[value] = static_cast<std::uint8_t>(std::max(value & 15U, value >> 4U));
            return values;
        }();
        for (const auto value : bytes) {
            result.checksum = (result.checksum ^ value) * 1099511628211ULL;
            if (mode == StrongValidationMode::Legacy) {
                const auto low = static_cast<std::uint8_t>(value & 15U);
                const auto high = static_cast<std::uint8_t>(value >> 4U);
                if (low == 15 || high == 15 || low > coverage_depth || high > coverage_depth) {
                    result.valid = false;
                    break;
                }
                result.maximum = std::max({result.maximum, low, high});
            } else
                result.maximum = std::max(result.maximum, maxima[value]);
        }
        result.valid &= result.maximum < 15 && result.maximum <= coverage_depth;
    }
    return result;
}

StrongPatternDatabase::StrongPatternDatabase(const std::filesystem::path &path, LoaderControl *loader,
                                             StrongValidationMode mode) {
    LoaderControl::Participant coordinator(loader);
    const auto started = std::chrono::steady_clock::now();
    symmetry_ = std::make_shared<SortedSliceSymmetry>([&] { coordinator.checkpoint(); });
    symmetry_initialization_seconds_ =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    if (symmetry_->class_count() != 788)
        throw std::runtime_error("strong PDB symmetry class count changed");
    const auto mapping_started = std::chrono::steady_clock::now();
    const auto absolute = std::filesystem::absolute(path);
    HANDLE file = CreateFileW(absolute.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE)
        throw windows_error("open strong PDB");
    file_ = file;
    LARGE_INTEGER size{};
    if (!GetFileSizeEx(file, &size) || size.QuadPart < static_cast<LONGLONG>(sizeof(StrongHeader))) {
        CloseHandle(file);
        file_ = nullptr;
        throw std::runtime_error("strong PDB size is invalid");
    }
    HANDLE mapping = CreateFileMappingW(file, nullptr, PAGE_READONLY, 0, 0, nullptr);
    if (mapping == nullptr) {
        CloseHandle(file);
        file_ = nullptr;
        throw windows_error("map strong PDB");
    }
    mapping_ = mapping;
    view_ = static_cast<const std::uint8_t *>(MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0));
    if (view_ == nullptr) {
        CloseHandle(mapping);
        CloseHandle(file);
        mapping_ = nullptr;
        file_ = nullptr;
        throw windows_error("view strong PDB");
    }
    const auto *header = reinterpret_cast<const StrongHeader *>(view_);
    const bool nibble = valid_nibble_header(*header, static_cast<std::uint64_t>(size.QuadPart));
    const bool byte = valid_header(*header, static_cast<std::uint64_t>(size.QuadPart));
    const auto *data = view_ + (nibble ? header->header_size : sizeof(StrongHeader));
    bool valid = nibble || byte;
    mapping_seconds_ = std::chrono::duration<double>(std::chrono::steady_clock::now() - mapping_started).count();
    if (nibble) {
        const auto *chunk_checksums = view_ + sizeof(StrongHeader);
        valid = checksum_bytes(chunk_checksums, kNibbleChunkCount * sizeof(std::uint64_t)) == header->checksum;
        if (valid) {
            struct ChunkResult {
                bool valid{true};
                std::uint8_t maximum{};
                double checksum_seconds{};
                double nibble_seconds{};
            };
            const int thread_count = std::clamp(
                loader && loader->threads > 0 ? loader->threads : static_cast<int>(std::thread::hardware_concurrency()),
                1, 8);
            std::atomic<std::uint64_t> cursor{0};
            std::vector<ChunkResult> results(static_cast<std::size_t>(thread_count));
            std::vector<std::thread> workers;
            workers.reserve(static_cast<std::size_t>(thread_count));
            for (int thread = 0; thread < thread_count; ++thread)
                workers.emplace_back([&, thread] {
                    LoaderControl::Participant participant(loader);
                    auto &part = results[static_cast<std::size_t>(thread)];
                    while (part.valid) {
                        participant.checkpoint();
                        const auto chunk = cursor.fetch_add(1, std::memory_order_relaxed);
                        if (chunk >= kNibbleChunkCount)
                            break;
                        const auto offset = chunk * kNibbleChunkBytes;
                        const auto length = std::min(kNibbleChunkBytes, kNibbleDataBytes - offset);
                        std::uint64_t expected;
                        std::memcpy(&expected, chunk_checksums + chunk * sizeof(expected), sizeof(expected));
                        const auto checked =
                            validate_strong_chunk({data + offset, static_cast<std::size_t>(length)},
                                                  static_cast<std::uint8_t>(header->coverage_depth), mode);
                        part.valid &= checked.valid && checked.checksum == expected;
                        part.maximum = std::max(part.maximum, checked.maximum);
                        part.checksum_seconds += checked.checksum_seconds;
                        part.nibble_seconds += checked.nibble_seconds;
                    }
                });
            coordinator.suspend();
            for (auto &worker : workers)
                worker.join();
            coordinator.resume();
            std::uint8_t maximum = 0;
            for (const auto &part : results) {
                valid &= part.valid;
                maximum = std::max(maximum, part.maximum);
                checksum_worker_seconds_ += part.checksum_seconds;
                nibble_worker_seconds_ += part.nibble_seconds;
            }
            valid &= maximum == header->max_distance;
        }
    } else if (byte) {
        std::uint64_t checksum = 1469598103934665603ULL;
        std::uint64_t unknown = 0;
        std::uint8_t maximum = 0;
        for (std::uint64_t index = 0; index < kStrongPatternEntries; ++index) {
            if (index % (4ULL << 20U) == 0)
                coordinator.checkpoint();
            const auto distance = data[index];
            checksum = (checksum ^ distance) * 1099511628211ULL;
            if (distance == 255)
                ++unknown;
            else if (distance > header->coverage_depth) {
                valid = false;
                break;
            } else
                maximum = std::max(maximum, distance);
        }
        valid = valid && checksum == header->checksum && unknown == header->unknown_count &&
                maximum == header->max_distance;
    }
    if (!valid) {
        UnmapViewOfFile(view_);
        CloseHandle(mapping);
        CloseHandle(file);
        view_ = nullptr;
        mapping_ = nullptr;
        file_ = nullptr;
        throw std::runtime_error("strong PDB header or checksum is invalid");
    }
    data_ = data;
    packed_ = nibble;
    coverage_depth_ = static_cast<int>(header->coverage_depth);
    max_distance_ = static_cast<std::uint8_t>(header->max_distance);
    complete_ = (header->flags & kCompleteFlag) != 0;
    verification_seconds_ = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count() -
                            symmetry_initialization_seconds_;
}

StrongPatternDatabase::~StrongPatternDatabase() {
    if (view_ != nullptr)
        UnmapViewOfFile(view_);
    if (mapping_ != nullptr)
        CloseHandle(static_cast<HANDLE>(mapping_));
    if (file_ != nullptr)
        CloseHandle(static_cast<HANDLE>(file_));
}

std::uint8_t StrongPatternDatabase::distance(std::uint16_t twist, std::uint16_t flip, std::uint16_t sorted,
                                             bool affine) const noexcept {
    return load_distance(prepare_index(twist, flip, sorted, affine));
}

std::uint64_t StrongPatternDatabase::prepare_index(std::uint16_t twist, std::uint16_t flip, std::uint16_t sorted,
                                                   bool affine) const noexcept {
    return affine ? symmetry_->canonical_index(twist, flip, sorted)
                  : symmetry_->canonical_index_reference(twist, flip, sorted);
}

std::uint8_t StrongPatternDatabase::load_distance(std::uint64_t index) const noexcept {
    const auto value = raw_distance(index);
    return value == 255 ? static_cast<std::uint8_t>(coverage_depth_ + 1) : value;
}

void StrongPatternDatabase::prefetch(std::uint64_t index) const noexcept {
    __builtin_prefetch(data_ + (packed_ ? index >> 1U : index), 0, 1);
}

std::uint8_t StrongPatternDatabase::raw_distance(std::uint64_t index) const noexcept {
    if (!packed_)
        return data_[index];
    return static_cast<std::uint8_t>((data_[index >> 1U] >> ((index & 1U) * 4U)) & 15U);
}

std::uint16_t StrongPatternDatabase::sorted_move(std::uint16_t sorted, int move) const noexcept {
    return symmetry_->moved(sorted, move);
}

bool StrongPatternDatabase::complete() const noexcept { return complete_; }
int StrongPatternDatabase::coverage_depth() const noexcept { return coverage_depth_; }
std::uint8_t StrongPatternDatabase::max_distance() const noexcept { return max_distance_; }
bool StrongPatternDatabase::packed() const noexcept { return packed_; }
double StrongPatternDatabase::symmetry_initialization_seconds() const noexcept {
    return symmetry_initialization_seconds_;
}
double StrongPatternDatabase::verification_seconds() const noexcept { return verification_seconds_; }
double StrongPatternDatabase::mapping_seconds() const noexcept { return mapping_seconds_; }
double StrongPatternDatabase::checksum_worker_seconds() const noexcept { return checksum_worker_seconds_; }
double StrongPatternDatabase::nibble_worker_seconds() const noexcept { return nibble_worker_seconds_; }

StrongVerification StrongPatternDatabase::verify_all(const CoordinateTables &tables, int threads) const {
    if (!complete_)
        throw std::invalid_argument("full strong PDB certificate requires complete coverage");
    threads = std::clamp(threads, 1, 64);
    StrongTransitions transitions(*symmetry_, tables);
    const auto goal = symmetry_->canonical_index(0, 0, sorted_slice_coord(CubieCube{}));
    std::atomic<bool> failed{false};
    std::atomic<std::uint32_t> cursor{0};
    std::vector<StrongVerification> local(static_cast<std::size_t>(threads));
    std::vector<std::thread> workers;
    workers.reserve(threads);
    for (int thread = 0; thread < threads; ++thread) {
        workers.emplace_back([&, thread] {
            auto &result = local[static_cast<std::size_t>(thread)];
            while (!failed.load(std::memory_order_relaxed)) {
                const auto class_index = cursor.fetch_add(1, std::memory_order_relaxed);
                if (class_index >= symmetry_->class_count())
                    break;
                for (std::uint32_t flip = 0; flip < 2048 && !failed.load(std::memory_order_relaxed); ++flip) {
                    for (std::uint32_t twist = 0; twist < 2187; ++twist) {
                        const auto index = (static_cast<std::uint64_t>(class_index) * 2048U + flip) * 2187U + twist;
                        const auto distance = raw_distance(index);
                        if (distance == 255 || (distance == 0) != (index == goal)) {
                            failed.store(true, std::memory_order_relaxed);
                            break;
                        }
                        ++result.entries;
                        ++result.distance_histogram[distance];
                        bool predecessor = distance == 0;
                        for (std::size_t quarter = 0; quarter < kQuarterMoves.size(); ++quarter) {
                            const std::size_t slot =
                                static_cast<std::size_t>(class_index) * kQuarterMoves.size() + quarter;
                            const auto child_class = transitions.next_class[slot];
                            const auto child_flip = transitions.next_flip[slot * 2048U + flip];
                            const auto child_twist = transitions.next_twist[slot * 2187U + twist];
                            const auto child =
                                (static_cast<std::uint64_t>(child_class) * 2048U + child_flip) * 2187U + child_twist;
                            const auto next_distance = raw_distance(child);
                            if (next_distance + 1U < distance || distance + 1U < next_distance) {
                                failed.store(true, std::memory_order_relaxed);
                                break;
                            }
                            predecessor |= next_distance + 1U == distance;
                        }
                        if (!predecessor || failed.load(std::memory_order_relaxed)) {
                            failed.store(true, std::memory_order_relaxed);
                            break;
                        }
                    }
                }
            }
        });
    }
    for (auto &worker : workers)
        worker.join();
    if (failed.load())
        throw std::runtime_error("strong PDB violates a rooted exact-distance transition certificate");
    StrongVerification result;
    for (const auto &part : local) {
        result.entries += part.entries;
        for (std::size_t depth = 0; depth < result.distance_histogram.size(); ++depth)
            result.distance_histogram[depth] += part.distance_histogram[depth];
    }
    if (result.entries != kStrongPatternEntries)
        throw std::runtime_error("strong PDB certificate did not cover every coordinate");
    return result;
}

namespace {

void write_checkpoint(const std::filesystem::path &checkpoint, const std::atomic<std::uint8_t> *distances, int depth,
                      std::uint64_t discovered) {
    const auto *bytes = reinterpret_cast<const std::uint8_t *>(distances);
    std::cerr << "strong-pdb checkpoint depth=" << depth << " checksum-start\n";
    const StrongHeader header = make_header(depth, discovered, bytes);
    auto temporary = checkpoint;
    temporary += ".writing";
    {
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        if (!output)
            throw std::runtime_error("cannot create strong PDB checkpoint");
        output.write(reinterpret_cast<const char *>(&header), sizeof(header));
        constexpr std::uint64_t chunk_bytes = 64ULL * 1024ULL * 1024ULL;
        for (std::uint64_t offset = 0; offset < kStrongPatternEntries; offset += chunk_bytes) {
            const auto length = std::min(chunk_bytes, kStrongPatternEntries - offset);
            output.write(reinterpret_cast<const char *>(bytes + offset), static_cast<std::streamsize>(length));
            if (!output)
                throw std::runtime_error("strong PDB checkpoint chunk write failed");
        }
        output.flush();
        if (!output)
            throw std::runtime_error("cannot finish strong PDB checkpoint");
    }
    if (!MoveFileExW(temporary.c_str(), checkpoint.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        throw windows_error("publish strong PDB checkpoint");
    std::cerr << "strong-pdb checkpoint depth=" << depth << " published\n";
}

std::pair<int, std::uint64_t> restore_checkpoint(const std::filesystem::path &path,
                                                 std::atomic<std::uint8_t> *distances,
                                                 std::vector<std::uint64_t> &frontier) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input || input.tellg() != static_cast<std::streamoff>(sizeof(StrongHeader) + kStrongPatternEntries))
        throw std::runtime_error("strong PDB checkpoint is missing or truncated");
    input.seekg(0);
    StrongHeader header;
    input.read(reinterpret_cast<char *>(&header), sizeof(header));
    if (!input || !valid_header(header, sizeof(StrongHeader) + kStrongPatternEntries))
        throw std::runtime_error("strong PDB checkpoint parameters or source version differ");
    auto *bytes = reinterpret_cast<std::uint8_t *>(distances);
    constexpr std::uint64_t chunk_bytes = 64ULL * 1024ULL * 1024ULL;
    for (std::uint64_t offset = 0; offset < kStrongPatternEntries; offset += chunk_bytes) {
        const auto length = std::min(chunk_bytes, kStrongPatternEntries - offset);
        input.read(reinterpret_cast<char *>(bytes + offset), static_cast<std::streamsize>(length));
        if (!input)
            throw std::runtime_error("strong PDB checkpoint chunk read failed");
    }
    if (!input || checksum_bytes(bytes, kStrongPatternEntries) != header.checksum)
        throw std::runtime_error("strong PDB checkpoint checksum failed");
    std::uint64_t unknown = 0;
    std::uint64_t frontier_count = 0;
    for (std::uint64_t index = 0; index < kStrongPatternEntries; ++index) {
        const auto distance = bytes[index];
        if (distance == 255)
            ++unknown;
        else if (distance > header.coverage_depth)
            throw std::runtime_error("strong PDB checkpoint contains an unfinished layer");
        if (distance == header.coverage_depth) {
            frontier[index >> 6U] |= 1ULL << (index & 63U);
            ++frontier_count;
        }
    }
    if (unknown != header.unknown_count || frontier_count == 0)
        throw std::runtime_error("strong PDB checkpoint coverage is inconsistent");
    return {static_cast<int>(header.coverage_depth), kStrongPatternEntries - unknown};
}

} // namespace

StrongVerification convert_strong_pattern_database_to_nibble(const std::filesystem::path &source,
                                                             const std::filesystem::path &target) {
    if (std::filesystem::exists(target) || std::filesystem::absolute(source) == std::filesystem::absolute(target))
        throw std::invalid_argument("nibble target must be a new file distinct from the byte source");
    const auto source_bytes = std::filesystem::file_size(source);
    std::ifstream input(source, std::ios::binary);
    StrongHeader source_header;
    input.read(reinterpret_cast<char *>(&source_header), sizeof(source_header));
    if (!input || !valid_header(source_header, source_bytes) || (source_header.flags & kCompleteFlag) == 0 ||
        source_header.max_distance > 14)
        throw std::invalid_argument("nibble conversion requires a complete verified byte strong PDB with max <=14");
    if (!target.parent_path().empty())
        std::filesystem::create_directories(target.parent_path());
    auto temporary = target;
    temporary += ".writing";
    if (std::filesystem::exists(temporary))
        throw std::runtime_error("nibble conversion temporary file already exists");
    std::fstream output(temporary, std::ios::binary | std::ios::in | std::ios::out | std::ios::trunc);
    if (!output)
        throw std::runtime_error("cannot create nibble strong PDB");
    const std::uint32_t header_bytes =
        static_cast<std::uint32_t>(sizeof(StrongHeader) + kNibbleChunkCount * sizeof(std::uint64_t));
    std::vector<char> placeholder(header_bytes, 0);
    output.write(placeholder.data(), static_cast<std::streamsize>(placeholder.size()));
    std::vector<std::uint8_t> byte_chunk(static_cast<std::size_t>(2 * kNibbleChunkBytes));
    std::vector<std::uint8_t> packed_chunk(static_cast<std::size_t>(kNibbleChunkBytes));
    std::vector<std::uint64_t> chunk_checksums(static_cast<std::size_t>(kNibbleChunkCount));
    StrongVerification verification;
    std::uint64_t source_checksum = 1469598103934665603ULL;
    std::uint8_t maximum = 0;
    for (std::uint64_t chunk = 0; chunk < kNibbleChunkCount; ++chunk) {
        const auto packed_length = std::min(kNibbleChunkBytes, kNibbleDataBytes - chunk * kNibbleChunkBytes);
        const auto byte_length = 2 * packed_length;
        input.read(reinterpret_cast<char *>(byte_chunk.data()), static_cast<std::streamsize>(byte_length));
        if (!input)
            throw std::runtime_error("byte strong PDB ended during nibble conversion");
        for (std::uint64_t index = 0; index < packed_length; ++index) {
            const auto low = byte_chunk[2 * index];
            const auto high = byte_chunk[2 * index + 1];
            source_checksum = (source_checksum ^ low) * 1099511628211ULL;
            source_checksum = (source_checksum ^ high) * 1099511628211ULL;
            if (low > 14 || high > 14)
                throw std::runtime_error("byte strong PDB has unknown or out-of-range distances");
            ++verification.distance_histogram[low];
            ++verification.distance_histogram[high];
            verification.entries += 2;
            maximum = std::max({maximum, low, high});
            packed_chunk[index] = static_cast<std::uint8_t>(low | (high << 4U));
            if ((packed_chunk[index] & 15U) != low || (packed_chunk[index] >> 4U) != high)
                throw std::runtime_error("nibble conversion failed round-trip verification");
        }
        chunk_checksums[chunk] = checksum_bytes(packed_chunk.data(), packed_length);
        output.write(reinterpret_cast<const char *>(packed_chunk.data()), static_cast<std::streamsize>(packed_length));
        if (!output)
            throw std::runtime_error("cannot write nibble strong PDB chunk");
    }
    if (source_checksum != source_header.checksum || maximum != source_header.max_distance ||
        verification.entries != kStrongPatternEntries)
        throw std::runtime_error("byte strong PDB source verification failed during conversion");
    StrongHeader target_header = source_header;
    target_header.version = kNibbleVersion;
    target_header.header_size = header_bytes;
    target_header.bits_per_entry = 4;
    target_header.data_bytes = kNibbleDataBytes;
    target_header.checksum = checksum_bytes(reinterpret_cast<const std::uint8_t *>(chunk_checksums.data()),
                                            kNibbleChunkCount * sizeof(std::uint64_t));
    output.seekp(0);
    output.write(reinterpret_cast<const char *>(&target_header), sizeof(target_header));
    output.write(reinterpret_cast<const char *>(chunk_checksums.data()),
                 static_cast<std::streamsize>(kNibbleChunkCount * sizeof(std::uint64_t)));
    output.flush();
    if (!output)
        throw std::runtime_error("cannot finalize nibble strong PDB");
    output.close();
    if (!MoveFileExW(temporary.c_str(), target.c_str(), MOVEFILE_WRITE_THROUGH))
        throw windows_error("publish nibble strong PDB");
    return verification;
}

void build_strong_pattern_database(const std::filesystem::path &path, const CoordinateTables &tables, int threads,
                                   int coverage_depth, bool resume, double memory_limit_gib) {
    if (coverage_depth < 0 || coverage_depth > 254)
        throw std::invalid_argument("strong PDB coverage depth must be 0..254");
    if (!std::isfinite(memory_limit_gib) || memory_limit_gib <= 0)
        throw std::invalid_argument("strong PDB memory limit must be positive and finite");
    if (std::filesystem::exists(path)) {
        try {
            StrongPatternDatabase existing(path);
            if (existing.complete() || existing.coverage_depth() >= coverage_depth)
                return;
        } catch (const std::exception &) {
            if (!resume)
                throw;
        }
    }
    MEMORYSTATUSEX memory{};
    memory.dwLength = sizeof(memory);
    if (!GlobalMemoryStatusEx(&memory))
        throw windows_error("query available memory");
    const auto user_limit = static_cast<std::uint64_t>(memory_limit_gib * 1024.0 * 1024.0 * 1024.0);
    const auto hard_limit = std::min(user_limit, memory.ullAvailPhys * 7ULL / 10ULL);
    const std::uint64_t estimated =
        kStrongPatternEntries + 2ULL * kWordCount * sizeof(std::uint64_t) + 512ULL * 1024ULL * 1024ULL;
    if (estimated > hard_limit)
        throw std::runtime_error("strong PDB estimated memory exceeds configured/free-memory limit");
    threads = std::clamp(threads > 0 ? threads : static_cast<int>(std::thread::hardware_concurrency()), 1, 64);
    if (!path.parent_path().empty())
        std::filesystem::create_directories(path.parent_path());
    auto checkpoint = path;
    checkpoint += ".checkpoint";
    if (!resume && std::filesystem::exists(checkpoint))
        throw std::runtime_error("strong PDB checkpoint exists; pass --resume to preserve its completed layers");

    const auto started = std::chrono::steady_clock::now();
    SortedSliceSymmetry symmetry;
    if (symmetry.class_count() != 788)
        throw std::runtime_error("strong PDB requires the enumerated 788 sorted-slice classes");
    StrongTransitions transitions(symmetry, tables);
    auto distances = std::make_unique<std::atomic<std::uint8_t>[]>(kStrongPatternEntries);
    std::vector<std::uint64_t> frontier(kWordCount, 0), next(kWordCount, 0);
    int depth = 0;
    std::uint64_t discovered = 1;
    if (resume && (std::filesystem::exists(checkpoint) || std::filesystem::exists(path))) {
        const auto source = std::filesystem::exists(checkpoint) ? checkpoint : path;
        std::tie(depth, discovered) = restore_checkpoint(source, distances.get(), frontier);
        std::cerr << "strong-pdb resumed depth=" << depth << " discovered=" << discovered << "\n";
    } else {
        const int initializer_count = threads;
        std::vector<std::thread> initializers;
        for (int thread = 0; thread < initializer_count; ++thread)
            initializers.emplace_back([&, thread] {
                for (std::uint64_t index = kStrongPatternEntries * thread / initializer_count;
                     index < kStrongPatternEntries * (thread + 1) / initializer_count; ++index)
                    distances[index].store(255, std::memory_order_relaxed);
            });
        for (auto &initializer : initializers)
            initializer.join();
        const auto goal = symmetry.canonical_index(0, 0, sorted_slice_coord(CubieCube{}));
        distances[goal].store(0, std::memory_order_relaxed);
        frontier[goal >> 6U] |= 1ULL << (goal & 63U);
    }
    while (depth < coverage_depth && discovered < kStrongPatternEntries) {
        const auto next_depth = static_cast<std::uint8_t>(depth + 1);
        std::vector<std::thread> workers;
        std::vector<std::uint64_t> local_new(threads, 0);
        workers.reserve(threads);
        for (int thread = 0; thread < threads; ++thread) {
            workers.emplace_back([&, thread] {
                auto claim = [&](std::uint64_t child) {
                    std::uint8_t expected = 255;
                    if (distances[child].compare_exchange_strong(expected, next_depth, std::memory_order_relaxed)) {
                        std::atomic_ref<std::uint64_t>(next[child >> 6U])
                            .fetch_or(1ULL << (child & 63U), std::memory_order_relaxed);
                        ++local_new[thread];
                    }
                };
                for (std::uint64_t word_index = thread; word_index < kWordCount; word_index += threads) {
                    std::uint64_t bits = frontier[word_index];
                    while (bits != 0) {
                        const int bit = std::countr_zero(bits);
                        bits &= bits - 1U;
                        const std::uint64_t coordinate = (word_index << 6U) + static_cast<unsigned>(bit);
                        if (coordinate >= kStrongPatternEntries)
                            continue;
                        const std::uint32_t class_index = static_cast<std::uint32_t>(coordinate / kClassStride);
                        const std::uint32_t remainder = static_cast<std::uint32_t>(coordinate % kClassStride);
                        const std::uint16_t flip = static_cast<std::uint16_t>(remainder / 2187U);
                        const std::uint16_t twist = static_cast<std::uint16_t>(remainder % 2187U);
                        for (std::size_t quarter = 0; quarter < kQuarterMoves.size(); ++quarter) {
                            const std::size_t slot =
                                static_cast<std::size_t>(class_index) * kQuarterMoves.size() + quarter;
                            const auto child_class = transitions.next_class[slot];
                            const auto child_flip = transitions.next_flip[slot * 2048U + flip];
                            const auto child_twist = transitions.next_twist[slot * 2187U + twist];
                            claim((static_cast<std::uint64_t>(child_class) * 2048U + child_flip) * 2187U + child_twist);
                            for (const auto &stabilizer : transitions.stabilizers[child_class]) {
                                const auto equivalent_flip = stabilizer.flip[child_flip];
                                const auto equivalent_twist =
                                    symmetry.phase1().twist_conjugate(child_twist, stabilizer.symmetry);
                                claim((static_cast<std::uint64_t>(child_class) * 2048U + equivalent_flip) * 2187U +
                                      equivalent_twist);
                            }
                        }
                    }
                }
            });
        }
        for (auto &worker : workers)
            worker.join();
        std::uint64_t layer_count = 0;
        for (auto count : local_new)
            layer_count += count;
        if (layer_count == 0)
            break;
        discovered += layer_count;
        ++depth;
        frontier.swap(next);
        std::fill(next.begin(), next.end(), 0);
        write_checkpoint(checkpoint, distances.get(), depth, discovered);
        std::cerr << "strong-pdb metric=QTM depth=" << depth << " frontier=" << layer_count
                  << " discovered=" << discovered
                  << " elapsed=" << std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count()
                  << "s\n";
    }
    if (!std::filesystem::exists(checkpoint))
        write_checkpoint(checkpoint, distances.get(), depth, discovered);
    if (!MoveFileExW(checkpoint.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        throw windows_error("publish strong PDB");
    std::cerr << "strong-pdb complete=" << (discovered == kStrongPatternEntries) << " depth=" << depth
              << " discovered=" << discovered << " file=" << utf8_path(path) << "\n";
}

} // namespace cube
