"""
Module for interacting with the GitHub API via PyGithub.
"""

import logging
import os
import re
import time
from typing import Optional, TypedDict
import subprocess

import github
from github.WorkflowRun import WorkflowRun


class Commit(TypedDict):
  sha: str
  message: str


class Workflow(TypedDict):
  name: str
  path: str


class Run(TypedDict):
  """Represents a GitHub Actions workflow run.

  Attributes:
      headSha: The SHA of the head commit for the workflow run.
      status: The current status of the workflow run (e.g., "completed", "in_progress", "queued").
      createdAt: The timestamp when the workflow run was created.
      conclusion: The conclusion of the workflow run if completed (e.g., "success", "failure", "cancelled"). Optional.
      databaseId: The unique identifier for the workflow run in the GitHub database.
      url: The URL to the workflow run on GitHub.
      workflowDatabaseId: The unique identifier for the workflow in the GitHub database.
      headBranch: The branch on which the workflow run was triggered.
      event: The event that triggered the workflow run (e.g., "push", "pull_request").
  """

  headSha: str
  status: str
  createdAt: str
  conclusion: Optional[str]
  databaseId: int
  url: str
  workflowDatabaseId: int
  headBranch: str
  event: str


class GithubClient:
  """
  A client for interacting with the GitHub API via PyGithub.
  """

  def __init__(self, repo: str, token: str):
    """
    Initializes the GithubClient.

    Args:
        repo: The GitHub repository in 'owner/repo' format.
        token: The GitHub access token for authentication.
    """
    self._github = github.Github(auth=github.Auth.Token(token))
    self._repo = self._github.get_repo(repo, lazy=True)

  def _to_run_dict(self, run: WorkflowRun) -> Run:
    """Converts a PyGithub WorkflowRun object to a Run TypedDict."""
    return {
      "headSha": run.head_sha,
      "status": run.status,
      "createdAt": run.created_at.isoformat(),
      "conclusion": run.conclusion,
      "databaseId": run.id,
      "url": run.html_url,
      "workflowDatabaseId": run.workflow_id,
      "headBranch": run.head_branch,
      "event": run.event,
    }

  def compare_commits(self, base_sha: str, head_sha: str) -> list[Commit]:
    """
    Gets the list of commits between two SHAs.

    Args:
        base_sha: The starting commit SHA (exclusive).
        head_sha: The ending commit SHA (inclusive).

    Returns:
        A list of dictionaries, where each dictionary represents a commit
        in the range (base_sha...head_sha].
    """
    comparison = self._repo.compare(base_sha, head_sha)
    return [{"sha": c.sha, "message": c.commit.message} for c in comparison.commits]

  def trigger_workflow(
    self, workflow_file: str, branch: str, inputs: dict[str, str]
  ) -> None:
    """
    Triggers a workflow_dispatch event for a specific workflow on a branch.

    Args:
        workflow_file: The filename or ID of the workflow to trigger.
        branch: The git branch reference to run the workflow on.
        inputs: A dictionary of input keys and values for the workflow dispatch event.
    """
    workflow = self._repo.get_workflow(workflow_file)
    workflow.create_dispatch(branch, inputs)

  def get_latest_run(
    self,
    workflow_id: str | int,
    branch: str,
    event: str,
    created: Optional[str] = None,
    status: Optional[str] = None,
  ) -> Run | None:
    """
    Gets the latest workflow run for a specific branch and workflow.

    Args:
        workflow_id: The filename or ID of the workflow to query.
        branch: The git branch reference to filter runs by.
        event: The event that triggered the workflow run (e.g., "push", "pull_request").
        created: Optional timestamp to filter runs by creation time.
        status: Optional status to filter runs by (e.g., "success", "failure").

    Returns:
        A dictionary representing the latest workflow run object, or None if no runs are found.
    """
    workflow = self._repo.get_workflow(workflow_id)

    kwargs = {}
    if created:
      kwargs["created"] = created
    if status:
      kwargs["status"] = status

    runs = workflow.get_runs(branch=branch, event=event, **kwargs)

    if runs.totalCount > 0:
      return self._to_run_dict(runs[0])
    return None

  def check_branch_exists(self, branch_name: str) -> bool:
    """
    Checks if a branch exists in the remote repository.

    Args:
        branch_name: The name of the branch to check.

    Returns:
        True if the branch exists, False otherwise.
    """
    try:
      self._repo.get_branch(branch_name)
      return True
    except github.GithubException:
      return False

  def create_branch(self, branch_name: str, sha: str) -> None:
    """
    Creates a new git branch (ref) from a specific SHA in the remote repository.

    Args:
        branch_name: The name of the new branch to create (e.g., 'my-feature-branch').
        sha: The commit SHA to base the new branch on.
    """
    self._repo.create_git_ref(f"refs/heads/{branch_name}", sha)

  def wait_for_branch_creation(self, branch_name: str, timeout: int = 60) -> None:
    """
    Waits for a branch to be available in the remote repository.

    Args:
        branch_name: The name of the branch to wait for.
        timeout: The maximum time to wait in seconds.

    Raises:
        ValueError: If the branch is not created within the timeout.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
      if self.check_branch_exists(branch_name):
        # Even if the branch exists in git, the Actions subsystem needs a moment to sync.
        # Without this delay, the workflow trigger often falls back to the default branch.
        time.sleep(5)
        logging.info("Awaited for branch %s creation successfully", branch_name)
        return
      time.sleep(1)
    raise ValueError(f"Branch {branch_name} not created within timeout")

  def delete_branch(self, branch_name: str) -> None:
    """
    Deletes a git branch (ref) from the remote repository.

    Args:
        branch_name: The name of the branch to delete.
    """
    ref = self._repo.get_git_ref(f"heads/{branch_name}")
    ref.delete()

  def get_workflows(self) -> list[Workflow]:
    """
    Retrieves a list of workflows in the repository.

    Returns:
        A list of dictionaries, where each dictionary contains the 'name' and 'path' of a workflow.
    """
    return [{"name": w.name, "path": w.path} for w in self._repo.get_workflows()]

  def get_workflow(self, workflow_id: int | str) -> Workflow:
    """
    Retrieves details of a specific workflow by its ID or filename.

    Args:
        workflow_id: The ID or filename (e.g., 'main.yml') of the workflow.

    Returns:
        A dictionary containing workflow details (name, path).
    """
    workflow_details = self._repo.get_workflow(workflow_id)
    return {"name": workflow_details.name, "path": workflow_details.path}

  def get_run(self, run_id: str) -> Run:
    """
    Retrieves detailed information about a specific workflow run.

    Args:
        run_id: The unique database ID or number of the workflow run.

    Returns:
        A Run object containing metadata such as head SHA, status, and conclusion.
    """
    run = self._repo.get_workflow_run(int(run_id))
    return self._to_run_dict(run)

  def get_run_from_url(self, url: str) -> Run:
    """
    Retrieves workflow run details using a GitHub Actions URL.

    The URL must follow one of these structures:
    - https://github.com/owner/repo/actions/runs/:runId
    - https://github.com/owner/repo/actions/runs/:runId/jobs/:jobId

    Args:
        url: The full GitHub URL to the workflow run or specific job.

    Returns:
        A Run object containing metadata for the extracted run ID.

    Raises:
        ValueError: If the run ID cannot be parsed from the provided URL.
    """
    match = re.search(r"actions/runs/(\d+)", url)
    if not match:
      raise ValueError(f"Could not extract run ID from URL: {url}")

    run_id = match.group(1)
    return self.get_run(run_id)

  def find_previous_successful_run(self, run: Run) -> Run:
    """
    Finds the last successful run for the given failed run, considering the same event type and branch.
    If no successful run is found, falls back to the last successful 'push' event.

    Args:
      run: The failed run for which to find the previous successful run.

    Returns:
      The latest successful run.

    Raises:
      ValueError: If no successful run is found.
    """
    # Try to find a successful run with the same event type first.
    # This ensures we are comparing runs with similar contexts (e.g., Pull Request vs Push),
    # minimizing false positives caused by differences in merge commits or environment specifics.
    last_successful_run = self.get_latest_run(
      run["workflowDatabaseId"],
      run["headBranch"],
      run["event"],
      created=f"<{run['createdAt']}",
      status="success",
    )

    # Fallback: If strict matching failed, try to find the last successful 'push' event.
    if not last_successful_run and run["event"] != "push":
      logging.info(
        "No successful run found for event '%s'. Falling back to 'push' event.",
        run["event"],
      )
      last_successful_run = self.get_latest_run(
        run["workflowDatabaseId"],
        run["headBranch"],
        event="push",
        created=f"<{run['createdAt']}",
        status="success",
      )

    if not last_successful_run:
      workflow = self._repo.get_workflow(run["workflowDatabaseId"])
      raise ValueError(
        f"No previous successful run found for workflow '{workflow.name}' on branch {run['headBranch']}"
      )

    return last_successful_run


def get_github_token() -> str | None:
  """Retrieves the GitHub access token from the environment or from the the GitHub CLI if not present.

  Returns:
    The GitHub access token if present, otherwise None.

  """
  token = os.environ.get("GH_TOKEN")
  if token:
    return token
  try:
    result = subprocess.run(
      ["gh", "auth", "token"], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()
  except (subprocess.CalledProcessError, FileNotFoundError):
    # Handle cases where gh is not installed or user is not logged in
    return None
