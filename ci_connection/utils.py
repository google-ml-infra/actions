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


"""Miscellaneous config/utilities for remote connection functionality."""

import logging
import os
import sys


# Default path constants for saving/reading execution state
STATE_OUT_DIR = os.path.join(os.path.expandvars("$HOME"), ".workflow_state")
# Path for info for last command, current directory, env vars, etc.
STATE_EXEC_INFO_FILENAME = "execution_state.json"
STATE_INFO_PATH = os.path.join(STATE_OUT_DIR, STATE_EXEC_INFO_FILENAME)
# Environment variables standalone file path, for being ingested via `source`,
STATE_ENV_FILENAME = "env.txt"
STATE_ENV_OUT_PATH = os.path.join(STATE_OUT_DIR, STATE_ENV_FILENAME)


# Check if debug logging should be enabled for the scripts:
# WAIT_FOR_CONNECTION_DEBUG is a custom variable.
# RUNNER_DEBUG and ACTIONS_RUNNER_DEBUG are GH env vars, which can be set
# in various ways, one of them - enabling debug logging from the UI, when
# triggering a run:
# https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/store-information-in-variables#default-environment-variables
# https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/troubleshooting-workflows/enabling-debug-logging#enabling-runner-diagnostic-logging
_SHOW_DEBUG = bool(
  os.getenv(
    "WAIT_FOR_CONNECTION_DEBUG",
    os.getenv("RUNNER_DEBUG", os.getenv("ACTIONS_RUNNER_DEBUG")),
  )
)


def setup_logging():
  logging.basicConfig(
    level=logging.INFO if not _SHOW_DEBUG else logging.DEBUG,
    format="%(levelname)s: %(message)s",
    stream=sys.stderr,
  )
