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
import json
import logging
import os
import socket
import time
import threading
import subprocess

import preserve_run_state
import utils
from utils import ConnectionSignals


utils.setup_logging()

_LOCK = threading.Lock()

# Configuration (same as wait_for_connection.py)
HOST, PORT = "127.0.0.1", 12455
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

  Args:
      message: The message to send
      expect_response: Whether to wait for and return a response

  Returns:
      The raw response data if expect_response is True, otherwise None
  """
  with _LOCK:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
      try:
        sock.connect((HOST, PORT))
        sock.sendall(f"{message}\n".encode("utf-8"))

        if expect_response:
          data = b""
          while True:
            chunk = sock.recv(4096)
            if not chunk:
              # Connection closed by server
              break
            data += chunk
          return data
        return None
      except ConnectionRefusedError:
        logging.error(
          f"Could not connect to server at {HOST}:{PORT}. Is the server running?"
        )
      except Exception as e:
        logging.error(f"An error occurred: {e}")
      return None


def request_env_state() -> dict[str, str] | None:
  data = send_message(ConnectionSignals.ENV_STATE_REQUESTED, expect_response=True)
  if not data:
    return None
  try:
    json_data = data.decode("utf-8").strip()
    env_data = json.loads(json_data)
    return env_data
  except Exception as e:
    logging.error(f"An error occurred while parsing env state response: {e}")


def keep_alive():
  while True:
    time.sleep(KEEP_ALIVE_INTERVAL)
    send_message(ConnectionSignals.KEEP_ALIVE)


def get_execution_state(no_env: bool = False):
  """
  Returns the shell command, directory, and environment to replicate.

  If `no_env` is True, environment is returned as None.
  Otherwise, we prefer the environment data from the saved
  execution-state file. If that is not present, we attempt
  to retrieve the environment from the remote waiting server.
  """
  if not os.path.exists(utils.STATE_INFO_PATH):
    logging.debug(f"Did not find the execution state file at {utils.STATE_INFO_PATH}")
    data = {}
  else:
    logging.debug(f"Found the execution state file at {utils.STATE_INFO_PATH}")
    with open(utils.STATE_INFO_PATH, "r", encoding="utf-8") as f:
      try:
        data: preserve_run_state.StateInfo = json.load(f)
      except json.JSONDecodeError as e:
        logging.error(
          f"Could not parse the execution state file:\n{e.msg}\n"
          "Continuing without reproducing the environment..."
        )
        data = {}

  shell_command = data.get("shell_command")
  directory = data.get("directory")

  if no_env:
    env = None
  # Prefer `env` data from file over the data available via server,
  # since its presence there means its was explicitly requested by the user
  elif "env" in data:
    env = data.get("env")
  else:
    env = request_env_state()

  return shell_command, directory, env


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

  shell_command, directory, env = get_execution_state(no_env=args.no_env)

  # If we have environment data saved, apply it to the environment we pass to the shell
  if env is not None:
    env_data = os.environ.copy()
    env_data.update(env)
  else:
    env_data = None

  # Change working directory if we have one
  if directory is not None:
    os.chdir(directory)

  if shell_command:
    print("=" * 100)
    print(f"Failed command was:\n{shell_command}\n")
    print("=" * 100)

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
