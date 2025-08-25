function(raisin_find_package package_name)
    if(NOT TARGET ${package_name})
        find_package(${package_name} REQUIRED)
    endif()
endfunction()

function(raisin_install_without_config PROJECT_NAME)
    install(DIRECTORY include/ DESTINATION include)

    install(
        TARGETS ${PROJECT_NAME}
        EXPORT export_${PROJECT_NAME}
        LIBRARY DESTINATION lib
        ARCHIVE DESTINATION lib
        RUNTIME DESTINATION bin
        INCLUDES DESTINATION include
    )

    install(
        EXPORT export_${PROJECT_NAME}
        FILE ${PROJECT_NAME}Targets.cmake
        DESTINATION lib/cmake/${PROJECT_NAME}
    )
endfunction()

function(raisin_install PROJECT_NAME)
    raisin_install_without_config(${PROJECT_NAME})
    include(CMakePackageConfigHelpers)

    set(find_package_string "")
    foreach(libName IN LISTS ARGN)
        string(APPEND find_package_string "find_package(${libName} REQUIRED)\n")
    endforeach()

    set(_package_config_in_content
        "@PACKAGE_INIT@\n\n${find_package_string}\ninclude(\"\${CMAKE_CURRENT_LIST_DIR}/${PROJECT_NAME}Targets.cmake\")\n"
    )

    set(_package_config_in_path "${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}Config.cmake.in")
    file(WRITE "${_package_config_in_path}" "${_package_config_in_content}")

    configure_package_config_file(
        "${_package_config_in_path}"
        "${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}Config.cmake"
        INSTALL_DESTINATION "lib/cmake/${PROJECT_NAME}"
    )

    install(
        FILES
        "${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}Config.cmake"
        DESTINATION lib/cmake/${PROJECT_NAME}
    )
endfunction()

function(raisin_install_config_string PROJECT_NAME CONFIG_STRING)
    raisin_install_without_config(${PROJECT_NAME})
    include(CMakePackageConfigHelpers)

    set(_package_config_in_content
        "@PACKAGE_INIT@\n\n${CONFIG_STRING}\ninclude(\"\${CMAKE_CURRENT_LIST_DIR}/${PROJECT_NAME}Targets.cmake\")\n"
    )

    set(_package_config_in_path "${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}Config.cmake.in")
    file(WRITE "${_package_config_in_path}" "${_package_config_in_content}")

    configure_package_config_file(
        "${_package_config_in_path}"
        "${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}Config.cmake"
        INSTALL_DESTINATION "lib/cmake/${PROJECT_NAME}"
    )

    install(
        FILES
        "${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}Config.cmake"
        DESTINATION lib/cmake/${PROJECT_NAME}
    )
endfunction()

function(raisin_recommended_clang_tidy)
    find_program(CLANG_TIDY_EXE
            NAMES clang-tidy clang-tidy-18 clang-tidy-17 clang-tidy-16 clang-tidy-15 clang-tidy-14)

    if(NOT CLANG_TIDY_EXE)
        message(WARNING "clang-tidy not found – disabled")
        return()
    endif()

    set(_clang_checks
            "-checks=clang-analyzer-*"
            ",-clang-analyzer-optin.cplusplus.UninitializedObject"
            ",-clang-analyzer-cplusplus.StringChecker"
            ",bugprone-use-after-move"
            ",bugprone-dangling-handle"
            ",bugprone-infinite-loop"
            ",bugprone-sizeof-expression"
            ",bugprone-misplaced-widening-cast"
            ",misc-dangling-handle"
            ",bugprone-return-stack-address"
            ",cppcoreguidelines-dangling-handle"
            ",cppcoreguidelines-no-dangling-reference"
            ",security.insecureAPI.*"
    )
    string(JOIN "" CLANG_TIDY_CHECKS ${_clang_checks})

    # Get full GCC version string (e.g. "11.4.0")
    execute_process(
            COMMAND ${CMAKE_CXX_COMPILER} -dumpfullversion
            OUTPUT_VARIABLE GCC_FULL_VERSION
            OUTPUT_STRIP_TRAILING_WHITESPACE
    )

    if(NOT GCC_FULL_VERSION)
        # fallback if -dumpfullversion unsupported
        execute_process(
                COMMAND ${CMAKE_CXX_COMPILER} -dumpversion
                OUTPUT_VARIABLE GCC_FULL_VERSION
                OUTPUT_STRIP_TRAILING_WHITESPACE
        )
    endif()

    # Extract major version (digits before first dot)
    string(REGEX MATCH "^[0-9]+" GCC_MAJOR_VERSION "${GCC_FULL_VERSION}")

    message(STATUS "GCC major version: ${GCC_MAJOR_VERSION}")

    set(CLANG_TIDY_OPTS
            "${CLANG_TIDY_CHECKS}"
            "-warnings-as-errors=*"
            "-extra-arg=-Wno-unused-command-line-argument"
            "-extra-arg=-Qunused-arguments"
            "--extra-arg-before=-I/usr/include/c++/${GCC_MAJOR_VERSION}"
            "--extra-arg-before=-I/usr/include/x86_64-linux-gnu/c++/${GCC_MAJOR_VERSION}"
    )

    set(CMAKE_CXX_CLANG_TIDY
            "${CLANG_TIDY_EXE};${CLANG_TIDY_OPTS}"
            PARENT_SCOPE)
endfunction()