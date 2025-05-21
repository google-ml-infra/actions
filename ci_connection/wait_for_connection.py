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

"""Wait for a remote connection from a user, if a wait was requested."""

import asyncio
import json
import logging
import os
import shutil
import sys
import time
import platform

from typing import Optional

import preserve_run_state
import utils

from get_labels import retrieve_labels
from utils import ConnectionSignals

utils.setup_logging()

# Note: there's always a small possibility these labels may change on the
# repo/org level, in which case, they'd need to be updated below as well.
HALT_ALWAYS_LABEL = "CI Connection Halt - Always"
HALT_ON_RETRY_LABEL = "CI Connection Halt - On Retry"
HALT_ON_ERROR_LABEL = "CI Connection Halt - On Error"


def _get_run_attempt_num() -> int | None:
  try:
    attempt = int(os.getenv("GITHUB_RUN_ATTEMPT"))
    return attempt
  except ValueError:  # shouldn't be possible in GitHub Actions, but to be safe
    logging.error("Could not retrieve GITHUB_RUN_ATTEMPT, assuming first attempt...")
    return 1


_RUN_ATTEMPT = _get_run_attempt_num()  # The workflow (re-)run number


def _is_true_like_env_var(var_name: str) -> bool:
  var_val = os.getenv(var_name, "").lower()
  negative_choices = {"0", "false", "n", "no", "none", "null", "n/a"}
  if var_val and var_val not in negative_choices:
    return True
  return False


def is_debug_logging_enabled_and_job_type_is_schedule_or_workflow_dispatch() -> bool:
  """
  Check if GitHub Actions debug logging is enabled AND the workflow
  was triggered by a schedule/workflow_dispatch event.

  This is useful, or even necessary, as it currently appears to be the sole way
  of marking a continuous job, or a re-run of a nightly job to wait for connection.
  """
  actions_debug_enabled = _is_true_like_env_var("RUNNER_DEBUG")

  event_name = os.getenv("GITHUB_EVENT_NAME")
  is_schedule_or_workflow_dispatch = event_name in {"schedule", "workflow_dispatch"}

  result = actions_debug_enabled and is_schedule_or_workflow_dispatch
  if result:
    logging.info(
      "Job is of the 'schedule/workflow_dispatch' type, and runner debugging is enabled"
    )
  else:
    if not is_schedule_or_workflow_dispatch:
      logging.debug(f"Job type is {event_name}, not 'schedule' or 'workflow_dispatch'")
    if not actions_debug_enabled:
      logging.debug(
        f"Job does not have logging enabled: RUNNER_DEBUG={actions_debug_enabled}"
      )
  return result


def check_if_labels_require_connection_halting() -> Optional[bool]:
  """Check whether the necessary conditions, involving labels, are met."""

  # Check if any of the relevant labels are present
  labels = retrieve_labels(print_to_stdout=False)
  if labels is None:
    return None

  if HALT_ON_ERROR_LABEL in labels and os.path.exists(utils.STATE_INFO_PATH):
    logging.info(
      f"Halt for connection requested via presence "
      f"of the {HALT_ON_ERROR_LABEL!r} label.\n"
      f"Found a file with the execution state info for a previous command..."
    )
    return True
  else:
    if HALT_ON_ERROR_LABEL not in labels:
      logging.debug(f"No {HALT_ON_ERROR_LABEL!r} label found on the PR")
    else:
      logging.debug(
        f"Found the {HALT_ON_ERROR_LABEL!r} label, but no execution state "
        f"file found at {utils.STATE_INFO_PATH} path"
      )

  if HALT_ALWAYS_LABEL in labels:
    logging.info(
      f"Halt for connection requested via presence of the {HALT_ALWAYS_LABEL!r} label"
    )
    return True
  else:
    logging.debug(f"No {HALT_ALWAYS_LABEL!r} label found on the PR")

  if _RUN_ATTEMPT > 1 and HALT_ON_RETRY_LABEL in labels:
    logging.info(
      f"Halt for connection requested via presence "
      f"of the {HALT_ON_RETRY_LABEL!r} label, "
      f"due to workflow run attempt being 2+ ({_RUN_ATTEMPT})"
    )
    return True
  else:
    if not HALT_ON_RETRY_LABEL:
      logging.debug(f"No {HALT_ON_RETRY_LABEL!r} label found on the PR")
    else:
      logging.debug(
        f"Found the {HALT_ON_RETRY_LABEL!r} label, but this is the first attempt"
      )

  return False


def should_halt_for_connection(
  wait_regardless: bool = False, wait_after_conditions_check: bool = False
) -> bool:
  """Check if the workflow should wait, due to inputs, vars, and labels."""

  logging.info("Checking if the workflow should be halted for a connection...")

  _wait_after_halt_check_var_name = "MLCI_WAIT_AFTER_HALT_CHECK"
  if not wait_after_conditions_check:
    # Useful for debugging why halting conditions were/were not triggered
    wait_after_conditions_check = _is_true_like_env_var(_wait_after_halt_check_var_name)

  if not wait_after_conditions_check and wait_regardless:
    logging.info("Wait for connection requested explicitly via code")
    return True

  explicit_halt_requested = _is_true_like_env_var("HALT_DISPATCH_INPUT")
  if explicit_halt_requested:
    logging.info(
      "Halt for connection requested via explicit `halt-dispatch-input` input"
    )
    return True
  else:
    logging.debug("No `halt-dispatch-input` detected")

  if is_debug_logging_enabled_and_job_type_is_schedule_or_workflow_dispatch():
    return True

  # NOTE: If other methods are added for checking whether a connection should be
  # waited for, they MUST go above this check, or this check must be changed to
  # not be fatal
  labels_require_halting = check_if_labels_require_connection_halting()
  if labels_require_halting:
    return True
  if labels_require_halting is None:
    if not wait_after_conditions_check:
      logging.critical(
        "Exiting due to inability to retrieve PR labels, and no "
        "other halting conditions being met"
      )
      sys.exit(1)

  if wait_after_conditions_check:
    logging.info(
      "Wait for connection requested explicitly via code, "
      f"or {_wait_after_halt_check_var_name}"
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
    if message == ConnectionSignals.KEEP_ALIVE:
      logging.info("Keep-alive received")
      WaitInfo.last_time = time.time()
    elif message == ConnectionSignals.CONNECTION_CLOSED:
      WaitInfo.waiting_for_close = True
      WaitInfo.stop_event.set()
    elif message == ConnectionSignals.CONNECTION_ESTABLISHED:
      WaitInfo.last_time = time.time()
      WaitInfo.timeout = WaitInfo.re_connect_timeout
      logging.info("Remote connection detected.")
    elif message == ConnectionSignals.ENV_STATE_REQUESTED:
      logging.info(
        "Environment state requested (to disable on next time, add `--no-env` to command)"
      )
      # Send the JSON dump of os.environ
      env_data = preserve_run_state.save_env_state(out_path=None)
      json_data = json.dumps(env_data)
      # Send the data back to the client
      writer.write((json_data + "\n").encode())
      await writer.drain()
      logging.info("Environment state sent to the client")
    else:
      logging.warning(f"Unknown message received: {message!r}")
  writer.close()


def construct_connection_command() -> tuple[str, str]:
  runner_name = os.getenv("CONNECTION_POD_NAME")
  cluster = os.getenv("CONNECTION_CLUSTER")
  location = os.getenv("CONNECTION_LOCATION")
  ns = os.getenv("CONNECTION_NS")

  actions_path = os.path.dirname(__file__)

  is_windows = platform.system() == "Windows"
  if is_windows:
    actions_path = actions_path.replace("\\", "\\\\")

  connect_command = (
    f"ml-actions-connect "
    f"--runner={runner_name} "
    f"--ns={ns} "
    f"--loc={location} "
    f"--cluster={cluster}"
  )
  python_bin = sys.executable
  main_connect_command = (
    f"CONNECTION COMMAND (MAIN):\n"
    f'{connect_command} --entrypoint="{python_bin} {actions_path}/notify_connection.py"'
  )
  fallback_connect_command = (
    f'CONNECTION COMMAND (FALLBACK):\n{connect_command} --entrypoint="bash -i"'
  )

  return main_connect_command, fallback_connect_command


async def wait_for_connection(host: str = "127.0.0.1", port: int = 12455):
  # Print out the data required to connect to this VM
  connect_command, fallback_connect_command = construct_connection_command()

  logging.info("Googler connection only")
  logging.info("See go/ml-github-actions:connect for details\n")
  _sep = "-" * 100
  logging.info(
    f"\n{_sep}\n{connect_command}\n{_sep}\n", extra={"bold": True, "underline": True}
  )

  logging.info(f"{fallback_connect_command}\n")
  logging.info(
    "If the Python-based command doesn't work, use the Bash fallback above.\n"
    "Using this fallback will not let the runner know a connection "
    "was made, and will not cause the runner to wait automatically.\n"
    "For the fallback, add a wait/sleep somewhere after the "
    "'Wait for Connection' in your workflow manually, or use a different "
    "image/container/Python so the main command can run successfully.\n"
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


def main(wait_regardless: bool = False, wait_after_conditions_check: bool = False):
  try:
    if should_halt_for_connection(
      wait_regardless=wait_regardless,
      wait_after_conditions_check=wait_after_conditions_check,
    ):
      asyncio.run(wait_for_connection())
    else:
      logging.info("No conditions for halting the workflow for connection were met")

  finally:
    logging.debug("Deleting execution state data...")
    try:
      shutil.rmtree(utils.STATE_OUT_DIR)
    except FileNotFoundError:
      logging.debug("Did not find any execution state data to delete")


if __name__ == "__main__":
  main()
