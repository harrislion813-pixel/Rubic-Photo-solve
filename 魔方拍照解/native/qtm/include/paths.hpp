#pragma once

#include <filesystem>
#include <string>
#include <string_view>

namespace cube {

inline std::filesystem::path path_from_utf8(std::string_view text) {
    return std::filesystem::path(std::u8string(text.begin(), text.end()));
}

inline std::string utf8_path(const std::filesystem::path &path) {
    const auto encoded = path.u8string();
    return std::string(encoded.begin(), encoded.end());
}

} // namespace cube
