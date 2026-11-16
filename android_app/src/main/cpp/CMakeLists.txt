cmake_minimum_required(VERSION 3.22.1)
project("dew_native_ai" LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Optimizaciones SIMD ARM64 para móviles (Snapdragon / Tensor / Dimensity / Exynos)
if(ANDROID_ABI STREQUAL "arm64-v8a")
    add_compile_options(-march=armv8.2-a+dotprod+fp16 -O3 -ffast-math -funroll-loops)
elseif(ANDROID_ABI STREQUAL "x86_64")
    add_compile_options(-mavx2 -mfma -mf16c -O3)
endif()

# Detectar si el submódulo de llama.cpp está presente en third_party/llama.cpp
set(LLAMA_CPP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../../third_party/llama.cpp")
if(EXISTS "${LLAMA_CPP_DIR}/CMakeLists.txt")
    message(STATUS "[Dew Native] Compilando con motor llama.cpp completo desde: ${LLAMA_CPP_DIR}")
    set(LLAMA_BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(LLAMA_BUILD_SERVER OFF CACHE BOOL "" FORCE)
    add_subdirectory("${LLAMA_CPP_DIR}" build-llama EXCLUDE_FROM_ALL)
    add_compile_definitions(DEW_HAS_LLAMA_CPP=1)
else()
    message(STATUS "[Dew Native] Compilando puente JNI en modo ligero (ejecuta scripts/setup_native_deps.ps1 para enlazar llama.cpp completo)")
    add_compile_definitions(DEW_HAS_LLAMA_CPP=0)
endif()

add_library(
    dew_native_ai
    SHARED
    dew_jni_bridge.cpp
)

find_library(log-lib log)
find_library(android-lib android)

target_link_libraries(
    dew_native_ai
    ${log-lib}
    ${android-lib}
)

if(EXISTS "${LLAMA_CPP_DIR}/CMakeLists.txt")
    target_link_libraries(dew_native_ai llama common)
endif()
