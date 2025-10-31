# Copyright 2025 Google LLC
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

"""
Script to perform static threshold analysis on a benchmark result.
"""

import argparse
import json
import sys
from typing import List
from google.protobuf import json_format
from benchmarking.proto import benchmark_registry_pb2
from benchmarking.proto import benchmark_result_pb2
from benchmarking.static_threshold_analyzer.static_threshold_analyzer_lib import (
  StaticAnalyzer,
)


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


def _load_benchmark_result(
  benchmark_result_file: str,
) -> benchmark_result_pb2.BenchmarkResult:
  """Loads a JSON benchmark result artifact and returns the BenchmarkResult proto."""
  try:
    with open(benchmark_result_file, "r") as f:
      result_dict = json.load(f)

    result_proto = benchmark_result_pb2.BenchmarkResult()
    json_format.ParseDict(result_dict, result_proto)
    return result_proto

  except Exception as e:
    print(
      f"Error: Failed to process artifact {benchmark_result_file}. Error: {e}",
      file=sys.stderr,
    )
    sys.exit(1)


def main():
  parser = argparse.ArgumentParser(description="Analyze benchmark results.")
  parser.add_argument("--metrics_manifest_json", required=True)
  parser.add_argument("--benchmark_result_file", required=True)
  args = parser.parse_args()

  metric_manifest = _parse_metric_manifest(args.metrics_manifest_json)
  benchmark_result = _load_benchmark_result(args.benchmark_result_file)
  analyzer = StaticAnalyzer(metric_manifest)
  analyzer.run_analysis(benchmark_result)
  analyzer.report_results()


if __name__ == "__main__":
  main()
