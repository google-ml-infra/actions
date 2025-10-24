# Copyright 2025 Google LLC
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
from protovalidate import validate, ValidationError

Runner = Dict[str, Any]
RunnerPool = Dict[str, List[Runner]]
RunnerMap = Dict[str, RunnerPool]
ContainerMap = Dict[str, str]
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

  def __init__(self, gha_runners: RunnerMap, containers: ContainerMap):
    """Initializes the generator with configuration data.

    Args:
      gha_runners: A nested dictionary defining the available runners, keyed
        by repository name and then by HardwareCategory.
      containers: A dictionary mapping HardwareCategory strings to the
        container image URL.
    """
    self.gha_runners = gha_runners
    self.containers = containers

  def _find_gha_runner(
    self, hw_config: benchmark_registry_pb2.HardwareConfig, repo_name: str
  ) -> Runner | None:
    """Finds the best GHA runner for a given hardware config."""
    if repo_name not in self.gha_runners:
      print(
        f"Error: No runner pool defined for repository '{repo_name}' in gha_runners.json.",
        file=sys.stderr,
      )
      sys.exit(1)

    pool = self.gha_runners[repo_name]
    spec = hw_config.resource_spec
    hw_category = benchmark_registry_pb2.HardwareCategory.Name(
      hw_config.hardware_category
    )
    candidates = pool.get(hw_category, [])

    # Default OS is LINUX
    target_os = benchmark_registry_pb2.OS.Name(
      spec.os or benchmark_registry_pb2.OS.LINUX
    )
    candidates = [r for r in candidates if r.get("os") == target_os]

    if spec.min_vcpu_count:
      candidates = [r for r in candidates if r.get("vcpu", 0) >= spec.min_vcpu_count]
    if spec.gpu_count:
      candidates = [r for r in candidates if r.get("gpu_count", 0) == spec.gpu_count]
    if spec.tpu_topology:
      candidates = [r for r in candidates if r.get("tpu_topology") == spec.tpu_topology]

    if not candidates:
      return None

    # Return the best runner that meets the requirements.
    # 1. For CPU requests (`min_vcpu_count`), it correctly selects the runner
    #    with the fewest vCPUs that still meets the requirement.
    # 2. For non-CPU requests (GPU/TPU), it picks the one
    #    that appears first in the JSON file or has the fewest vCPUs if
    #    that key is present.
    return sorted(candidates, key=lambda r: r.get("vcpu", float("inf")))[0]

  def generate(self, suite, workflow_type_str, repo_name: str) -> List[MatrixEntry]:
    """Generates the full matrix."""
    matrix: List[MatrixEntry] = []
    workflow_enum = benchmark_registry_pb2.WorkflowType.Value(workflow_type_str.upper())

    for benchmark in suite.benchmarks:
      for hw_config in benchmark.hardware_configs:
        if workflow_enum not in hw_config.workflow_type:
          continue

        runner = self._find_gha_runner(hw_config, repo_name)
        hw_category = benchmark_registry_pb2.HardwareCategory.Name(
          hw_config.hardware_category
        )
        container = self.containers.get(hw_category)

        if not runner or not container:
          print(
            f"Error: Could not find a matching runner or container for "
            f"benchmark '{benchmark.name}' with hardware '{hw_category}' "
            f"in runner pool for repository '{repo_name}'. "
            f"Please check config files.",
            file=sys.stderr,
          )
          sys.exit(1)

        hw_short = (
          hw_category.lower()
          .replace("gpu_", "")
          .replace("cpu_", "")
          .replace("tpu_", "")
        )
        topo = hw_config.topology
        topo_short = f"{topo.num_hosts}h{topo.num_devices_per_host}d"
        workflow_short = workflow_type_str.lower()
        workload = benchmark.workload
        workload_type = workload.WhichOneof("workload")
        workload_details = getattr(workload, workload_type)
        runtime_flags = list(workload.runtime_flags) + list(hw_config.runtime_flags)

        pip_extra_deps = []
        if workload_type == "python_workload":
          pip_extra_deps.extend(workload_details.pip_optional_dependencies)

        if hw_config.pip_optional_dependencies:
          pip_extra_deps.extend(hw_config.pip_optional_dependencies)

        entry: MatrixEntry = {
          "config_id": f"{benchmark.name}_{hw_short}_{topo_short}_{workflow_short}",
          "runner_label": runner["label"],
          "container_image": container,
          "benchmark_name": benchmark.name,
          "description": benchmark.description,
          "owner": benchmark.owner,
          "workload_type": workload_type,
          "workload_details": MessageToDict(workload_details),
          "hardware_config": MessageToDict(hw_config),
          "github_labels": list(benchmark.github_labels),
          "pip_extra_deps": pip_extra_deps,
          "runtime_flags": runtime_flags,
          "metrics": [MessageToDict(m) for m in benchmark.metrics],
        }
        matrix.append(entry)
    return matrix
