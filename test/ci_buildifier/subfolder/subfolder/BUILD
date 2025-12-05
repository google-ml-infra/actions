# This BUILD file contained intentional formatting errors
# and is then formatted by running the buildifier locally.

package(default_visibility = ["//visibility:public"])

licenses(["notice"])  # Apache 2.0

cc_library(
    name = "my_library",
    srcs = [
        "my_library.cc",
    ],
    hdrs = [
        "my_library.h",
    ],
    deps = [
        "//third_party/some_lib",
        "//util:common_utils",
    ],
)

cc_binary(
    name = "my_binary",
    srcs = [
        "main.cc",
    ],
    deps = [
        ":my_library",
        "//framework:base",
    ],
)
