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
import shutil

from collections import defaultdict
from packaging.version import Version

from seed_env.config import (
  TPU_SPECIFIC_DEPS,
  CUDA12_SPECIFIC_DEPS,
  CUDA13_SPECIFIC_DEPS,
  TENSORFLOW_DEPS,
)
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

  # TODO(kanglant): Remove this index url later; modify seed lock file before running uv add command
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
      split_pinned_dep = pinned_dep.split(";")
      lower_bound_dep = split_pinned_dep[0].replace("==", ">=")
      if len(split_pinned_dep) > 1:
        lower_bound_dep = ";".join([lower_bound_dep] + split_pinned_dep[1:])
    lower_bound_deps.append(lower_bound_dep)

  return lower_bound_deps


def replace_dependencies_in_project_toml(new_deps_list: list, filepath: str):
  """
  Replaces the dependencies section in a pyproject.toml file with a new set of dependencies.

  Args:
      new_deps_list (list): The new dependencies list.
      filepath (str): Path to the pyproject.toml file to update.

  This function reads the specified pyproject.toml file, finds the existing project dependencies array,
  and replaces it with the provided new_deps_list list. The updated content is then written back to the file.
  """
  if new_deps_list:
    new_deps = 'dependencies = [\n    "' + '",\n    "'.join(new_deps_list) + '",\n]'
  else:
    new_deps = "dependencies = []"

  dependencies_regex = re.compile(
    r"^dependencies\s*=\s*\[(\n+\s*.*,\s*)*[\n\r]*\]", re.MULTILINE
  )
  project_header_regex = re.compile(r"^\[project\]", re.MULTILINE)

  with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

  if dependencies_regex.search(content):
    new_content = dependencies_regex.sub(new_deps, content)
  elif project_header_regex.search(content):
    # If it doesn't exist but [project] does, add it after the [project] header.
    new_content = project_header_regex.sub(f"[project]\n{new_deps}", content, count=1)
  else:
    logging.error("No project table found in the template pyproject.toml.")
    raise

  with open(filepath, "w", encoding="utf-8") as f:
    f.write(new_content)


def replace_python_requirement_in_project_toml(min_python: str, filepath: str):
  """
  Replaces the pinned requires-python section in a pyproject.toml file with a lower bound.

  Args:
      min_python (str): Minimum Python version to support.
      filepath (str): Path to the pyproject.toml file to update.

  This function reads the specified pyproject.toml file, finds the existing project requires-python string,
  and replaces it with the min_python as the lower bound. The updated content is then written back to the file.
  """
  min_python_regex = re.compile(r'requires-python\s*=\s*".*?"')
  new_requires_line = f'requires-python = ">={min_python}"'

  with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()
  new_content = min_python_regex.sub(new_requires_line, content)

  with open(filepath, "w", encoding="utf-8") as f:
    f.write(new_content)


def set_exact_python_requirement_in_project_toml(python_version: str, filepath: str):
  """
  Sets or adds the requires-python section in a pyproject.toml file to an exact version series.

  Args:
      python_version (str): The target Python version (e.g., '3.12').
      filepath (str): Path to the pyproject.toml file to update.
  """
  python_req_regex = re.compile(r'requires-python\s*=\s*".*?"')
  project_header_regex = re.compile(r"^\[project\]", re.MULTILINE)
  new_requires_line = f'requires-python = "=={python_version}.*"'

  with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

  if python_req_regex.search(content):
    # If 'requires-python' exists, substitute it.
    new_content = python_req_regex.sub(new_requires_line, content)
  elif project_header_regex.search(content):
    # If it doesn't exist but [project] does, add it after the [project] header.
    new_content = project_header_regex.sub(
      f"[project]\n{new_requires_line}", content, count=1
    )
  else:
    logging.error("No project table found in the template pyproject.toml.")
    raise

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
  replace_dependencies_in_project_toml(lower_bound_deps, pyproject_toml)


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
          dep
          .split("==")[0]
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
    hardware_specific_deps_list = CUDA12_SPECIFIC_DEPS.copy()
    hardware_specific_deps_list.extend(CUDA13_SPECIFIC_DEPS)
    hardware_specific_deps_list.extend(TENSORFLOW_DEPS)
  elif hardware == "gpu" or hardware == "cuda12":
    # For GPU, we assume cuda12 is the default and exclude TPU and cuda13 specific dependencies.
    hardware_specific_deps_list = TPU_SPECIFIC_DEPS.copy()
    hardware_specific_deps_list.extend(CUDA13_SPECIFIC_DEPS)
    hardware_specific_deps_list.extend(TENSORFLOW_DEPS)
  elif hardware == "cuda13":
    hardware_specific_deps_list = TPU_SPECIFIC_DEPS.copy()
    hardware_specific_deps_list.extend(CUDA12_SPECIFIC_DEPS)
    hardware_specific_deps_list.extend(TENSORFLOW_DEPS)
  else:
    logging.warning(f"Unknown hardware {hardware}. Please use tpu or gpu.")
    return

  project_deps = _get_required_dependencies_from_pyproject_toml(pyproject_file)

  exclude_deps = set()
  for pattern in hardware_specific_deps_list:
    # Check for literal matches first for efficiency
    if pattern in project_deps:
      exclude_deps.add(pattern)
      continue

    # If it's a pattern, use regex and match
    if "*" in pattern:
      regex = re.compile(pattern)
      for proj_dep in project_deps:
        if regex.match(proj_dep):
          exclude_deps.add(proj_dep)

  if exclude_deps:
    command = [
      "uv",
      "remove",
      "--managed-python",
      "--resolution=highest",
      "--no-sync",
      "--directory",
      output_dir,
      *sorted(exclude_deps),
    ]
    run_command(command)


def calculate_merged_deps(file_paths: list):
  """
  Merges pyproject.toml files by grouping identical dependencies and creating
  a Python version range marker for them.

  This function works by:
  1.  Grouping dependencies that are identical strings across multiple files.
  2.  For each group, determining the min and max Python version it supports.
  3.  Creating a combined version marker (e.g., "python_version >= '3.10'") if needed.
  4.  Appending this new marker to the dependency string.

  Args:
      file_paths: A list of Path objects for the pyproject.toml files.

  Returns:
      A minimal supported python version.
      A dictionary representing the merged pyproject.toml configuration.

  Raises:
      ValueError: If the list of file paths is empty or a Python version
                  cannot be parsed from a file's content.
  """
  if not file_paths:
    raise ValueError("The list of file paths cannot be empty.")

  # Step 1: Group identical dependencies and collect their Python versions
  # The key is the full dependency string, the value is a list of versions
  dep_groups = defaultdict(list)
  all_python_versions = set()
  version_pattern = re.compile(r"(\d+\.\d+)")

  for path in file_paths:
    if not os.path.isfile(path):
      raise ValueError(f"An versioned pyproject.toml is not found: {path}")
    config = toml.load(path)
    requires_python_str = config.get("project", {}).get("requires-python", "")
    match = version_pattern.search(requires_python_str)
    if not match:
      raise ValueError(f"Could not parse Python version from {path}")

    py_version = Version(match.group(1))
    all_python_versions.add(py_version)

    dependencies = config.get("project", {}).get("dependencies", [])
    for dep_string in dependencies:
      dep_groups[dep_string].append(py_version)

  min_project_version = min(all_python_versions)
  max_project_version = max(all_python_versions)

  final_deps = []
  # Step 2: Process the groups to create new, merged dependency strings
  for dep_string, versions in dep_groups.items():
    dep_req = dep_string.split(";", 1)
    versions.sort()
    min_ver, max_ver = versions[0], versions[-1]

    # Create a version marker based on the collected versions
    if min_ver == min_project_version and max_ver == max_project_version:
      version_marker = ""
    elif max_ver == max_project_version:
      version_marker = f"python_version >= '{min_ver}'"
    elif min_ver == max_ver:
      version_marker = f"python_version == '{min_ver}'"
    else:
      version_marker = (
        f"python_version >= '{min_ver}' and python_version <= '{max_ver}'"
      )

    # Combine with any existing markers
    base_spec = dep_req[0].strip()
    if len(dep_req) > 1:
      old_marker = dep_req[1].strip()
      if version_marker:
        new_marker = f"{old_marker} and {version_marker}"
      else:
        new_marker = old_marker
    else:
      new_marker = version_marker

    if new_marker:
      final_deps.append(f"{base_spec} ; {new_marker}")
    else:
      final_deps.append(f"{base_spec}")

  return min_project_version, sorted(final_deps)


def merge_project_toml_files(file_paths: list, output_dir: str, template_path: str):
  """
  Merges multiple pyproject.toml files from file_paths into a single pyproject.toml at output_dir.

  This function:
    1. Assumes the pyproject.toml files are identical except for their dependency lists and
      requires-python values.
    2. Finds the minimal Python version from all the files to use as a new lower bound for the final file.
    3. Combines all dependencies, adding a Python version markers if needed.
    4. Writes a new pyproject.toml file in the output_dir, using the first input file as a template.
    5. Updates the new pyproject.toml using the the combined dependency list and the minimal Python version.
    6. Returns the final deps
  """
  if not file_paths:
    raise ValueError("The list of file paths cannot be empty.")

  pyproject_file = os.path.join(output_dir, "pyproject.toml")

  if template_path:
    logging.info(f"Using template {template_path}")
    shutil.copy(template_path, pyproject_file)
    # Clear any existing dependencies from the template to start fresh.
    replace_dependencies_in_project_toml([], pyproject_file)
  else:
    shutil.copy(file_paths[0], pyproject_file)

  min_py_version, final_deps = calculate_merged_deps(file_paths)
  replace_python_requirement_in_project_toml(min_py_version, pyproject_file)
  replace_dependencies_in_project_toml(final_deps, pyproject_file)
  return final_deps
