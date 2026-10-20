cmake_minimum_required(VERSION 3.15)
project(vrhand_driver LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Статическая библиотека C++ — чтобы у пользователя не требовался Visual C++ Redistributable.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

set(OPENVR_DIR "" CACHE PATH "Путь к клону https://github.com/ValveSoftware/openvr")
if(NOT EXISTS "${OPENVR_DIR}/headers/openvr_driver.h")
    message(FATAL_ERROR "Укажите -DOPENVR_DIR=<папка openvr> (нужен headers/openvr_driver.h)")
endif()

add_library(driver_vrhand SHARED src/driver_main.cpp src/protocol.h)
target_include_directories(driver_vrhand SYSTEM PRIVATE "${OPENVR_DIR}/headers")
set_target_properties(driver_vrhand PROPERTIES PREFIX "")

if(WIN32)
    target_compile_definitions(driver_vrhand PRIVATE _CRT_SECURE_NO_WARNINGS)
    target_link_libraries(driver_vrhand PRIVATE ws2_32)
else()
    set_target_properties(driver_vrhand PROPERTIES CXX_VISIBILITY_PRESET hidden)
    find_package(Threads REQUIRED)
    target_link_libraries(driver_vrhand PRIVATE Threads::Threads)
endif()

# Готовая папка драйвера для SteamVR:  <prefix>/vrhand/{driver.vrdrivermanifest, bin/win64/driver_vrhand.dll, resources/...}
install(DIRECTORY package/vrhand DESTINATION .)
install(TARGETS driver_vrhand
        RUNTIME DESTINATION vrhand/bin/win64
        LIBRARY DESTINATION vrhand/bin/win64)
