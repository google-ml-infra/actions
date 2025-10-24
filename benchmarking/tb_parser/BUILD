# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

load("@rules_python//python:py_binary.bzl", "py_binary")
load("@rules_python//python:py_test.bzl", "py_test")
load("@rules_python//python:py_library.bzl", "py_library")

py_library(
    name = "tb_parser_lib",
    srcs = ["tb_parser_lib.py"],
    deps = [
        "//benchmarking/proto:benchmark_registry_py_proto",
        "//benchmarking/proto:benchmark_result_py_proto",
        "//benchmarking/proto/common:stat_py_proto",
        "@pypi//numpy",
        "@pypi//tensorflow",
        "@pypi//setuptools"
    ],
)

py_binary(
    name = "tb_parser",
    main = "tb_parser.py",
    srcs = ["tb_parser.py"],
    deps = [
        ":tb_parser_lib",
        "@pypi//protovalidate",
        "@pypi//bufbuild_protovalidate_protocolbuffers_python",
        "//benchmarking/proto:benchmark_registry_py_proto",
        "//benchmarking/proto:benchmark_result_py_proto",
    ],
)

py_test(
    name = "tb_parser_test",
    srcs = ["tb_parser_test.py"],
    deps = [
        ":tb_parser_lib",
        "@pypi//pytest"
    ],
)
