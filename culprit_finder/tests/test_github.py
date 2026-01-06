"""Tests for the github module."""

import json
import pytest
from culprit_finder import github


def test_compare_commits_multiple_pages(mocker):
  """Test fetching commits spanning multiple pages."""
  mock_run_command = mocker.patch("culprit_finder.github.GithubClient._run_command")

  repo = "owner/repo"
  base_sha = "base"
  head_sha = "head"

  page1_commits = [
    {"sha": f"sha{i}", "commit": {"message": f"msg{i}"}} for i in range(3)
  ]
  response_page_1 = json.dumps({"commits": page1_commits})

  page2_commits = [{"sha": "sha3", "commit": {"message": "msg3"}}]
  response_page_2 = json.dumps({"commits": page2_commits})

  response_page_3 = json.dumps({"commits": []})

  mock_run_command.side_effect = [response_page_1, response_page_2, response_page_3]

  client = github.GithubClient(repo)
  commits = client.compare_commits(base_sha, head_sha)

  assert len(commits) == 4
  assert commits[0]["sha"] == "sha0"
  assert commits[3]["sha"] == "sha3"

  assert mock_run_command.call_count == 3


def test_wait_for_branch_creation_success(mocker):
  """Tests that wait_for_branch_creation returns when the branch is found."""
  client = github.GithubClient("owner/repo")
  mock_check = mocker.patch.object(client, "check_branch_exists")
  # Simulate branch not found first time, then found
  mock_check.side_effect = [False, True]

  mocker.patch("time.sleep")  # Don't actually sleep in tests

  # Should complete without raising an error
  client.wait_for_branch_creation("test-branch", timeout=5)

  assert mock_check.call_count == 2


def test_wait_for_branch_creation_timeout(mocker):
  """Tests that wait_for_branch_creation raises ValueError if timeout is reached."""
  client = github.GithubClient("owner/repo")
  mock_check = mocker.patch.object(client, "check_branch_exists", return_value=False)

  mocker.patch("time.sleep")
  # Mock time.time to simulate passage of time
  mocker.patch("time.time", side_effect=[0, 1, 2, 3, 4, 5, 6])

  with pytest.raises(ValueError, match="Branch test-branch not created within timeout"):
    client.wait_for_branch_creation("test-branch", timeout=5)

  assert mock_check.call_count > 1
