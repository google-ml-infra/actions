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

# Script to install workload pip deps.
#
# Environment variables:
#
# GITHUB_WORKSPACE (REQUIRED): Default working directory on the runner.
# PIP_PROJECT_PATH (REQUIRED): The path to the Python project directory, relative to the repository root (e.g., '.').
# PIP_EXTRA_DEPS_JSON (REQUIRED): A JSON string array of optional 'extras' to install (e.g., '["test", "dev"]' or '[]'). Only used if 'pyproject.toml' is found.

set -euo pipefail

USER_REPO="$GITHUB_WORKSPACE/user_repo"
PROJECT_DIR="$USER_REPO/$PIP_PROJECT_PATH"

cd "$PROJECT_DIR" || exit 1
echo "Searching for dependency files in $PROJECT_DIR."

if [[ -f "requirements.lock" ]]; then
    echo "Found requirements.lock, installing from lock file."
    pip install -r requirements.lock

elif [[ -f "pyproject.toml" ]]; then
    echo "Found pyproject.toml, installing from source."
    pip install .

PIP_EXTRA_DEPS="$(jq -r 'join(",")' <<< "$PIP_EXTRA_DEPS_JSON")"

if [[ -n "$PIP_EXTRA_DEPS" ]]; then
    echo "Installing optional dependencies: [$PIP_EXTRA_DEPS]"
    pip install .["$PIP_EXTRA_DEPS"]
fi

elif [[ -f "requirements.txt" ]]; then
    echo "Found requirements.txt, installing."
    pip install -r requirements.txt

else
    echo "Warning: Workload was python_workload, but no dependency file was found in $PROJECT_DIR."
fi
