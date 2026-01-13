"""Tests for the github module."""

import os
import subprocess

import pytest

from culprit_finder import github_client

import tests.factories as factories


@pytest.fixture(autouse=True)
def mock_pygithub(mocker):
  """Mocks the PyGithub client to avoid network requests."""
  return mocker.patch("culprit_finder.github_client.github.Github")


def test_wait_for_branch_creation_success(mocker):
  """Tests that wait_for_branch_creation returns when the branch is found."""
  client = github_client.GithubClient("owner/repo", token="test-token")
  mock_check = mocker.patch.object(client, "check_branch_exists")
  # Simulate branch not found first time, then found
  mock_check.side_effect = [False, True]

  mocker.patch("time.sleep")  # Don't actually sleep in tests

  # Should complete without raising an error
  client.wait_for_branch_creation("test-branch", timeout=5)

  assert mock_check.call_count == 2


def test_wait_for_branch_creation_timeout(mocker):
  """Tests that wait_for_branch_creation raises ValueError if timeout is reached."""
  client = github_client.GithubClient("owner/repo", token="test-token")
  mock_check = mocker.patch.object(client, "check_branch_exists", return_value=False)

  mocker.patch("time.sleep")
  # Mock time.time to simulate passage of time
  mocker.patch("time.time", side_effect=[0, 1, 2, 3, 4, 5, 6])

  with pytest.raises(ValueError, match="Branch test-branch not created within timeout"):
    client.wait_for_branch_creation("test-branch", timeout=5)

  assert mock_check.call_count > 1


@pytest.mark.parametrize(
  "event_type, runs_data, expected_sha, expected_calls",
  [
    # Case 1: Strict match found immediately for 'push'
    (
      "push",
      [{"event": "push", "conclusion": "success", "head_sha": "good_sha"}],
      "good_sha",
      1,
    ),
    # Case 2: No strict match for 'workflow_dispatch', fall back to 'push'
    (
      "workflow_dispatch",
      [
        None,  # First call (strict match)
        {
          "event": "push",
          "conclusion": "success",
          "head_sha": "fallback_sha",
        },  # Second call (fallback)
      ],
      "fallback_sha",
      2,
    ),
  ],
)
def test_get_start_commit(mocker, event_type, runs_data, expected_sha, expected_calls):
  """Tests that _get_start_commit handles strict matching and fallback logic correctly."""
  client = github_client.GithubClient("owner/repo", token="test-token")
  mock_latest_run = mocker.patch.object(client, "get_latest_run")

  runs = [factories.create_run(mocker, **data) if data else None for data in runs_data]
  mock_latest_run.side_effect = runs

  failed_run = factories.create_run(mocker, event_type, "failure", "bad_sha")
  previous_run = client.find_previous_successful_run(failed_run)

  assert previous_run.head_sha == expected_sha
  assert mock_latest_run.call_count == expected_calls


def test_get_start_commit_raises_value_error_if_none_found(mocker):
  """Tests that ValueError is raised if no successful run is found even after fallback."""
  client = github_client.GithubClient("owner/repo", token="test-token")
  mock_latest_run = mocker.patch.object(client, "get_latest_run")
  mock_latest_run.return_value = None

  with pytest.raises(ValueError, match="No previous successful run found"):
    client.find_previous_successful_run(
      factories.create_run(mocker, "workflow_dispatch", "failure", "bad_sha")
    )

  assert mock_latest_run.call_count == 2


def test_get_github_token_env_var(mocker):
  """Tests retrieving token from environment variable."""
  mocker.patch.dict(os.environ, {"GH_TOKEN": "env-token"})
  assert github_client.get_github_token() == "env-token"


def test_get_github_token_gh_cli(mocker):
  """Tests retrieving token from gh cli when env var is not set."""
  # Ensure GH_TOKEN is not set/empty
  mocker.patch.dict(os.environ, clear=True)

  mock_run = mocker.patch("subprocess.run")
  mock_run.return_value.stdout = "cli-token\n"

  assert github_client.get_github_token() == "cli-token"
  mock_run.assert_called_with(
    ["gh", "auth", "token"], capture_output=True, text=True, check=True
  )


def test_get_github_token_gh_cli_error(mocker):
  """Tests returning None when gh cli fails (e.g. not logged in)."""
  mocker.patch.dict(os.environ, clear=True)
  mocker.patch(
    "subprocess.run",
    side_effect=subprocess.CalledProcessError(1, ["gh", "auth", "token"]),
  )
  assert github_client.get_github_token() is None


def test_get_github_token_gh_not_found(mocker):
  """Tests returning None when gh cli is not installed."""
  mocker.patch.dict(os.environ, clear=True)
  mocker.patch("subprocess.run", side_effect=FileNotFoundError)
  assert github_client.get_github_token() is None
