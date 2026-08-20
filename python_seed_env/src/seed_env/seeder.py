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

import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any

from seed_env.utils import (
  valid_python_version_format,
  get_latest_project_version_from_pypi,
)
from seed_env.git_utils import (
  download_remote_git_file,
  resolve_github_tag_to_commit,
  is_valid_commit_hash,
  looks_like_commit_hash,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class Seeder:
  """
  A unified seeder class that loads its configuration from a dictionary,
  typically parsed from a YAML file. It handles downloading framework-specific
  seed lock files based on the provided configuration.
  """

  def __init__(
    self, seed_tag_or_commit: str, config: Dict[str, Any], download_dir: Optional[Path]
  ):
    self.seed_tag_or_commit = seed_tag_or_commit
    if download_dir is None:
      download_dir = Path.cwd() / "seed_locks"
    self.download_dir = download_dir  # Path to the download directory where seed lock files will be stored.

    # Load configurations from the provided dictionary
    self.pypi_project_name = config.get("pypi_project_name")
    self.github_org_repo = config.get("github_org_repo")
    self.lock_file_pattern = config.get("lock_file_pattern")
    self.release_tag_pattern = config.get("release_tag_pattern", "latest")

    if not all([
      self.pypi_project_name,
      self.github_org_repo,
      self.lock_file_pattern,
      self.release_tag_pattern,
    ]):
      raise ValueError(
        f"Missing essential configuration for seeder. "
        f"Ensure 'pypi_project_name', 'github_org_repo', 'lock_file_pattern', and 'release_tag_pattern' are provided in the config. "
        f"Config received: {config}"
      )

  def download_seed_lock_requirement(self, python_version: str) -> str:
    """
    Downloads a seed lock file based on the seeder's configuration
    for the specified Python version and returns its local path.
    """
    if not valid_python_version_format(python_version):
      raise ValueError(
        f"Invalid Python version: {python_version}. It should be in format X.Y"
      )

    # Format the lock file name based on the pattern from config
    python_version_underscored = python_version.replace(".", "_")
    file_name = self.lock_file_pattern.format(
      python_version=python_version,
      python_version_underscored=python_version_underscored,
    )

    # Validate the seed tag or commit
    seed_commit = ""

    if not self.seed_tag_or_commit:
      raise ValueError(
        "No specific tag or commit provided. "
        "Please provide a valid tag/commit or use 'latest' to determine the latest release version."
      )

    if self.seed_tag_or_commit.lower() == "latest":
      logging.info(
        f"Using 'latest' to determine the most recent stable {self.pypi_project_name} version."
      )
      latest_version = get_latest_project_version_from_pypi(self.pypi_project_name)
      target_tag_or_commit_for_resolve = self.release_tag_pattern.format(
        latest_version=latest_version
      )

      logging.info(
        f"Latest {self.pypi_project_name} version determined: {latest_version}. "
        f"Attempting to resolve tag/version: {target_tag_or_commit_for_resolve}"
      )
      seed_commit = resolve_github_tag_to_commit(
        self.github_org_repo, target_tag_or_commit_for_resolve
      )
    elif looks_like_commit_hash(self.seed_tag_or_commit):
      if not is_valid_commit_hash(self.github_org_repo, self.seed_tag_or_commit):
        raise ValueError(
          f"Provided commit hash '{self.seed_tag_or_commit}' is not valid for {self.github_org_repo}."
        )
      seed_commit = self.seed_tag_or_commit
    else:
      logging.info(
        f"Assuming the provided seed commit '{self.seed_tag_or_commit}' is a {self.pypi_project_name} tag."
      )
      seed_commit = resolve_github_tag_to_commit(
        self.github_org_repo, self.seed_tag_or_commit
      )

    if not seed_commit:
      raise ValueError(
        f"Could not resolve '{self.seed_tag_or_commit}' to a commit for {self.github_org_repo}."
      )

    # Construct the final seed file path based on the commit and Python version.
    final_seed_file_url = f"https://raw.githubusercontent.com/{self.github_org_repo}/{seed_commit}/{file_name}"

    # Download the seed lock file from the remote repository.
    seed_requirements_file = download_remote_git_file(
      final_seed_file_url, self.download_dir
    )
    if not seed_requirements_file:
      raise ValueError(
        f"Failed to download the seed lock file from {final_seed_file_url}. "
        "Please ensure the file exists in the repository at the specified commit."
      )

    return os.path.abspath(seed_requirements_file)
