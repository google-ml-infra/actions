# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Library for generating a GitHub Actions matrix from a benchmark registry."""

import os
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Any
from google.protobuf import text_format
from google.protobuf.json_format import MessageToDict
from protovalidate import validate, ValidationError
from benchmarking.proto import benchmark_registry_pb2
from benchmarking.proto import benchmark_job_pb2
from benchmarking.proto.common import workload_action_pb2
from benchmarking.proto.common import workflow_type_pb2


def _format_validation_error(violation) -> str:
  """Formats a single protovalidate violation into a human-readable string."""
  field_path_str = ".".join(
    f"{elem.field_name}[{elem.index}]" if elem.index else elem.field_name
    for elem in violation.proto.field.elements
  )
  return f"  - Field: {field_path_str}\n    Error: {violation.proto.message}"


def _get_workflow_type_from_gh_event(
  github_event: str,
) -> workflow_type_pb2.WorkflowType:
  """Maps a GitHub event name to internal WorkflowType.

  Args:
    github_event: The name of the GitHub event (e.g., 'pull_request', 'push').

  Returns:
    The corresponding WorkflowType value.

  Mapping Logic:
    - PRESUBMIT: pull_request, pull_request_target, merge_group
    - SCHEDULED: schedule
    - POSTSUBMIT: push, release
    - MANUAL: workflow_dispatch, repository_dispatch, and all other events.
  """
  if github_event in ("pull_request", "pull_request_target", "merge_group"):
    return workflow_type_pb2.WorkflowType.PRESUBMIT

  elif github_event == "schedule":
    return workflow_type_pb2.WorkflowType.SCHEDULED

  elif github_event in ("push", "release"):
    return workflow_type_pb2.WorkflowType.POSTSUBMIT

  elif github_event in ("workflow_dispatch", "repository_dispatch"):
    return workflow_type_pb2.WorkflowType.MANUAL

  # Default to MANUAL for all other events (e.g. issues, watch, etc.).
  else:
    return workflow_type_pb2.WorkflowType.MANUAL


def load_and_validate_suite_from_pbtxt(
  path: str,
) -> benchmark_registry_pb2.BenchmarkSuite:
  """Loads and validates the benchmark suite from a .pbtxt file."""
  if not os.path.isabs(path):
    workspace_dir = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if workspace_dir:
      path = os.path.join(workspace_dir, path)

  try:
    with open(path, "r") as f:
      suite = text_format.Parse(f.read(), benchmark_registry_pb2.BenchmarkSuite())
  except (FileNotFoundError, text_format.ParseError) as e:
    print(f"Error loading or parsing registry file '{path}': {e}", file=sys.stderr)
    sys.exit(1)

  try:
    validate(suite)
  except ValidationError as e:
    error_messages = "\n".join(_format_validation_error(v) for v in e.violations)
    raise ValueError(
      f"Error: Registry file '{path}' is invalid.\nValidation Errors:\n{error_messages}",
    )

  return suite


class MatrixGenerator:
  """Generates a GitHub Actions matrix from a benchmark registry."""

  def generate(
    self,
    suite: benchmark_registry_pb2.BenchmarkSuite,
    github_event: str,
    benchmark_filter: str = "",
    environment_filter: str = "",
    tag_filter: Sequence[str] | None = None,
    ab_mode: bool = False,
    baseline_ref: str = "",
    experiment_ref: str = "",
  ) -> Sequence[Mapping[str, Any]]:
    """Generates the full matrix using the BenchmarkJob proto to enforce strict validation.

    Args:
      suite: The parsed BenchmarkSuite proto containing all benchmark definitions.
      github_event: The name of the GitHub event triggering this run (e.g. 'pull_request', 'push').
        Used to infer the correct WorkflowType for the generated job.
      benchmark_filter: Regex pattern to filter by benchmark name (e.g. 'resnet.*').
        Defaults to empty string (no filtering).
      environment_filter: Regex pattern to filter by environment config ID (e.g. 'a100.*').
        Defaults to empty string (no filtering).
      tag_filter: A sequence of tags. A benchmark/environment must share at least one tag
        with this list to be included. Defaults to None (no filtering).
      ab_mode: If True, generates a pair of jobs (i.e. baseline and experiment) for each
        matching configuration. Defaults to False.
      baseline_ref: The git ref (branch/SHA) to check out for the baseline group.
        Only used if ab_mode is True. Defaults to empty string.
      experiment_ref: The git ref (branch/SHA) to check out for the experiment group.
        Only used if ab_mode is True. Defaults to empty string.

    Returns:
      A sequence of dictionaries, where each dictionary represents a validated
      BenchmarkJob suitable for JSON serialization into a GitHub Actions matrix.

    Selection Logic:
      - benchmark_filter: Matches against 'benchmark.name'.
      - environment_filter: Matches against 'environment_config.id'.
      - tag_filter: Requires intersection between requested tags and (benchmark tags + environment config tags).
      - If no filters are provided, all benchmarks are generated.
    """
    matrix = []

    # Determine the workflow type based on the GitHub event.
    workflow_type = _get_workflow_type_from_gh_event(github_event)

    # Pre-compile regex if provided.
    bench_pattern = re.compile(benchmark_filter) if benchmark_filter else None
    env_pattern = re.compile(environment_filter) if environment_filter else None

    # Normalize wanted tags to a set for fast lookup.
    wanted_tags = set(tag_filter) if tag_filter else set()

    for benchmark in suite.benchmarks:
      # Filter by benchmark name.
      if bench_pattern and not bench_pattern.search(benchmark.name):
        continue

      for env_config in benchmark.environment_configs:
        # Filter by environment ID.
        if env_pattern and not env_pattern.search(env_config.id):
          continue

        # Config ID (e.g., 'resnet50_basic_gpu') is constructed from the benchmark name
        # plus the specific environment ID.
        config_id = f"{benchmark.name}_{env_config.id}"

        # Merge global benchmark tags with environment config tags.
        # If wanted_tags is provided, we require an intersection.
        if wanted_tags:
          all_tags = set(benchmark.tags) | set(env_config.tags)
          if not (wanted_tags & all_tags):
            continue

        workload_action = workload_action_pb2.WorkloadAction()
        workload_action.CopyFrom(benchmark.workload)

        # Environment workload inputs overwrite/append base workload inputs
        for key, value in env_config.workload_action_inputs.items():
          workload_action.action_inputs[key] = value

        # Build the base BenchmarkJob proto
        base_job = benchmark_job_pb2.BenchmarkJob()
        base_job.config_id = config_id
        base_job.workflow_type = workflow_type
        base_job.environment_config.CopyFrom(env_config)
        base_job.benchmark_name = benchmark.name
        base_job.description = benchmark.description
        base_job.owner = benchmark.owner
        base_job.workload.CopyFrom(workload_action)
        base_job.github_labels.extend(benchmark.github_labels)
        base_job.metrics.extend(benchmark.metrics)

        jobs_to_emit = []

        if ab_mode:
          # Baseline job
          baseline_job = benchmark_job_pb2.BenchmarkJob()
          baseline_job.CopyFrom(base_job)
          baseline_job.ab_test_group = benchmark_job_pb2.AbTestGroup.BASELINE
          baseline_job.checkout_ref = baseline_ref
          jobs_to_emit.append(baseline_job)

          # Experiment job
          experiment_job = benchmark_job_pb2.BenchmarkJob()
          experiment_job.CopyFrom(base_job)
          experiment_job.ab_test_group = benchmark_job_pb2.AbTestGroup.EXPERIMENT
          experiment_job.checkout_ref = experiment_ref
          jobs_to_emit.append(experiment_job)
        else:
          # Standard mode (single job)
          jobs_to_emit.append(base_job)

        # Validate and append
        for job in jobs_to_emit:
          try:
            validate(job)
          except ValidationError as e:
            error_msg = _format_validation_error(e.violations[0])
            raise ValueError(
              f"Generated invalid benchmark job for '{job.config_id}':\n{error_msg}"
            )

          matrix.append(MessageToDict(job, preserving_proto_field_name=True))

    return matrix
