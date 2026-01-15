"""Quick setup: handshake + save state to temp file."""

import json
import os
import sys
import tempfile

import preserve_run_state
import utils

utils.setup_logging()


def main():
  utils.send_message(utils.ConnectionSignals.CONNECTION_ESTABLISHED)

  # Gather state
  shell_command, directory, env = preserve_run_state.get_execution_state(no_env=False)

  if env is None:
    env_bytes = utils.send_message(
      utils.ConnectionSignals.ENV_STATE_REQUESTED, expect_response=True
    )
    env = preserve_run_state.parse_env_from_server_response(env_bytes)

  state = {"env": env, "directory": directory}

  # Print to STDERR so it doesn't interfere with the path printing below
  preserve_run_state.print_failed_command(shell_command, file=sys.stderr)

  # Write state for PowerShell to consume
  os.makedirs(utils.STATE_OUT_DIR, exist_ok=True)
  # Use mkstemp to ensure unique file
  fd, state_file_path = tempfile.mkstemp(
    prefix="connection_state_",
    suffix=".json",
    text=True,
    dir=utils.STATE_OUT_DIR,
  )
  with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(state, f)

  print(state_file_path)  # print out the path for consumption by an entrypoint


if __name__ == "__main__":
  main()
