"""Tests for the CLI."""

import sys
import pytest
from culprit_finder import cli, github


def _get_culprit_finder_command(
  repo: str | None,
  start_sha: str | None,
  end_sha: str | None,
  workflow_file: str | None,
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

  cli.main()

  mock_finder.assert_called_once_with(
    repo="owner/repo",
    start_sha="sha1",
    end_sha="sha2",
    workflow_file="test.yml",
    has_culprit_finder_workflow=has_culprit_workflow,
    github_client=mock_gh_client_instance,
  )
  mock_finder.return_value.run_bisection.assert_called_once()

  captured = capsys.readouterr()
  assert expected_output in captured.out


@pytest.mark.parametrize(
  "run_status, extra_args, expected_start, expected_end",
  [
    ("success", ["--end", "sha2"], "sha_from_url", "sha2"),
    ("failure", ["--start", "sha1"], "sha1", "sha_from_url"),
  ],
)
def test_cli_with_url(
  monkeypatch, mocker, run_status, extra_args, expected_start, expected_end
):
  """Tests that the CLI correctly infers arguments from a URL based on run status."""
  mock_finder = mocker.patch("culprit_finder.cli.culprit_finder.CulpritFinder")
  mock_gh_client_instance = _mock_gh_client(
    mocker,
    True,
    [{"path": ".github/workflows/culprit_finder.yml", "name": "Culprit Finder"}],
  )

  mock_gh_client_instance.get_run_from_url.return_value = {
    "headSha": "sha_from_url",
    "status": run_status,
    "workflowName": "test.yml",
    "workflowDatabaseId": 123,
  }

  url = "https://github.com/owner/repo/actions/runs/123"
  args = ["culprit_finder", url] + extra_args
  monkeypatch.setattr(sys, "argv", args)

  cli.main()

  mock_finder.assert_called_once_with(
    repo="owner/repo",
    start_sha=expected_start,
    end_sha=expected_end,
    workflow_file="test.yml",
    has_culprit_finder_workflow=True,
    github_client=mock_gh_client_instance,
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


@pytest.mark.parametrize(
  "run_status, extra_args, expected_error_msg",
  [
    ("success", [], "the following arguments are required: -e/--end"),
    ("failure", [], "the following arguments are required: -s/--start"),
  ],
)
def test_missing_args_with_url(
  monkeypatch, mocker, capsys, run_status, extra_args, expected_error_msg
):
  """Tests that the CLI fails when required arguments are missing even with URL."""
  mock_gh_client_instance = _mock_gh_client(mocker, True)
  mock_gh_client_instance.get_run_from_url.return_value = {
    "headSha": "sha_from_url",
    "status": run_status,
    "workflowName": "test.yml",
    "workflowDatabaseId": 123,
  }

  url = "https://github.com/owner/repo/actions/runs/123"
  args = ["culprit_finder", url] + extra_args
  monkeypatch.setattr(sys, "argv", args)

  with pytest.raises(SystemExit):
    cli.main()

  captured = capsys.readouterr()
  assert expected_error_msg in captured.err
