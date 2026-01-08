"""
Module for interacting with the GitHub API via the gh CLI.
"""

import subprocess
import json
import logging
import re
import time
from typing import Optional, TypedDict


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
      workflowName: The name of the workflow file (e.g. "test.yml") or the name of the workflow.
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
  workflowName: str
  workflowDatabaseId: int
  headBranch: str
  event: str


class GithubClient:
  """
  A client for interacting with the GitHub API via the gh CLI.
  """

  def __init__(self, repo: str):
    """
    Initializes the GithubClient.

    Args:
        repo: The GitHub repository in 'owner/repo' format.
    """
    self.repo = repo

  def _run_command(self, args: list[str]) -> str:
    """
    Executes a gh CLI command and returns the stdout.

    Args:
        args: A list of arguments to pass to the 'gh' command.

    Returns:
        The standard output of the command as a string.

    Raises:
        subprocess.CalledProcessError: If the command fails (returns non-zero exit code).
    """
    try:
      result = subprocess.run(["gh"] + args, check=True, capture_output=True, text=True)
      return result.stdout.strip()
    except subprocess.CalledProcessError as e:
      logging.error("Command failed: %s", e.cmd)
      logging.error("STDERR: %s", e.stderr)
      raise

  def check_auth_status(self) -> bool:
    """
    Checks if the user is authenticated with the GitHub CLI.

    Returns:
        True if authenticated, False otherwise.
    """
    try:
      subprocess.run(["gh", "auth", "status"], check=True, capture_output=True)
      return True
    except subprocess.CalledProcessError:
      return False

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
    # 250 is the limit of the compare endpoint
    per_page = 250
    page = 1

    all_commits = []

    while True:
      endpoint = f"repos/{self.repo}/compare/{base_sha}...{head_sha}?page={page}&per_page={per_page}"
      comparison_json = self._run_command(["api", endpoint])
      comparison = json.loads(comparison_json)
      commit_batch = comparison.get("commits", [])

      if not commit_batch:
        break

      all_commits.extend(commit_batch)
      page += 1

    return [{"sha": c["sha"], "message": c["commit"]["message"]} for c in all_commits]

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
    cmd = ["workflow", "run", workflow_file, "--ref", branch, "--repo", self.repo]
    for key, value in inputs.items():
      cmd.extend(["-f", f"{key}={value}"])

    self._run_command(cmd)

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
        A dictionary representing the latest workflow run object (containing fields like
        headSha, status, conclusion, etc.), or None if no runs are found.
    """
    fields = "headSha,status,createdAt,conclusion,databaseId,url,event"
    cmd = [
      "run",
      "list",
      "--workflow",
      str(workflow_id),
      "--branch",
      branch,
      "--event",
      event,
      "--limit",
      "1",
      "--json",
      fields,
      "--repo",
      self.repo,
    ]
    if created:
      cmd.extend(["--created", created])
    if status:
      cmd.extend(["--status", status])

    output = self._run_command(cmd)
    runs = json.loads(output)
    return runs[0] if runs else None

  def check_branch_exists(self, branch_name: str) -> bool:
    """
    Checks if a branch exists in the remote repository.

    Args:
        branch_name: The name of the branch to check.

    Returns:
        True if the branch exists, False otherwise.
    """
    endpoint = f"repos/{self.repo}/git/refs/heads/{branch_name}"
    try:
      # We use subprocess directly here instead of run_command to avoid
      # logging errors when the branch doesn't exist (which returns 404).
      subprocess.run(
        ["gh", "api", endpoint, "--silent"], check=True, capture_output=True
      )
      return True
    except subprocess.CalledProcessError:
      return False

  def create_branch(self, branch_name: str, sha: str) -> None:
    """
    Creates a new git branch (ref) from a specific SHA in the remote repository.

    Args:
        branch_name: The name of the new branch to create (e.g., 'my-feature-branch').
        sha: The commit SHA to base the new branch on.
    """
    endpoint = f"repos/{self.repo}/git/refs"
    cmd = ["api", endpoint, "-f", f"ref=refs/heads/{branch_name}", "-f", f"sha={sha}"]
    self._run_command(cmd)

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
    endpoint = f"repos/{self.repo}/git/refs/heads/{branch_name}"
    cmd = ["api", "--method", "DELETE", endpoint]
    self._run_command(cmd)

  def get_workflows(self) -> list[Workflow]:
    """
    Retrieves a list of workflows in the repository.

    Returns:
        A list of dictionaries, where each dictionary contains the 'name' and 'path' of a workflow.
    """
    cmd = ["workflow", "list", "--json", "path,name", "--repo", self.repo]
    workflows = self._run_command(cmd)
    return json.loads(workflows)

  def get_workflow(self, workflow_id: int | str) -> Workflow:
    """
    Retrieves details of a specific workflow by its ID or filename.

    Args:
        workflow_id: The ID or filename (e.g., 'main.yml') of the workflow.

    Returns:
        A dictionary containing workflow details (id, name, path, state, etc.).
    """
    endpoint = f"repos/{self.repo}/actions/workflows/{workflow_id}"
    cmd = ["api", endpoint]
    output = self._run_command(cmd)
    return json.loads(output)

  def get_run(self, run_id: str) -> Run:
    """
    Retrieves detailed information about a specific workflow run.

    Args:
        run_id: The unique database ID or number of the workflow run.

    Returns:
        A Run object containing metadata such as head SHA, status, and conclusion.
    """
    cmd = [
      "run",
      "view",
      run_id,
      "--json",
      "headSha,status,createdAt,conclusion,databaseId,url,workflowName,workflowDatabaseId,headBranch,event",
      "--repo",
      self.repo,
    ]
    run = self._run_command(cmd)
    return json.loads(run)

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
