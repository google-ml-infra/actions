#!/usr/bin/python
"""Utilities for saving environment/execution state for use in SSH sessions.

The setup/environment of a workflow can be saved, and later reproduced within
an SSH session to the runner that is running the workflow in question.

This is generally meant for debugging errors in CI.

Can be used both as CLI, and library.
"""

import argparse
import json
import logging
import os
import re
from typing import NotRequired, Sequence, TypedDict

import actions.ci_connection.utils as utils


utils.setup_logging()

VARS_BLACKLIST = (
    'GITHUB_TOKEN',
)

# This env var is, by default, checked for additional variables to blacklist.
# Vars must be comma-separated.
ENV_BLACKLIST_VAR_NAME = 'GML_ACTIONS_DEBUG_VARS_BLACKLIST'


class StateInfo(TypedDict):
  shell_command: NotRequired[str | None]
  directory: NotRequired[str | None]
  env: NotRequired[dict[str, str] | None]


def parse_cli_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
      description='Preserve the current execution state of a shell script. '
                  'Useful for saving the current state of a workflow, so that '
                  'it can be later reproduced within an SSH session, on the '
                  'same runner that is running the workflow in question.',
      usage='python preserve_run_state.py '
            '--shell-command=<relevant-command> '
            '--execution-dir="$(pwd)"'
  )
  parser.add_argument(
      '--shell-command',
      dest='shell_command',
      required=False,
      help='A command which should be saved as the last one executed, '
           'typically a failing one. '
           'Falls back to $LAST_COMMAND, if not specified.'
  )
  parser.add_argument(
      '--execution-dir', required=False,
      dest='execution_dir',
      help='Directory at time of command execution.\n'
           'If not passed, saves the directory from which this script was called.'
  )
  parser.add_argument('--save-env',
                      dest='save_env',
                      action='store_true',
                      default=True,
                      help='Save the environment variables, and their values.\n'
                           'Some variables may be excluded due to their '
                           'potential sensitive nature. True by default.',
                      )
  parser.add_argument('--no-save-env',
                      dest='save_env',
                      action='store_false',
                      help='Do not save the environment variables.')
  parser.add_argument(
      '--env-vars-blacklist',
      dest='env_vars_blacklist',
      help='A comma-separated list of additional environment variables '
           'to ignore.'
  )
  parser.add_argument('--out-dir',
                      dest='out_dir',
                      required=False,
                      help='The directory to which to save the info. Optional. '
                           'Uses $HOME by default.')
  args = parser.parse_args()
  return args


def _get_names_from_env_vars_list(
    env_var_list: str,
    raise_on_invalid_value: bool = False
) -> list[str]:
  """Best-effort attempt to validate, and parse env var names."""
  env_vars_list = env_var_list.strip()
  if not env_vars_list:
    return []

  # Check for characters that aren't alphanumeric, underscores, or commas.
  is_valid = re.search(r'[^\w,]', env_vars_list)
  if not is_valid:
    err_msg = (f'{env_var_list} contains invalid characters.\n'
               f'Expected only letters, digits, underscores, and commas, '
               f'got: {env_vars_list}')
    if raise_on_invalid_value:
      raise ValueError(err_msg)
    else:
      err_msg = f'{err_msg}\n' \ 
                f'Ignoring contents of this variable.'
      logging.error(err_msg)

  parsed_env_names = [n.strip() for n in env_vars_list.split(',')]
  return parsed_env_names


def add_blacklist_vars_from_env(env_list_var_name: str,
                                var_list: Sequence[str]) -> list[str]:
  final_list = [*(var_list or [])]
  list_from_env = os.getenv(env_list_var_name, '')
  final_list.extend(_get_names_from_env_vars_list(list_from_env))
  final_list = sorted(set(final_list))
  return final_list


def save_env_state(
    out_path: str = utils.STATE_ENV_OUT_PATH,
    blacklist: Sequence[str] = VARS_BLACKLIST,
    check_env_lists_for_additional_vars: bool = True
) -> dict[str, str]:
  """
  Retrieves the current env var state in the form of the `env` command output.

  Takes blacklist, and whitelist into consideration.
  Saved separately from other relevant information, so that it can be ingested
  via `source`.
  """
  # Ingest potential additional blacklist variables from the env var, if needed.
  final_blacklist = blacklist
  if check_env_lists_for_additional_vars:
    final_blacklist = add_blacklist_vars_from_env(ENV_BLACKLIST_VAR_NAME,
                                                  final_blacklist)
    print(f'final blacklist: {final_blacklist}')

  # Include env vars that are not in the blacklist
  out_vars = {k: v for k, v in os.environ.items() if k not in final_blacklist}
  out_str = '\n'.join(f'{k}={v!r}' for k, v in out_vars.items())

  if out_path:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    out_file_path = os.path.join(out_path)
    with open(out_file_path, 'w', encoding='utf-8') as f:
      f.write(out_str)

  return out_vars


def save_current_execution_info(shell_command: str | None = None,
                                directory: str | None = None,
                                env_state: dict[str, str] = None,
                                out_path: str = utils.STATE_INFO_PATH):
  """Writes info such as last command, current directory, and env, to a file."""
  with open(out_path, 'w', encoding='utf-8') as f:
    output: StateInfo = {'shell_command': shell_command,
                         'directory': directory,
                         'env': env_state}
    json.dump(output, f, indent=4)
  return output


def save_all_info():
  args = parse_cli_args()
  out_dir = args.out_dir or utils.STATE_OUT_DIR

  if args.save_env:
    blacklist_vars = list(VARS_BLACKLIST)
    blacklist_vars.extend(args.env_vars_blacklist or [])
    env_state = save_env_state(out_path=os.path.join(out_dir,
                                                     utils.STATE_ENV_FILENAME),
                               blacklist=blacklist_vars)
  else:
    env_state = {}

  save_current_execution_info(
      shell_command=args.shell_command or os.getenv('BASH_COMMAND'),
      directory=args.execution_dir or os.getcwd(),
      env_state=env_state
  )


if __name__ == '__main__':
  save_all_info()