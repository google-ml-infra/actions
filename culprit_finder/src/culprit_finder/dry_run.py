"""Utilities for dry run mode of culprit-finder."""

import math
from typing import Optional


class DryRunHalt(Exception):
  """Raised by CulpritFinder when the first write operation is reached.

  Carries the branch name and commit SHA that would have been used, allowing
  the caller to print a summary of what would happen next.
  """

  def __init__(self, branch_name: str, commit_sha: str):
    self.branch_name = branch_name
    self.commit_sha = commit_sha


def print_dry_run_summary(
  repo: str,
  start: str,
  end: str,
  workflow_file_name: str,
  job_name: Optional[str],
  halt: DryRunHalt,
  commits: list,
  workflows: list,
) -> None:
  """Prints a dry-run summary showing validated configuration and the bisection plan.

  Args:
      repo: The GitHub repository in 'owner/repo' format.
      start: The SHA of the last known good commit.
      end: The SHA of the first known bad commit.
      workflow_file_name: The name of the workflow file to test.
      job_name: The specific job name within the workflow (if provided).
      halt: The DryRunHalt exception containing the midpoint branch and commit.
      commits: The list of commits in the bisection range.
      workflows: The list of workflows available in the repository.
  """
  workflow_found = any(
    wf.path.endswith(f"/{workflow_file_name}") or wf.path == workflow_file_name
    for wf in workflows
  )
  workflow_status = "[found]" if workflow_found else "[not found]"

  print("\nDRY RUN: Configuration")
  print(f"  Repository:   {repo}")
  print(f"  Workflow:     {workflow_file_name} {workflow_status}")
  print(f"  Start (good): {start}")
  print(f"  End (bad):    {end}")
  if job_name:
    print(f"  Job:          {job_name}")

  commit_count = len(commits)
  print(f"\nDRY RUN: Found {commit_count} commit(s) in range.")

  mid_commit = next((c for c in commits if c.sha == halt.commit_sha), None)
  if mid_commit:
    message = mid_commit.commit.message.splitlines()[0]
    print(f"DRY RUN: Bisection midpoint: {halt.commit_sha} — {message!r}")
  else:
    print(f"DRY RUN: Bisection midpoint: {halt.commit_sha}")

  remaining_iterations = math.ceil(math.log2(commit_count)) if commit_count > 1 else 1
  print("\nDRY RUN: Next step would be:")
  print(f"  1. Create branch '{halt.branch_name}' at {halt.commit_sha}")
  print(f"  2. Trigger workflow '{workflow_file_name}' on that branch")
  print(
    f"  3. Poll for result, narrow range, and repeat (~{remaining_iterations} iteration(s) total for {commit_count} commits)"
  )
