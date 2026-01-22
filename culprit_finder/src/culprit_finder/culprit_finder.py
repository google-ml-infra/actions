"""
Core logic for detecting regression commits using binary search.

This module defines the `CulpritFinder` class, which orchestrates the bisection process.
"""

import time
import logging
import uuid

from github.Commit import Commit
from github.WorkflowRun import WorkflowRun
from github.WorkflowJob import WorkflowJob

from culprit_finder import github_client
from culprit_finder import culprit_finder_state


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
    gh_client: github_client.GithubClient,
    state: culprit_finder_state.CulpritFinderState,
    state_persister: culprit_finder_state.StatePersister,
    job: str | None = None,
  ):
    """
    Initializes the CulpritFinder instance.

    Args:
        repo: The GitHub repository in 'owner/repo' format.
        start_sha: The SHA of the last known good commit.
        end_sha: The SHA of the first known bad commit.
        workflow_file: The name of the workflow file to test (e.g., 'build.yml').
        has_culprit_finder_workflow: Whether the repo being tested has a Culprit Finder workflow.
        gh_client: The GithubClient instance used to interact with GitHub.
        state: The CulpritFinderState object containing the current bisection state.
        state_persister: The StatePersister object used to save the bisection state.
        job: The specific job name within the workflow to monitor for pass/fail.
    """
    self._repo = repo
    self._start_sha = start_sha
    self._end_sha = end_sha
    self._culprit_finder_workflow_file = CULPRIT_FINDER_WORKFLOW_NAME
    self._workflow_file = workflow_file
    self._has_culprit_finder_workflow = has_culprit_finder_workflow
    self._gh_client = gh_client
    self._state = state
    self._state_persister = state_persister
    self._job = job

  def _wait_for_workflow_completion(
    self,
    workflow_file: str,
    branch_name: str,
    commit_sha: str,
    previous_run_id: int | None,
    poll_interval=30,
    timeout=7200,  # 2 hours
  ) -> WorkflowRun | None:
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
    start_time = time.time()
    while time.time() - start_time < timeout:
      latest_run = self._gh_client.get_latest_run(
        workflow_file, branch_name, event="workflow_dispatch"
      )

      if not latest_run:
        logging.info(
          "No workflow runs found yet for branch %s, waiting...",
          branch_name,
        )
        time.sleep(poll_interval)
        continue

      if previous_run_id and latest_run.id == previous_run_id:
        logging.info(
          "Waiting for new workflow run to appear...",
        )
        time.sleep(poll_interval)
        continue

      if latest_run.status == "completed":
        return latest_run

      logging.info(
        "Run for %s on branch %s is still in progress (%s)...",
        commit_sha,
        branch_name,
        latest_run.status,
      )

      time.sleep(poll_interval)
    raise TimeoutError("Timed out waiting for workflow to complete")

  def _get_target_job(self, jobs: list[WorkflowJob]) -> WorkflowJob:
    """
    Finds a specific job in the list, handling nested caller/called names.

    Args:
        jobs: A list of Job objects from a workflow run.

    Returns:
        The Job object that matches the target job name.

    Raises:
        ValueError: If the specified job is not found in the workflow run.
    """

    def get_job_name(name: str) -> str:
      if self._has_culprit_finder_workflow:
        # when calling a workflow from another workflow, the job name is
        # in the format "Caller Job Name / Called Job Name"
        return name.split("/", 1)[-1].strip()
      return name

    target_job = next(
      (job for job in jobs if get_job_name(job.name) == self._job), None
    )
    if target_job:
      return target_job

    logging.error(
      "Job %s not found, jobs in workflow %s",
      self._job,
      self._workflow_file,
    )
    raise ValueError(f"Job {self._job} not found in workflow {self._workflow_file}")

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
    previous_run = self._gh_client.get_latest_run(
      workflow_to_trigger, branch_name, event="workflow_dispatch"
    )
    previous_run_id = previous_run.id if previous_run else None

    self._gh_client.trigger_workflow(
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

    if run.conclusion == "skipped" and self._has_culprit_finder_workflow:
      raise ValueError(
        f"Bisection stopped: The culprit finder workflow was skipped while testing '{self._workflow_file}'.\n"
        f"Please ensure that 'culprit_finder.yml' is configured to trigger on '{self._workflow_file}' "
        f"and that all required permissions are set."
      )

    if self._job:
      jobs = self._gh_client.get_run_jobs(run.id)
      target_job = self._get_target_job(jobs)
      return target_job.conclusion == "success"

    return run.conclusion == "success"

  def run_bisection(self) -> Commit | None:
    """
    Runs bisection logic (binary search) to find the culprit commit for a GitHub workflow.

    This method iteratively:
    1. Picks a midpoint commit between the known good and bad states.
    2. Creates a temporary branch for that commit.
    3. Triggers the workflow.
    4. Narrows down the range of commits based on the workflow result (success/failure).

    Returns:
      Commit | None: The commit identified through the bisection process
      as the cause of the specified issue. If the bisection process does not
      identify a commit, None is returned.
    """
    commits = self._gh_client.compare_commits(self._start_sha, self._end_sha)
    if not commits:
      logging.info("No commits found between %s and %s", self._start_sha, self._end_sha)
      return None

    # Initially, start_sha is good, which is before commits[0], so -1
    good_idx = -1
    bad_idx = len(commits)

    while bad_idx - good_idx > 1:
      mid_idx = (good_idx + bad_idx) // 2
      commit_sha = commits[mid_idx].sha

      if commit_sha in self._state["cache"]:
        logging.info("Using cached result for commit %s", commit_sha)
        is_good = self._state["cache"][commit_sha] == "PASS"

        if is_good:
          good_idx = mid_idx
          logging.info("Commit %s is good", commit_sha)
        else:
          bad_idx = mid_idx
          logging.info("Commit %s is bad", commit_sha)

        continue

      branch_name = f"culprit-finder/test-{commit_sha}_{uuid.uuid4()}"

      # Ensure the branch does not exist from a previous run
      if not self._gh_client.check_branch_exists(branch_name):
        self._gh_client.create_branch(branch_name, commit_sha)
        logging.info("Created branch %s", branch_name)
        self._gh_client.wait_for_branch_creation(branch_name, timeout=180)

      try:
        is_good = self._test_commit(commit_sha, branch_name)
      finally:
        if self._gh_client.check_branch_exists(branch_name):
          logging.info("Deleting branch %s", branch_name)
          self._gh_client.delete_branch(branch_name)

      if is_good:
        good_idx = mid_idx
        self._state["current_good"] = commit_sha
        self._state["cache"][commit_sha] = "PASS"
        logging.info("Commit %s is good", commit_sha)
      else:
        bad_idx = mid_idx
        self._state["current_bad"] = commit_sha
        self._state["cache"][commit_sha] = "FAIL"
        logging.info("Commit %s is bad", commit_sha)

      self._state_persister.save(self._state)

    if bad_idx == len(commits):
      return None

    return commits[bad_idx]
