#include "cube.hpp"
#include "strong_coords.hpp"
#include "symmetry.hpp"

#include <iostream>

int main() {
    const cube::CubieCube goal;
    std::uint64_t checked = 0;
    // Expand any QTM solution into unit quarter turns. Immediately before
    // its last turn the cube is one quarter turn from the goal; at least one
    // of the three projections is already at its abstract goal there.
    for (int move = 0; move < 18; ++move) {
        if (move % 3 == 1)
            continue;
        const auto predecessor = goal.apply_move(move);
        bool phase1_goal = false;
        bool strong_goal = false;
        for (int axis = 0; axis < 3; ++axis) {
            const auto rotated_goal = axis == 0 ? goal : cube::conjugate_axis(goal, axis - 1);
            const auto rotated_predecessor = axis == 0 ? predecessor :
                cube::conjugate_axis(predecessor, axis - 1);
            const bool twist_flip = cube::twist_coord(rotated_goal) == cube::twist_coord(rotated_predecessor) &&
                                    cube::flip_coord(rotated_goal) == cube::flip_coord(rotated_predecessor);
            phase1_goal |= twist_flip && cube::slice_comb_coord(rotated_goal) ==
                                           cube::slice_comb_coord(rotated_predecessor);
            strong_goal |= twist_flip && cube::sorted_slice_coord(rotated_goal) ==
                                          cube::sorted_slice_coord(rotated_predecessor);
        }
        if (!phase1_goal || !strong_goal) {
            std::cerr << "axis goal property failed move=" << move << " phase1=" << phase1_goal
                      << " strong=" << strong_goal << '\n';
            return 1;
        }
        ++checked;
    }
    std::cout << "{\"ok\":true,\"last_quarter_turns\":" << checked << "}\n";
}
