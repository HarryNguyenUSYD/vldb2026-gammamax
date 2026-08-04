cmake_minimum_required(VERSION 3.20)
project(betamax LANGUAGES CXX)

add_executable(betamax src/main.cpp)

target_compile_features(betamax PRIVATE cxx_std_20)

target_include_directories(
  betamax PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_SOURCE_DIR}/third_party
)

if(WIN32)
  target_link_libraries(betamax PRIVATE psapi)
endif()
