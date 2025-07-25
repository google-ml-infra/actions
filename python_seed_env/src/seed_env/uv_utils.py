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

import re
import os
import toml
import logging
from seed_env.config import TPU_SPECIFIC_DEPS, GPU_SPECIFIC_DEPS
from seed_env.utils import run_command

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def build_seed_env(
  host_requirements_file: str,
  seed_lock_file: str,
  output_dir: str,
  hardware: str,
  host_lock_file_name: str,
):
  """
  Builds the seed environment by combining the host requirements and seed lock files.

  Args:
      host_requirements_file (str): Path to the host requirements file.
      seed_lock_file (str): Path to the seed lock file.
      output_dir (str): Directory where the output files will be saved.
      hardware (str): The target hardware for the environment (e.g., 'tpu', 'gpu').
      host_lock_file_name (str): The name of the host lock file to be generated.
  """
  if not os.path.isfile(host_requirements_file):
    raise FileNotFoundError(
      f"Host requirements file does not exist: {host_requirements_file}"
    )
  if not os.path.isfile(seed_lock_file):
    raise FileNotFoundError(f"Seed lock file does not exist: {seed_lock_file}")

  # Ensure a minimal pyproject.toml file exists in the output directory
  pyproject_file = os.path.join(output_dir, "pyproject.toml")
  if not os.path.isfile(pyproject_file):
    raise FileNotFoundError(
      f"A minimal pyproject.toml file does not exist in output directory: {output_dir}"
    )

  # Remove uv.lock if it exists, as we will generate a new one
  uv_lock_file = os.path.join(output_dir, "uv.lock")
  if os.path.isfile(uv_lock_file):
    try:
      os.remove(uv_lock_file)
      logging.info(f"Removed existing uv.lock file: {uv_lock_file}")
    except OSError as e:
      logging.error(
        f"Failed to remove existing uv.lock file: {e}. It may cause issues with the new lock generation."
      )
      raise

  command = [
    "uv",
    "add",
    "--managed-python",
    "--no-build",
    "--no-sync",
    "--resolution=highest",
    "--directory",
    output_dir,
    "-r",
    seed_lock_file,
  ]
  run_command(command)

  _remove_hardware_specific_deps(hardware, pyproject_file, output_dir)

  command = [
    "uv",
    "add",
    "--managed-python",
    "--no-sync",
    "--resolution=highest",
    "--directory",
    output_dir,
    "-r",
    host_requirements_file,
  ]
  run_command(command)

  _remove_hardware_specific_deps(hardware, pyproject_file, output_dir)

  command = [
    "uv",
    "export",
    "--managed-python",
    "--locked",
    "--no-hashes",
    "--no-annotate",
    "--resolution=highest",
    "--directory",
    output_dir,
    "--output-file",
    host_lock_file_name,
  ]
  run_command(command)

  lock_to_lower_bound_project(
    os.path.join(output_dir, host_lock_file_name), pyproject_file
  )

  os.remove(uv_lock_file)
  command = [
    "uv",
    "lock",
    "--managed-python",
    "--resolution=lowest",
    "--directory",
    output_dir,
  ]
  run_command(command)

  command = [
    "uv",
    "export",
    "--managed-python",
    "--locked",
    "--no-hashes",
    "--no-annotate",
    "--resolution=lowest",
    "--directory",
    output_dir,
    "--output-file",
    host_lock_file_name,
  ]
  run_command(command)

  logging.info("Environment build process completed successfully.")


def build_pypi_package(output_dir: str):
  """
  Builds a PyPI wheel package from a pyproject.toml file in the specified output directory.

  Args:
      output_dir (str): The directory containing the pyproject.toml file.

  Raises:
      FileNotFoundError: If the pyproject.toml file does not exist in the output directory.
      subprocess.CalledProcessError: If the build command fails.

  This function uses 'uv build --wheel' to generate a wheel package in the given directory.
  """
  # Use uv build --wheel to build a pypi package at output_dir
  # Assume there is a pyproject.toml
  pyproject_file = os.path.join(output_dir, "pyproject.toml")
  if not os.path.isfile(pyproject_file):
    raise FileNotFoundError(
      f"A pyproject.toml file does not exist in output directory: {output_dir}"
    )

  command = [
    "uv",
    "build",
    "--wheel",
    "--directory",
    output_dir,
  ]
  run_command(command)


def _read_pinned_deps_from_a_req_lock_file(filepath):
  """
  Reads a requirements lock file and extracts all pinned dependencies.

  Args:
      filepath (str): Path to the requirements lock file.

  Returns:
      list[str]: A list of dependency strings (e.g., 'package==version').
                 Lines that are comments or do not contain '==' or '@' are ignored.

  This function skips comment lines and only includes lines that specify pinned dependencies
  (using '==' or '@' for VCS links).
  """
  lines = []
  with open(filepath, "r", encoding="utf-8") as file:
    for line in file:
      if "#" not in line and ("==" in line or "@" in line):
        lines.append(line.strip())
  return lines


def _convert_pinned_deps_to_lower_bound(pinned_deps):
  """
  Converts a list of pinned dependencies (e.g., 'package==version') to lower-bound dependencies (e.g., 'package>=version').

  Args:
      pinned_deps (list[str]): A list of dependency strings pinned to specific versions.

  Returns:
      list[str]: A list of dependency strings with lower-bound version specifiers.

  This function replaces '==' with '>=' for each dependency, preserving other dependency formats (such as VCS links).
  """
  lower_bound_deps = []
  for pinned_dep in pinned_deps:
    lower_bound_dep = pinned_dep
    if "==" in pinned_dep:
      lower_bound_dep = pinned_dep.replace("==", ">=")
    lower_bound_deps.append(lower_bound_dep)

  return lower_bound_deps


def _replace_dependencies_in_project_toml(new_deps: str, filepath: str):
  """
  Replaces the dependencies section in a pyproject.toml file with a new set of dependencies.

  Args:
      new_deps (str): The new dependencies block as a string.
      filepath (str): Path to the pyproject.toml file to update.

  This function reads the specified pyproject.toml file, finds the existing [project] dependencies array,
  and replaces it with the provided new_deps string. The updated content is then written back to the file.
  """
  dependencies_regex = re.compile(
    r"^dependencies\s*=\s*\[(\n+\s*.*,\s*)*[\n\r]*\]", re.MULTILINE
  )

  with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()
  new_content = dependencies_regex.sub(new_deps, content)

  with open(filepath, "w", encoding="utf-8") as f:
    f.write(new_content)


def lock_to_lower_bound_project(host_lock_file: str, pyproject_toml: str):
  """
  Updates the dependencies in a pyproject.toml file to use lower-bound versions based on a lock file.

  Args:
      host_lock_file (str): Path to the requirements lock file containing pinned dependencies.
      pyproject_toml (str): Path to the pyproject.toml file to update.

  This function reads all pinned dependencies from the lock file, converts them to lower-bound specifiers (e.g., 'package>=version'),
  formats them as a TOML dependencies array, and replaces the dependencies section in the given pyproject.toml file.
  """
  pinned_deps = _read_pinned_deps_from_a_req_lock_file(host_lock_file)
  lower_bound_deps = _convert_pinned_deps_to_lower_bound(pinned_deps)
  new_deps = 'dependencies = [\n    "' + '",\n    "'.join(lower_bound_deps) + '"\n]'
  _replace_dependencies_in_project_toml(new_deps, pyproject_toml)


def _get_required_dependencies_from_pyproject_toml(file_path="pyproject.toml"):
  """Reads pyproject.toml and extracts dependency names."""
  deps = []
  if not os.path.exists(file_path):
    return deps
  try:
    with open(file_path, "r") as f:
      data = toml.load(f)
    if "project" in data and "dependencies" in data["project"]:
      for dep in data["project"]["dependencies"]:
        # Extract the package name before any version specifiers
        package_name = (
          dep.split("==")[0]
          .split(">=")[0]
          .split("<=")[0]
          .split("~=")[0]
          .split("<")[0]
          .split(">")[0]
          .split("!=")[0]
          .split("[")[0]  # Get the package name without extra
          .strip()
        )
        deps.append(package_name)
    return deps
  except Exception as e:
    print(f"Error reading {file_path}: {e}")
    return deps


def _remove_hardware_specific_deps(hardware: str, pyproject_file: str, output_dir: str):
  if hardware == "tpu":
    hardware_specific_deps_list = GPU_SPECIFIC_DEPS.copy()
  elif hardware == "gpu":
    hardware_specific_deps_list = (TPU_SPECIFIC_DEPS.copy(),)
  else:
    logging.warning(f"Unknown hardware {hardware}. Please use tpu or gpu.")
    return

  project_deps = _get_required_dependencies_from_pyproject_toml(pyproject_file)

  exclude_deps = []
  for dep in hardware_specific_deps_list:
    if dep in project_deps:
      exclude_deps.append(dep)

  if exclude_deps:
    command = [
      "uv",
      "remove",
      "--managed-python",
      "--resolution=highest",
      "--no-sync",
      "--directory",
      output_dir,
      *exclude_deps,
    ]
    run_command(command)
