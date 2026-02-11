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

# Configuration for projects that require special handling for external dependencies.
# Some projects (e.g., JAX) depend on the HEAD of another repository (e.g., XLA).
# When bisecting historical commits, running them against the *current* HEAD of the dependency
# often causes build failures unrelated to the regression being investigated.
#
# This map defines how to "time-travel" for these dependencies:
# - dependency_repo: The external repository to look up.
# - input_name: The workflow input variable to set with the pinned commit hash.
# - workflows: The specific workflows where this logic should apply.
PROJECT_CONFIG = {
    "jax-ml/jax": {
        "dependency_repo": "openxla/xla",
        "input_name": "xla-commit",
        "workflows": ["wheel_tests_continuous.yml", "build_artifacts.yml"],
    },
    "google-ml-infra/jax-fork": {
        "dependency_repo": "openxla/xla",
        "input_name": "xla-commit",
        "workflows": ["wheel_tests_continuous.yml", "build_artifacts.yml"],
    },
}


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
    use_cache: bool = True,
    retries: int = 0,
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
        use_cache: Whether to use the cached results from previous runs. Defaults to True.
        retries: Number of times to retry workflow runs in case of failure.
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
    self._use_cache = use_cache
    self._retries = retries

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
        workflow_id=workflow_file, branch=branch_name, event="workflow_dispatch"
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

  def _get_target_job(
    self, jobs: list[WorkflowJob], invoked_from_another_workflow: bool
  ) -> WorkflowJob:
    """
    Finds a specific job in the list, handling nested caller/called names.

    Args:
        jobs: A list of Job objects from a workflow run.
        invoked_from_another_workflow: Whether the workflow was invoked from another workflow.

    Returns:
        The Job object that matches the target job name.

    Raises:
        ValueError: If the specified job is not found in the workflow run.
    """

    def get_job_name(name: str) -> str:
      if invoked_from_another_workflow:
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

    run: WorkflowRun | None = None
    for attempt in range(self._retries + 1):
      # Get the ID of the previous run (if any) to distinguish it from the new one we are about to trigger
      previous_run = self._gh_client.get_latest_run(
        workflow_id=workflow_to_trigger, branch=branch_name, event="workflow_dispatch"
      )
      previous_run_id = previous_run.id if previous_run else None

      if self._repo in PROJECT_CONFIG and self._workflow_file in PROJECT_CONFIG[self._repo]["workflows"]:
          config = PROJECT_CONFIG[self._repo]
          logging.info("Project %s matched special case config", self._repo)

          # Get date of the commit we are testing
          commit_details = self._gh_client.get_commit(commit_sha)
          # PyGithub returns naive datetime objects in UTC.
          # get_last_commit_before's `until` parameter natively handles this datetime object.
          commit_date = commit_details.commit.committer.date

          # Find dependency commit at that time
          dep_repo = config["dependency_repo"]
          logging.info("Looking up dependency commit for %s at %s", dep_repo, commit_date)
          dep_commit = self._gh_client.get_last_commit_before(dep_repo, commit_date)

          if dep_commit:
              input_name = config["input_name"]
              logging.info("Pinning %s to %s", input_name, dep_commit.sha)
              inputs[input_name] = dep_commit.sha
          else:
              logging.warning("Could not find matching commit for %s at %s", dep_repo, commit_date)

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

      if run and run.conclusion == "success":
        return True

      if run and run.conclusion == "skipped" and self._has_culprit_finder_workflow:
        raise ValueError(
          f"Bisection stopped: The culprit finder workflow was skipped while testing '{self._workflow_file}'.\n"
          f"Please ensure that 'culprit_finder.yml' is configured to trigger on '{self._workflow_file}' "
          f"and that all required permissions are set."
        )

      if run and self._job:
        jobs = self._gh_client.get_run_jobs(run.id)
        target_job = self._get_target_job(jobs, self._has_culprit_finder_workflow)
        if target_job.conclusion == "success":
          return True

      if attempt < self._retries:
        logging.info(
          "Retrying workflow for commit %s (attempt %d/%d)",
          commit_sha,
          attempt + 1,
          self._retries,
        )

    if not run:
      logging.error("Workflow failed to complete for commit %s", commit_sha)
      return False

    return run.conclusion == "success"

  def _check_existing_run(self, commit_sha: str) -> bool | None:
    """
    Checks for an existing workflow run for the commit.

    Args:
        commit_sha: The SHA of the commit to check for existing runs.

    Returns:
        True if a successful run is found, False if a failed run is found,
        or None if no completed run exists.
    """
    previous_run = self._gh_client.get_latest_run(
      workflow_id=self._workflow_file, commit=commit_sha, status="completed"
    )
    if previous_run:
      logging.info(
        "Found result from previous run for commit %s, skipping test", commit_sha
      )
      if self._job:
        jobs = self._gh_client.get_run_jobs(previous_run.id)
        target_job = self._get_target_job(jobs, False)
        return target_job.conclusion == "success"
      return previous_run.conclusion == "success"
    return None

  def _execute_test_with_branch(self, commit_sha: str) -> bool:
    """
    Creates a branch, runs the test, and cleans up.

    Args:
        commit_sha: The SHA of the commit to be tested.

    Returns:
        True if the test passed, False otherwise.
    """
    branch_name = f"culprit-finder/test-{commit_sha}_{uuid.uuid4()}"

    # Ensure the branch does not exist from a previous run
    if not self._gh_client.check_branch_exists(branch_name):
      self._gh_client.create_branch(branch_name, commit_sha)
      logging.info("Created branch %s", branch_name)
      self._gh_client.wait_for_branch_creation(branch_name, timeout=180)

    try:
      return self._test_commit(commit_sha, branch_name)
    finally:
      if self._gh_client.check_branch_exists(branch_name):
        logging.info("Deleting branch %s", branch_name)
        self._gh_client.delete_branch(branch_name)

  def _update_state(self, commit_sha: str, is_good: bool) -> None:
    """
    Updates the state and persists it.

    Args:
        commit_sha: The SHA of the commit that was tested.
        is_good: Whether the commit was identified as good (True) or bad (False).
    """
    if is_good:
      self._state["current_good"] = commit_sha
      self._state["cache"][commit_sha] = "PASS"
    else:
      self._state["current_bad"] = commit_sha
      self._state["cache"][commit_sha] = "FAIL"
    self._state_persister.save(self._state)

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
      is_good = None
      is_cached = False

      if commit_sha in self._state["cache"]:
        logging.info("Using cached result for commit %s", commit_sha)
        is_good = self._state["cache"][commit_sha] == "PASS"
        is_cached = True

      if is_good is None and self._use_cache:
        is_good = self._check_existing_run(commit_sha)

      if is_good is None:
        is_good = self._execute_test_with_branch(commit_sha)

      if is_good:
        good_idx = mid_idx
        logging.info("Commit %s is good", commit_sha)
      else:
        bad_idx = mid_idx
        logging.info("Commit %s is bad", commit_sha)

      if not is_cached:
        self._update_state(commit_sha, is_good)

    if bad_idx == len(commits):
      return None

    return commits[bad_idx]
