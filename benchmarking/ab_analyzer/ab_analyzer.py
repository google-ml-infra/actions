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

"""A/B testing analyzer for benchmark results."""

import argparse
import json
import sys
from typing import Dict
from google.protobuf import json_format
from benchmarking.ab_analyzer import ab_analyzer_lib
from benchmarking.proto import benchmark_job_pb2


def main():
  parser = argparse.ArgumentParser(description="Analyze A/B benchmark results.")

  parser.add_argument(
    "--matrix_json",
    required=True,
    help="Raw JSON string containing a list of BenchmarkJob protos.",
  )
  parser.add_argument(
    "--results_dir",
    required=True,
    help="Directory containing downloaded benchmark artifacts.",
  )
  parser.add_argument(
    "--output_file",
    default="ab_report.md",
    help="Output path for the markdown report.",
  )

  args = parser.parse_args()

  # Parse Matrix JSON string
  try:
    matrix_list = json.loads(args.matrix_json)
  except json.JSONDecodeError as e:
    print(f"Error decoding matrix JSON string: {e}", file=sys.stderr)
    sys.exit(1)

  # Deserialize into BenchmarkJob protos
  matrix_map: Dict[str, benchmark_job_pb2.BenchmarkJob] = {}
  try:
    for job_dict in matrix_list:
      job = benchmark_job_pb2.BenchmarkJob()
      json_format.ParseDict(job_dict, job, ignore_unknown_fields=True)

      # Strictly use the BASELINE job definition as the source of truth.
      # This filters out:
      # Standard jobs (UNSPECIFIED) - we don't A/B test them.
      # Experiment jobs - we use Baseline for the shared MetricSpecs to avoid duplicates.
      if job.ab_test_group == benchmark_job_pb2.BenchmarkJob.BASELINE:
        matrix_map[job.config_id] = job

  except json_format.ParseError as e:
    print(f"Error parsing matrix JSON into BenchmarkJob proto: {e}", file=sys.stderr)
    sys.exit(1)

  # Load paired results from the artifacts directory
  pairs = ab_analyzer_lib.load_results(args.results_dir)

  # Generate report using the typed matrix_map
  report_content, is_success = ab_analyzer_lib.generate_report(pairs, matrix_map)

  # Write A/B report to output file
  with open(args.output_file, "w") as f:
    f.write(report_content)

  print(f"Report written to {args.output_file}")

  # Exit code based on regression status
  if not is_success:
    print("Regressions detected!", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
  main()
