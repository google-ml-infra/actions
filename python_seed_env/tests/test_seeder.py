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

import pytest
from pathlib import Path
from unittest.mock import patch
import os

from seed_env.seeder import Seeder

# --- Fixtures for common setup ---


@pytest.fixture
def seeder_config():
  """Returns a basic valid seeder configuration."""
  return {
    "pypi_project_name": "example-project",
    "github_org_repo": "example_org/example_repo",
    "lock_file_pattern": "seed_lock_py{python_version_underscored}.txt",
    "release_tag_pattern": "v{latest_version}",
  }


@pytest.fixture
def download_dir(tmp_path):
  """Provides a temporary download directory for tests."""
  return tmp_path / "test_downloads"


# --- Tests for Seeder.__init__ ---


def test_seeder_init_valid_config(seeder_config, download_dir):
  """Test Seeder initialization with a valid configuration."""
  seeder = Seeder(
    seed_tag_or_commit="v1.0.0", config=seeder_config, download_dir=download_dir
  )

  assert seeder.seed_tag_or_commit == "v1.0.0"
  assert seeder.download_dir == download_dir
  assert seeder.pypi_project_name == "example-project"
  assert seeder.github_org_repo == "example_org/example_repo"
  assert seeder.lock_file_pattern == "seed_lock_py{python_version_underscored}.txt"
  assert seeder.release_tag_pattern == "v{latest_version}"


def test_seeder_init_default_download_dir():
  """Test Seeder initialization with default download directory."""
  config = {
    "pypi_project_name": "test-project",
    "github_org_repo": "test_org/test_repo",
    "lock_file_pattern": "lock.txt",
    "release_tag_pattern": "latest",
  }
  seeder = Seeder(seed_tag_or_commit="latest", config=config, download_dir=None)
  # The default behavior is Path.cwd() / "seed_locks"
  assert seeder.download_dir == Path.cwd() / "seed_locks"


def test_seeder_init_missing_config_raises_error(download_dir):
  """Test Seeder initialization raises ValueError for missing config keys."""
  invalid_config = {
    "pypi_project_name": "example-project",
    # "github_org_repo" is missing
    "lock_file_pattern": "seed.txt",
    "release_tag_pattern": "latest",
  }
  with pytest.raises(ValueError, match="Missing essential configuration for seeder"):
    Seeder(
      seed_tag_or_commit="v1.0.0", config=invalid_config, download_dir=download_dir
    )


# --- Tests for Seeder.download_seed_lock_requirement ---


def test_download_seed_lock_requirement_invalid_python_version_raises_error(
  seeder_config, download_dir
):
  """Test invalid Python version format raises ValueError."""
  seeder = Seeder("latest", seeder_config, download_dir)
  with pytest.raises(
    ValueError, match="Invalid Python version: 3. It should be in format X.Y"
  ):
    seeder.download_seed_lock_requirement("3")
  with pytest.raises(
    ValueError, match="Invalid Python version: 3.X.Y. It should be in format X.Y"
  ):
    seeder.download_seed_lock_requirement("3.X.Y")


def test_download_seed_lock_requirement_no_seed_tag_or_commit_raises_error(
  seeder_config, download_dir
):
  """Test no seed_tag_or_commit raises ValueError."""
  seeder = Seeder("", seeder_config, download_dir)
  with pytest.raises(ValueError, match="No specific tag or commit provided"):
    seeder.download_seed_lock_requirement("3.9")


@patch("seed_env.seeder.get_latest_project_version_from_pypi")
@patch("seed_env.seeder.resolve_github_tag_to_commit")
@patch("seed_env.seeder.download_remote_git_file")
@patch("seed_env.seeder.logging")  # Patch logging to capture calls
def test_download_seed_lock_requirement_latest_tag(
  mock_logging,
  mock_download_remote_git_file,
  mock_resolve_github_tag_to_commit,
  mock_get_latest_project_version_from_pypi,
  seeder_config,
  download_dir,
):
  """Test 'latest' seed_tag_or_commit behavior."""
  # Mock return values
  mock_get_latest_project_version_from_pypi.return_value = "1.2.3"
  mock_resolve_github_tag_to_commit.return_value = (
    "abcdef123456"  # Resolved commit hash
  )
  mock_download_remote_git_file.return_value = os.path.join(
    download_dir, "downloaded_file.txt"
  )

  seeder = Seeder("latest", seeder_config, download_dir)
  python_version = "3.8"
  result_path = seeder.download_seed_lock_requirement(python_version)

  # Assertions
  mock_get_latest_project_version_from_pypi.assert_called_once_with("example-project")
  mock_resolve_github_tag_to_commit.assert_called_once_with(
    "example_org/example_repo", "v1.2.3"
  )
  expected_file_url = "https://raw.githubusercontent.com/example_org/example_repo/abcdef123456/seed_lock_py3_8.txt"
  mock_download_remote_git_file.assert_called_once_with(expected_file_url, download_dir)
  assert result_path == os.path.abspath(
    os.path.join(download_dir, "downloaded_file.txt")
  )

  # Assert logging calls
  mock_logging.info.assert_any_call(
    "Using 'latest' to determine the most recent stable example-project version."
  )
  mock_logging.info.assert_any_call(
    "Latest example-project version determined: 1.2.3. "
    "Attempting to resolve tag/version: v1.2.3"
  )


@pytest.mark.parametrize(
  "seed_tag, expected_commit, is_valid_commit",
  [
    (
      "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
      "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
      True,
    ),  # Valid commit hash
    (
      "my-custom-tag",
      "resolved-custom-commit",
      False,
    ),  # Tag, not a commit hash initially
  ],
)
@patch("seed_env.seeder.is_valid_commit_hash")
@patch("seed_env.seeder.looks_like_commit_hash")
@patch("seed_env.seeder.resolve_github_tag_to_commit")
@patch("seed_env.seeder.download_remote_git_file")
@patch("seed_env.seeder.logging")
def test_download_seed_lock_requirement_specific_tag_or_commit(
  mock_logging,
  mock_download_remote_git_file,
  mock_resolve_github_tag_to_commit,
  mock_looks_like_commit_hash,
  mock_is_valid_commit_hash,
  seeder_config,
  download_dir,
  seed_tag,
  expected_commit,
  is_valid_commit,
):
  """Test specific tag/commit behavior, including commit hash validation."""
  mock_looks_like_commit_hash.return_value = (
    is_valid_commit  # Simulate if it looks like a hash
  )
  mock_is_valid_commit_hash.return_value = (
    True  # Assume valid if it looks like one, for this test
  )
  mock_resolve_github_tag_to_commit.return_value = expected_commit
  mock_download_remote_git_file.return_value = os.path.join(
    download_dir, "downloaded_specific.txt"
  )

  seeder = Seeder(seed_tag, seeder_config, download_dir)
  python_version = "3.9"
  result_path = seeder.download_seed_lock_requirement(python_version)

  # Assertions
  if is_valid_commit:  # If it looks like a commit, should call is_valid_commit_hash
    mock_is_valid_commit_hash.assert_called_once_with(
      seeder_config["github_org_repo"], seed_tag
    )
    # resolve_github_tag_to_commit should *not* be called if it's already a valid commit
    mock_resolve_github_tag_to_commit.assert_not_called()
    assert (
      seeder.seed_tag_or_commit == expected_commit
    )  # It uses the provided commit directly
  else:  # If it doesn't look like a commit, or it's a tag, it should try to resolve it
    mock_is_valid_commit_hash.assert_not_called()
    mock_resolve_github_tag_to_commit.assert_called_once_with(
      seeder_config["github_org_repo"], seed_tag
    )
    mock_logging.info.assert_any_call(
      f"Assuming the provided seed commit '{seed_tag}' is a example-project tag."
    )

  expected_file_url = f"https://raw.githubusercontent.com/{seeder_config['github_org_repo']}/{expected_commit}/seed_lock_py3_9.txt"
  mock_download_remote_git_file.assert_called_once_with(expected_file_url, download_dir)
  assert result_path == os.path.abspath(
    os.path.join(download_dir, "downloaded_specific.txt")
  )


@patch("seed_env.seeder.is_valid_commit_hash")
@patch("seed_env.seeder.looks_like_commit_hash")
def test_download_seed_lock_requirement_invalid_commit_hash_raises_error(
  mock_looks_like_commit_hash, mock_is_valid_commit_hash, seeder_config, download_dir
):
  """Test an invalid commit hash raises an error."""
  mock_looks_like_commit_hash.return_value = True  # It looks like a commit
  mock_is_valid_commit_hash.return_value = False  # But it's not valid

  seeder = Seeder("invalidcommit123", seeder_config, download_dir)
  with pytest.raises(
    ValueError,
    match="Provided commit hash 'invalidcommit123' is not valid for example_org/example_repo.",
  ):
    seeder.download_seed_lock_requirement("3.9")


@patch("seed_env.seeder.get_latest_project_version_from_pypi", return_value="1.0.0")
@patch(
  "seed_env.seeder.resolve_github_tag_to_commit", return_value=""
)  # Simulate failure to resolve
def test_download_seed_lock_requirement_resolve_failure_raises_error(
  mock_resolve_github_tag_to_commit,
  mock_get_latest_project_version_from_pypi,
  seeder_config,
  download_dir,
):
  """Test when tag/commit cannot be resolved to a commit."""
  seeder = Seeder("latest", seeder_config, download_dir)
  with pytest.raises(
    ValueError,
    match="Could not resolve 'latest' to a commit for example_org/example_repo.",
  ):
    seeder.download_seed_lock_requirement("3.9")


@patch("seed_env.seeder.get_latest_project_version_from_pypi", return_value="1.0.0")
@patch("seed_env.seeder.resolve_github_tag_to_commit", return_value="abcdef123")
@patch(
  "seed_env.seeder.download_remote_git_file", return_value=""
)  # Simulate download failure
def test_download_seed_lock_requirement_download_failure_raises_error(
  mock_download_remote_git_file,
  mock_resolve_github_tag_to_commit,
  mock_get_latest_project_version_from_pypi,
  seeder_config,
  download_dir,
):
  """Test when the download of the seed lock file fails."""
  seeder = Seeder("latest", seeder_config, download_dir)
  with pytest.raises(ValueError, match="Failed to download the seed lock file from"):
    seeder.download_seed_lock_requirement("3.9")
