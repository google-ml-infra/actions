"""Tests for the CulpritFinder class."""

import re

import pytest

from culprit_finder import culprit_finder, culprit_finder_state, github_client

import tests.factories as factories

WORKFLOW_FILE = "test_workflow.yml"
CULPRIT_WORKFLOW = "culprit_finder.yml"
REPO = "owner/repo"


@pytest.fixture
def mock_gh_client(mocker):
  """Returns a mock GithubClient."""
  return mocker.create_autospec(github_client.GithubClient, instance=True)


@pytest.fixture
def mock_state_persister(mocker):
  """Returns a mock StatePersister."""
  return mocker.create_autospec(culprit_finder_state.StatePersister, instance=True)


@pytest.fixture
def mock_state() -> culprit_finder_state.CulpritFinderState:
  return {
    "repo": "test_repo",
    "workflow": "test_workflow",
    "original_start": "original_start_sha",
    "original_end": "original_end_sha",
    "current_good": "",
    "current_bad": "",
    "cache": {},
    "job": None,
  }


@pytest.fixture
def finder_factory(mock_gh_client, mock_state_persister, mock_state):
  """Returns a factory function to create CulpritFinder instances for testing."""

  def _make_finder(**kwargs):
    defaults = {
      "repo": REPO,
      "start_sha": "start_sha",
      "end_sha": "end_sha",
      "workflow_file": WORKFLOW_FILE,
      "has_culprit_finder_workflow": True,
      "gh_client": mock_gh_client,
      "state": mock_state,
      "state_persister": mock_state_persister,
      "use_cache": False,
      "retries": 0,
    }
    defaults.update(kwargs)
    return culprit_finder.CulpritFinder(**defaults)

  return _make_finder


@pytest.fixture
def finder(request, finder_factory):
  """Returns a CulpritFinder instance for testing."""
  has_culprit_finder_workflow = getattr(request, "param", True)
  return finder_factory(has_culprit_finder_workflow=has_culprit_finder_workflow)


@pytest.mark.parametrize("finder", [True, False], indirect=True)
def test_wait_for_workflow_completion_success(mocker, finder, mock_gh_client):
  """
  Tests that _wait_for_workflow_completion correctly handles a successful workflow run.
  """
  mocker.patch("time.sleep", return_value=None)  # Skip sleep

  branch_name = "test-branch"
  commit_sha = "sha1"
  previous_run_id = None

  run_in_progress = factories.create_run(
    mocker, head_sha=commit_sha, status="in_progress"
  )
  run_completed = factories.create_run(
    mocker, head_sha=commit_sha, conclusion="success", status="completed"
  )

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
    assert call_args.kwargs["workflow_id"] == workflow


def test_test_commit_with_retries(mocker, mock_gh_client, finder_factory):
  """Tests that _test_commit retries the specified number of times on failure."""
  mocker.patch("culprit_finder.culprit_finder.github_client")

  finder = finder_factory(retries=2)

  branch = "test-branch"
  commit_sha = "sha1"

  mock_wait = mocker.patch.object(finder, "_wait_for_workflow_completion")
  mock_wait.side_effect = [
    factories.create_run(mocker, head_sha=commit_sha, conclusion="failure"),
    factories.create_run(mocker, head_sha=commit_sha, conclusion="failure"),
    factories.create_run(mocker, head_sha=commit_sha, conclusion="success"),
  ]

  is_good = finder._test_commit(commit_sha, branch)

  assert is_good is True
  assert mock_wait.call_count == 3
  assert mock_gh_client.trigger_workflow.call_count == 3


@pytest.mark.parametrize(
  "conclusion, expected_is_good",
  [
    ("success", True),
    ("failure", False),
  ],
)
@pytest.mark.parametrize("finder", [True, False], indirect=True)
def test_test_commit_outcomes(
  mocker, finder, mock_gh_client, conclusion, expected_is_good
):
  """Tests that _test_commit returns correct boolean based on workflow conclusion."""
  branch = "test-branch"
  commit_sha = "sha1"

  mock_wait = mocker.patch.object(finder, "_wait_for_workflow_completion")
  mock_wait.return_value = factories.create_run(
    mocker, head_sha=commit_sha, conclusion=conclusion, status="completed"
  )

  # Mock get_latest_run to return None for the "previous run" check
  mock_gh_client.get_latest_run.return_value = None

  is_good = finder._test_commit(commit_sha, branch)

  assert is_good is expected_is_good

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


@pytest.mark.parametrize("has_culprit_workflow", [True, False])
def test_test_commit_with_project_config(
  mocker, mock_gh_client, has_culprit_workflow, mock_state, mock_state_persister
):
  """Tests that _test_commit injects the pinned dependency if the repo matches PROJECT_CONFIG."""
  repo_name = "jax-ml/jax"
  workflow_file = "wheel_tests_continuous.yml"
  branch = "test-branch"
  commit_sha = "sha1"
  dep_commit_sha = "xla_sha_123"

  # Create finder with specific repo and workflow
  finder = culprit_finder.CulpritFinder(
    repo=repo_name,
    start_sha="start_sha",
    end_sha="end_sha",
    workflow_file=workflow_file,
    has_culprit_finder_workflow=has_culprit_workflow,
    gh_client=mock_gh_client,
    state=mock_state,
    state_persister=mock_state_persister,
  )

  # Mock completion
  mock_wait = mocker.patch.object(finder, "_wait_for_workflow_completion")
  mock_wait.return_value = factories.create_run(
    mocker, head_sha=commit_sha, conclusion="success", status="completed"
  )
  mock_gh_client.get_latest_run.return_value = None

  # Mock dependency lookup
  mock_commit = mocker.Mock()
  mock_commit.commit.committer.date = "2023-01-01T00:00:00Z"
  mock_gh_client.get_commit.return_value = mock_commit
  
  mock_dep_commit = mocker.Mock()
  mock_dep_commit.sha = dep_commit_sha
  mock_gh_client.get_last_commit_before.return_value = mock_dep_commit
  
  is_good = finder._test_commit(commit_sha, branch)

  assert is_good is True
  mock_gh_client.get_commit.assert_called_once_with(commit_sha)
  mock_gh_client.get_last_commit_before.assert_called_once_with(
    "openxla/xla", "2023-01-01T00:00:00Z"
  )

  # Determine expected arguments based on configuration
  if has_culprit_workflow:
    expected_workflow = CULPRIT_WORKFLOW
    expected_inputs = {"workflow-to-debug": workflow_file, "xla-commit": dep_commit_sha}
  else:
    expected_workflow = workflow_file
    expected_inputs = {"xla-commit": dep_commit_sha}

  mock_gh_client.trigger_workflow.assert_called_once_with(
    expected_workflow,
    branch,
    expected_inputs,
  )


def test_test_commit_failure(mocker, finder, mock_gh_client):
  """Tests that _test_commit returns False if the workflow fails."""
  mock_wait = mocker.patch.object(finder, "_wait_for_workflow_completion")
  mock_wait.return_value = factories.create_run(mocker, "sha", "completed", "failure")

  # Mock get_latest_run to return None for the "previous run" check
  mock_gh_client.get_latest_run.return_value = None

  assert finder._test_commit("sha", "branch") is False


@pytest.mark.parametrize("has_culprit_workflow", [True, False])
def test_test_commit_with_specific_job(
  mocker, finder_factory, mock_gh_client, has_culprit_workflow
):
  """Tests that _test_commit checks a specific job when the job parameter is set."""
  finder = finder_factory(
    has_culprit_finder_workflow=has_culprit_workflow,
    job="test-job",
  )

  branch = "test-branch"
  commit_sha = "sha1"
  run_id = 123

  mock_wait = mocker.patch.object(finder, "_wait_for_workflow_completion")
  mock_wait.return_value = factories.create_run(
    mocker, head_sha=commit_sha, conclusion="failure", run_id=run_id
  )

  prefix = "Caller Job / " if has_culprit_workflow else ""

  mock_gh_client.get_run_jobs.return_value = [
    factories.create_job(mocker, f"{prefix}test-job", "success"),
    factories.create_job(mocker, f"{prefix}other-job", "failure"),
  ]

  is_good = finder._test_commit(commit_sha, branch)

  assert is_good is True
  mock_gh_client.get_run_jobs.assert_called_once_with(run_id)

  if has_culprit_workflow:
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


@pytest.mark.parametrize("has_culprit_workflow", [True, False])
def test_find_job(
  mocker,
  finder_factory,
  mock_gh_client,
  has_culprit_workflow,
):
  """Tests that _find_job correctly finds a job with or without culprit workflow."""
  target_job = "Pytest CPU / linux x86"
  finder = finder_factory(
    has_culprit_finder_workflow=has_culprit_workflow,
    job=target_job,
  )

  prefix = "Caller Job / " if has_culprit_workflow else ""
  jobs = [
    factories.create_job(mocker, f"{prefix}other-job", "success"),
    factories.create_job(mocker, f"{prefix}{target_job}", "failure"),
    factories.create_job(mocker, f"{prefix}another-job", "success"),
  ]

  job = finder._get_target_job(jobs, has_culprit_workflow)

  assert job == jobs[1]


def test_find_job_not_found(mocker, finder_factory):
  """Tests that _find_job raises ValueError when the job is not found."""
  finder = finder_factory(
    has_culprit_finder_workflow=False,
    job="missing-job",
  )

  jobs = [
    factories.create_job(mocker, "job1", "success"),
    factories.create_job(mocker, "job2", "success"),
  ]

  with pytest.raises(ValueError, match="Job missing-job not found in workflow"):
    finder._get_target_job(jobs, False)


@pytest.mark.parametrize(
  "commits_data, test_results, expected_culprit_idx",
  [
    # Scenario 1: Culprit found (C1 is bad)
    (
      [("c0", "m0"), ("c1", "m1"), ("c2", "m2")],
      [False, True],
      1,
    ),
    # Scenario 2: All commits are good
    # [C0 (Good), C1 (Good), C2 (Good)]
    # Search path: Mid=1 (C1) -> Good. Mid=2 (C2) -> Good.
    # Result: None
    (
      [("c0", "m0"), ("c1", "m1"), ("c2", "m2")],
      [True, True],  # Results for checks on C1, then C2
      None,
    ),
    # Scenario 3: All commits are bad
    # [C0 (Bad), C1 (Bad), C2 (Bad)]
    # Search path: Mid=1 (C1) -> Bad. Mid=0 (C0) -> Bad.
    # Result: C0 (index 0)
    (
      [("c0", "m0"), ("c1", "m1"), ("c2", "m2")],
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
      [("c0", "m0")],
      [True],
      None,
    ),
    # Scenario 6: Single commit is BAD
    (
      [("c0", "m0")],
      [False],
      0,
    ),
  ],
)
def test_run_bisection(
  mocker, finder, mock_gh_client, commits_data, test_results, expected_culprit_idx
):
  """Tests various bisection scenarios including finding a culprit, no culprit, etc."""
  commits = [factories.create_commit(mocker, sha, msg) for sha, msg in commits_data]
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
  commits = [factories.create_commit(mocker, "c0", "m0")]
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
  commits = [factories.create_commit(mocker, "c0", "m0")]
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


def test_run_bisection_updates_and_saves_state_each_iteration(
  mocker, finder, mock_gh_client
):
  """
  Verifies:
  - state fields are updated between iterations
  - state is saved after each non-cached iteration
  """
  commits = [
    factories.create_commit(mocker, "c0", "m0"),
    factories.create_commit(mocker, "c1", "m1"),
    factories.create_commit(mocker, "c2", "m2"),
  ]
  mock_gh_client.compare_commits.return_value = commits

  # Two iterations will test two commits; each iteration calls check_branch_exists twice.
  mock_gh_client.check_branch_exists.side_effect = [False, True, False, True]

  mock_test = mocker.patch.object(finder, "_test_commit")
  # Mid=1 => c1 is BAD, then mid=0 => c0 is GOOD
  mock_test.side_effect = [False, True]

  culprit = finder.run_bisection()
  assert culprit == commits[1]

  assert finder._state_persister.save.call_count == 2

  # After first iteration (c1 BAD) state must reflect the failure.
  state_after_1 = finder._state_persister.save.call_args_list[0][0][0]
  assert state_after_1["current_bad"] == "c1"
  assert state_after_1["cache"]["c1"] == "FAIL"

  # After second iteration (c0 GOOD) state must reflect the pass and retain prior cache.
  state_after_2 = finder._state_persister.save.call_args_list[1][0][0]
  assert state_after_2["current_good"] == "c0"
  assert state_after_2["cache"]["c0"] == "PASS"
  assert state_after_2["cache"]["c1"] == "FAIL"


def test_run_bisection_skips_testing_cached_commit(mocker, finder, mock_gh_client):
  """
  Verifies that when the midpoint commit already exists in the cache,
  it is not tested (_test_commit is not called for it).
  """
  commits = [
    factories.create_commit(mocker, "c0", "m0"),
    factories.create_commit(mocker, "c1", "m1"),
    factories.create_commit(mocker, "c2", "m2"),
  ]
  mock_gh_client.compare_commits.return_value = commits

  # Force first midpoint (c1) to be cached as PASS, so bisection should skip testing it.
  finder._state["cache"]["c1"] = "PASS"

  mock_test = mocker.patch.object(finder, "_test_commit")
  # With good_idx updated by cached c1, next midpoint will be c2; test it once.
  mock_test.side_effect = [False]

  # Only one real iteration should create/cleanup a branch => two calls.
  mock_gh_client.check_branch_exists.side_effect = [False, True]

  culprit = finder.run_bisection()
  assert culprit == commits[2]

  # Ensure c1 was not tested because it was cached.
  tested_shas = [call.args[0] for call in mock_test.call_args_list]
  assert "c1" not in tested_shas
  assert tested_shas == ["c2"]

  # Cache-hit path should not persist state; only the real test of c2 should save.
  finder._state_persister.save.assert_called_once()
  saved_state = finder._state_persister.save.call_args[0][0]
  assert saved_state["cache"]["c2"] == "FAIL"


@pytest.mark.parametrize("use_job", [False, True], ids=["no_job", "with_job"])
def test_run_bisection_uses_cache_variants(
  mocker, finder_factory, mock_gh_client, use_job
):
  """Tests that bisection uses cached results when available, with or without job."""
  commits = [
    factories.create_commit(mocker, "c0", "m0"),
    factories.create_commit(mocker, "c1", "m1"),
  ]
  mock_gh_client.compare_commits.return_value = commits

  target_job = "test-job" if use_job else None
  finder = finder_factory(use_cache=True, job=target_job)

  # Scenario:
  # c0 is GOOD (via cache).
  # c1 is BAD (via _test_commit or cache).
  # Result: c1 is culprit.

  if use_job:
    # c0 workflow fails, but job succeeds -> GOOD
    mock_gh_client.get_latest_run.side_effect = lambda **kwargs: (
      factories.create_run(mocker, head_sha="c0", conclusion="failure", run_id=100)
      if kwargs.get("commit") == "c0"
      else None
    )
    mock_gh_client.get_run_jobs.return_value = [
      factories.create_job(mocker, target_job, "success")
    ]
  else:
    # c0 workflow succeeds -> GOOD
    mock_gh_client.get_latest_run.side_effect = lambda **kwargs: (
      factories.create_run(mocker, head_sha="c0", conclusion="success", run_id=100)
      if kwargs.get("commit") == "c0"
      else None
    )

  # Mock _test_commit for c1 (failure)
  mock_test_commit = mocker.patch.object(finder, "_test_commit")
  mock_test_commit.return_value = False

  # Mock branch existence for c1 test
  mock_gh_client.check_branch_exists.side_effect = [False, True]

  culprit = finder.run_bisection()

  assert culprit == commits[1]


@pytest.mark.parametrize(
  "run_data, job_data, expected_result",
  [
    ({"conclusion": "success"}, None, True),
    ({"conclusion": "failure"}, None, False),
    (None, None, None),
    ({"conclusion": "failure"}, {"name": "test-job", "conclusion": "success"}, True),
    ({"conclusion": "success"}, {"name": "test-job", "conclusion": "failure"}, False),
  ],
)
def test_check_existing_run_variants(
  finder_factory, mock_gh_client, mocker, run_data, job_data, expected_result
):
  """Tests _check_existing_run with various previous run outcomes, including jobs."""
  target_job = job_data["name"] if job_data else None
  finder = finder_factory(use_cache=True, job=target_job)

  mock_gh_client.get_latest_run.return_value = (
    factories.create_run(mocker, "sha", run_data["conclusion"], run_id=123)
    if run_data
    else None
  )

  if job_data:
    mock_gh_client.get_run_jobs.return_value = [
      factories.create_job(mocker, job_data["name"], job_data["conclusion"]),
      factories.create_job(mocker, "other-job", "ignored"),
    ]

  result = finder._check_existing_run("sha")
  assert result is expected_result


def test_execute_test_with_branch_success(mocker, finder, mock_gh_client):
  """Tests _execute_test_with_branch with successful execution."""
  commit_sha = "sha1"

  # Mock branch check: doesn't exist initially, exists for deletion
  mock_gh_client.check_branch_exists.side_effect = [False, True]

  mocker.patch.object(finder, "_test_commit", return_value=True)

  result = finder._execute_test_with_branch(commit_sha)

  assert result is True
  mock_gh_client.create_branch.assert_called_once()
  args, _ = mock_gh_client.create_branch.call_args
  assert args[1] == commit_sha
  assert "culprit-finder/test-sha1_" in args[0]


def test_execute_test_with_branch_exception_cleanup(mocker, finder, mock_gh_client):
  """Tests cleanup in _execute_test_with_branch when an exception occurs."""
  commit_sha = "sha1"

  mock_gh_client.check_branch_exists.side_effect = [False, True]
  mocker.patch.object(finder, "_test_commit", side_effect=Exception("Test error"))

  with pytest.raises(Exception, match="Test error"):
    finder._execute_test_with_branch(commit_sha)

  mock_gh_client.create_branch.assert_called_once()
  mock_gh_client.delete_branch.assert_called_once()


@pytest.mark.parametrize(
  "is_good, expected_status",
  [
    (True, "PASS"),
    (False, "FAIL"),
  ],
)
def test_update_state(finder, mock_state_persister, is_good, expected_status):
  """Tests _update_state for good and bad commits."""
  commit_sha = "sha1"
  finder._update_state(commit_sha, is_good=is_good)

  field = "current_good" if is_good else "current_bad"
  assert finder._state[field] == commit_sha
  assert finder._state["cache"][commit_sha] == expected_status
