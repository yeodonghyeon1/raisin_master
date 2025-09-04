cmake_minimum_required(VERSION 3.15)
project(raisin_gui_empty_window)

raisin_find_package(raisin_gui_base REQUIRED)

add_library(${PROJECT_NAME} SHARED ${PROJECT_NAME}.cpp)

target_include_directories(${PROJECT_NAME}
        PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<BUILD_INTERFACE:${RAISIN_MASTER_INCLUDE}> ## headers for the message files
        $<INSTALL_INTERFACE:include>)

target_link_libraries(${PROJECT_NAME} raisin_gui_base)
set_target_properties(${PROJECT_NAME} PROPERTIES POSITION_INDEPENDENT_CODE TRUE)

install(TARGETS ${PROJECT_NAME}
        EXPORT export_${PROJECT_NAME}
        LIBRARY DESTINATION lib
        ARCHIVE DESTINATION lib
        RUNTIME DESTINATION bin
        INCLUDES DESTINATION include
)

install(TARGETS ${PROJECT_NAME} DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY include/ DESTINATION include)


