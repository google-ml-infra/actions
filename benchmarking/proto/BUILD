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

load("@protobuf//bazel:proto_library.bzl", "proto_library")
load("@protobuf//bazel:py_proto_library.bzl", "py_proto_library")
load("@rules_python//python:py_library.bzl", "py_library")

proto_library(
    name = "benchmark_registry_proto",
    srcs = ["benchmark_registry.proto"],
    deps = [
        "@protovalidate//proto/protovalidate/buf/validate:validate_proto",
    ],
)

py_proto_library(
    name = "benchmark_registry_py_proto",
    deps = [":benchmark_registry_proto"],
    visibility = ["//benchmarking:__subpackages__"],
)
