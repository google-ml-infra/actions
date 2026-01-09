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


def create_run(event: str, conclusion: str, head_sha: str) -> github.Run:
  return {
    "workflowDatabaseId": 123,
    "headBranch": "main",
    "event": event,
    "createdAt": "2023-01-01T12:00:00Z",
    "workflowName": "Test Workflow",
    "headSha": head_sha,
    "status": "completed",
    "conclusion": conclusion,
    "url": "https://github.com/owner/repo/actions/runs/123",
    "databaseId": 456,
  }


@pytest.mark.parametrize(
  "event_type, runs, expected_sha, expected_calls",
  [
    # Case 1: Strict match found immediately for 'push'
    (
      "push",
      [create_run("push", "success", "good_sha")],
      "good_sha",
      1,
    ),
    # Case 2: No strict match for 'workflow_dispatch', fall back to 'push'
    (
      "workflow_dispatch",
      [
        None,  # First call (strict match)
        create_run("push", "success", "fallback_sha"),  # Second call (fallback)
      ],
      "fallback_sha",
      2,
    ),
  ],
)
def test_get_start_commit(mocker, event_type, runs, expected_sha, expected_calls):
  """Tests that _get_start_commit handles strict matching and fallback logic correctly."""
  client = github.GithubClient("owner/repo")
  mock_latest_run = mocker.patch.object(client, "get_latest_run")
  mock_latest_run.side_effect = runs

  failed_run = create_run(event_type, "failure", "bad_sha")
  previous_run = client.find_previous_successful_run(failed_run)

  assert previous_run == create_run("push", "success", expected_sha)
  assert mock_latest_run.call_count == expected_calls


def test_get_start_commit_raises_value_error_if_none_found(mocker):
  """Tests that ValueError is raised if no successful run is found even after fallback."""
  client = github.GithubClient("owner/repo")
  mock_latest_run = mocker.patch.object(client, "get_latest_run")
  mock_latest_run.return_value = None

  with pytest.raises(ValueError, match="No previous successful run found"):
    client.find_previous_successful_run(
      create_run("workflow_dispatch", "failure", "bad_sha")
    )

  assert mock_latest_run.call_count == 2
