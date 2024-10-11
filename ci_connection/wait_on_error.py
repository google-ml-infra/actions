# Copyright 2024 Google LLC

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     https://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Wait for a connection on error.

A convenience script that can be triggered on error (via `trap`), without having
to add a separate wait-for-connection step to a workflow.

When a command errors out, and the script is called, it will:
1. Save the environment state at the moment of error.
2. Begin waiting for connection.
3. If/when a remote connection is established, load in the env state from earlier,
   to closely approximate the state of the workflow at the moment of failure.

For more details, see the code.

Examples:
    See the wait-for-connection-on-error-test.yaml workflow in this repo.
"""

import preserve_run_state
import wait_for_connection


if __name__ == "__main__":
  preserve_run_state.save_all_info()
  wait_for_connection.main()
