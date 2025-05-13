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


# Wrapper that attempts to ensure a suitable Python is available before invoking
# wait_for_connection.py. When debugging is enabled,
# Bash x-trace is logged to a file for easier inspection.

source "$(dirname "$0")/utils.sh"

# X-trace setup — write set -x output only to $TRACE_FILE
TRACE_FILE="$(_normalize_path "${HOME}/connection_trace_$(date +%s).log")"
exec 19> "${TRACE_FILE}"           # FD 5 opened for the trace
export BASH_XTRACEFD=19            # Bash will write x-trace to FD 19

set -exuo pipefail

# Cleanup trap — always runs, even on SIGINT
cleanup() {
  local status=$?
  if [[ $status -ne 0 ]]; then
    # Show the trace in the GitHub Actions log, foldable as a group
    echo "::group::connection-debug-trace"
    cat "${TRACE_FILE}"
    echo "::endgroup::"
  fi
  rm -f "${TRACE_FILE}"
  exec 5>&-                       # close FD 5
  exit "$status"
}
trap cleanup EXIT

# Run the code
source "$(dirname "$0")/utils.sh"

python_bin=""
ensure_suitable_python_is_available python_bin
"$python_bin" -V
"$python_bin" "$GITHUB_ACTION_PATH/wait_for_connection.py"
