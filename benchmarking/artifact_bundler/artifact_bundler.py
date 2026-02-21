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

"""
Artifact Bundler

This tool collects individual artifacts produced by parallel benchmark runs
and bundles them into a single, structured directory tree for final storage.

Expected input structure (in raw_dir):
  shard-matrix-{job_id}/
    └── matrix.json
  shard-ab-report-{job_id}/
    └── ab_report.md
  shard-benchmark-result-{config}-{group}-{job_id}/
    └── benchmark_result.json
  shard-workload-artifacts-{config}-{group}-{job_id}/
    └── [arbitrary workload artifacts]

Final output structure (in final_dir):
  matrix.json
  ab_report.md (optional)
  <benchmark_name>/
    <environment_config_id>/
      <group>/                (default: 'single_run')
        benchmark_result.json
        workload_artifacts/
"""

import argparse
from pathlib import Path
from benchmarking.artifact_bundler import artifact_bundler_lib


def main():
  parser = argparse.ArgumentParser(
    description="Bundles individual artifacts produced by parallel benchmark runs into a single, structured directory."
  )
  parser.add_argument("--job_id", required=True, help="The top-level job ID.")
  parser.add_argument(
    "--raw_dir",
    required=True,
    type=Path,
    help="Directory containing the downloaded raw artifacts.",
  )
  parser.add_argument(
    "--final_dir",
    required=True,
    type=Path,
    help="Target directory for the consolidated artifact bundle.",
  )
  args = parser.parse_args()

  print(f"Bundling artifacts for Job ID: {args.job_id}")
  print(f"Target bundle directory: {args.final_dir}")

  if not args.raw_dir.is_dir():
    raise ValueError(f"{args.raw_dir} is not a valid directory.")

  if not args.final_dir.is_dir():
    raise ValueError(f"{args.final_dir} is not a valid directory.")

  try:
    artifact_bundler_lib.move_root_artifacts(args.raw_dir, args.final_dir, args.job_id)
    artifact_bundler_lib.process_benchmarks(args.raw_dir, args.final_dir, args.job_id)
    print(f"Successfully bundled artifacts in: {args.final_dir}")
  except Exception as e:
    raise RuntimeError(f"Unexpected error bundling artifacts: {e}") from e


if __name__ == "__main__":
  main()
