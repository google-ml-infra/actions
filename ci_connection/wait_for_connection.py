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
import os
from multiprocessing.connection import Listener
import time
import signal
import threading
import sys

from get_labels import retrieve_labels

# Check if debug logging should be enabled for the script:
# WAIT_FOR_CONNECTION_DEBUG is a custom variable.
# RUNNER_DEBUG and ACTIONS_RUNNER_DEBUG are GH env vars, which can be set
# in various ways, one of them - enabling debug logging from the UI, when
# triggering a run:
# https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/store-information-in-variables#default-environment-variables
# https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/troubleshooting-workflows/enabling-debug-logging#enabling-runner-diagnostic-logging
_SHOW_DEBUG = bool(
  os.getenv("WAIT_FOR_CONNECTION_DEBUG",
            os.getenv("RUNNER_DEBUG",
                      os.getenv("ACTIONS_RUNNER_DEBUG")))
)
logging.basicConfig(level=logging.INFO if not _SHOW_DEBUG else logging.DEBUG,
                    format="%(levelname)s: %(message)s", stream=sys.stderr)


last_time = time.time()
timeout = 600  # 10 minutes for initial connection
keep_alive_timeout = (
  900  # 30 minutes for keep-alive, if no closed message (allow for reconnects)
)


def _is_truthy_env_var(var_name: str) -> bool:
  var_val = os.getenv(var_name, "").lower()
  negative_choices = {"0", "false", "n", "no", "none", "null", "n/a"}
  if var_val and var_val not in negative_choices:
    return True
  return False


def should_halt_for_connection() -> bool:
  """Check if the workflow should wait, due to inputs, vars, and labels."""

  logging.info("Checking if the workflow should be halted for a connection...")

  if not _is_truthy_env_var("INTERACTIVE_CI"):
    logging.info("INTERACTIVE_CI env var is not "
                 "set, or is set to a falsy value in the workflow")
    return False

  explicit_halt_requested = _is_truthy_env_var("HALT_DISPATCH_INPUT")
  if explicit_halt_requested:
    logging.info("Halt for connection requested via "
                 "explicit `halt-dispatch-input` input")
    return True

  # Check if any of the relevant labels are present
  labels = retrieve_labels(print_to_stdout=False)

  # Note: there's always a small possibility these labels may change on the
  # repo/org level, in which case, they'd need to be updated below as well.

  # TODO(belitskiy): Add the ability to halt on CI error.

  always_halt_label = "CI Connection Halt - Always"
  if always_halt_label in labels:
    logging.info(f"Halt for connection requested via presence "
                 f"of the {always_halt_label!r} label")
    return True

  attempt = int(os.getenv("GITHUB_RUN_ATTEMPT"))
  halt_on_retry_label = "CI Connection Halt - On Retry"
  if attempt > 1 and halt_on_retry_label in labels:
    logging.info(f"Halt for connection requested via presence "
                 f"of the {halt_on_retry_label!r} label, "
                 f"due to workflow run attempt being 2+ ({attempt})")
    return True

  return False


def wait_for_notification(address):
  """Waits for connection notification from the listener."""
  # TODO(belitskiy): Get rid of globals?
  global last_time, timeout
  while True:
    with Listener(address) as listener:
      logging.info("Waiting for connection...")
      with listener.accept() as conn:
        while True:
          try:
            message = conn.recv()
          except EOFError as e:
            logging.error("EOFError occurred:", e)
            break
          logging.info("Received message")
          if message == "keep_alive":
            logging.info("Keep-alive received")
            last_time = time.time()
            continue  # Keep-alive received, continue waiting
          elif message == "closed":
            logging.info("Connection closed by the other process.")
            return  # Graceful exit
          elif message == "connected":
            last_time = time.time()
            timeout = keep_alive_timeout
            logging.info("Connected")
          else:
            logging.warning("Unknown message received:", message)
            continue


def timer():
  while True:
    logging.info("Checking status")
    time_elapsed = time.time() - last_time
    if time_elapsed < timeout:
      logging.info(f"Time since last keep-alive: {int(time_elapsed)}s")
    else:
      logging.info("Timeout reached, exiting")
      os.kill(os.getpid(), signal.SIGTERM)
    time.sleep(60)


def wait_for_connection():
  address = ("localhost", 12455)  # Address and port to listen on

  # Print out the data required to connect to this VM
  host = os.getenv("HOSTNAME")
  cluster = os.getenv("CONNECTION_CLUSTER")
  location = os.getenv("CONNECTION_LOCATION")
  ns = os.getenv("CONNECTION_NS")
  actions_path = os.getenv("GITHUB_ACTION_PATH")

  logging.info("Googler connection only\n"
               "See go/ml-github-actions:ssh for details")
  logging.info(
    f"Connection string: ml-actions-connect "
    f"--runner={host} "
    f"--ns={ns} "
    f"--loc={location} "
    f"--cluster={cluster} "
    f"--halt_directory={actions_path}"
  )

  # Thread is running as a daemon, so it will quit when the
  # main thread terminates.
  timer_thread = threading.Thread(target=timer, daemon=True)
  timer_thread.start()

  # Wait for connection and get the connection object
  wait_for_notification(address)

  logging.info("Exiting connection wait loop.")
  # Force a flush so we don't miss messages
  sys.stdout.flush()


if __name__ == "__main__":
  if not should_halt_for_connection():
    logging.info("No conditions for halting the workflow"
                 "for connection were met")
    exit()

  wait_for_connection()
