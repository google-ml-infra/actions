"""
Command-line interface for the Culprit Finder tool.

This module acts as the entry point for the application, handling argument parsing, input validation,
and authentication checks. It initializes the `CulpritFinder` with user-provided parameters
(repository, commit range, workflow) and reports the identified culprit commit or the lack thereof.
"""

import argparse
import logging
import os
import sys
import re

from culprit_finder import culprit_finder
from culprit_finder import culprit_finder_state
from culprit_finder import github

logging.basicConfig(
  level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def _validate_repo(repo: str) -> str:
  parts = repo.split("/")
  if len(parts) != 2 or not all(parts):
    raise argparse.ArgumentTypeError(f"Invalid repo format: {repo}")

  return repo


def _get_repo_from_url(url: str) -> str:
  match = re.search(r"github\.com/([^/]+/[^/]+)", url)
  if not match:
    raise ValueError(f"Could not extract repo from URL: {url}")
  return match.group(1)


def _get_start_commit(failed_run: github.Run, gh_client: github.GithubClient) -> str:
  """
  Finds the last successful run for the given failed run, considering the same event type and branch.
  If no successful run is found, falls back to the last successful 'push' event.

  Returns:
    The SHA of the last successful commit, or None if no successful run is found.

  Raises:
    ValueError: If no successful run is found.
  """
  # Try to find a successful run with the same event type first.
  # This ensures we are comparing runs with similar contexts (e.g., Pull Request vs Push),
  # minimizing false positives caused by differences in merge commits or environment specifics.
  last_successful_run = gh_client.get_latest_run(
    failed_run["workflowDatabaseId"],
    failed_run["headBranch"],
    failed_run["event"],
    created=f"<{failed_run['createdAt']}",
    status="success",
  )

  # Fallback: If strict matching failed, try to find the last successful 'push' event.
  if not last_successful_run and failed_run["event"] != "push":
    logging.info(
      "No successful run found for event '%s'. Falling back to 'push' event.",
      failed_run["event"],
    )
    last_successful_run = gh_client.get_latest_run(
      failed_run["workflowDatabaseId"],
      failed_run["headBranch"],
      event="push",
      created=f"<{failed_run['createdAt']}",
      status="success",
    )

  if not last_successful_run:
    raise ValueError(
      f"No previous successful run found for workflow '{failed_run['workflowName']}' on branch {failed_run['headBranch']}"
    )

  return last_successful_run["headSha"]


def main() -> None:
  """
  Entry point for the culprit finder CLI.

  Parses command-line arguments then initiates the bisection process using CulpritFinder.
  """
  parser = argparse.ArgumentParser(description="Culprit finder for GitHub Actions.")
  parser.add_argument("url", nargs="?", help="GitHub Actions Run URL")
  parser.add_argument(
    "-r",
    "--repo",
    help="Target GitHub repository (e.g., owner/repo)",
    type=_validate_repo,
  )
  parser.add_argument("-s", "--start", help="Last known good commit SHA")
  parser.add_argument("-e", "--end", help="First known bad commit SHA")
  parser.add_argument(
    "-w",
    "--workflow",
    help="Workflow filename (e.g., build_and_test.yml)",
  )
  parser.add_argument(
    "--clear-cache",
    action="store_true",
    help="Deletes the local state file before execution",
  )

  args = parser.parse_args()

  repo: str | None = args.repo
  start: str | None = args.start
  end: str | None = args.end
  workflow_file_name: str | None = args.workflow

  if args.url:
    repo = _get_repo_from_url(args.url)

  if not repo:
    parser.error(
      "the following arguments are required: -r/--repo (or provided via URL)"
    )

  gh_client = github.GithubClient(repo=repo)

  is_authenticated_with_cli = gh_client.check_auth_status()
  has_access_token = os.environ.get("GH_TOKEN") is not None

  if not is_authenticated_with_cli and not has_access_token:
    logging.error("Not authenticated with GitHub CLI or GH_TOKEN env var is not set.")
    sys.exit(1)

  if args.url:
    run = gh_client.get_run_from_url(args.url)
    if run["conclusion"] != "failure":
      raise ValueError("The provided URL does not point to a failed workflow run.")

    if not start:
      start = _get_start_commit(run, gh_client)
    end = run["headSha"]

    workflow_details = gh_client.get_workflow(run["workflowDatabaseId"])
    workflow_file_name = workflow_details["path"].split("/")[-1]

  if not start:
    parser.error("the following arguments are required: -s/--start")
  if not end:
    parser.error("the following arguments are required: -e/--end")
  if not workflow_file_name:
    parser.error("the following arguments are required: -w/--workflow")

  logging.info("Initializing culprit finder for %s", repo)
  logging.info("Start commit: %s", start)
  logging.info("End commit: %s", end)
  logging.info("Workflow: %s", workflow_file_name)

  state_persister = culprit_finder_state.StatePersister(
    repo=repo, workflow=workflow_file_name
  )

  if args.clear_cache and state_persister.exists():
    state_persister.delete()

  if state_persister.exists():
    print("\nA previous bisection state was found.")
    resume = input("Do you want to resume from the saved state? (y/n): ").lower()
    if resume not in ["y", "yes"]:
      print("Starting a new bisection. Deleting the old state...")
      state_persister.delete()
      state: culprit_finder_state.CulpritFinderState = {
        "repo": repo,
        "workflow": workflow_file_name,
        "original_start": start,
        "original_end": end,
        "current_good": "",
        "current_bad": "",
        "cache": {},
      }
    else:
      state = state_persister.load()
      print("Resuming from the saved state.")
  else:
    state: culprit_finder_state.CulpritFinderState = {
      "repo": repo,
      "workflow": workflow_file_name,
      "original_start": start,
      "original_end": end,
      "current_good": "",
      "current_bad": "",
      "cache": {},
    }

  has_culprit_finder_workflow = any(
    wf["path"] == ".github/workflows/culprit_finder.yml"
    for wf in gh_client.get_workflows()
  )

  logging.info("Using culprit finder workflow: %s", has_culprit_finder_workflow)

  finder = culprit_finder.CulpritFinder(
    repo=repo,
    start_sha=start,
    end_sha=end,
    workflow_file=workflow_file_name,
    has_culprit_finder_workflow=has_culprit_finder_workflow,
    github_client=gh_client,
    state=state,
    state_persister=state_persister,
  )

  try:
    culprit_commit = finder.run_bisection()
    if culprit_commit:
      commit_message = culprit_commit["message"].splitlines()[0]
      print(
        f"\nThe culprit commit is: {commit_message} (SHA: {culprit_commit['sha']})",
      )
    else:
      print("No culprit commit found.")

    state_persister.delete()
  except KeyboardInterrupt:
    logging.info("Bisection interrupted by user (CTRL+C). Saving current state...")
    state_persister.save(state)
    logging.info("State saved.")


if __name__ == "__main__":
  main()
