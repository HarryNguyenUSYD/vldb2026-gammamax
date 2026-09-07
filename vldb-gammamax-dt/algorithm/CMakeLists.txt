cmake_minimum_required(VERSION 3.20)
project(vldb_theory_algorithm LANGUAGES CXX)

add_executable(vldb_theory_algorithm src/main.cpp)
target_compile_features(vldb_theory_algorithm PRIVATE cxx_std_20)
target_include_directories(vldb_theory_algorithm PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_SOURCE_DIR}/vendor)
if(WIN32)
  target_link_libraries(vldb_theory_algorithm PRIVATE psapi)
endif()

include(CTest)
if(BUILD_TESTING)
  add_executable(vldb_theory_algorithm_tests tests/tests.cpp)
  target_compile_features(vldb_theory_algorithm_tests PRIVATE cxx_std_20)
  target_include_directories(vldb_theory_algorithm_tests PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor)
  add_test(NAME vldb_theory_algorithm_tests COMMAND vldb_theory_algorithm_tests)
endif()
