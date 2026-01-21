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
import logging
from importlib.resources import files
from random import randint
from string import hexdigits

import yaml

from seed_env.seeder import Seeder
from seed_env.utils import generate_minimal_pyproject_toml
from seed_env.git_utils import download_remote_git_file
from seed_env.uv_utils import (
  build_seed_env,
  build_pypi_package,
  merge_project_toml_files,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class EnvironmentSeeder:
  """
  Handles the seeding and setup of a reproducible Python environment for host projects.

  This class supports:
    - Downloading a seed project's requirements lock file at a specific commit or version.
    - Downloading or using a local requirements file for the target (host) project.
    - Building dependency lock files for the host project based on both the seed project and
      the host requirements, ensuring consistent environment setup.
    - Optionally building a PyPI package for the host project.

  The EnvironmentSeeder is designed to streamline the process of creating reliable and
  reproducible environments by leveraging a known-good seed configuration and integrating
  it with the host project's requirements.
  """

  def __init__(
    self,
    host_name: str,
    host_source_type: str,
    host_github_org_repo: str,
    host_requirements_file_path: str,
    host_commit: str,
    seed_config: str,
    seed_tag_or_commit: str,
    python_version: str,
    hardware: str,
    build_pypi_package: bool,
    output_dir: str,
    template_pyproject_toml: str = None,
    requirements_txt: None | str = None,
  ):
    self.host_name = host_name
    self.host_source_type = host_source_type
    self.host_github_org_repo = host_github_org_repo
    self.host_requirements_file_path = host_requirements_file_path
    self.host_commit = host_commit
    self.seed_config_input = seed_config
    self.template_pyproject_toml = template_pyproject_toml
    self.loaded_seed_config = None
    self.seed_tag_or_commit = seed_tag_or_commit
    self.python_versions = python_version.split(",")
    self.hardware = hardware
    self.build_pypi_package = build_pypi_package
    self.output_dir = output_dir
    self.requirements_txt = (
      "requirements.txt" if requirements_txt == "" else requirements_txt
    )

    self._load_seed_config()

  def _load_seed_config(self):
    """
    Loads configuration data for a seeder.

    It employs a two-tiered lookup strategy to find the specified YAML configuration file:
    1. Package Data First: It initially attempts to locate the configuration file as a package data resource
        in a seeder_configs subfolder.
    2. Local File Fallback: If the file isn't found within the package data, it then attempts to load it
        from a local, absolute file path.
    """
    try:
      package_config_file = files("seed_env.seeder_configs").joinpath(
        self.seed_config_input
      )
      logging.info(
        f"Attempting to load seed config from package data: {package_config_file}"
      )
      with package_config_file.open("r") as f:
        self.loaded_seed_config = yaml.safe_load(f)
      logging.info("Successfully loaded seed config from package data.")
    except FileNotFoundError:
      logging.info(
        f"Config file '{self.seed_config_input}' not found in package data. Falling back to local lookup."
      )
      local_config_file_path = os.path.abspath(self.seed_config_input)
      if os.path.exists(local_config_file_path):
        logging.info(f"Loading seed config from local path: {local_config_file_path}")
        with open(local_config_file_path, "r") as f:
          self.loaded_seed_config = yaml.safe_load(f)
        logging.info("Successfully loaded seed config from local path.")
      else:
        raise FileNotFoundError(
          f"Seed configuration file '{self.seed_config_input}' not found in package data "
          f"({package_config_file}) nor at local path ({local_config_file_path})."
        )

    # Ensure seed_config was loaded successfully before proceeding
    if self.loaded_seed_config is None:
      raise RuntimeError(
        f"Failed to load seed configuration for '{self.seed_config_input}'."
      )

  def seed_environment(self):
    """
    Orchestrates the full environment seeding process for the host project.

    This method performs the following steps:
      1. Retrieves the host project's requirements file, either by downloading it from a remote repository
            at a specific commit or using a local file.
      2. Determines the appropriate seed project and resolves the exact commit or tag to use.
            If 'latest' is specified, finds the latest release version;
            if the input reference looks like a commit, i.e., a 40-character hexadecimal string, validate it;
            if a tag is specified, resolves it to a commit hash.
      3. Downloads the seed project's lock file (e.g., build/requirements_lock_3_12.txt) for the specified
            Python version, e.g., 3.12, and commit.
      4. Generates a minimal pyproject.toml file for the specified Python environment.
      5. Combines the seed lock file and the host requirements to generate a new pyproject.toml, uv.lock,
            and host_requirements.txt in the output directory, using uv commands. Handles hardware-specific
            dependency exclusions (e.g., excludes libtpu for GPU, or CUDA dependencies for TPU).
      6. Optionally builds a PyPI package for the host project if requested.

    Raises:
        FileNotFoundError: If the local host requirements file does not exist for local host mode.
    """
    # Ensure the output directory exists
    os.makedirs(self.output_dir, exist_ok=True)
    self.output_dir = os.path.abspath(self.output_dir)

    # Determine the template for pyproject.toml. The explicit CLI argument takes precedence.
    template_path = self.template_pyproject_toml
    if not template_path and os.path.isfile("./pyproject.toml"):
      template_path = os.path.abspath("./pyproject.toml")
      logging.info(
        f"Found pyproject.toml in the current directory. Using it as a template: {template_path}"
      )

    # Pre-flight check: Ensure the output directory root is clean of a pyproject.toml, as we will generate one.
    final_pyproject_path = os.path.join(self.output_dir, "pyproject.toml")
    if os.path.isfile(final_pyproject_path):
      # Check for the specific edge case where the output directory is the project root
      # and the existing pyproject.toml is the one we are using as a template.
      if template_path and os.path.samefile(template_path, final_pyproject_path):
        raise FileExistsError(
          f"The output directory ('{self.output_dir}') contains a 'pyproject.toml', which was found to be used as a template. "
          "Running this would overwrite the original template file. Please use a different --output-dir; or move the"
          "existing pyproject.toml to a different location and use the --template-pyproject-toml flag to specify its new location."
        )
      # General case: the output directory contains a pre-existing pyproject.toml.
      raise FileExistsError(
        f"A pyproject.toml file already exists in the output directory: {self.output_dir}. "
        "Please provide a clean directory or remove the file to avoid accidentaly overwriting it."
      )

    # Create a directory for storing the downloaded requirements file
    self.download_dir = "downloaded_base_and_seed_requirements"
    os.makedirs(self.download_dir, exist_ok=True)

    # 1. Determine the host requirements file based on the source type
    HOST_REQUIREMENTS_FILE = None
    if self.host_source_type == "remote":
      # Download the host requirements file from the remote repository at the specified commit
      logging.info(
        f"Downloading host requirements file {self.host_requirements_file_path} from {self.host_github_org_repo} at commit/branch {self.host_commit}"
      )
      remote_host_url = f"https://raw.githubusercontent.com/{self.host_github_org_repo}/{self.host_commit}/{self.host_requirements_file_path}"
      HOST_REQUIREMENTS_FILE = os.path.abspath(
        download_remote_git_file(remote_host_url, self.download_dir + "/host")
      )
    elif self.host_source_type == "local":
      if not os.path.isfile(self.host_requirements_file_path):
        raise FileNotFoundError(
          f"Local requirements file does not exist: {self.host_requirements_file_path}"
        )
      HOST_REQUIREMENTS_FILE = self.host_requirements_file_path
    else:
      raise ValueError(
        f"Unsupported host source type: {self.host_source_type}. Supported: 'remote', 'local'."
      )

    # 2. Initialize the seeder instance with the seed config, passing the path where the seed requirements lock files will be downloaded
    self.seeder = Seeder(
      seed_tag_or_commit=self.seed_tag_or_commit,
      config=self.loaded_seed_config,
      download_dir=self.download_dir + "/seed",
    )
    logging.info(
      f"Using {self.seeder.pypi_project_name} at tag/commit {self.seed_tag_or_commit} on {self.seeder.github_org_repo} as seed"
    )

    versioned_project_toml_files = []
    for python_version in self.python_versions:
      # Generate a subdir for each python version
      versioned_output_dir = (
        self.output_dir + "/python" + python_version.replace(".", "_")
      )
      os.makedirs(versioned_output_dir, exist_ok=True)
      versioned_pyproject_path = os.path.join(versioned_output_dir, "pyproject.toml")
      versioned_project_toml_files.append(versioned_pyproject_path)

      # 3. Download the seed lock file for the specified Python version
      SEED_LOCK_FILE = os.path.abspath(
        self.seeder.download_seed_lock_requirement(python_version)
      )

      # 4. Generate a pyproject.toml file for the specified Python version.
      logging.info(f"Generating minimal pyproject.toml for Python {python_version}")
      generate_minimal_pyproject_toml(
        self.host_name, python_version, versioned_output_dir
      )

      # Construct the host lock file name
      HOST_LOCK_FILE_NAME = f"{self.host_name.replace('-', '_')}_requirements_lock_{python_version.replace('.', '_')}.txt"
      # 5. Generate the pyproject.toml, uv.lock, and host_requirements.txt in the output directory
      build_seed_env(
        HOST_REQUIREMENTS_FILE,
        SEED_LOCK_FILE,
        versioned_output_dir,
        self.hardware,
        HOST_LOCK_FILE_NAME,
      )

    # Combine the individual pyproject.toml files from each python_version subdirectory
    # into a single pyproject.toml file at the output dir.
    final_deps = merge_project_toml_files(
      versioned_project_toml_files, self.output_dir, template_path
    )
    if self.requirements_txt:
      parent = os.path.dirname(self.requirements_txt)
      if parent in ("", ".") or not os.path.isdir(parent):
        self.requirements_txt = os.path.join(self.output_dir, self.requirements_txt)

      if self.requirements_txt == HOST_REQUIREMENTS_FILE:
        alts = (
          os.path.join(self.output_dir, "requirements.txt"),
          os.path.join(self.output_dir, "requirements-gen.txt"),
          os.path.join(
            self.output_dir,
            f"requirements-{
              ''.join(map(lambda _: hexdigits[randint(0, 16)], range(5)))
            }.txt",
          ),
        )
        raise FileNotFoundError(
          f"Expected unique requirements.txt file found existing {HOST_REQUIREMENTS_FILE}. "
          f"Try setting `--requirements-txt` to: "
          f"{alts[0] if not os.path.isfile(alts[0]) else alts[1] if not os.path.isfile(alts[1]) else alts[2]}"
        )

      # create or overwrite the requirements.txt file with the final dependencies
      logging.info(f"Writing final requirements to {self.requirements_txt}")
      os.makedirs(os.path.dirname(self.requirements_txt), exist_ok=True)
      with open(self.requirements_txt, "w", encoding="utf8") as f:
        f.write("# Generated by seed-env. Do not edit manually.\n")
        f.write(
          "# If you need to modify dependencies, please do so in the host requirements file and run seed-env again.\n\n"
        )
        f.write("\n".join(sorted(final_deps)))

    # 6. Build pypi package
    # TODO(kanglant): Assume where the seed-env cli is called is the project root
    # and move the generated pyproject.toml to the project root? If there is an old
    # pyproject.toml here, this behavior will overwrite it. I think this is risky.
    # Another option is to copy the source files, specified in the new pyproject.toml,
    # from the project root to the output_dir folder. Then perform a fully isolated
    # build at the output_dir.
    if self.build_pypi_package:
      # Use the new pyproject.toml file at the output dir to build the package.
      build_pypi_package(self.output_dir)
      logging.info("Successfully build a python package")
