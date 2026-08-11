cmake_minimum_required(VERSION 3.20)
project(gammamax LANGUAGES CXX)

add_executable(gammamax src/main.cpp)

target_compile_features(gammamax PRIVATE cxx_std_20)

target_include_directories(
  gammamax PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_SOURCE_DIR}/third_party
)

if(WIN32)
  target_link_libraries(gammamax PRIVATE psapi)
endif()

include(CTest)
if(BUILD_TESTING)
  add_executable(gammamax_tests tests/gammamax_tests.cpp)
  target_compile_features(gammamax_tests PRIVATE cxx_std_20)
  target_include_directories(gammamax_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/third_party)
  add_test(NAME gammamax_tests COMMAND gammamax_tests)
endif()

