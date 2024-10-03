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

"""Wait for an SSH connection from a user, if a wait was requested."""

import asyncio
import logging
import os
import time

from get_labels import retrieve_labels
from logging_setup import setup_logging

setup_logging()

ALWAYS_HALT_LABEL = "CI Connection Halt - Always"
HALT_ON_RETRY_LABEL = "CI Connection Halt - On Retry"


def _is_true_like_env_var(var_name: str) -> bool:
  var_val = os.getenv(var_name, "").lower()
  negative_choices = {"0", "false", "n", "no", "none", "null", "n/a"}
  if var_val and var_val not in negative_choices:
    return True
  return False


def should_halt_for_connection() -> bool:
  """Check if the workflow should wait, due to inputs, vars, and labels."""

  logging.info("Checking if the workflow should be halted for a connection...")

  if not _is_true_like_env_var("INTERACTIVE_CI"):
    logging.info(
      "INTERACTIVE_CI env var is not "
      "set, or is set to a false-like value in the workflow"
    )
    return False

  explicit_halt_requested = _is_true_like_env_var("HALT_DISPATCH_INPUT")
  if explicit_halt_requested:
    logging.info(
      "Halt for connection requested via explicit `halt-dispatch-input` input"
    )
    return True

  # Check if any of the relevant labels are present
  labels = retrieve_labels(print_to_stdout=False)

  # Note: there's always a small possibility these labels may change on the
  # repo/org level, in which case, they'd need to be updated below as well.

  # TODO(belitskiy): Add the ability to halt on CI error.

  if ALWAYS_HALT_LABEL in labels:
    logging.info(
      f"Halt for connection requested via presence "
      f"of the {ALWAYS_HALT_LABEL!r} label"
    )
    return True

  attempt = int(os.getenv("GITHUB_RUN_ATTEMPT"))
  if attempt > 1 and HALT_ON_RETRY_LABEL in labels:
    logging.info(
      f"Halt for connection requested via presence "
      f"of the {HALT_ON_RETRY_LABEL!r} label, "
      f"due to workflow run attempt being 2+ ({attempt})"
    )
    return True

  return False


class WaitInfo:
  pre_connect_timeout = 10 * 60  # 10 minutes for initial connection
  # allow for reconnects, in case no 'closed' message is received
  re_connect_timeout = 15 * 60  # 15 minutes for reconnects
  # Dynamic, depending on whether a connection was established, or not
  timeout = pre_connect_timeout
  last_time = time.time()
  waiting_for_close = False
  stop_event = asyncio.Event()


async def process_messages(reader, writer):
  data = await reader.read(1024)
  # Since this is a stream, multiple messages could come in at once
  messages = [m for m in data.decode().strip().splitlines() if m]
  for message in messages:
    if message == "keep_alive":
      logging.info("Keep-alive received")
      WaitInfo.last_time = time.time()
    elif message == "connection_closed":
      WaitInfo.waiting_for_close = True
      WaitInfo.stop_event.set()
    elif message == "connection_established":
      WaitInfo.last_time = time.time()
      WaitInfo.timeout = WaitInfo.re_connect_timeout
      logging.info("SSH connection detected.")
    else:
      logging.warning(f"Unknown message received: {message!r}")
  writer.close()


async def wait_for_connection(host: str = "localhost", port: int = 12455):
  # Print out the data required to connect to this VM
  runner_name = os.getenv("HOSTNAME")
  cluster = os.getenv("CONNECTION_CLUSTER")
  location = os.getenv("CONNECTION_LOCATION")
  ns = os.getenv("CONNECTION_NS")
  actions_path = os.getenv("GITHUB_ACTION_PATH")

  logging.info("Googler connection only\nSee go/ml-github-actions:ssh for details")
  logging.info(
    f"Connection string: ml-actions-connect "
    f"--runner={runner_name} "
    f"--ns={ns} "
    f"--loc={location} "
    f"--cluster={cluster} "
    f"--halt_directory={actions_path}"
  )

  server = await asyncio.start_server(process_messages, host, port)
  terminate = False

  logging.info(f"Listening for connection notifications on {host}:{port}...")
  async with server:
    while not WaitInfo.stop_event.is_set():
      # Send a status msg every 60 seconds, unless a stop message is received
      # from the companion script
      await asyncio.wait(
        [asyncio.create_task(WaitInfo.stop_event.wait())],
        timeout=60,
        return_when=asyncio.FIRST_COMPLETED,
      )

      elapsed_seconds = int(time.time() - WaitInfo.last_time)
      if WaitInfo.waiting_for_close:
        msg = "Connection was terminated."
        terminate = True
      elif elapsed_seconds > WaitInfo.timeout:
        terminate = True
        msg = f"No connection for {WaitInfo.timeout} seconds."

      if terminate:
        logging.info(f"{msg} Shutting down the waiting process...")
        server.close()
        await server.wait_closed()
        break

      logging.info(f"Time since last keep-alive: {elapsed_seconds}s")

    logging.info("Waiting process terminated.")


if __name__ == "__main__":
  if not should_halt_for_connection():
    logging.info("No conditions for halting the workflow for connection were met")
    exit()
  asyncio.run(wait_for_connection())
