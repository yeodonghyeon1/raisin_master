cmake_minimum_required(VERSION 3.14)
project("raisin_master")
set(CMAKE_CXX_STANDARD 17)       # Use C++17
set(CMAKE_CXX_STANDARD_REQUIRED ON) # Ensure the standard is required
set(CMAKE_CXX_EXTENSIONS OFF)       # Disable compiler-specific extensions (e.g., GNU extensions)

option(RAISIN_RELEASE_BUILD "Build unit tests for the project" OFF)

if(NOT RAISIN_RELEASE_BUILD)
    set(CMAKE_INSTALL_PREFIX "@@SCRIPT_DIR@@/install")
endif()

include(@@SCRIPT_DIR@@/cmake/raisin_helper.cmake)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -march=native")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -march=native")
set(CMAKE_PREFIX_PATH "@@SCRIPT_DIR@@/install;${CMAKE_PREFIX_PATH}" CACHE PATH "Search paths for CMake packages")
set(RAISIN_MASTER_INCLUDE @@SCRIPT_DIR@@/generated/include CACHE STRING "include path")
set(CMAKE_DEBUG_POSTFIX "_debug_build" CACHE STRING "Debug Postfix for lib, samples and tools")
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
add_compile_options(-Werror=return-type)
add_compile_options(-Wno-unused-function)
add_compile_options(-Wno-sign-compare)
add_compile_options($<$<COMPILE_LANGUAGE:CXX>:-Wno-reorder>)

## Top-level CMakeLists.txt
#set(SAN_FLAGS "-fsanitize=address,undefined,leak -fno-omit-frame-pointer")
#
#foreach(lang C CXX)
#    set(CMAKE_${lang}_FLAGS_DEBUG
#            "${CMAKE_${lang}_FLAGS_DEBUG} ${SAN_FLAGS}")
#endforeach()
#
#set(CMAKE_EXE_LINKER_FLAGS_DEBUG
#        "${CMAKE_EXE_LINKER_FLAGS_DEBUG} -fsanitize=address,undefined,leak")
#set(CMAKE_SHARED_LINKER_FLAGS_DEBUG
#        "${CMAKE_SHARED_LINKER_FLAGS_DEBUG} -fsanitize=address,undefined,leak")

if((CMAKE_CXX_COMPILER_ID MATCHES "Clang" OR CMAKE_CXX_COMPILER_ID MATCHES "GNU"))
    find_program(CCACHE_FOUND ccache)
    if(CCACHE_FOUND)
        message(STATUS "Using ccache to speed up incremental builds")
        set_property(GLOBAL PROPERTY RULE_LAUNCH_COMPILE ccache)
        set_property(GLOBAL PROPERTY RULE_LAUNCH_LINK ccache)
        set(ENV{CCACHE_CPP2} "true")
    endif()
endif()

# Define the output file path in the source directory
set(OUTPUT_FILE "${CMAKE_SOURCE_DIR}/RAISIN_BUILD_DIRECTORY")

# Write the build directory path to the file
file(WRITE "${OUTPUT_FILE}" "${CMAKE_BINARY_DIR}\n")

# Display a message in the console
message(STATUS "Build directory saved to ${OUTPUT_FILE}")

install(DIRECTORY generated/include/
        DESTINATION include  # where to install the headers
        FILES_MATCHING PATTERN "*.hpp"     # only install .hpp files
)

@@SUB_PROJECT@@