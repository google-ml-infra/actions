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

"""Utilities for saving environment/execution state for use in remote sessions.

The setup/environment of a workflow can be saved, and later reproduced within
a remote session to the runner that is running the workflow in question.

This is generally meant for debugging errors in CI.

Can be used both as CLI, and/or as a library.
"""

import argparse
import json
import logging
import os
import re
from typing import Sequence, TypedDict

import utils

utils.setup_logging()

VARS_DENYLIST = ("GITHUB_TOKEN",)

# Environment variables that define extra denylist/allowlist entries
ENV_DENYLIST_VAR_NAME = "GML_ACTIONS_DEBUG_VARS_DENYLIST"
ENV_ALLOWLIST_VAR_NAME = "GML_ACTIONS_DEBUG_VARS_ALLOWLIST"


class StateInfo(TypedDict):
  shell_command: str | None
  directory: str | None
  env: dict[str, str] | None


def parse_cli_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description="Preserve the current execution state of a shell script. "
    "Useful for saving the current state of a workflow, so that "
    "it can be later reproduced within a remote session, on the "
    "same runner that is running the workflow in question.",
    usage=(
      "python preserve_run_state.py "
      "--shell-command=<relevant-command> "
      '--execution-dir="$(pwd)"'
    ),
  )
  parser.add_argument(
    "--shell-command",
    dest="shell_command",
    required=False,
    help="A command which should be saved as the last one executed, "
    "typically a failing one. "
    "Falls back to $LAST_COMMAND, if not specified.",
  )
  parser.add_argument(
    "--execution-dir",
    required=False,
    dest="execution_dir",
    help="Directory at the time of command execution.\n"
    "If not passed, saves the directory from which this script was called.",
  )
  parser.add_argument(
    "--save-env",
    dest="save_env",
    action="store_true",
    default=True,
    help="Save the environment variables, and their values.\n"
    "Some variables may be excluded due to their "
    "potentially sensitive nature. True by default.",
  )
  parser.add_argument(
    "--no-save-env",
    dest="save_env",
    action="store_false",
    help="Do not save the environment variables.",
  )
  parser.add_argument(
    "--env-vars-denylist",
    dest="env_vars_denylist",
    help="A comma-separated list of additional environment variables to ignore.",
  )
  parser.add_argument(
    "--env-vars-allowlist",
    dest="env_vars_allowlist",
    help="A comma-separated list of environment variables to explicitly allow.\n"
    "If specified, only these variables (minus any in the denylist) will be saved.",
  )
  parser.add_argument(
    "--out-dir",
    dest="out_dir",
    required=False,
    help="The directory to which to save the info. Optional. Uses $HOME by default.",
  )
  args = parser.parse_args()
  return args


def _get_names_from_env_vars_list(
  env_var_list: str, raise_on_invalid_value: bool = False
) -> list[str]:
  """Best-effort attempt to validate and parse env var names from a comma-separated string."""
  env_vars_list = env_var_list.strip()
  if not env_vars_list:
    return []

  # Check for characters that aren't alphanumeric, underscores, or commas.
  invalid_chars = re.search(r"[^\w,]", env_vars_list)
  if invalid_chars:
    err_msg = (
      f"`{env_var_list}` contains invalid characters.\n"
      "Expected only letters, digits, underscores, and commas."
    )
    if raise_on_invalid_value:
      raise ValueError(err_msg)
    else:
      logging.error(f"{err_msg}\nIgnoring contents of this variable.")
      return []

  parsed_env_names = [n.strip() for n in env_vars_list.split(",") if n.strip()]
  return parsed_env_names


def add_vars_from_env(env_list_var_name: str, var_list: Sequence[str]) -> list[str]:
  """
  Reads a comma-separated list of env var names from the environment
  (`env_list_var_name`) and merges them with `var_list`.
  """
  final_list = [*(var_list or [])]
  list_from_env = os.getenv(env_list_var_name, "")
  final_list.extend(_get_names_from_env_vars_list(list_from_env))
  return sorted(set(final_list))


def save_env_state(
  out_path: str | None = utils.STATE_ENV_OUT_PATH,
  denylist: Sequence[str] = VARS_DENYLIST,
  allowlist: Sequence[str] | None = None,
  check_env_lists_for_additional_vars: bool = True,
) -> dict[str, str]:
  """
  Retrieves the current env var state in the form of KEY='VALUE' lines,
  with allowlist and denylist in mind.

  - Allowlist, if not empty, dictates to ignore any variables not included in it.
  - Variables in denylist override ones in allowslist, and are never included
    in the final output.

  Returns the resulting environment variables as a dict.
  """
  final_denylist = list(denylist) if denylist else []
  final_denylist.extend(VARS_DENYLIST)  # always honor the default denylist
  final_denylist = list(set(final_denylist))

  final_allowlist = list(allowlist) if allowlist else []

  if check_env_lists_for_additional_vars:
    final_denylist = add_vars_from_env(ENV_DENYLIST_VAR_NAME, final_denylist)
    final_allowlist = add_vars_from_env(ENV_ALLOWLIST_VAR_NAME, final_allowlist)

  final_denylist = set(final_denylist)
  final_allowlist = set(final_allowlist)

  out_vars = []
  for k, v in os.environ.items():
    # If the allowlist is not empty, and the variable is not in it, skip it
    if final_allowlist and k not in final_allowlist:
      continue
    # If the variable is in the denylist, skip it
    if k in final_denylist:
      continue
    out_vars.append((k, v))

  out_vars.sort(key=lambda item: item[0])

  out_str = "\n".join(f"{k}={v!r}" for k, v in out_vars)

  if out_path:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
      f.write(out_str)

  return dict(out_vars)


def save_current_execution_info(
  shell_command: str | None = None,
  directory: str | None = None,
  env_state: dict[str, str] = None,
  out_path: str = utils.STATE_INFO_PATH,
):
  """Writes info such as the last command, current directory, and env, to a file."""
  with open(out_path, "w", encoding="utf-8") as f:
    output: StateInfo = {
      "shell_command": shell_command,
      "directory": directory,
      "env": env_state,
    }
    json.dump(output, f, indent=4)
  return output


def save_all_info():
  args = parse_cli_args()
  out_dir = args.out_dir or utils.STATE_OUT_DIR
  os.makedirs(out_dir, exist_ok=True)

  # Convert CLI arguments for allow/deny lists to lists
  cli_denylist = []
  if args.env_vars_denylist:
    cli_denylist.extend(_get_names_from_env_vars_list(args.env_vars_denylist))
  cli_allowlist = []
  if args.env_vars_allowlist:
    cli_allowlist = _get_names_from_env_vars_list(args.env_vars_allowlist)

  if args.save_env:
    env_state = save_env_state(
      out_path=os.path.join(out_dir, utils.STATE_ENV_FILENAME),
      denylist=cli_denylist or VARS_DENYLIST,
      allowlist=cli_allowlist,
    )
  else:
    env_state = {}

  save_current_execution_info(
    shell_command=args.shell_command or os.getenv("BASH_COMMAND"),
    directory=args.execution_dir or os.getcwd(),
    env_state=env_state,
    out_path=os.path.join(out_dir, utils.STATE_INFO_PATH),
  )


if __name__ == "__main__":
  save_all_info()
