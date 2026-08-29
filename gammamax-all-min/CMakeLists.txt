cmake_minimum_required(VERSION 3.20)
project(gammamax_all_min LANGUAGES CXX)

add_executable(gammamax-all-min src/main.cpp)

target_compile_features(gammamax-all-min PRIVATE cxx_std_20)

target_include_directories(
  gammamax-all-min PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_SOURCE_DIR}/third_party
)

if(WIN32)
  target_link_libraries(gammamax-all-min PRIVATE psapi)
endif()

include(CTest)
if(BUILD_TESTING)
  add_executable(gammamax_all_min_tests tests/gammamax_tests.cpp)
  target_compile_features(gammamax_all_min_tests PRIVATE cxx_std_20)
  target_include_directories(gammamax_all_min_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/third_party)
  add_test(NAME gammamax_all_min_tests COMMAND gammamax_all_min_tests)
endif()
