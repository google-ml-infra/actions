#!/usr/bin/env bash

# Copyright 2025 Google LLC

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     https://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Requires Bash 4.3+ (out in February 2014). Other shells likely will not work.
#
# Wrapper that attempts to ensure a suitable Python is available before invoking
# wait_for_connection.py.
# Bash x-trace is logged to a file, which is shown on error, for easier inspection.

set -euo pipefail

source "$(dirname "$0")/utils.sh"

# X-trace setup — write set -x output only to $TRACE_FILE
TRACE_FILE="$(_normalize_path "${HOME}/connection_trace_$(date +%s).log")"
# Automatically find an available FD (>=10) and store its number in trace_fd
exec {trace_fd}>"${TRACE_FILE}"
export BASH_XTRACEFD="$trace_fd"   # Bash will write x-trace to this FD

set -x

# Cleanup trap — always runs, even on SIGINT
cleanup() {
  local status=$?
  if [[ $status -ne 0 ]]; then
    # Show the trace in the GitHub Actions log, foldable as a group
    echo >&2
    echo ">>>> Script execution trace (set -x output) to help diagnose failures:" >&2
    echo "::group::connection-debug-trace"
    cat "${TRACE_FILE}"
    echo "::endgroup::"

    print_basic_connection_command_if_requested
  fi

  rm -f "${TRACE_FILE}"
  exec {trace_fd}>&-               # close the FD opened for X-trace
  exit "$status"
}
trap cleanup EXIT

# This step is for testing purposes only.
# This will attempt to "hide" Pythons available via python/python3, so the
# Python procurement script can run in full.
if [[ -n "${MLCI_HIDE_PYTHON:-}" ]]; then
  hide_existing_pythons
fi

echo "INFO: Ensuring a suitable Python exists for running debug connection logic." >&2

python_bin=""
ensure_suitable_python_is_available python_bin
"$python_bin" -V
"$python_bin" "$GITHUB_ACTION_PATH/wait_for_connection.py"
