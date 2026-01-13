"""Quick setup: handshake + save state to temp file."""

import json
import os
import tempfile

import preserve_run_state
import utils

utils.setup_logging()


def main():
  # Signal connection established
  utils.send_message(utils.ConnectionSignals.CONNECTION_ESTABLISHED)

  def fetch_env():
    return utils.send_message(
      utils.ConnectionSignals.ENV_STATE_REQUESTED, expect_response=True
    )

  # Gather state
  shell_command, directory, env = preserve_run_state.get_execution_state(
    no_env=False, fetch_remote_env_callback=fetch_env
  )

  state = {"env": env, "directory": directory, "shell_command": shell_command}

  # Write state for PowerShell to consume
  # Use mkstemp to ensure unique file
  fd, state_file = tempfile.mkstemp(prefix="connection_state_",
                                    suffix=".json",
                                    text=True)
  with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(state, f)

  print(state_file)


if __name__ == "__main__":
  main()
