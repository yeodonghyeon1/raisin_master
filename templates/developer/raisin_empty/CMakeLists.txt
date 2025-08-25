cmake_minimum_required(VERSION 3.15)

## write your package name
project(raisin_empty)

## added your dependencies here (not necessary for this demo)
#raisin_find_package(raisin_parameters REQUIRED)

add_library(${PROJECT_NAME} SHARED
        src/raisin_empty.cpp
)
set_property(TARGET ${PROJECT_NAME} PROPERTY POSITION_INDEPENDENT_CODE ON)

## write your dependencies here
#target_link_libraries(${PROJECT_NAME} yaml-cpp raisin_master Eigen3::Eigen)

target_include_directories(${PROJECT_NAME}
        PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<BUILD_INTERFACE:${RAISIN_MASTER_INCLUDE}> ## headers for the message files
        $<INSTALL_INTERFACE:include>)

## write your install dependencies here
raisin_install(${PROJECT_NAME}) ## Eigen3 yaml-cpp) ## dependencies for the installed packages should go here


