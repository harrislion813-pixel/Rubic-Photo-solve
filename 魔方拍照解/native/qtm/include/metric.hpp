#pragma once

#include <span>
#include <string>

namespace cube {

enum class MoveMetric { HTM, QTM };
[[nodiscard]] MoveMetric parse_metric(const std::string &value);
[[nodiscard]] const char *metric_name(MoveMetric metric) noexcept;
[[nodiscard]] int move_cost(int move, MoveMetric metric);
[[nodiscard]] int solution_cost(std::span<const int> moves, MoveMetric metric);
[[nodiscard]] int default_max_depth(MoveMetric metric) noexcept;

} // namespace cube
