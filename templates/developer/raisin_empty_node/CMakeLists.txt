cmake_minimum_required(VERSION 3.15)

## write your package name
project(raisin_empty_node)

set(ENV{RAISIN_WS} "../../..") ## set the path to your raisin workspace
set(CMAKE_PREFIX_PATH $ENV{RAISIN_WS}/install)

## added your dependencies here
find_package(raisin_network REQUIRED)

add_library(${PROJECT_NAME} SHARED
        src/raisin_empty_publisher_service.cpp
        src/raisin_empty_subscriber_client.cpp
)
set_property(TARGET ${PROJECT_NAME} PROPERTY POSITION_INDEPENDENT_CODE ON)

## write your dependencies here
target_link_libraries(${PROJECT_NAME} raisin_network)

target_include_directories(${PROJECT_NAME}
        PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<BUILD_INTERFACE:${RAISIN_MASTER_INCLUDE}> ## headers for the message files
        $<INSTALL_INTERFACE:include>)
target_include_directories(${PROJECT_NAME} PRIVATE  $ENV{RAISIN_WS}/install)

add_executable(ps src/main_ps.cpp)
target_link_libraries(ps ${PROJECT_NAME})

add_executable(sc src/main_sc.cpp)
target_link_libraries(sc ${PROJECT_NAME})
