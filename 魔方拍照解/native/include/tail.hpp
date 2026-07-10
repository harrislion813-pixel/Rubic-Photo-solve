#pragma once

#include "cube.hpp"

#include <cstdint>
#include <filesystem>
#include <optional>
#include <vector>

namespace cube {

struct TailHit {
    std::uint8_t distance{};
    std::uint8_t move_to_goal{255};
};

class TailDatabase {
public:
    explicit TailDatabase(const std::filesystem::path& path);
    ~TailDatabase();

    TailDatabase(const TailDatabase&) = delete;
    TailDatabase& operator=(const TailDatabase&) = delete;

    [[nodiscard]] int depth() const noexcept;
    [[nodiscard]] std::optional<TailHit> lookup(const CubieCube& cube) const noexcept;
    [[nodiscard]] std::vector<int> solution_suffix(CubieCube cube) const;

private:
    void* file_{nullptr};
    void* mapping_{nullptr};
    const std::uint8_t* view_{nullptr};
    const void* entries_{nullptr};
    std::uint64_t slot_count_{0};
    std::uint64_t mask_{0};
    int depth_{0};
};

void build_tail_database(
    const std::filesystem::path& path,
    int depth = 6,
    bool force = false);

}  // namespace cube
