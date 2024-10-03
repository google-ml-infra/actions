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

import logging
import socket
import time
import threading
import subprocess

from logging_setup import setup_logging

setup_logging()

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


def main():
  send_message("connection_established")

  # Thread is running as a daemon so it will quit
  # when the main thread terminates
  timer_thread = threading.Thread(target=keep_alive, daemon=True)
  timer_thread.start()

  # Enter an interactive Bash session
  subprocess.run(["bash", "-i"])

  send_message("connection_closed")


if __name__ == "__main__":
  main()
