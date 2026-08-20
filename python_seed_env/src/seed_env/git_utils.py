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
import re
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def download_remote_git_file(url: str, output_dir: str) -> str:
  """
  Downloads a file from a given GitHub raw URL and saves it to the specified output directory.

  Args:
      url (str): The raw GitHub URL of the file to download.
      output_dir (str): The directory where the file should be saved.

  Returns:
      str: The path to the downloaded file.

  Raises:
      requests.RequestException: If the download fails.
      OSError: If the file cannot be written.
  """
  os.makedirs(output_dir, exist_ok=True)  # Ensure the output directory exists
  filename = os.path.basename(url)
  output_path = os.path.join(output_dir, filename)
  try:
    logging.info(f"Downloading file from {url} to {output_path}")
    response = requests.get(url)
    response.raise_for_status()
    with open(output_path, "wb") as f:
      f.write(response.content)
    logging.info(f"File downloaded successfully: {output_path}")
    return output_path
  except Exception as e:
    logging.error(f"Failed to download file from {url}: {e}")
    raise


def resolve_github_tag_to_commit(github_org_repo: str, tag: str) -> str:
  """
  Resolves a GitHub tag to its corresponding commit hash.

  Args:
      github_org_repo (str): The GitHub organization and repository in the format 'org/repo'.
      tag (str): The tag to resolve.

  Returns:
      str: The commit hash associated with the tag.

  Raises:
      requests.RequestException: If the request to GitHub fails.
      ValueError: If the tag is not found or does not resolve to a commit.
  """
  url = f"https://api.github.com/repos/{github_org_repo}/git/ref/tags/{tag}"
  try:
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()
    if "object" not in data or "sha" not in data["object"]:
      raise ValueError(f"Tag '{tag}' not found in repo '{github_org_repo}'.")
    return data["object"]["sha"]
  except requests.RequestException as e:
    logging.error(f"Failed to resolve tag '{tag}' in repo '{github_org_repo}': {e}")
    raise


def is_valid_commit_hash(github_org_repo: str, commit_hash: str) -> bool:
  """
  Checks if a given commit hash is valid in a GitHub repository.

  Args:
      github_org_repo (str): The GitHub organization and repository in the format 'org/repo'.
      commit_hash (str): The commit hash to validate.

  Returns:
      bool: True if the commit hash is valid, False otherwise.

  Raises:
      requests.RequestException: If the request to GitHub fails.
  """
  url = f"https://api.github.com/repos/{github_org_repo}/commits/{commit_hash}"
  try:
    response = requests.get(url)
    return response.status_code == 200
  except requests.RequestException as e:
    logging.error(
      f"Failed to check commit hash '{commit_hash}' in repo '{github_org_repo}': {e}"
    )
    raise


def looks_like_commit_hash(commit_hash: str) -> bool:
  """
  Checks if a string looks like a valid commit hash, i.e.,
  a 40-character hexadecimal string.

  Args:
      commit_hash (str): The string to check.

  Returns:
      bool: True if the string looks like a commit hash, False otherwise.
  """
  return re.fullmatch(r"[0-9a-f]{40}", commit_hash) is not None
