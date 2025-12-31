"""
Command-line interface for the Culprit Finder tool.

This module acts as the entry point for the application, handling argument parsing, input validation,
and authentication checks. It initializes the `CulpritFinder` with user-provided parameters
(repository, commit range, workflow) and reports the identified culprit commit or the lack thereof.
"""

import argparse
import logging
import sys
import re

from culprit_finder import culprit_finder
from culprit_finder import culprit_finder_state
from culprit_finder import github_client

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
    "-j",
    "--job",
    required=False,
    help="The specific job name within the workflow to monitor for pass/fail",
  )
  parser.add_argument(
    "--clear-cache",
    action="store_true",
    help="Deletes the local state file before execution",
  )
  parser.add_argument(
    "--no-cache",
    action="store_true",
    help="Disabled cached results. This will run the workflow on all commits.",
  )
  parser.add_argument(
    "--retry",
    required=False,
    help="Number of times to retry the workflow run if it fails (default: 0).",
    default=0,
    type=int,
  )
  parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Simulates the bisection process by printing the API calls that would be made without actually executing them",
  )

  args = parser.parse_args()

  repo: str | None = args.repo
  start: str | None = args.start
  end: str | None = args.end
  workflow_file_name: str | None = args.workflow
  job_name: str | None = args.job

  if args.url:
    repo = _get_repo_from_url(args.url)

  if not repo:
    parser.error(
      "the following arguments are required: -r/--repo (or provided via URL)"
    )

  token = github_client.get_github_token()
  if token is None:
    logging.error("Not authenticated with GitHub CLI or GH_TOKEN env var is not set.")
    sys.exit(1)

  real_client = github_client.GithubClient(repo=repo, token=token)

  if args.url:
    run, job_details = real_client.get_run_and_job_from_url(args.url)
    if run.conclusion != "failure":
      raise ValueError("The provided URL does not point to a failed workflow run.")

    if not start:
      if job_details:
        previous_run = real_client.find_previous_successful_job_run(
          run, job_details.name
        )
      else:
        previous_run = real_client.find_previous_successful_run(run)
      start = previous_run.head_sha
    end = run.head_sha

    workflow_details = real_client.get_workflow(run.workflow_id)
    workflow_file_name = workflow_details.path.split("/")[-1]
    if job_details:
      job_name = job_details.name

  gh_client = (
    github_client.DryRunGithubClient(real_client, job_name=job_name)
    if args.dry_run
    else real_client
  )

  if not start:
    parser.error("the following arguments are required: -s/--start")
  if not end:
    parser.error("the following arguments are required: -e/--end")
  if not workflow_file_name:
    parser.error("the following arguments are required: -w/--workflow")

  use_cache = not args.no_cache

  logging.info("Initializing culprit finder for %s", repo)
  logging.info("Start commit: %s", start)
  logging.info("End commit: %s", end)
  logging.info("Workflow: %s", workflow_file_name)
  logging.info("Job: %s", job_name)
  logging.info("Use cache: %s", use_cache)
  logging.info("Retries: %s", args.retry)

  state_persister = culprit_finder_state.StatePersister(
    repo=repo, workflow=workflow_file_name, job=job_name
  )

  if args.clear_cache and state_persister.exists():
    state_persister.delete()

  state: culprit_finder_state.CulpritFinderState = {
    "repo": repo,
    "workflow": workflow_file_name,
    "original_start": start,
    "job": job_name,
    "original_end": end,
    "current_good": "",
    "current_bad": "",
    "cache": {},
  }
  if state_persister.exists():
    print("\nA previous bisection state was found.")
    resume = input("Do you want to resume from the saved state? (y/n): ").lower()
    if resume not in ["y", "yes"]:
      print("Starting a new bisection. Deleting the old state...")
      state_persister.delete()
      state = {
        "repo": repo,
        "workflow": workflow_file_name,
        "original_start": start,
        "original_end": end,
        "current_good": "",
        "current_bad": "",
        "job": job_name,
        "cache": {},
      }
    else:
      state = state_persister.load()
      print("Resuming from the saved state.")

  has_culprit_finder_workflow = any(
    wf.path == ".github/workflows/culprit_finder.yml"
    for wf in gh_client.get_workflows()
  )

  logging.info("Using culprit finder workflow: %s", has_culprit_finder_workflow)

  finder = culprit_finder.CulpritFinder(
    repo=repo,
    start_sha=start,
    end_sha=end,
    workflow_file=workflow_file_name,
    has_culprit_finder_workflow=has_culprit_finder_workflow,
    gh_client=gh_client,
    state=state,
    state_persister=state_persister,
    job=job_name,
    use_cache=use_cache,
    retries=args.retry,
  )

  try:
    culprit_commit = finder.run_bisection()
    if not args.dry_run:
      if culprit_commit:
        commit_message = culprit_commit.commit.message.splitlines()[0]
        print(
          f"\nThe culprit commit is: {commit_message} (SHA: {culprit_commit.sha})",
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
