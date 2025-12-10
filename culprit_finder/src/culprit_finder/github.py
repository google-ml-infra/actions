"""
Module for interacting with the GitHub API via the gh CLI.
"""

import subprocess
import json
import logging
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
  """

  headSha: str
  status: str
  createdAt: str
  conclusion: Optional[str]
  databaseId: int
  url: str


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

  def get_latest_run(self, workflow_file: str, branch: str) -> Run | None:
    """
    Gets the latest workflow run for a specific branch and workflow.

    Args:
        workflow_file: The filename or ID of the workflow to query.
        branch: The git branch reference to filter runs by.

    Returns:
        A dictionary representing the latest workflow run object (containing fields like
        headSha, status, conclusion, etc.), or None if no runs are found.
    """
    fields = "headSha,status,createdAt,conclusion,databaseId,url"
    cmd = [
      "run",
      "list",
      "--workflow",
      workflow_file,
      "--branch",
      branch,
      "--event",
      "workflow_dispatch",
      "--limit",
      "1",
      "--json",
      fields,
      "--repo",
      self.repo,
    ]

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
