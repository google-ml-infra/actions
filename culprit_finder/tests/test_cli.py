"""Tests for the CLI."""

import sys
import pytest
import logging
from unittest import mock
from typing import TypedDict

from culprit_finder import cli, github


def _get_culprit_finder_command(
  repo: str | None,
  start_sha: str | None,
  end_sha: str | None,
  workflow_file: str | None,
  clear_cache: bool = False,
) -> list[str]:
  command = ["culprit_finder"]
  if repo:
    command.extend(["--repo", repo])
  if start_sha:
    command.extend(["--start", start_sha])
  if end_sha:
    command.extend(["--end", end_sha])
  if workflow_file:
    command.extend(["--workflow", workflow_file])
  if clear_cache:
    command.append("--clear-cache")
  return command


@pytest.mark.parametrize(
  "args, expected_error_msg",
  [
    (
      _get_culprit_finder_command("invalidrepo", "sha1", "sha2", "test.yml"),
      "Invalid repo format: invalidrepo",
    ),
    (
      _get_culprit_finder_command("/repo", "sha1", "sha2", "test.yml"),
      "Invalid repo format: /repo",
    ),
    (
      _get_culprit_finder_command("owner/", "sha1", "sha2", "test.yml"),
      "Invalid repo format: owner/",
    ),
    (_get_culprit_finder_command("", "sha1", "sha2", "test.yml"), "error"),
  ],
)
def test_invalid_repo_format(monkeypatch, capsys, args, expected_error_msg):
  """Tests that the CLI exits with an error for invalid inputs (missing args or invalid formats)."""
  monkeypatch.setattr(sys, "argv", args)

  with pytest.raises(SystemExit):
    cli.main()

  captured = capsys.readouterr()
  assert expected_error_msg.lower() in captured.err.lower()


def _mock_gh_client(
  mocker, is_authenticated: bool, workflows: list[github.Workflow] | None = None
):
  mock_gh_client_class = mocker.patch("culprit_finder.github.GithubClient")
  mock_gh_client_instance = mock_gh_client_class.return_value
  mock_gh_client_instance.check_auth_status.return_value = is_authenticated
  if workflows:
    mock_gh_client_instance.get_workflows.return_value = workflows
  return mock_gh_client_instance


class _MockStatePatches(TypedDict):
  state_persister_cls: mock.MagicMock
  state_persister_inst: mock.MagicMock


def _mock_state(mocker, existing_state=None) -> _MockStatePatches:
  state_persister_cls = mocker.patch(
    "culprit_finder.culprit_finder_state.StatePersister"
  )
  state_persister_inst = state_persister_cls.return_value

  state_persister_inst.load.return_value = existing_state
  state_persister_inst.exists.return_value = existing_state is not None

  return {
    "state_persister_cls": state_persister_cls,
    "state_persister_inst": state_persister_inst,
  }


def test_cli_not_authenticated(monkeypatch, mocker, caplog):
  """Tests that the CLI exits with an error when not authenticated via CLI or Token."""
  _mock_gh_client(mocker, False)

  monkeypatch.delenv("GH_TOKEN", raising=False)

  monkeypatch.setattr(
    sys,
    "argv",
    _get_culprit_finder_command("owner/repo", "sha1", "sha2", "test.yml"),
  )

  with pytest.raises(SystemExit) as excinfo:
    cli.main()

  assert excinfo.value.code == 1
  assert (
    "Not authenticated with GitHub CLI or GH_TOKEN env var is not set." in caplog.text
  )


@pytest.mark.parametrize(
  "cli_auth, token_auth",
  [
    (False, "fake_token"),  # Auth via token only
    (True, None),  # Auth via CLI only
  ],
)
def test_cli_auth_success(monkeypatch, mocker, cli_auth, token_auth):
  """Tests that the CLI proceeds if authenticated via CLI or GH_TOKEN."""
  mock_finder = mocker.patch("culprit_finder.cli.culprit_finder.CulpritFinder")
  _mock_gh_client(mocker, cli_auth, [{"path": "some/path", "name": "Culprit Finder"}])
  _mock_state(mocker)

  if token_auth:
    monkeypatch.setenv("GH_TOKEN", token_auth)
  else:
    monkeypatch.delenv("GH_TOKEN", raising=False)

  monkeypatch.setattr(
    sys,
    "argv",
    _get_culprit_finder_command("owner/repo", "sha1", "sha2", "test.yml"),
  )

  cli.main()

  mock_finder.assert_called_once()


@pytest.mark.parametrize(
  "workflows_list, has_culprit_workflow, found_culprit_commit, expected_output",
  [
    # Scenario 1: Culprit finder workflow present, Culprit Found
    (
      [
        {"path": ".github/workflows/culprit_finder.yml", "name": "Culprit Finder"},
        {"path": ".github/workflows/test.yml", "name": "Other"},
      ],
      True,
      {"sha": "badsha123", "message": "Bad commit message\nDetails"},
      "The culprit commit is: Bad commit message (SHA: badsha123)",
    ),
    # Scenario 2: Culprit finder workflow absent, Culprit Found
    (
      [{"path": ".github/workflows/test.yml", "name": "Other"}],
      False,
      {"sha": "badsha456", "message": "Another bad one"},
      "The culprit commit is: Another bad one (SHA: badsha456)",
    ),
    # Scenario 3: Culprit finder workflow present, No Culprit Found
    (
      [
        {"path": ".github/workflows/culprit_finder.yml", "name": "Culprit Finder"},
      ],
      True,
      None,
      "No culprit commit found.",
    ),
  ],
)
def test_cli_success(
  monkeypatch,
  mocker,
  capsys,
  workflows_list: list[github.Workflow],
  has_culprit_workflow: bool,
  found_culprit_commit: github.Commit | None,
  expected_output: str,
):
  """
  Tests the happy path.
  Verifies that the CulpritFinder is initialized with correct arguments and run_bisection is called.
  Also verifies the CLI output based on whether a culprit is found.
  """
  mock_finder = mocker.patch("culprit_finder.cli.culprit_finder.CulpritFinder")
  mock_gh_client_instance = _mock_gh_client(mocker, True, workflows_list)
  mock_finder.return_value.run_bisection.return_value = found_culprit_commit

  monkeypatch.setattr(
    sys,
    "argv",
    _get_culprit_finder_command("owner/repo", "sha1", "sha2", "test.yml"),
  )

  patches = _mock_state(mocker)

  cli.main()

  expected_state = {
    "repo": "owner/repo",
    "workflow": "test.yml",
    "original_start": "sha1",
    "original_end": "sha2",
    "current_good": "",
    "current_bad": "",
    "cache": {},
  }

  mock_finder.assert_called_once_with(
    repo="owner/repo",
    start_sha="sha1",
    end_sha="sha2",
    workflow_file="test.yml",
    has_culprit_finder_workflow=has_culprit_workflow,
    github_client=mock_gh_client_instance,
    state=expected_state,
    state_persister=patches["state_persister_inst"],
  )
  mock_finder.return_value.run_bisection.assert_called_once()

  captured = capsys.readouterr()
  assert expected_output in captured.out


@pytest.mark.parametrize(
  "state_exists, user_input, expected_delete_calls, expected_resume",
  [
    (False, None, 1, False),  # No state file, should create new, delete at end
    (True, "y", 1, True),  # State exists, resume, should delete at end
    (
      True,
      "n",
      2,
      False,
    ),  # State exists, discard, delete old, create new, delete at end
  ],
)
def test_cli_state_management(
  monkeypatch,
  mocker,
  state_exists,
  user_input,
  expected_delete_calls,
  expected_resume,
):
  """Tests state loading, user prompt, and cleanup."""
  mock_finder_cls = mocker.patch("culprit_finder.cli.culprit_finder.CulpritFinder")
  mock_finder = mock_finder_cls.return_value
  mock_finder.run_bisection.return_value = {"sha": "found_sha", "message": "msg"}

  mock_gh_client_instance = _mock_gh_client(mocker, True)
  existing_state = (
    {
      "repo": "owner/repo",
      "workflow": "test.yml",
      "original_start": "sha1",
      "original_end": "sha2",
      "current_good": "good_sha",
      "current_bad": "bad_sha",
      "cache": {},
    }
    if state_exists
    else None
  )
  patches = _mock_state(mocker, existing_state)
  mock_persister_inst = patches["state_persister_inst"]

  if user_input:
    mocker.patch("builtins.input", return_value=user_input)

  monkeypatch.setattr(
    sys,
    "argv",
    _get_culprit_finder_command("owner/repo", "sha1", "sha2", "test.yml"),
  )

  cli.main()

  assert mock_persister_inst.delete.call_count == expected_delete_calls

  if state_exists and expected_resume:
    mock_finder_cls.assert_called_with(
      repo="owner/repo",
      start_sha="sha1",
      end_sha="sha2",
      workflow_file="test.yml",
      has_culprit_finder_workflow=False,
      state=existing_state,
      github_client=mock_gh_client_instance,
      state_persister=patches["state_persister_inst"],
    )
  else:
    # If not exists or discarded, new state created
    assert mock_finder_cls.called


def test_cli_interrupted_saves_state(monkeypatch, mocker, caplog):
  """Tests that state is saved when execution is interrupted."""
  caplog.set_level(logging.INFO)
  mock_finder_cls = mocker.patch("culprit_finder.cli.culprit_finder.CulpritFinder")
  mock_finder = mock_finder_cls.return_value
  mock_finder.run_bisection.side_effect = KeyboardInterrupt

  _mock_gh_client(mocker, True)

  patches = _mock_state(mocker)
  mock_persister_inst = patches["state_persister_inst"]

  monkeypatch.setattr(
    sys,
    "argv",
    _get_culprit_finder_command("owner/repo", "sha1", "sha2", "test.yml"),
  )

  cli.main()

  mock_persister_inst.save.assert_called_once()
  mock_persister_inst.delete.assert_not_called()
  assert (
    "Bisection interrupted by user (CTRL+C). Saving current state..." in caplog.text
  )


def test_cli_clear_cache_deletes_state(monkeypatch, mocker):
  """Tests that the --clear-cache argument triggers state deletion."""
  mock_finder = mocker.patch("culprit_finder.cli.culprit_finder.CulpritFinder")
  mock_finder.return_value.run_bisection.return_value = None

  _mock_gh_client(mocker, True)

  patches = _mock_state(mocker)
  mock_persister_inst = patches["state_persister_inst"]
  # Simulate state exists initially, then is deleted (so subsequent exists() calls return False)
  # First call: checks if exists for clear-cache logic -> True
  # Second call: checks if exists for resume logic -> False (simulating it was deleted)
  mock_persister_inst.exists.side_effect = [True, False]

  monkeypatch.setattr(
    sys,
    "argv",
    _get_culprit_finder_command(
      "owner/repo", "sha1", "sha2", "test.yml", clear_cache=True
    ),
  )

  cli.main()

  # delete() should be called at start (due to clear-cache) and potentially at end (if no culprit found/successful run)
  assert mock_persister_inst.delete.called


def test_cli_with_url(monkeypatch, mocker):
  """Tests that the CLI correctly infers arguments from a URL based on run status."""
  mock_finder = mocker.patch("culprit_finder.cli.culprit_finder.CulpritFinder")
  mock_gh_client_instance = _mock_gh_client(
    mocker,
    True,
    [{"path": ".github/workflows/culprit_finder.yml", "name": "Culprit Finder"}],
  )
  patches = _mock_state(mocker)

  mock_gh_client_instance.get_run_from_url.return_value = {
    "headSha": "sha_from_url",
    "status": "failure",
    "workflowName": "Test Workflow",
    "workflowDatabaseId": 123,
    "conclusion": "failure",
    "headBranch": "main",
    "event": "push",
    "createdAt": "2023-01-01T00:00:00Z",
  }
  mock_gh_client_instance.get_workflow.return_value = {
    "path": ".github/workflows/test.yml"
  }
  mock_gh_client_instance.get_latest_run.return_value = {
    "headSha": "sha1",
    "status": "completed",
    "workflowName": "Test Workflow",
    "workflowDatabaseId": 123,
    "conclusion": "success",
    "headBranch": "main",
    "event": "push",
    "createdAt": "2023-01-01T00:00:00Z",
  }

  url = "https://github.com/owner/repo/actions/runs/123"
  args = ["culprit_finder", url, "--start", "sha1"]
  monkeypatch.setattr(sys, "argv", args)

  cli.main()

  expected_start = "sha1"
  expected_end = "sha_from_url"
  expected_state = {
    "repo": "owner/repo",
    "workflow": "test.yml",
    "original_start": expected_start,
    "original_end": expected_end,
    "current_good": "",
    "current_bad": "",
    "cache": {},
  }
  mock_finder.assert_called_once_with(
    repo="owner/repo",
    start_sha=expected_start,
    end_sha=expected_end,
    workflow_file="test.yml",
    has_culprit_finder_workflow=True,
    github_client=mock_gh_client_instance,
    state=expected_state,
    state_persister=patches["state_persister_inst"],
  )


@pytest.mark.parametrize(
  "args, expected_error_msg",
  [
    (
      ["culprit_finder"],
      "the following arguments are required: -r/--repo (or provided via URL)",
    ),
    (
      _get_culprit_finder_command(None, "sha1", "sha2", "test.yml"),
      "the following arguments are required: -r/--repo (or provided via URL)",
    ),
  ],
)
def test_missing_repo_args(monkeypatch, capsys, args, expected_error_msg):
  """Tests that the CLI exits with an error when repo is missing (before auth check)."""
  monkeypatch.setattr(sys, "argv", args)
  with pytest.raises(SystemExit):
    cli.main()
  captured = capsys.readouterr()
  assert expected_error_msg in captured.err


@pytest.mark.parametrize(
  "args, expected_error_msg",
  [
    (
      _get_culprit_finder_command("owner/repo", None, "sha2", "test.yml"),
      "the following arguments are required: -s/--start",
    ),
    (
      _get_culprit_finder_command("owner/repo", "sha1", None, "test.yml"),
      "the following arguments are required: -e/--end",
    ),
    (
      _get_culprit_finder_command("owner/repo", "sha1", "sha2", None),
      "the following arguments are required: -w/--workflow",
    ),
  ],
)
def test_missing_args_standard_authenticated(
  monkeypatch, mocker, capsys, args, expected_error_msg
):
  """Tests that the CLI exits with an error for missing args after repo check (requires auth)."""
  _mock_gh_client(mocker, True)
  monkeypatch.setattr(sys, "argv", args)

  with pytest.raises(SystemExit):
    cli.main()

  captured = capsys.readouterr()
  assert expected_error_msg in captured.err
