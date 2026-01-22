# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law of a greedor agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Library for generating GitHub Actions matrices from benchmark registries."""

import os
import sys
from typing import Any, Dict, List
from google.protobuf import text_format
from google.protobuf.json_format import MessageToDict
from benchmarking.proto import benchmark_registry_pb2
from benchmarking.proto.common import workflow_type_pb2
from protovalidate import validate, ValidationError

MatrixEntry = Dict[str, Any]


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
    print(
      f"Error: Registry file '{path}' is invalid.\nValidation Errors:\n{error_messages}",
      file=sys.stderr,
    )
    sys.exit(1)

  return suite


class MatrixGenerator:
  """Generates a GitHub Actions matrix from a benchmark registry."""

  def generate(self, suite, workflow_type_str) -> List[MatrixEntry]:
    """Generates the full matrix."""
    matrix: List[MatrixEntry] = []
    workflow_enum = workflow_type_pb2.WorkflowType.Value(workflow_type_str.upper())

    for benchmark in suite.benchmarks:
      for env_config in benchmark.environment_configs:
        if workflow_enum not in env_config.workflow_type:
          continue

        runner_label = env_config.runner_label
        container_image = env_config.container_image

        # Config ID (e.g., 'resnet50_basic_gpu') is constructed from the benchmark name
        # plus the specific environment ID.
        config_id = f"{benchmark.name}_{env_config.id}"

        env_config_dict = MessageToDict(env_config, preserving_proto_field_name=True)
        workload_dict = MessageToDict(
          benchmark.workload, preserving_proto_field_name=True
        )
        workload_base_inputs = workload_dict.get("action_inputs", {})
        env_workload_inputs = env_config_dict.get("workload_action_inputs", {})

        # Environment workload inputs overwrite/append base workload inputs
        workload_base_inputs.update(env_workload_inputs)
        workload_dict["action_inputs"] = workload_base_inputs

        entry: MatrixEntry = {
          "config_id": config_id,
          "workflow_type": workflow_type_str.upper(),
          "runner_label": runner_label,
          "container_image": container_image,
          "benchmark_name": benchmark.name,
          "description": benchmark.description,
          "owner": benchmark.owner,
          "workload": workload_dict,
          "github_labels": list(benchmark.github_labels),
          "metrics": [
            MessageToDict(m, preserving_proto_field_name=True)
            for m in benchmark.metrics
          ],
        }
        matrix.append(entry)
    return matrix
