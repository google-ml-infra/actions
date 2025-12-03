"""
Core logic for detecting regression commits using binary search.

This module defines the `CulpritFinder` class, which orchestrates the bisection process.
"""

import time
import logging
from culprit_finder import github


CULPRIT_FINDER_WORKFLOW_NAME = "culprit_finder.yml"


class CulpritFinder:
  """Culprit finder class to find the culprit commit for a GitHub workflow."""

  def __init__(
    self,
    repo: str,
    start_sha: str,
    end_sha: str,
    workflow_file: str,
    has_culprit_finder_workflow: bool,
  ):
    """
    Initializes the CulpritFinder instance.

    Args:
        repo: The GitHub repository in 'owner/repo' format.
        start_sha: The SHA of the last known good commit.
        end_sha: The SHA of the first known bad commit.
        workflow_file: The name of the workflow file to test (e.g., 'build.yml').
        has_culprit_finder_workflow: Whether the repo being tested has a Culprit Finder workflow.
    """
    self._repo = repo
    self._start_sha = start_sha
    self._end_sha = end_sha
    self._culprit_finder_workflow_file = CULPRIT_FINDER_WORKFLOW_NAME
    self._workflow_file = workflow_file
    self._has_culprit_finder_workflow = has_culprit_finder_workflow

  def _wait_for_workflow_completion(
    self,
    workflow_file: str,
    branch_name: str,
    commit_sha: str,
    previous_run_id: int | None,
    poll_interval=30,
  ) -> github.Run | None:
    """
    Polls for the completion of the most recent workflow_dispatch run on the branch.

    Args:
        workflow_file: The filename of the workflow to poll.
        branch_name: The name of the branch where the workflow is running.
        previous_run_id: The ID of the latest run before triggering (to distinguish the new run).
        commit_sha: The commit SHA associated with the workflow run.
        poll_interval: Time to wait between polling attempts (in seconds).

    Returns:
        A dictionary containing workflow run details if successful and completed
    """
    while True:
      latest_run = github.get_latest_run(workflow_file, branch_name)

      if not latest_run:
        logging.info(
          "No workflow runs found yet for branch %s, waiting...",
          branch_name,
        )
        time.sleep(poll_interval)
        continue

      if previous_run_id and latest_run["databaseId"] == previous_run_id:
        logging.info(
          "Waiting for new workflow run to appear...",
        )
        time.sleep(poll_interval)
        continue

      if latest_run["status"] == "completed":
        return latest_run

      logging.info(
        "Run for %s on branch %s is still in progress (%s)...",
        commit_sha,
        branch_name,
        latest_run["status"],
      )

      time.sleep(poll_interval)

  def _test_commit(
    self,
    commit_sha: str,
    branch_name: str,
  ) -> bool:
    """
    Tests a commit by triggering a GitHub workflow on it.

    Args:
        commit_sha: The SHA of the commit to test.
        branch_name: The name of the temporary branch created for testing.

    Returns:
        True if the workflow completes successfully, False otherwise.
    """
    logging.info("Testing commit %s on branch %s", commit_sha, branch_name)

    if self._has_culprit_finder_workflow:
      workflow_to_trigger = self._culprit_finder_workflow_file
      inputs = {"workflow-to-debug": self._workflow_file}
    else:
      workflow_to_trigger = self._workflow_file
      inputs = {}

    logging.info(
      "Triggering workflow %s on %s",
      workflow_to_trigger,
      branch_name,
    )

    # Get the ID of the previous run (if any) to distinguish it from the new one we are about to trigger
    previous_run = github.get_latest_run(workflow_to_trigger, branch_name)
    previous_run_id = previous_run["databaseId"] if previous_run else None

    github.trigger_workflow(
      workflow_to_trigger,
      branch_name,
      inputs,
    )

    run = self._wait_for_workflow_completion(
      workflow_to_trigger,
      branch_name,
      commit_sha,
      previous_run_id,
    )
    if not run:
      logging.error("Workflow failed to complete")
      return False

    return run["conclusion"] == "success"

  def run_bisection(self) -> github.Commit | None:
    """
    Runs bisection logic (binary search) to find the culprit commit for a GitHub workflow.

    This method iteratively:
    1. Picks a midpoint commit between the known good and bad states.
    2. Creates a temporary branch for that commit.
    3. Triggers the workflow.
    4. Narrows down the range of commits based on the workflow result (success/failure).

    Returns:
      github.Commit | None: The commit identified through the bisection process
      as the cause of the specified issue. If the bisection process does not
      identify a commit, None is returned.
    """
    commits = github.compare_commits(self._repo, self._start_sha, self._end_sha)
    if not commits:
      logging.info("No commits found between %s and %s", self._start_sha, self._end_sha)
      return None

    # Initially, start_sha is good, which is before commits[0], so -1
    good_idx = -1
    bad_idx = len(commits)

    while bad_idx - good_idx > 1:
      mid_idx = (good_idx + bad_idx) // 2

      commit_sha = commits[mid_idx]["sha"]
      branch_name = f"culprit-finder/test-{commit_sha}"

      # Ensure the branch does not exist from a previous run
      if not github.check_branch_exists(self._repo, branch_name):
        github.create_branch(self._repo, branch_name, commit_sha)
        logging.info("Created branch %s", branch_name)

      try:
        is_good = self._test_commit(commit_sha, branch_name)
      finally:
        if github.check_branch_exists(self._repo, branch_name):
          logging.info("Deleting branch %s", branch_name)
          github.gh_delete_branch(self._repo, branch_name)

      if is_good:
        good_idx = mid_idx
        logging.info("Commit %s is good", commit_sha)
      else:
        bad_idx = mid_idx
        logging.info("Commit %s is bad", commit_sha)

    if bad_idx == len(commits):
      return None

    return commits[bad_idx]
