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
    suite,
    workflow_type_str: str,
    ab_mode: bool = False,
    baseline_ref: str = "main",
    experiment_ref: str = "",
  ) -> Sequence[Mapping[str, Any]]:
    """Generates the full matrix using the BenchmarkJob proto to enforce strict validation."""
    matrix = []
    workflow_enum = workflow_type_pb2.WorkflowType.Value(workflow_type_str.upper())

    for benchmark in suite.benchmarks:
      for env_config in benchmark.environment_configs:
        if workflow_enum not in env_config.workflow_type:
          continue

        workload_action = workload_action_pb2.WorkloadAction()
        workload_action.CopyFrom(benchmark.workload)

        # Environment workload inputs overwrite/append base workload inputs
        for key, value in env_config.workload_action_inputs.items():
          workload_action.action_inputs[key] = value

        # Build the base BenchmarkJob proto
        base_job = benchmark_job_pb2.BenchmarkJob()

        # Config ID (e.g., 'resnet50_basic_gpu') is constructed from the benchmark name
        # plus the specific environment ID.
        base_job.config_id = f"{benchmark.name}_{env_config.id}"

        base_job.workflow_type = workflow_enum
        base_job.runner_label = env_config.runner_label
        base_job.container_image = env_config.container_image
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
