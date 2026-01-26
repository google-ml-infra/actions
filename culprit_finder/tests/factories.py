"""Factories for creating GitHub objects for testing."""

from datetime import datetime, timezone
import random
from typing import Optional

from github.Commit import Commit
from github.Workflow import Workflow
from github.WorkflowJob import WorkflowJob
from github.WorkflowRun import WorkflowRun


def create_run(
  mocker,
  head_sha: str,
  conclusion: Optional[str] = None,
  event: str = "push",
  status: str = "completed",
  run_id: Optional[int] = None,
  jobs: Optional[list[WorkflowJob]] = None,
) -> WorkflowRun:
  """Create a mock WorkflowRun object.

  Args:
    mocker: The pytest-mocker fixture.
    head_sha: The SHA of the head commit.
    conclusion: The conclusion of the run (e.g., "success", "failure").
    event: The event that triggered the run.
    status: The status of the run.
    run_id: The database ID of the run.
    jobs: The list of jobs for the run.

  Returns:
    A mock WorkflowRun object.
  """
  run = mocker.Mock(spec=WorkflowRun)
  run.workflow_id = random.randint(1000, 9999)
  run.head_branch = "main"
  run.event = event
  run.created_at = datetime.now(timezone.utc)
  run.head_sha = head_sha
  run.status = status
  run.conclusion = conclusion
  run.url = f"https://github.com/owner/repo/actions/runs/{run.workflow_id}"
  run.id = run_id or random.randint(1000, 9999)
  run.jobs.return_value = jobs or []
  return run


def create_commit(mocker, sha: str, message: str) -> Commit:
  """Create a mock Commit object.

  Args:
    mocker: The pytest-mocker fixture.
    sha: The SHA of the commit.
    message: The commit message.

  Returns:
    A mock Commit object.
  """
  commit = mocker.Mock(spec=Commit)
  commit.sha = sha
  commit.commit = mocker.Mock()
  commit.commit.message = message
  return commit


def create_workflow(mocker, name: str, path: str) -> Workflow:
  """Create a mock Workflow object.

  Args:
    mocker: The pytest-mocker fixture.
    name: The name of the workflow.
    path: The path to the workflow file.

  Returns:
    A mock Workflow object.
  """
  workflow = mocker.Mock(spec=Workflow)
  workflow.id = random.randint(1000, 9999)
  workflow.name = name
  workflow.path = path
  return workflow


def create_job(
  mocker, name: str, conclusion: str, job_id: Optional[int] = None
) -> WorkflowJob:
  """Create a mock WorkflowJob object.

  Args:
    mocker: The pytest-mocker fixture.
    name: The name of the job.
    conclusion: The conclusion of the job.
    job_id: The database ID of the job.

  Returns:
    A mock WorkflowJob object.
  """
  job = mocker.Mock(spec=WorkflowJob)
  job.name = name
  job.conclusion = conclusion
  job.status = "completed"
  job.id = job_id or random.randint(1000, 9999)
  return job
