#include "strong_coords.hpp"
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <new>
#include <vector>

static std::uint64_t allocation_calls = 0;
void* operator new(std::size_t size) {
    ++allocation_calls;
    if (void* memory = std::malloc(size == 0 ? 1 : size)) return memory;
    throw std::bad_alloc();
}
void operator delete(void* memory) noexcept { std::free(memory); }
void operator delete(void* memory, std::size_t) noexcept { std::free(memory); }

struct Query { std::uint16_t twist, flip, sorted; };

int main() {
    cube::SortedSliceSymmetry symmetry;
    std::vector<std::uint16_t> offsets(cube::kSortedSliceCount * 16U);
    for (unsigned s=0;s<cube::kSortedSliceCount;++s)
        for (unsigned y=0;y<16;++y)
            offsets[s*16+y]=symmetry.flip_conjugate(0,s,y) ^ symmetry.phase1().flip_conjugate(0,y);
    std::uint64_t checked=0;
    for(unsigned s=0;s<cube::kSortedSliceCount;++s)
        for(unsigned y=0;y<16;++y)
            for(unsigned b=0;b<12;++b) {
                const unsigned f=b==11 ? 0 : 1U<<b;
                if((symmetry.phase1().flip_conjugate(f,y)^offsets[s*16+y])!=symmetry.flip_conjugate(f,s,y)) return 2;
                ++checked;
            }
    std::uint32_t seed=20260929;
    auto random=[&] { seed=seed*1664525U+1013904223U;return seed; };
    std::vector<Query> queries(1U<<20);
    for(auto& q:queries) q={static_cast<std::uint16_t>(random()%2187),static_cast<std::uint16_t>(random()%2048),static_cast<std::uint16_t>(random()%cube::kSortedSliceCount)};
    auto fast=[&](const Query& q) {
        const auto y=symmetry.symmetry_to_representative(q.sorted);
        const auto f=symmetry.phase1().flip_conjugate(q.flip,y)^offsets[q.sorted*16+y];
        return (static_cast<std::uint64_t>(symmetry.class_index(q.sorted))*2048+f)*2187+symmetry.phase1().twist_conjugate(q.twist,y);
    };
    for(const auto& q:queries) { if(fast(q)!=symmetry.canonical_index_reference(q.twist,q.flip,q.sorted) ||
            fast(q)!=symmetry.canonical_index(q.twist,q.flip,q.sorted)) return 3; ++checked; }
    cube::CubieCube legal;
    for (unsigned sample=0; sample<100000; ++sample) {
        legal=legal.apply_move(static_cast<int>(random()%18));
        const Query q{cube::twist_coord(legal),cube::flip_coord(legal),cube::sorted_slice_coord(legal)};
        if (fast(q)!=symmetry.canonical_index_reference(q.twist,q.flip,q.sorted)) return 5;
        ++checked;
    }
    std::cout<<"{\"scope\":\"coordinate-only; no PDB accesses or solver speedup claim\",\"checked\":"<<checked<<",\"extra_offset_bytes\":"<<offsets.size()*sizeof(offsets[0])<<",\"runs\":[";
    std::uint64_t expected=0;
    for(int r=0;r<6;++r) {
        const bool affine=r%2;
        const auto start=std::chrono::steady_clock::now();
        const auto allocations_before=allocation_calls;
        std::uint64_t checksum=0;
        for(unsigned pass=0;pass<4;++pass)
            for(const auto& q:queries) checksum += affine ? symmetry.canonical_index(q.twist,q.flip,q.sorted)
                                                          : symmetry.canonical_index_reference(q.twist,q.flip,q.sorted);
        const double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
        const auto allocations=allocation_calls-allocations_before;
        if(r==0) expected=checksum;
        if(checksum!=expected) return 4;
        if(r) std::cout<<',';
        std::cout<<"{\"variant\":\""<<(affine?"affine":"current")<<"\",\"queries\":"<<queries.size()*4<<",\"seconds\":"<<seconds<<",\"allocations\":"<<allocations<<",\"checksum\":"<<checksum<<'}';
    }
    std::cout<<"]}\n";
}
