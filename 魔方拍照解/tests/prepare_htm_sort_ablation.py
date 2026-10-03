"""Recreate rejected H2 builds from the immutable next-speed HTM baseline."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; ablations never overwrite a checkout")
    for folder in ("src", "include"):
        shutil.copytree(args.baseline / folder, args.output / folder)
    shutil.copy2(args.baseline / "build.ps1", args.output / "build.ps1")
    path = args.output / "src/solver.cpp"
    source = path.read_text(encoding="utf-8")
    source = source.replace("#include <utility>\n", """#include <utility>

// Build-time ablation: keep the frozen allocation/sort path until the
// independent complete-tree comparison passes its adoption threshold.
#ifndef CUBE_HTM_CANDIDATE_SORT
#define CUBE_HTM_CANDIDATE_SORT 0
#endif
""")
    source = source.replace("""        std::vector<Candidate> candidates;
        candidates.reserve(15);""", """#if CUBE_HTM_CANDIDATE_SORT == 0
        std::vector<Candidate> candidates;
        candidates.reserve(15);
#else
        std::array<Candidate, kMoveCount> candidates;
        std::size_t candidate_count = 0;
#endif""")
    source = source.replace("            candidates.push_back(Candidate{std::move(child), move, face, child_heuristic});", """            Candidate candidate{std::move(child), move, face, child_heuristic};
#if CUBE_HTM_CANDIDATE_SORT == 0
            candidates.push_back(std::move(candidate));
#else
            candidates[candidate_count++] = std::move(candidate);
#endif""")
    source = source.replace("""        std::stable_sort(candidates.begin(), candidates.end(), [](const Candidate &left, const Candidate &right) {
            return left.heuristic < right.heuristic;
        });
        for (const Candidate &candidate : candidates) {""", """        auto candidate_end = candidates.end();
#if CUBE_HTM_CANDIDATE_SORT != 0
        candidate_end = candidates.begin() + candidate_count;
#endif
#if CUBE_HTM_CANDIDATE_SORT == 2
        // Shift only strictly greater keys so equal lower bounds retain the
        // original move order, including all eighteen moves at the root.
        for (auto current = candidates.begin() + (candidate_count != 0); current != candidate_end; ++current) {
            Candidate value = std::move(*current);
            auto position = current;
            while (position != candidates.begin() && (position - 1)->heuristic > value.heuristic) {
                *position = std::move(*(position - 1));
                --position;
            }
            *position = std::move(value);
        }
#else
        std::stable_sort(candidates.begin(), candidate_end, [](const Candidate &left, const Candidate &right) {
            return left.heuristic < right.heuristic;
        });
#endif
        for (auto current = candidates.begin(); current != candidate_end; ++current) {
            const Candidate &candidate = *current;""")
    if "candidate_count" not in source:
        raise RuntimeError("baseline candidate block not found")
    path.write_text(source, encoding="utf-8", newline="\r\n")
    build_path = args.output / "build.ps1"
    build = build_path.read_text(encoding="utf-8")
    build = build.replace("    [string]$OutputDirectory\n", '    [string]$OutputDirectory,\n    [ValidateSet("Legacy", "FixedStable", "FixedInsertion")][string]$CandidateSort = "Legacy"\n')
    build = build.replace("if ($ProfileGuided) {\n", 'if ($ProfileGuided) {\n    if ($CandidateSort -ne "Legacy") { throw "CandidateSort ablations are ordinary O3/LTO builds only" }\n')
    architecture = '$architectureFlags = if ($Portable) { @("-march=x86-64", "-mtune=generic") } else { @("-march=native", "-mtune=native") }\n'
    build = build.replace(architecture, architecture + '$candidateSortFlag = "-DCUBE_HTM_CANDIDATE_SORT=$(@{ Legacy = 0; FixedStable = 1; FixedInsertion = 2 }[$CandidateSort])"\n')
    build = build.replace("        @architectureFlags `\n", "        @architectureFlags `\n        $candidateSortFlag `\n")
    build = build.replace("$($architectureFlags -join ' ') -flto", "$($architectureFlags -join ' ') $candidateSortFlag -flto")
    build = build.replace("    portable = [bool]$Portable\n", "    candidate_sort = $CandidateSort\n    portable = [bool]$Portable\n")
    build_path.write_text(build, encoding="utf-8", newline="\r\n")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
