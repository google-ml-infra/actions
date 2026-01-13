"""
Module for interacting with the GitHub API via PyGithub.
"""

import logging
import os
import re
import time
from typing import Optional
import subprocess

import github
from github.Commit import Commit
from github.WorkflowRun import WorkflowRun
from github.Workflow import Workflow


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
    self._repo = github.Github(auth=github.Auth.Token(token)).get_repo(repo, lazy=True)

  def compare_commits(self, base_sha: str, head_sha: str) -> list[Commit]:
    """
    Gets the list of commits between two SHAs.

    Args:
        base_sha: The starting commit SHA (exclusive).
        head_sha: The ending commit SHA (inclusive).

    Returns:
        A list of commits objects in the range (base_sha...head_sha].
    """
    comparison = self._repo.compare(base_sha, head_sha)
    return list(comparison.commits)

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
  ) -> WorkflowRun | None:
    """
    Gets the latest workflow run for a specific branch and workflow.

    Args:
        workflow_id: The filename or ID of the workflow to query.
        branch: The git branch reference to filter runs by.
        event: The event that triggered the workflow run (e.g., "push", "pull_request").
        created: Optional timestamp to filter runs by creation time.
        status: Optional status to filter runs by (e.g., "success", "failure").

    Returns:
        The latest workflow run object, or None if no runs are found.
    """
    workflow = self._repo.get_workflow(workflow_id)

    kwargs = {}
    if created:
      kwargs["created"] = created
    if status:
      kwargs["status"] = status

    runs = workflow.get_runs(branch=branch, event=event, **kwargs)

    if runs.totalCount > 0:
      return runs[0]
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
    return list(self._repo.get_workflows())

  def get_workflow(self, workflow_id: int | str) -> Workflow:
    """
    Retrieves details of a specific workflow by its ID or filename.

    Args:
        workflow_id: The ID or filename (e.g., 'main.yml') of the workflow.

    Returns:
        The workflow object.
    """
    return self._repo.get_workflow(workflow_id)

  def get_run(self, run_id: str) -> WorkflowRun:
    """
    Retrieves detailed information about a specific workflow run.

    Args:
        run_id: The unique database ID or number of the workflow run.

    Returns:
        A WorkflowRun object containing metadata such as head SHA, status, and conclusion.
    """
    return self._repo.get_workflow_run(int(run_id))

  def get_run_from_url(self, url: str) -> WorkflowRun:
    """
    Retrieves workflow run details using a GitHub Actions URL.

    The URL must follow one of these structures:
    - https://github.com/owner/repo/actions/runs/:runId
    - https://github.com/owner/repo/actions/runs/:runId/jobs/:jobId

    Args:
        url: The full GitHub URL to the workflow run or specific job.

    Returns:
        A WorkflowRun object containing metadata for the extracted run ID.

    Raises:
        ValueError: If the run ID cannot be parsed from the provided URL.
    """
    match = re.search(r"actions/runs/(\d+)", url)
    if not match:
      raise ValueError(f"Could not extract run ID from URL: {url}")

    run_id = match.group(1)
    return self.get_run(run_id)

  def find_previous_successful_run(self, run: WorkflowRun) -> WorkflowRun:
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
      run.workflow_id,
      run.head_branch,
      run.event,
      created=f"<{run.created_at}",
      status="success",
    )

    # Fallback: If strict matching failed, try to find the last successful 'push' event.
    if not last_successful_run and run.event != "push":
      logging.info(
        "No successful run found for event '%s'. Falling back to 'push' event.",
        run.event,
      )
      last_successful_run = self.get_latest_run(
        run.workflow_id,
        run.head_branch,
        event="push",
        created=f"<{run.created_at}",
        status="success",
      )

    if not last_successful_run:
      workflow = self._repo.get_workflow(run.workflow_id)
      raise ValueError(
        f"No previous successful run found for workflow '{workflow.name}' on branch {run.head_branch}"
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
