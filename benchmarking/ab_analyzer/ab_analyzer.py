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
from pathlib import Path
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
    type=Path,
    help="Directory containing downloaded benchmark result artifacts.",
  )
  parser.add_argument(
    "--output_file",
    required=True,
    type=Path,
    help="Output path for the markdown report.",
  )
  parser.add_argument(
    "--repo_url",
    required=True,
    help="The base URL of the repository (e.g. https://github.com/org/repo).",
  )
  parser.add_argument(
    "--workflow_name",
    required=True,
    help="The name of the GitHub Actions workflow.",
  )

  args = parser.parse_args()

  if not args.results_dir.is_dir():
    raise ValueError(f"{args.results_dir} is not a valid directory.")

  # Parse matrix JSON string
  try:
    matrix_list = json.loads(args.matrix_json)
  except json.JSONDecodeError as e:
    raise ValueError(f"Provided matrix JSON is not valid: {e}") from e

  # Deserialize into BenchmarkJob protos
  matrix_map: dict[str, benchmark_job_pb2.BenchmarkJob] = {}
  try:
    for job_dict in matrix_list:
      job = benchmark_job_pb2.BenchmarkJob()
      json_format.ParseDict(job_dict, job, ignore_unknown_fields=True)

      if job.ab_test_group == benchmark_job_pb2.AbTestGroup.BASELINE:
        matrix_map[job.config_id] = job
  except json_format.ParseError as e:
    raise ValueError(
      f"Error parsing benchmark job JSON into BenchmarkJob proto: {e}"
    ) from e

  # Load results
  results = ab_analyzer_lib.load_results(args.results_dir)

  # Generate report
  report_content, is_success = ab_analyzer_lib.generate_report(
    results, matrix_map, args.repo_url, args.workflow_name
  )

  # Write A/B report
  args.output_file.write_text(report_content)

  print(f"Report written to {args.output_file}")

  if not is_success:
    print("Regressions detected!", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
  main()
