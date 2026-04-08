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


"""Miscellaneous config/utilities for remote connection functionality."""

import logging
import os
import platform
import shutil
import sys

from datetime import datetime
from typing import Optional


class ConnectionSignals:
  CONNECTION_ESTABLISHED: str = "connection_established"
  CONNECTION_CLOSED: str = "connection_closed"
  KEEP_ALIVE: str = "keep_alive"
  ENV_STATE_REQUESTED: str = "env_state_requested"


# Default path constants for saving/reading execution state
STATE_OUT_DIR = os.path.join(os.path.expandvars("$HOME"), ".workflow_state")
# Path for info for last command, current directory, env vars, etc.
STATE_EXEC_INFO_FILENAME = "execution_state.json"
STATE_INFO_PATH = os.path.join(STATE_OUT_DIR, STATE_EXEC_INFO_FILENAME)
# Environment variables standalone file path, for being ingested via `source`,
STATE_ENV_FILENAME = "env.txt"
STATE_ENV_OUT_PATH = os.path.join(STATE_OUT_DIR, STATE_ENV_FILENAME)

_UNIX_SHELLS = "bash", "sh", "zsh"
_WINDOWS_SHELLS = "pwsh.exe", "powershell.exe", "cmd.exe"

# Check if debug logging should be enabled for the scripts:
# WAIT_FOR_CONNECTION_DEBUG is a custom variable.
# RUNNER_DEBUG is a GH env var, which can be set
# in various ways, one of them - enabling debug logging from the UI, when
# triggering a run:
# https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/store-information-in-variables#default-environment-variables
# https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/troubleshooting-workflows/enabling-debug-logging#enabling-runner-diagnostic-logging
# Note that the above mentions ACTIONS_RUNNER_DEBUG,
# but it doesn't appear to get set - perhaps it is set via secrets
_SHOW_DEBUG = bool(
  os.getenv(
    "WAIT_FOR_CONNECTION_DEBUG",
    os.getenv("RUNNER_DEBUG"),
  )
)


_ANSI = {
  # Colors
  "DEBUG": "\033[94m",  # Light Blue
  "INFO": "\033[92m",  # Light Green
  "WARNING": "\033[93m",  # Light Yellow
  "CRITICAL": "\033[91m",  # Red
  "ERROR": "\033[91m",  # Red
  # Styles
  "BOLD": "\033[1m",
  "UNDERLINE": "\033[4m",
  # Reset the style/coloring
  "RESET": "\033[0m",
}


class _ColoredFormatter(logging.Formatter):
  def format(self, record):
    super().format(record)
    colored_text = self.style_text(f"{record.levelname}: {record.msg}", record)
    record.msg = self.style_text(record.msg, record)
    file_name = record.filename.removesuffix(".py")
    timestamp = datetime.now().strftime("%H:%M:%S")
    out = f"[{file_name}] {timestamp} {colored_text}"
    if record.exc_text:
      out += f"\n{self.style_text(record.exc_text, record)}"
    return out

  @staticmethod
  def style_text(text: str, record: logging.LogRecord) -> str:
    # Get ANSI Escape codes
    color = _ANSI.get(record.levelname, "")
    styles = [color]
    if hasattr(record, "bold"):
      styles.append(_ANSI["BOLD"])
    if hasattr(record, "underline"):
      styles.append(_ANSI["UNDERLINE"])
    styles = "".join(styles)

    lines = text.split("\n")
    out = [f"{styles}{line}{_ANSI['RESET']}" for line in lines]
    return "\n".join(out)


def setup_logging():
  level = logging.INFO if not _SHOW_DEBUG else logging.DEBUG
  logger = logging.getLogger()
  logger.setLevel(level)
  logger.handlers.clear()

  handler = logging.StreamHandler(sys.stdout)
  handler.setFormatter(_ColoredFormatter())
  handler.setLevel(level)
  logger.addHandler(handler)
  return logger


def get_best_shell(
  ci_env: dict[str, str] | None = None, use_native: bool = False
) -> tuple[Optional[str], tuple[str, ...]]:
  """Get the most convenient shell."""

  ci_env_path = ci_env.get("PATH") if ci_env else None

  if platform.system() == "Windows":
    if use_native:
      suitable_shells = _WINDOWS_SHELLS
    else:
      # Just in case, add .exe for safer matching
      unix_exe_shells = tuple(f"{shell}.exe" for shell in _UNIX_SHELLS)
      suitable_shells = unix_exe_shells + _WINDOWS_SHELLS
  else:
    suitable_shells = _UNIX_SHELLS

  for shell in suitable_shells:
    shell_path = None
    if ci_env_path:
      # On the off-chance a shell was installed during a workflow
      shell_path = shutil.which(shell, path=ci_env_path)
    if not shell_path:
      shell_path = shutil.which(shell)

    if shell_path:
      return shell_path, suitable_shells

  return None, suitable_shells


def get_shell_invocation(
  ci_env: dict[str, str] | None = None, use_native: bool = False
) -> tuple[str, ...]:
  """Create the invocation command for the shell subprocess."""

  shell, preferred_shells = get_best_shell(ci_env=ci_env, use_native=use_native)
  if not shell:
    # This should not be possible - at least one should be found.
    raise RuntimeError(f"Could not find a suitable shell out of: {preferred_shells}.")
  shell_name = os.path.basename(shell)

  if shell_name in _WINDOWS_SHELLS:
    if shell_name == "cmd.exe":
      return (shell,)
    else:
      return shell, "-NoLogo", "-NoProfile"
  else:
    return shell, "-i"
