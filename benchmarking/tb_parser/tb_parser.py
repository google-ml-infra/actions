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

"""Script to parse TensorBoard benchmark results and produce a BenchmarkResult JSON file."""

import argparse
import json
import os
import sys
from typing import List
from google.protobuf import json_format, timestamp_pb2
from benchmarking.proto import benchmark_registry_pb2
from benchmarking.proto import benchmark_result_pb2
from benchmarking.tb_parser import tb_parser_lib
from protovalidate import validate, ValidationError


def _parse_metric_manifest(
  metrics_manifest_json: str,
) -> List[benchmark_registry_pb2.MetricSpec]:
  """Parses the JSON metrics manifest into a list of MetricSpec protos."""
  try:
    metrics_manifest_dicts = json.loads(metrics_manifest_json)
  except json.JSONDecodeError as e:
    print(f"Error: Failed to parse --metrics_manifest_json: {e}", file=sys.stderr)
    sys.exit(1)

  # Convert list of metric spec dicts to a list of MetricSpec protos
  metric_manifest = []
  for metric_dict in metrics_manifest_dicts:
    metric_spec = benchmark_registry_pb2.MetricSpec()
    json_format.ParseDict(metric_dict, metric_spec)
    metric_manifest.append(metric_spec)

  return metric_manifest


def _format_validation_error(violation) -> str:
  """Formats a single protovalidate violation into a human-readable string."""
  field_path_str = ".".join(
    f"{elem.field_name}[{elem.index}]" if elem.index else elem.field_name
    for elem in violation.proto.field.elements
  )
  return f"  - Field: {field_path_str}\n    Error: {violation.proto.message}"


def main():
  parser = argparse.ArgumentParser(description="Parse TensorBoard logs.")
  parser.add_argument("--metrics_manifest_json", required=True)
  parser.add_argument("--tblog_dir", required=True)
  parser.add_argument("--output_dir", required=True)
  parser.add_argument("--config_id", required=True)
  parser.add_argument("--commit_sha", required=True)
  parser.add_argument("--github_run_id", required=True)
  parser.add_argument("--workflow_type", required=True, help="e.g. PRESUBMIT")
  parser.add_argument("--runner_label", required=True, help="e.g. linux-x86-n2-32")
  parser.add_argument("--branch", required=True, help="e.g. main")
  parser.add_argument("--run_url", required=True, help="GitHub Actions Run URL")

  args = parser.parse_args()

  metric_manifest = _parse_metric_manifest(args.metrics_manifest_json)
  tb_parser = tb_parser_lib.TensorBoardParser(metric_manifest)
  computed_stats = tb_parser.parse_and_compute(args.tblog_dir)

  ts = timestamp_pb2.Timestamp()
  ts.GetCurrentTime()

  # Create BenchmarkResult message
  result = benchmark_result_pb2.BenchmarkResult(
    config_id=args.config_id,
    commit_sha=args.commit_sha,
    run_timestamp=ts,
    stats=computed_stats,
    github_run_id=int(args.github_run_id),
    workflow_type=args.workflow_type,
    runner_label=args.runner_label,
    branch=args.branch,
    run_url=args.run_url,
  )

  try:
    validate(result)
  except ValidationError as e:
    error_messages = "\n".join(_format_validation_error(v) for v in e.violations)
    print(
      f"Error: Internal validation of BenchmarkResult failed:\n{error_messages}",
      file=sys.stderr,
    )
    sys.exit(1)

  benchmark_result_file = os.path.join(args.output_dir, "benchmark_result.json")

  # Create benchmark result artifact file
  try:
    with open(benchmark_result_file, "w") as f:
      f.write(json_format.MessageToJson(result))
    print(f"Successfully parsed TensorBoard logs and created {benchmark_result_file}.")
  except Exception as e:
    print(
      f"Error writing result artifact to '{benchmark_result_file}': {e}",
      file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
  main()
