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


"""
Establish a connection, and keep it alive.

If provided, will reproduce execution state (directory, failed command, env)
in the established remote session.
"""

import argparse
import logging
import os
import time
import threading
import subprocess

import preserve_run_state
import utils
from utils import ConnectionSignals


utils.setup_logging()

_LOCK = threading.Lock()

KEEP_ALIVE_INTERVAL = 30


def parse_args():
  parser = argparse.ArgumentParser()
  parser.add_argument(
    "--no-env",
    dest="no_env",
    help=(
      "Whether to use the env variables from the CI shell, in the shell spawned "
      "for the user. True by default. If `wait_on_error.py` was used with an "
      "explicit request to save the env, the script can retrieve them from that time. "
      "Otherwise, the `env` information is retrieved from "
      "`wait_for_connection.py`, dynamically."
    ),
    action="store_true",
  )
  return parser.parse_args()


def send_message(message: str, expect_response: bool = False) -> bytes | None:
  """
  Communicates with the server by sending a message and optionally receiving a response.
  """
  with _LOCK:
    return utils.send_message(message, expect_response)


def keep_alive():
  while True:
    time.sleep(KEEP_ALIVE_INTERVAL)
    send_message(ConnectionSignals.KEEP_ALIVE)


def main():
  """
  1. Signal to the waiting script that we have 'connection_established'.
  2. Start a keep-alive thread to maintain the connection.
  3. Load the previous environment/directory/command if available
     and desired, then spawn an interactive shell in that context.
  """
  args = parse_args()

  send_message(ConnectionSignals.CONNECTION_ESTABLISHED)

  # Start keep-alive pings on a background thread
  timer_thread = threading.Thread(target=keep_alive, daemon=True)
  timer_thread.start()

  shell_command, directory, env = preserve_run_state.get_execution_state(
    no_env=args.no_env
  )

  # If env was not retrieved from file, and is not prohibited, fetch it from server
  if env is None and not args.no_env:
    env_bytes = send_message(
      ConnectionSignals.ENV_STATE_REQUESTED, expect_response=True
    )
    env = preserve_run_state.parse_env_from_server_response(env_bytes)

  # If environment data is provided, use it for the session to be created
  if env is not None:
    env_data = os.environ.copy()
    env_data.update(env)
  else:
    env_data = None

  # Change working directory if we have one
  if directory is not None:
    os.chdir(directory)

  preserve_run_state.print_failed_command(shell_command)

  if utils.is_linux_or_linux_like_shell():
    logging.info("Launching interactive Bash session...")
    subprocess.run(["bash", "-i"], env=env_data)
  else:
    logging.info("Launching interactive PowerShell session...")
    # -NoExit keeps the shell open after running any profile scripts
    subprocess.run(["powershell.exe", "-NoExit"], env=env_data)

  send_message(ConnectionSignals.CONNECTION_CLOSED)


if __name__ == "__main__":
  main()
