#include "loader.hpp"
#include "strong_coords.hpp"

#include <atomic>
#include <chrono>
#include <exception>
#include <future>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <thread>

namespace {
using Clock = std::chrono::steady_clock;
void require(bool condition, const char *message) {
    if (!condition)
        throw std::runtime_error(message);
}
double seconds(Clock::time_point start) {
    return std::chrono::duration<double>(Clock::now() - start).count();
}
void equivalent(const cube::SortedSliceSymmetry &left, const cube::SortedSliceSymmetry &right) {
    const auto &a = left.phase1();
    const auto &b = right.phase1();
    require(a.class_count() == cube::kFlipSliceClassCount && a.class_count() == b.class_count(), "phase1 classes");
    require(a.twist_table() == b.twist_table() && a.raw_to_class_table() == b.raw_to_class_table() &&
                a.raw_to_symmetry_table() == b.raw_to_symmetry_table() && a.representatives() == b.representatives(),
            "phase1 tables changed with optional checkpoints");
    for (int symmetry = 0; symmetry < cube::kPhase1SymmetryCount; ++symmetry) {
        for (std::uint16_t flip = 0; flip < 2048; ++flip)
            require(a.flip_conjugate(flip, symmetry) == b.flip_conjugate(flip, symmetry), "flip table");
        for (std::uint16_t slice = 0; slice < 495; ++slice)
            require(a.slice_conjugate(slice, symmetry) == b.slice_conjugate(slice, symmetry), "slice table");
    }
    require(left.class_count() == 788 && left.class_count() == right.class_count(), "sorted classes");
    for (std::uint16_t raw = 0; raw < cube::kSortedSliceCount; ++raw) {
        require(left.class_index(raw) == right.class_index(raw) &&
                    left.symmetry_to_representative(raw) == right.symmetry_to_representative(raw), "sorted class");
        for (int move = 0; move < 18; ++move)
            require(left.moved(raw, move) == right.moved(raw, move), "sorted move table");
        for (int symmetry = 0; symmetry < cube::kPhase1SymmetryCount; ++symmetry)
            require(left.conjugate(raw, symmetry) == right.conjugate(raw, symmetry), "sorted conjugates");
        const auto flip = static_cast<std::uint16_t>(raw % 2048);
        const auto twist = static_cast<std::uint16_t>(raw % 2187);
        require(left.canonical_index(twist, flip, raw) == right.canonical_index(twist, flip, raw) &&
                    right.canonical_index(twist, flip, raw) == right.canonical_index_reference(twist, flip, raw),
                "sorted canonical index");
    }
    for (std::uint16_t index = 0; index < left.class_count(); ++index)
        require(left.representative(index) == right.representative(index) &&
                    left.stabilizer_mask(index) == right.stabilizer_mask(index), "sorted representative");
}
} // namespace

int main() {
    try {
        auto started = Clock::now();
        const cube::SortedSliceSymmetry defaults;
        const auto default_seconds = seconds(started);
        cube::LoaderControl loader(1);
        std::promise<void> reached, proceed;
        auto reached_future = reached.get_future();
        auto proceed_future = proceed.get_future();
        std::atomic<int> callbacks{0};
        std::atomic<bool> complete{false};
        std::unique_ptr<cube::SortedSliceSymmetry> paused;
        std::exception_ptr failure;
        double max_gap = 0;
        started = Clock::now();
        std::thread worker([&] {
            try {
                cube::LoaderControl::Participant coordinator(&loader);
                auto previous = Clock::now();
                paused = std::make_unique<cube::SortedSliceSymmetry>([&] {
                    max_gap = std::max(max_gap, seconds(previous));
                    // Callback 4 is inside the member's twist-table construction,
                    // before SortedSliceSymmetry's own constructor body starts.
                    if (++callbacks == 4) {
                        reached.set_value();
                        proceed_future.wait();
                    }
                    coordinator.checkpoint();
                    previous = Clock::now();
                });
                complete = true;
            } catch (...) { failure = std::current_exception(); }
        });
        if (reached_future.wait_for(std::chrono::seconds(10)) != std::future_status::ready) {
            proceed.set_value();
            loader.resume();
            worker.join();
            throw std::runtime_error("member checkpoint was not reached");
        }
        const bool active_before = loader.executing() == 1;
        loader.request_pause();
        proceed.set_value();
        const auto pause_started = Clock::now();
        const bool acknowledged = loader.pause_for(std::chrono::milliseconds(500));
        const auto pause_seconds = seconds(pause_started);
        const auto count_paused = callbacks.load();
        std::this_thread::sleep_for(std::chrono::milliseconds(40));
        const bool blocked = !complete && loader.executing() == 0 && callbacks == count_paused;
        loader.resume();
        worker.join();
        const auto callback_seconds = seconds(started) - .04;
        if (failure)
            std::rethrow_exception(failure);
        require(active_before && acknowledged && blocked, "real member construction did not pause quiescently");
        require(complete && loader.executing() == 0 && callbacks > 2000, "resume did not finish initialization");
        equivalent(defaults, *paused);

        // Exceptions from a real constructor checkpoint unwind the coordinator;
        // no partially initialized symmetry object is published.
        int cancellation_callbacks = 0;
        bool cancelled = false;
        try {
            cube::LoaderControl::Participant coordinator(&loader);
            cube::SortedSliceSymmetry interrupted([&] {
                coordinator.checkpoint();
                if (++cancellation_callbacks == 4)
                    throw std::runtime_error("test initialization cancellation");
            });
        } catch (const std::runtime_error &error) {
            cancelled = std::string(error.what()) == "test initialization cancellation";
        }
        require(cancelled && loader.executing() == 0, "checkpoint exception leaked participation");
        std::cout << "{\"pause_acknowledged\":true,\"executing_while_paused\":0,\"resume_complete\":true,"
                     "\"optional_callback_equivalent\":true,\"exception_unwinds\":true,\"callbacks\":"
                  << callbacks << ",\"pause_seconds\":" << pause_seconds << ",\"max_work_gap_seconds\":" << max_gap
                  << ",\"default_initialization_seconds\":" << default_seconds
                  << ",\"callback_initialization_seconds_excluding_hold\":" << callback_seconds << "}\n";
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
