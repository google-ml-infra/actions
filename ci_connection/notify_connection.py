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


"""Establish a connection, and keep it alive.

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


utils.setup_logging()

_LOCK = threading.Lock()

# Configuration (same as wait_for_connection.py)
HOST, PORT = "localhost", 12455
KEEP_ALIVE_INTERVAL = 30


def parse_args():
  parser = argparse.ArgumentParser()
  parser.add_argument(
    "--no-env",
    dest="no_env",
    help="Whether to use the env variables from the CI shell, in the shell spawned "
    "for the user. True by default.\nIf `wait_on_error.py`, with the explicit request "
    "of saving the `env` information, then the information is saved/used from that "
    "point in time. Otherwise, the `env` information is retrieved from the moment in "
    "time `wait_on_connection.py` is triggered.",
    action="store_true",
  )
  return parser.parse_args()


def send_message(message: str):
  with _LOCK:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
      # Append a newline to split the messages on the backend,
      # in case multiple ones are received together
      try:
        sock.connect((HOST, PORT))
        sock.sendall(f"{message}\n".encode("utf-8"))
      except ConnectionRefusedError:
        logging.error(
          f"Could not connect to server at {HOST}:{PORT}. Is the server running?"
        )
      except Exception as e:
        logging.error(f"An error occurred: {e}")


def request_env_state() -> dict[str, str] | None:
  """Request the env data from the server-side session.

  Returns: environment (os.environ) data in the form of a dict.

  """
  with _LOCK:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
      try:
        sock.connect((HOST, PORT))
        # Send the request message
        sock.sendall("env_state_requested\n".encode("utf-8"))
        # Read the response until the connection is closed
        data = b""
        while True:
          chunk = sock.recv(4096)
          if not chunk:
            # Connection closed by server
            break
          data += chunk
        json_data = data.decode("utf-8").strip()
        env_data = json.loads(json_data)
        return env_data
      except Exception as e:
        logging.error(f"An error occurred while requesting env state: {e}")
        return None


def keep_alive():
  while True:
    time.sleep(KEEP_ALIVE_INTERVAL)
    send_message("keep_alive")


def get_execution_state(no_env: bool = True):
  """Returns execution state available from the workflow, if any."""
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
          f"Continuing without reproducing the environment..."
        )
        data = {}

  shell_command = data.get("shell_command")
  directory = data.get("directory")

  if no_env:
    env = None
  # Prefer `env` data from file, since its presence there means its was explicitly
  # requested by the user
  elif "env" in data:
    env = data.get("env")
  else:
    env = request_env_state()

  return shell_command, directory, env


def main():
  args = parse_args()
  send_message("connection_established")

  # Thread is running as a daemon so it will quit
  # when the main thread terminates
  timer_thread = threading.Thread(target=keep_alive, daemon=True)
  timer_thread.start()

  execution_state = get_execution_state(no_env=args.no_env)
  if execution_state is not None:
    shell_command, directory, env = execution_state
  else:
    shell_command, directory, env = None, None, None

  # Set environment variables for the Bash session
  if env is not None:
    bash_env = os.environ.copy()
    bash_env.update(env)
  else:
    bash_env = None

  # Change directory, if provided
  if directory is not None:
    os.chdir(directory)

  if shell_command:
    print(f"Failed command was:\n{shell_command}\n\n")

  # Start an interactive Bash session
  subprocess.run(["bash", "-i"], env=bash_env)

  send_message("connection_closed")


if __name__ == "__main__":
  main()
