"""Tests for the CulpritFinder class."""

from culprit_finder import culprit_finder, github
import re
import pytest
from datetime import datetime, timezone

WORKFLOW_FILE = "test_workflow.yml"
CULPRIT_WORKFLOW = "culprit_finder.yml"
REPO = "owner/repo"


@pytest.fixture
def mock_gh_client(mocker):
  """Returns a mock GithubClient."""
  return mocker.create_autospec(github.GithubClient, instance=True)


@pytest.fixture
def finder(request, mock_gh_client):
  """Returns a CulpritFinder instance for testing."""
  has_culprit_finder_workflow = getattr(request, "param", True)
  return culprit_finder.CulpritFinder(
    repo=REPO,
    start_sha="start_sha",
    end_sha="end_sha",
    workflow_file=WORKFLOW_FILE,
    has_culprit_finder_workflow=has_culprit_finder_workflow,
    github_client=mock_gh_client,
  )


@pytest.mark.parametrize("finder", [True, False], indirect=True)
def test_wait_for_workflow_completion_success(mocker, finder, mock_gh_client):
  """
  Tests that _wait_for_workflow_completion correctly handles a successful workflow run.
  """
  mocker.patch("time.sleep", return_value=None)  # Skip sleep

  branch_name = "test-branch"
  commit_sha = "sha1"
  previous_run_id = None

  run_in_progress = {
    "headSha": commit_sha,
    "status": "in_progress",
    "createdAt": datetime.now(timezone.utc).isoformat(),
    "databaseId": 102,
  }
  run_completed = {
    "headSha": commit_sha,
    "status": "completed",
    "conclusion": "success",
    "createdAt": datetime.now(timezone.utc).isoformat(),
    "databaseId": 102,
  }

  mock_gh_client.get_latest_run.side_effect = [
    None,
    run_in_progress,
    run_completed,
  ]

  workflow = CULPRIT_WORKFLOW if finder._has_culprit_finder_workflow else WORKFLOW_FILE
  result = finder._wait_for_workflow_completion(
    workflow, branch_name, commit_sha, previous_run_id, poll_interval=0.1
  )

  assert result == run_completed
  assert mock_gh_client.get_latest_run.call_count == 3

  for call_args in mock_gh_client.get_latest_run.call_args_list:
    assert call_args[0][0] == workflow


@pytest.mark.parametrize("finder", [True, False], indirect=True)
def test_test_commit_success(mocker, finder, mock_gh_client):
  """Tests that _test_commit triggers the workflow and returns True on success."""

  branch = "test-branch"
  commit_sha = "sha1"

  mock_wait = mocker.patch.object(finder, "_wait_for_workflow_completion")
  mock_wait.return_value = {"conclusion": "success"}

  # Mock get_latest_run to return None for the "previous run" check
  mock_gh_client.get_latest_run.return_value = None

  is_good = finder._test_commit(commit_sha, branch)

  assert is_good is True

  # Determine expected arguments based on configuration
  if finder._has_culprit_finder_workflow:
    expected_workflow = CULPRIT_WORKFLOW
    expected_inputs = {"workflow-to-debug": WORKFLOW_FILE}
  else:
    expected_workflow = WORKFLOW_FILE
    expected_inputs = {}

  mock_gh_client.trigger_workflow.assert_called_once_with(
    expected_workflow,
    branch,
    expected_inputs,
  )


def test_test_commit_failure(mocker, finder, mock_gh_client):
  """Tests that _test_commit returns False if the workflow fails."""
  mock_wait = mocker.patch.object(finder, "_wait_for_workflow_completion")
  mock_wait.return_value = {"conclusion": "failure"}

  # Mock get_latest_run to return None for the "previous run" check
  mock_gh_client.get_latest_run.return_value = None

  assert finder._test_commit("sha", "branch") is False


def _create_commit(sha: str, message: str) -> github.Commit:
  return {"sha": sha, "message": message}


@pytest.mark.parametrize(
  "commits, test_results, expected_culprit_idx",
  [
    # Scenario 1: Culprit found (C1 is bad)
    # [C0 (Good), C1 (Bad), C2 (Bad)]
    # Search path: Mid=1 (C1) -> Bad. Mid=0 (C0) -> Good.
    # Result: C1 (index 1)
    (
      [
        _create_commit("c0", "m0"),
        _create_commit("c1", "m1"),
        _create_commit("c2", "m2"),
      ],
      [False, True],  # Results for checks on C1, then C0
      1,
    ),
    # Scenario 2: All commits are good
    # [C0 (Good), C1 (Good), C2 (Good)]
    # Search path: Mid=1 (C1) -> Good. Mid=2 (C2) -> Good.
    # Result: None
    (
      [
        _create_commit("c0", "m0"),
        _create_commit("c1", "m1"),
        _create_commit("c2", "m2"),
      ],
      [True, True],  # Results for checks on C1, then C2
      None,
    ),
    # Scenario 3: All commits are bad
    # [C0 (Bad), C1 (Bad), C2 (Bad)]
    # Search path: Mid=1 (C1) -> Bad. Mid=0 (C0) -> Bad.
    # Result: C0 (index 0)
    (
      [
        _create_commit("c0", "m0"),
        _create_commit("c1", "m1"),
        _create_commit("c2", "m2"),
      ],
      [False, False],  # Results for checks on C1, then C0
      0,
    ),
    # Scenario 4: No commits
    (
      [],
      [],
      None,
    ),
    # Scenario 5: Single commit is GOOD
    (
      [_create_commit("c0", "m0")],
      [True],
      None,
    ),
    # Scenario 6: Single commit is BAD
    (
      [_create_commit("c0", "m0")],
      [False],
      0,
    ),
  ],
)
def test_run_bisection(
  mocker, finder, mock_gh_client, commits, test_results, expected_culprit_idx
):
  """Tests various bisection scenarios including finding a culprit, no culprit, etc."""
  mock_gh_client.compare_commits.return_value = commits

  # Mock check_branch_exists to alternate False/True to simulate creation/deletion needs
  # We need enough values for the max possible iterations (2 * len(commits))
  mock_gh_client.check_branch_exists.side_effect = [False, True] * (len(commits) + 1)

  mock_test = mocker.patch.object(finder, "_test_commit")
  mock_test.side_effect = test_results

  culprit_commit = finder.run_bisection()

  if expected_culprit_idx is None:
    assert culprit_commit is None
  else:
    assert culprit_commit == commits[expected_culprit_idx]

  if commits:
    # Verify compare_commits was called
    mock_gh_client.compare_commits.assert_called_once()
  else:
    # If no commits, create_branch should not be called
    mock_gh_client.create_branch.assert_not_called()


def test_run_bisection_branch_cleanup_on_failure(mocker, finder, mock_gh_client):
  """Tests that the temporary branch is deleted even if testing the commit fails."""
  commits = [{"sha": "c0", "commit": {"message": "m0"}}]
  mock_gh_client.compare_commits.return_value = commits

  # Branch doesn't exist initially (so create), but exists when cleaning up
  mock_gh_client.check_branch_exists.side_effect = [False, True]

  mock_test = mocker.patch.object(finder, "_test_commit")
  mock_test.side_effect = Exception("Something went wrong")

  with pytest.raises(Exception, match="Something went wrong"):
    finder.run_bisection()

  mock_gh_client.create_branch.assert_called_once()

  assert mock_gh_client.delete_branch.call_count == 1
  called_branch_name_delete = mock_gh_client.delete_branch.call_args[0][0]

  assert re.fullmatch(
    r"culprit-finder/test-c0_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    called_branch_name_delete,
  )


def test_run_bisection_branch_already_exists(mocker, finder, mock_gh_client):
  """Tests that create_branch is skipped if the branch already exists."""
  commits = [{"sha": "c0", "commit": {"message": "m0"}}]
  mock_gh_client.compare_commits.return_value = commits

  # Branch exists initially (skip create), and exists for cleanup
  mock_gh_client.check_branch_exists.return_value = True

  mocker.patch.object(finder, "_test_commit", return_value=True)

  finder.run_bisection()

  assert mock_gh_client.delete_branch.call_count == 1
  called_branch_name_delete = mock_gh_client.delete_branch.call_args[0][0]

  assert re.fullmatch(
    r"culprit-finder/test-c0_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    called_branch_name_delete,
  )
