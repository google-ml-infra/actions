#!/bin/bash
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

# Script for running the benchmark workload.
#
# Environment variables:
#
# GITHUB_WORKSPACE (REQUIRED): Default working directory on the runner.
# WORKLOAD_TYPE (REQUIRED): The type of workload to run ('bazel_workload' pr 'python_workload').
# RUNTIME_FLAGS_JSON (REQUIRED): A JSON string array of runtime flags to pass to the benchmark (e.g., '["--flag1", "value1"]').
# EXECUTION_TARGET (CONDITIONAL): The Bazel target to run. Required if WORKLOAD_TYPE is 'bazel_workload'. 
# SCRIPT_PATH (CONDITIONAL): The path to the Python script, relative to the repository root. Required if WORKLOAD_TYPE is 'python_workload'.

set -euo pipefail

USER_REPO="$GITHUB_WORKSPACE/user_repo"
export TENSORBOARD_OUTPUT_DIR="$GITHUB_WORKSPACE/tblogs"

mkdir -p "$TENSORBOARD_OUTPUT_DIR"
cd "$USER_REPO" || exit 1
readarray -t USER_FLAGS < <(jq -r '.[]' <<< "$RUNTIME_FLAGS_JSON")

if [[ "$WORKLOAD_TYPE" == "bazel_workload" ]]; then
    bazel run "$EXECUTION_TARGET" -- "${USER_FLAGS[@]}"

elif [[ "$WORKLOAD_TYPE" == "python_workload" ]]; then
    PYTHON_SCRIPT_PATH="$GITHUB_WORKSPACE/user_repo/$SCRIPT_PATH"
    python "$PYTHON_SCRIPT_PATH" "${USER_FLAGS[@]}"

else
    echo "Error: Unknown workload type '$WORKLOAD_TYPE'."
    exit 1
fi
