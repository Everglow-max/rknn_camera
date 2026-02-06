cmake_minimum_required(VERSION 3.10)

project(rknn_retinaface_demo)

if (ENABLE_ASAN)
	message(STATUS "BUILD WITH ADDRESS SANITIZER")
	set (CMAKE_C_FLAGS_DEBUG "${CMAKE_C_FLAGS_DEBUG} -fno-omit-frame-pointer -fsanitize=address")
	set (CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} -fno-omit-frame-pointer -fsanitize=address")
	set (CMAKE_LINKER_FLAGS_DEBUG "${CMAKE_LINKER_FLAGS_DEBUG} -fno-omit-frame-pointer -fsanitize=address")
endif ()

add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../../3rdparty/ 3rdparty.out)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../../utils/ utils.out)

# opencv
if(CMAKE_SIZEOF_VOID_P EQUAL 8)
message(STATUS "64bit")
set (TARGET_LIB_ARCH lib64)
else()
message(STATUS "32bit")
set (TARGET_LIB_ARCH lib)
endif()
if (CMAKE_SYSTEM_NAME STREQUAL "Android")
  set(OpenCV_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../3rdparty/opencv/opencv-android-sdk-build/sdk/native/jni/abi-${CMAKE_ANDROID_ARCH_ABI})
else()
    if(TARGET_LIB_ARCH STREQUAL "lib")
      set(OpenCV_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../3rdparty/opencv/opencv-linux-armhf/share/OpenCV)
    else()
      set(OpenCV_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../3rdparty/opencv/opencv-linux-aarch64/share/OpenCV)
    endif()
endif()
find_package(OpenCV REQUIRED)
message(STATUS OpenCV_DIR=${OpenCV_DIR})
message(STATUS OpenCV_LIBS=${OpenCV_LIBS})

set(CMAKE_INSTALL_RPATH "$ORIGIN/../lib")

if (TARGET_SOC STREQUAL "rk1808" OR TARGET_SOC STREQUAL "rv1109" OR TARGET_SOC STREQUAL "rv1126")
    set(retinaface_file rknpu1/retinaface.cc)
else()
    set(retinaface_file rknpu2/retinaface.cc)
endif()

file(GLOB SRCS ${CMAKE_CURRENT_SOURCE_DIR}/*.cc)

add_executable(${PROJECT_NAME}
    main.cc
    ${retinaface_file}
)

add_executable(rknn_retinaface_camera_demo
    camera_opencv_demo.cc
    ${retinaface_file}
)

target_link_libraries(${PROJECT_NAME}
    fileutils
    imageutils
    imagedrawing
    ${LIBRKNNRT}
    dl
)

target_link_libraries(rknn_retinaface_camera_demo
    fileutils
    imageutils
    imagedrawing
    ${OpenCV_LIBS}
    ${LIBRKNNRT}
    dl
)

if (CMAKE_SYSTEM_NAME STREQUAL "Android")
    target_link_libraries(${PROJECT_NAME} log )
    target_link_libraries(rknn_retinaface_camera_demo log )
endif()

if (CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(THREADS_PREFER_PTHREAD_FLAG ON)
    find_package(Threads REQUIRED)
    target_link_libraries(${PROJECT_NAME} Threads::Threads)
    target_link_libraries(rknn_retinaface_camera_demo Threads::Threads)
endif()



target_include_directories(${PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${LIBRKNNRT_INCLUDES}
    ${OpenCV_INCLUDE_DIRS}
)

target_include_directories(rknn_retinaface_camera_demo PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${LIBRKNNRT_INCLUDES}
    ${OpenCV_INCLUDE_DIRS}
)

install(TARGETS ${PROJECT_NAME} DESTINATION .)
install(TARGETS rknn_retinaface_camera_demo DESTINATION .)
install(FILES ${CMAKE_CURRENT_SOURCE_DIR}/../model/test.jpg DESTINATION model)
set(file_path ${CMAKE_CURRENT_SOURCE_DIR}/../model/RetinaFace.rknn)
if (EXISTS ${file_path})
    install(FILES ${file_path} DESTINATION model)
endif()
