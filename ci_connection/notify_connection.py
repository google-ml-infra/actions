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

import json
import logging
import os
import socket
import tempfile
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


def keep_alive():
  while True:
    time.sleep(KEEP_ALIVE_INTERVAL)
    send_message("keep_alive")


def get_execution_state():
  """Returns execution state available from the workflow, if any."""
  if not os.path.exists(utils.STATE_INFO_PATH):
    logging.debug(f"Did not find the execution state file at {utils.STATE_INFO_PATH}")
    return None
  logging.debug(f"Found the execution state file at {utils.STATE_INFO_PATH}")
  with open(utils.STATE_INFO_PATH, "r", encoding="utf-8") as f:
    try:
      data: preserve_run_state.StateInfo = json.load(f)
    except json.JSONDecodeError as e:
      logging.error(
        f"Could not parse the execution state file:\n{e.msg}\n"
        f"Continuing without reproducing the environment..."
      )

  shell_command = data.get("shell_command")
  directory = data.get("directory")
  env = data.get("env")

  return shell_command, directory, env


def main():
  send_message("connection_established")

  # Thread is running as a daemon so it will quit
  # when the main thread terminates
  timer_thread = threading.Thread(target=keep_alive, daemon=True)
  timer_thread.start()

  execution_state = get_execution_state()
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

  # Prepare the rcfile content
  rcfile_content = """
if [ -f ~/.bashrc ]; then
    source ~/.bashrc
fi

"""

  if shell_command:
    escaped_shell_command = shell_command.replace('"', '\\"')
    rcfile_content += f'printf "Failed command was:\n{escaped_shell_command}\n\n"\n'

  # Create a temporary rcfile, with the preserved execution info, if any
  with tempfile.NamedTemporaryFile("w", delete=False) as temp_rc:
    rcfile = temp_rc.name
    temp_rc.write(rcfile_content)

  # Start an interactive Bash session
  subprocess.run(["bash", "--rcfile", rcfile, "-i"], env=bash_env)

  # Clean up the temporary rcfile
  os.remove(rcfile)

  send_message("connection_closed")


if __name__ == "__main__":
  main()
