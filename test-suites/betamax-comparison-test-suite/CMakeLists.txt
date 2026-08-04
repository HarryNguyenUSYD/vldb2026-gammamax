cmake_minimum_required(VERSION 3.20)
project(betamax_comparison_test_suite LANGUAGES CXX)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
foreach(configuration Debug Release RelWithDebInfo MinSizeRel)
  string(TOUPPER ${configuration} configuration_upper)
  set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_${configuration_upper} ${CMAKE_BINARY_DIR})
endforeach()

set(BETAMAX_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/sources/betamax")
set(BETAMAX_OLD_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/sources/betamax-old/main.cpp")

add_subdirectory(${BETAMAX_SOURCE_DIR}
                 ${CMAKE_CURRENT_BINARY_DIR}/betamax-build)
add_executable(betamax-old ${BETAMAX_OLD_SOURCE})
target_compile_features(betamax-old PRIVATE cxx_std_20)

foreach(format date time url isbn ipv4 ipv6)
  add_executable(validate_${format} validators/validator.cpp)
  target_compile_features(validate_${format} PRIVATE cxx_std_20)

  add_executable(validate_old_${format} validators/validator.cpp)
  target_compile_features(validate_old_${format} PRIVATE cxx_std_20)
  target_compile_definitions(validate_old_${format} PRIVATE VALIDATOR_FILE_INPUT=1)
endforeach()
