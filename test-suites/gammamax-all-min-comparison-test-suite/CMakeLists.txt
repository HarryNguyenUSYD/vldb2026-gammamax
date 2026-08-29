cmake_minimum_required(VERSION 3.20)
project(gammamax_all_min_comparison_test_suite LANGUAGES CXX)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
foreach(configuration Debug Release RelWithDebInfo MinSizeRel)
  string(TOUPPER ${configuration} configuration_upper)
  set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_${configuration_upper} ${CMAKE_BINARY_DIR})
endforeach()

set(GAMMAMAX_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/sources/gammamax")
add_subdirectory(${GAMMAMAX_SOURCE_DIR} ${CMAKE_CURRENT_BINARY_DIR}/gammamax-build)
set(GAMMAMAX_ALL_MIN_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/sources/gammamax-all-min")
add_subdirectory(${GAMMAMAX_ALL_MIN_SOURCE_DIR} ${CMAKE_CURRENT_BINARY_DIR}/gammamax-all-min-build)

foreach(format date time url isbn ipv4 ipv6)
  add_executable(validate_${format} validators/validator.cpp)
  target_compile_features(validate_${format} PRIVATE cxx_std_20)
endforeach()
