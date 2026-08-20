"""
Copyright 2025 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import os
import subprocess
import logging
import re
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def get_latest_project_version_from_pypi(project_name: str) -> str:
  """
  Retrieves the latest version of a given project from PyPI.

  Args:
      project_name (str): The name of the project on PyPI.

  Returns:
      str: The latest version of the project.

  Raises:
      requests.RequestException: If the request to PyPI fails.
      ValueError: If the project is not found or has no releases.
  """
  url = f"https://pypi.org/pypi/{project_name}/json"
  try:
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()
    if "releases" not in data or not data["releases"]:
      raise ValueError(f"No releases found for project '{project_name}'")
    latest_version = max(
      data["releases"].keys(), key=lambda v: tuple(map(int, v.split(".")))
    )
    return latest_version
  except requests.RequestException as e:
    logging.error(f"Failed to fetch latest version for project '{project_name}': {e}")
    raise


def generate_minimal_pyproject_toml(
  project_name: str, python_version: str, output_dir: str
):
  """
  Generates a minimal pyproject.toml file for a given project and Python version.

  Args:
      project_name (str): The name of the project.
      python_version (str): The target Python version (e.g., '3.12').
      output_dir (str): The directory where the pyproject.toml file should be saved.

  Returns:
      str: The path to the generated pyproject.toml file.
  """
  if not project_name:
    raise ValueError("Project name cannot be empty in pyproject.toml.")
  if not valid_python_version_format(python_version):
    raise ValueError(
      f"Invalid Python version format: {python_version}. Expected format is 'X.Y'."
    )

  # TODO: Pass the version as an argument
  # For now, we use a fixed version "0.1.0" as a placeholder.
  # TODO: Remove the hardcoded part for maxtext in the furture.
  content = f"""\
# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{project_name}"
version = "0.0.1"
license = "Apache-2.0"
requires-python = "=={python_version}.*"
dependencies = [
]
classifiers = [
    "Programming Language :: Python",
]

[tool.hatch.build.targets.wheel]
packages = ["{project_name}"]

[tool.hatch.metadata]
allow-direct-references = true
"""
  try:
    pyproject_path = os.path.join(output_dir, "pyproject.toml")
    with open(pyproject_path, "w") as f:
      f.write(content)
    logging.info(f"Generated minimal pyproject.toml at {pyproject_path}")
    return pyproject_path
  except OSError as e:
    logging.error(f"Failed to write pyproject.toml to {pyproject_path}: {e}")
    raise


def run_command(command, cwd=None, capture_output=False, check=True):
  """
  Executes a shell command.
  Args:
      command (list or str): The command to execute.
      cwd (str, optional): The current working directory for the command.
      capture_output (bool): If True, stdout and stderr will be captured and returned.
      check (bool): If True, raise CalledProcessError if the command returns a non-zero exit code.
  Returns:
      subprocess.CompletedProcess: The result of the command execution.
  Raises:
      subprocess.CalledProcessError: If check is True and the command fails.
  """
  cmd_str = " ".join(command) if isinstance(command, list) else command
  logging.info(f"Executing command: {cmd_str}")
  try:
    result = subprocess.run(
      command,
      cwd=cwd,
      capture_output=capture_output,
      text=True,  # Decode stdout/stderr as text
      check=check,
    )
    if capture_output:
      # Only print debug output if logging level is DEBUG
      if logging.getLogger().level <= logging.DEBUG:
        logging.debug(f"Stdout:\n{result.stdout}")
        if result.stderr:
          logging.debug(f"Stderr:\n{result.stderr}")
    return result
  except FileNotFoundError:
    logging.error(
      f"Command not found: '{command[0]}'. Make sure it's installed and in your PATH."
    )
    raise
  except subprocess.CalledProcessError as e:
    logging.error(f"Command failed with exit code {e.returncode}: {e.cmd}")
    logging.error(f"Stdout:\n{e.stdout}")
    logging.error(f"Stderr:\n{e.stderr}")
    raise
  except Exception as e:
    logging.error(f"An unexpected error occurred while running command: {e}")
    raise


def valid_python_version_format(python_version: str) -> bool:
  """
  Validates that the Python version string is in the format X.Y where X and Y are integers.
  Returns True if valid, False otherwise.
  """
  if not isinstance(python_version, str):
    return False
  return re.fullmatch(r"\d+\.\d+", python_version) is not None
