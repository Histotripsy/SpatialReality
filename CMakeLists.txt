cmake_minimum_required(VERSION 3.16)
project(SRDBridge LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ------------------------------------------------------------
# Paths (repo root)
# ------------------------------------------------------------
set(ROOT_DIR ${CMAKE_CURRENT_SOURCE_DIR})
set(XR_DIR ${ROOT_DIR}/XR_API)
set(GL3W_DIR ${ROOT_DIR}/third_party/gl3w)
set(GLFW_DIR ${ROOT_DIR}/third_party/GLFW)
set(GLM_DIR ${ROOT_DIR}/third_party/glm)

# ------------------------------------------------------------
# Sony Native API (not redistributed — download separately)
# ------------------------------------------------------------
if(NOT EXISTS "${XR_DIR}/include/xr_api_wrapper.h")
    message(FATAL_ERROR
        "Sony SRD Native API not found at ${XR_DIR}\n"
        "1. Download Native API from:\n"
        "   https://xyn.sony.net/en/developer/setup/spatial-reality-display/download-info \n"
        "2. From the NativeAPI package, copy the XR_API folder to:\n"
        "   ${XR_DIR}\n"
        "   Expected layout:\n"
        "     XR_API/include/...\n"
        "     XR_API/lib/Release/xr_api.lib\n"
        "     XR_API/lib/Debug/xr_api.lib\n"
        "See XR_API/README.md for details."
    )
endif()

# ------------------------------------------------------------
# Shared library
# ------------------------------------------------------------
add_library(${PROJECT_NAME} SHARED
    src/${PROJECT_NAME}.cpp
    src/${PROJECT_NAME}.h
)

target_compile_definitions(
    ${PROJECT_NAME} PRIVATE
    ${PROJECT_NAME}_EXPORTS
    GLFW_INCLUDE_NONE
)

target_include_directories(${PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${XR_DIR}/include
    ${GL3W_DIR}/include
    ${GLFW_DIR}/include
    ${GLM_DIR}/include
)

if(EXISTS ${GL3W_DIR}/src/gl3w.c)
    set_source_files_properties(
        ${GL3W_DIR}/src/gl3w.c
        PROPERTIES LANGUAGE C
    )
    target_sources(${PROJECT_NAME} PRIVATE ${GL3W_DIR}/src/gl3w.c)
else()
    message(FATAL_ERROR "gl3w.c not found under third_party/gl3w")
endif()

# Select the GLFW library directory
if(MSVC)
    if(MSVC_VERSION GREATER_EQUAL 1930)
        set(GLFW_LIB_DIR "${GLFW_DIR}/lib-vc2022")
    else()
        set(GLFW_LIB_DIR "${GLFW_DIR}/lib-vc2019")
    endif()

    if(NOT EXISTS "${GLFW_LIB_DIR}")
        message(FATAL_ERROR
            "Could not find GLFW library directory:\n"
            "  ${GLFW_LIB_DIR}")
    endif()
endif()

target_link_directories(${PROJECT_NAME} PRIVATE
    ${XR_DIR}/lib/$<CONFIG>
    ${GLFW_LIB_DIR}
)

target_link_libraries(${PROJECT_NAME} PRIVATE
    xr_api
    glfw3
    opengl32
)

if(MSVC)
    target_compile_options(${PROJECT_NAME} PRIVATE /W3)
endif()

# Copy Sony runtime DLLs beside the bridge when the package provides bin/
set(SDK_BIN_DIR ${XR_DIR}/bin/$<CONFIG>)

if(EXISTS ${XR_DIR}/bin)
    add_custom_command(
        TARGET ${PROJECT_NAME}
        POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_directory
        ${SDK_BIN_DIR}
        $<TARGET_FILE_DIR:${PROJECT_NAME}>
        COMMENT "Copying SRD SDK runtime DLLs beside ${PROJECT_NAME}.dll"
    )
endif()

message(STATUS "Configuring ${PROJECT_NAME}")
