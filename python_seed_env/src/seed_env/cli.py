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

import argparse
import os
import sys
import logging

from seed_env.config import (
  DEFAULT_PROJECT_COMMIT,
  DEFAULT_PYTHON_VERSION,
  DEFAULT_HARDWARE,
  DEFAULT_BUILD_PROJECT,
  SUPPORTED_HARDWARE,
)
from seed_env.core import EnvironmentSeeder

# Configure basic logging for immediate feedback
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main():
  """
  Main entry point for the seed-env CLI tool.
  Parses command-line arguments and orchestrates the environment seeding process.
  """
  parser = argparse.ArgumentParser(
    prog="seed-env",  # The command-line program name
    description="Generate dependency lock files and optionally build PyPI packages for ML projects.",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
  )

  # --- Mutually Exclusive Group for Project Source ---
  # User must choose either a remote host OR a local path
  project_source_group = parser.add_mutually_exclusive_group(required=True)

  # Arguments for REMOTE host project
  project_source_group.add_argument(
    "--host-repo",
    type=str,
    help="The GitHub repository path (org/repo, e.g., 'AI-Hypercomputer/maxtext')."
    " Used when the host project is on GitHub.",
  )
  parser.add_argument(
    "--host-commit",  # Not part of the exclusive group, as it only applies to --host-repo
    type=str,
    default=DEFAULT_PROJECT_COMMIT,
    help=f"The commit hash or branch name of the host repository (e.g., '{DEFAULT_PROJECT_COMMIT}'). "
    "Only applies when --host-repo is used.",
  )
  parser.add_argument(
    "--host-requirements",  # Not part of the exclusive group
    type=str,
    help="Path to the main requirements file within the host repository (e.g., 'requirements.txt' at the repo root). "
    "Required when --host-repo is used.",
  )

  # Arguments for LOCAL host project
  project_source_group.add_argument(
    "--local-requirements",
    type=str,
    help="Path to a local requirements file for the host project (e.g., './requirements.txt', 'config/my_reqs.txt'). "
    "Recommend to specify --host-name when using this parameter.",
  )
  parser.add_argument(
    "--host-name",  # Applies when --local-requirements is used
    type=str,
    default="local_host",
    help="Name of the local host project. Used to generate the output directory name and python package name.",
  )

  # --- Common Arguments ---
  parser.add_argument(
    "--template-pyproject-toml",
    type=str,
    default=None,
    help="Path to a custom pyproject.toml file to use as a template.",
  )
  parser.add_argument(
    "--requirements-txt",
    type=str,
    default=None,
    help='Alternative to pyproject.toml alter/gen, this creates a "requirements.txt" file',
  )
  parser.add_argument(
    "--seed-config",
    type=str,
    default="jax_seed.yaml",
    help="Path to the configuration file of a seed project to use for generating the environment."
    "First search the file, e.g., jax_seed.yaml, in package data, then local paths.",
  )
  parser.add_argument(
    "--seed-commit",
    type=str,
    default="latest",
    help="The tag or commit hash of the seed repo (e.g., Tag 'jax-v0.6.2' in the jax-ml/jax github repo). "
    "Use 'latest' to try and find the most recent stable release version.",
  )
  parser.add_argument(
    "--python-version",
    type=str,
    default=DEFAULT_PYTHON_VERSION,
    help="The target Python version(s) for the environment (e.g., '3.12', or '3.11,3.12').",
  )
  parser.add_argument(
    "--hardware",
    type=str,
    default=DEFAULT_HARDWARE,
    choices=SUPPORTED_HARDWARE,
    help=f"The target hardware for the environment. Supported: {', '.join(SUPPORTED_HARDWARE)}",
  )

  # --- Optional Flags ---
  parser.add_argument(
    "--build-pypi-package",
    action="store_true",  # This makes it a boolean flag (True if present, False by default)
    default=DEFAULT_BUILD_PROJECT,  # Default behavior is not to build
    help="If set, build a PyPI package based on the generated pyproject.toml for the host project.",
  )
  parser.add_argument(
    "--output-dir",
    type=str,
    default="generated_env_artifacts",
    help="Directory to store the generated lock files and python package.",
  )

  args = parser.parse_args()

  # --- Determine Project Source and Validate Required Args ---
  host_name = None
  host_source_type = None  # "remote" or "local"
  host_github_org = None  # Only for remote
  host_github_repo = None  # Only for remote
  host_requirements_file_path = None  # Path relative to project root for remote; absolute path to the local requirements
  host_commit = None  # Commit hash or tag for remote, None for local

  if args.host_repo:
    host_source_type = "remote"
    try:
      host_github_org, host_github_repo = args.host_repo.split("/")
      if not host_github_org or not host_github_repo:
        raise ValueError
    except ValueError:
      logging.error(
        f"Error: Invalid --host-repo format: '{args.host_repo}'. Expected 'organization/repository_name'."
      )
      parser.print_help()
      sys.exit(1)

    if not args.host_requirements:
      logging.error("Error: --host-requirements is required when --host-repo is used.")
      parser.print_help()
      sys.exit(1)

    host_name = host_github_repo  # Use repo name as project name
    host_requirements_file_path = args.host_requirements
    host_commit = args.host_commit  # This commit applies to the remote repo

  elif args.local_requirements:
    host_source_type = "local"
    # Get the absolute path to the local project requirements
    host_requirements_file_path = os.path.abspath(args.local_requirements)
    host_name = args.host_name  # Use the provided project name
    host_github_org = None
    host_github_repo = None
    host_commit = None  # Commit doesn't apply to local path
  else:
    # This case should theoretically be caught by mutually_exclusive_group(required=True)
    # but as a fallback, explicitly handle.
    logging.error(
      "Error: Either --host-repo or --local-project-path must be specified."
    )
    parser.print_help()
    sys.exit(1)

  # --- Orchestrate the core logic ---
  logging.info(
    f"Starting environment seeding for project: '{host_name}' ({host_source_type})"
  )
  logging.info(f"Seed Config: {args.seed_config}")
  logging.info(f"Seed Commit: {args.seed_commit}")
  logging.info(f"Python Version: {args.python_version}")
  logging.info(f"Hardware: {args.hardware}")
  logging.info(f"Build PyPI Package: {args.build_pypi_package}")
  logging.info(f"Output Directory: {args.output_dir}")
  logging.info(f"Host Name: {host_name}")

  if host_source_type == "remote":
    logging.info(
      f"Host Repo: {host_github_org}/{host_github_repo} (Commit/Tag: {args.host_commit})"
    )
    logging.info(f"Host Requirements File: {args.host_requirements}")
  else:
    logging.info(f"Local Requirements File Path: {host_requirements_file_path}")

  try:
    host_env_seeder = EnvironmentSeeder(
      host_name=host_name,
      host_source_type=host_source_type,
      host_github_org_repo=args.host_repo,
      host_requirements_file_path=host_requirements_file_path,
      host_commit=host_commit,
      seed_config=args.seed_config,
      seed_tag_or_commit=args.seed_commit,
      python_version=args.python_version,
      hardware=args.hardware,
      build_pypi_package=args.build_pypi_package,
      output_dir=args.output_dir,
      template_pyproject_toml=args.template_pyproject_toml,
      requirements_txt=args.requirements_txt,
    )
    # Core function
    host_env_seeder.seed_environment()
    logging.info("Environment seeding completed successfully!")
  except Exception as e:
    logging.error(f"An error occurred during seeding: {e}")
    sys.exit(1)


if __name__ == "__main__":
  main()
