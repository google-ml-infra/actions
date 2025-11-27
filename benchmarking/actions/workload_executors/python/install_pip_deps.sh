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
# PIP_PROJECT_PATH (REQUIRED): The path to the Python project directory.
# PIP_OPTIONAL_DEPS (OPTIONAL): Base comma-separated list of extra pip packages.
# PIP_OPTIONAL_DEPS_HW (OPTIONAL): Comma-separated list of hardware-specific extra pip packages. This list is appended to pip_optional_dependencies.

set -euo pipefail

USER_REPO="$GITHUB_WORKSPACE/user_repo"
PROJECT_DIR="$USER_REPO/$PIP_PROJECT_PATH"

cd "$PROJECT_DIR" || exit 1
echo "Searching for dependency files in $PROJECT_DIR."

get_combined_extras() {
  local extras=()
  
  if [[ -n "${PIP_OPTIONAL_DEPS:-}" ]]; then
    extras+=("$PIP_OPTIONAL_DEPS")
  fi
  
  if [[ -n "${PIP_OPTIONAL_DEPS_HW:-}" ]]; then
    extras+=("$PIP_OPTIONAL_DEPS_HW")
  fi

  echo "$(IFS=,; echo "${extras[*]}")"
}

if [[ -f "requirements.lock" ]]; then
    echo "Found requirements.lock, installing from lock file."
    pip install -r requirements.lock

elif [[ -f "pyproject.toml" ]]; then
    COMBINED_EXTRA_DEPS="$(get_combined_extras)"
    echo "Found pyproject.toml, installing from source."

    if [[ -n "$COMBINED_EXTRA_DEPS" ]]; then
        echo "Installing optional deps: [$COMBINED_EXTRA_DEPS]"
        pip install ".[$COMBINED_EXTRA_DEPS]"
    else
        pip install .
    fi

elif [[ -f "requirements.txt" ]]; then
    echo "Found requirements.txt, installing."
    pip install -r requirements.txt

else
    echo "No dependency file was found in $PROJECT_DIR."
fi
