#pragma once

#include <chrono>
#include <condition_variable>
#include <mutex>

namespace cube {
// A pause is acknowledged only after all executing participants reach a checkpoint.
// Coordinators suspend their participation while joining validation workers.
class LoaderControl {
  public:
    explicit LoaderControl(int threads = 0, bool paused = false) : threads(threads), paused_(paused) {}
    int threads;
    class Participant {
      public:
        explicit Participant(LoaderControl *control) : control_(control) { resume(); }
        ~Participant() { suspend(); }
        void checkpoint() {
            if (!control_)
                return;
            suspend();
            resume();
        }
        void suspend() {
            if (!control_ || !active_)
                return;
            std::lock_guard lock(control_->mutex_);
            --control_->executing_;
            active_ = false;
            control_->condition_.notify_all();
        }
        void resume() {
            if (!control_ || active_)
                return;
            std::unique_lock lock(control_->mutex_);
            control_->condition_.wait(lock, [&] { return !control_->paused_; });
            ++control_->executing_;
            active_ = true;
        }

      private:
        LoaderControl *control_;
        bool active_{false};
    };
    void request_pause() {
        std::lock_guard lock(mutex_);
        paused_ = true;
    }
    bool pause_for(std::chrono::milliseconds timeout) {
        std::unique_lock lock(mutex_);
        paused_ = true;
        return condition_.wait_for(lock, timeout, [&] { return executing_ == 0; });
    }
    void resume() {
        std::lock_guard lock(mutex_);
        paused_ = false;
        condition_.notify_all();
    }
    int executing() {
        std::lock_guard lock(mutex_);
        return executing_;
    }

  private:
    std::mutex mutex_;
    std::condition_variable condition_;
    bool paused_;
    int executing_{0};
};
} // namespace cube
