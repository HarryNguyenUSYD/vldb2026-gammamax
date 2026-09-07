#pragma once

#include <algorithm>
#include <cstddef>
#include <filesystem>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>

#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#elif defined(__APPLE__) || defined(__linux__)
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
extern char** environ;
#else
#error "gammaMax external oracle supports only Windows and POSIX platforms"
#endif

namespace gammamax {

class Oracle {
public:
    virtual ~Oracle() = default;
    virtual bool accepts(std::string_view value) = 0;
};

class ExternalOracle final : public Oracle {
public:
    ExternalOracle(std::filesystem::path executable, std::size_t max_calls)
        : executable_(std::move(executable)), max_calls_(max_calls) {}

    bool accepts(std::string_view value) override {
        if (calls_ >= max_calls_) {
            throw std::runtime_error("maximum total oracle-call limit exhausted");
        }
        ++calls_;
#if defined(_WIN32)
        return accepts_windows(value);
#else
        return accepts_posix(value);
#endif
    }

    std::size_t calls() const noexcept { return calls_; }

private:
#if defined(_WIN32)
    class Handle {
    public:
        Handle() = default;
        explicit Handle(HANDLE value) : value_(value) {}
        ~Handle() { reset(); }
        Handle(const Handle&) = delete;
        Handle& operator=(const Handle&) = delete;
        Handle(Handle&& other) noexcept : value_(other.release()) {}
        Handle& operator=(Handle&& other) noexcept {
            if (this != &other) {
                reset(other.release());
            }
            return *this;
        }
        HANDLE get() const noexcept { return value_; }
        HANDLE release() noexcept {
            HANDLE result = value_;
            value_ = nullptr;
            return result;
        }
        void reset(HANDLE replacement = nullptr) noexcept {
            if (value_ && value_ != INVALID_HANDLE_VALUE) {
                CloseHandle(value_);
            }
            value_ = replacement;
        }

    private:
        HANDLE value_{nullptr};
    };

    static std::string windows_error(const char* operation) {
        return std::string(operation) + " failed with Windows error " +
               std::to_string(GetLastError());
    }

    bool accepts_windows(std::string_view value) const {
        SECURITY_ATTRIBUTES security{};
        security.nLength = sizeof(security);
        security.bInheritHandle = TRUE;

        HANDLE raw_read = nullptr;
        HANDLE raw_write = nullptr;
        if (!CreatePipe(&raw_read, &raw_write, &security, 0)) {
            throw std::runtime_error(windows_error("CreatePipe"));
        }
        Handle input_read(raw_read);
        Handle input_write(raw_write);
        if (!SetHandleInformation(input_write.get(), HANDLE_FLAG_INHERIT, 0)) {
            throw std::runtime_error(windows_error("SetHandleInformation"));
        }

        Handle null_output(CreateFileW(L"NUL", GENERIC_WRITE,
                                       FILE_SHARE_READ | FILE_SHARE_WRITE, &security,
                                       OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
        if (null_output.get() == INVALID_HANDLE_VALUE) {
            null_output.release();
            throw std::runtime_error(windows_error("CreateFileW(NUL)"));
        }

        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        startup.dwFlags = STARTF_USESTDHANDLES;
        startup.hStdInput = input_read.get();
        startup.hStdOutput = null_output.get();
        startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
        PROCESS_INFORMATION process{};

        const std::wstring executable = executable_.wstring();
        std::wstring command_line = L"\"" + executable + L"\"";
        if (!CreateProcessW(executable.c_str(), command_line.data(), nullptr, nullptr, TRUE,
                            0, nullptr, nullptr, &startup, &process)) {
            throw std::runtime_error(windows_error("CreateProcessW"));
        }
        Handle process_handle(process.hProcess);
        Handle thread_handle(process.hThread);
        input_read.reset();
        null_output.reset();

        std::size_t written_total = 0;
        while (written_total < value.size()) {
            const std::size_t remaining = value.size() - written_total;
            const DWORD chunk = static_cast<DWORD>(
                std::min<std::size_t>(remaining, std::numeric_limits<DWORD>::max()));
            DWORD written = 0;
            if (!WriteFile(input_write.get(), value.data() + written_total, chunk, &written,
                           nullptr)) {
                const DWORD error = GetLastError();
                input_write.reset();
                WaitForSingleObject(process_handle.get(), INFINITE);
                SetLastError(error);
                throw std::runtime_error(windows_error("WriteFile(oracle stdin)"));
            }
            if (written == 0) {
                throw std::runtime_error("zero-byte write to oracle stdin");
            }
            written_total += written;
        }
        input_write.reset();

        if (WaitForSingleObject(process_handle.get(), INFINITE) != WAIT_OBJECT_0) {
            throw std::runtime_error(windows_error("WaitForSingleObject"));
        }
        DWORD exit_code = 0;
        if (!GetExitCodeProcess(process_handle.get(), &exit_code)) {
            throw std::runtime_error(windows_error("GetExitCodeProcess"));
        }
        if (exit_code == 0) {
            return true;
        }
        if (exit_code == 1) {
            return false;
        }
        throw std::runtime_error("oracle exited with unexpected code " +
                                 std::to_string(exit_code));
    }
#else
    bool accepts_posix(std::string_view value) const {
        static const bool sigpipe_ignored = [] {
            return signal(SIGPIPE, SIG_IGN) != SIG_ERR;
        }();
        if (!sigpipe_ignored) {
            throw std::runtime_error("failed to ignore SIGPIPE for oracle writes");
        }
        int input_pipe[2];
        if (pipe(input_pipe) != 0) {
            throw std::runtime_error("pipe failed for oracle stdin");
        }

        posix_spawn_file_actions_t actions;
        if (posix_spawn_file_actions_init(&actions) != 0) {
            close(input_pipe[0]);
            close(input_pipe[1]);
            throw std::runtime_error("posix_spawn_file_actions_init failed");
        }
        const auto cleanup_actions = [&]() { posix_spawn_file_actions_destroy(&actions); };
        int action_error = posix_spawn_file_actions_adddup2(&actions, input_pipe[0], STDIN_FILENO);
        action_error = action_error == 0
                           ? posix_spawn_file_actions_addopen(&actions, STDOUT_FILENO, "/dev/null",
                                                             O_WRONLY, 0)
                           : action_error;
        action_error = action_error == 0
                           ? posix_spawn_file_actions_addclose(&actions, input_pipe[1])
                           : action_error;
        if (action_error != 0) {
            cleanup_actions();
            close(input_pipe[0]);
            close(input_pipe[1]);
            throw std::runtime_error("failed to configure posix_spawn file actions");
        }

        const std::string executable = executable_.string();
        char* argv[] = {const_cast<char*>(executable.c_str()), nullptr};
        pid_t pid{};
        const int spawn_error =
            posix_spawn(&pid, executable.c_str(), &actions, nullptr, argv, environ);
        cleanup_actions();
        close(input_pipe[0]);
        if (spawn_error != 0) {
            close(input_pipe[1]);
            throw std::runtime_error("posix_spawn failed with error " +
                                     std::to_string(spawn_error));
        }

        std::size_t written_total = 0;
        while (written_total < value.size()) {
            const ssize_t written =
                write(input_pipe[1], value.data() + written_total, value.size() - written_total);
            if (written < 0) {
                close(input_pipe[1]);
                waitpid(pid, nullptr, 0);
                throw std::runtime_error("write failed for oracle stdin");
            }
            if (written == 0) {
                close(input_pipe[1]);
                waitpid(pid, nullptr, 0);
                throw std::runtime_error("zero-byte write to oracle stdin");
            }
            written_total += static_cast<std::size_t>(written);
        }
        close(input_pipe[1]);

        int status = 0;
        if (waitpid(pid, &status, 0) < 0) {
            throw std::runtime_error("waitpid failed for oracle");
        }
        if (!WIFEXITED(status)) {
            throw std::runtime_error("oracle terminated without a normal exit");
        }
        const int exit_code = WEXITSTATUS(status);
        if (exit_code == 0) {
            return true;
        }
        if (exit_code == 1) {
            return false;
        }
        throw std::runtime_error("oracle exited with unexpected code " +
                                 std::to_string(exit_code));
    }
#endif

    std::filesystem::path executable_;
    std::size_t max_calls_{};
    std::size_t calls_{};
};

}  // namespace gammamax
