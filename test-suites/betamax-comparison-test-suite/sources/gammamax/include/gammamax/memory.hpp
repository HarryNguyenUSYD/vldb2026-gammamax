#pragma once

#include <cstdint>
#include <stdexcept>

#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <psapi.h>
#elif defined(__APPLE__)
#include <mach/mach.h>
#else
#error "gammaMax peak memory measurement supports only Windows and macOS"
#endif

namespace gammamax {

inline std::uint64_t peak_memory_bytes() {
#if defined(_WIN32)
    PROCESS_MEMORY_COUNTERS counters{};
    counters.cb = sizeof(counters);
    if (!GetProcessMemoryInfo(GetCurrentProcess(), &counters, sizeof(counters))) {
        throw std::runtime_error("GetProcessMemoryInfo failed");
    }
    return static_cast<std::uint64_t>(counters.PeakWorkingSetSize);
#else
    mach_task_basic_info_data_t info{};
    mach_msg_type_number_t count = MACH_TASK_BASIC_INFO_COUNT;
    if (task_info(mach_task_self(), MACH_TASK_BASIC_INFO,
                  reinterpret_cast<task_info_t>(&info), &count) != KERN_SUCCESS) {
        throw std::runtime_error("Mach task_info failed");
    }
    return static_cast<std::uint64_t>(info.resident_size_max);
#endif
}

}  // namespace gammamax

