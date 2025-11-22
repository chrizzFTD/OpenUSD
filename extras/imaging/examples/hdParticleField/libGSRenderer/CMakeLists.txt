
find_package(Imath REQUIRED)
find_package(OpenImageIO REQUIRED)

set(SOURCES
        gsRenderer.cpp
)

add_library(GSRenderer SHARED ${SOURCES})

set_target_properties(GSRenderer PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS ON)

target_link_libraries(GSRenderer PUBLIC
        Imath::Imath
        ${OIIO_LIBRARIES}
)

target_include_directories(GSRenderer
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/>
        ${OIIO_INCLUDE_DIRS}
)

install(TARGETS GSRenderer
        LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
)
