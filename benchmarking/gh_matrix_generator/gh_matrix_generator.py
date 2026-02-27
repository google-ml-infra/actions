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

"""Script for generating a GitHub Actions matrix from a benchmark registry."""

import argparse
import json
import shlex
from benchmarking.gh_matrix_generator.gh_matrix_generator_lib import (
  MatrixGenerator,
  load_and_validate_suite_from_pbtxt,
)


def main():
  parser = argparse.ArgumentParser(description="Generate GitHub Actions matrix.")
  parser.add_argument(
    "--registry_file",
    required=True,
    help="Path to the .pbtxt registry file.",
  )
  parser.add_argument(
    "--github_event",
    required=True,
    help="The GitHub event name triggering this run (e.g. pull_request, schedule).",
  )
  parser.add_argument(
    "--benchmark_filter",
    required=False,
    default="",
    help="Regex to filter by benchmark.name (e.g. 'resnet.*').",
  )
  parser.add_argument(
    "--environment_filter",
    required=False,
    default="",
    help="Regex to filter by environment_config.id (e.g. 'a100.*').",
  )
  parser.add_argument(
    "--tag_filter",
    required=False,
    nargs="*",
    default=[],
    help="List of tags to filter by. Benchmarks must match at least one tag.",
  )
  parser.add_argument(
    "--ab_mode",
    required=False,
    type=lambda x: str(x).lower() == "true",  # Handles 'true'/'True' strings
    default=False,
    help="If true, generate A/B testing matrix (Baseline vs Experiment).",
  )
  parser.add_argument(
    "--baseline_ref",
    required=False,
    default="main",
    help="Git ref for the baseline (control).",
  )
  parser.add_argument(
    "--experiment_ref",
    required=False,
    default="",
    help="Git ref for the experiment (candidate).",
  )

  args = parser.parse_args()

  # Normalize tag input to handle both CLI lists and GHA quoted strings
  normalized_tags = []
  for tag_arg in args.tag_filter:
    normalized_tags.extend(shlex.split(tag_arg))

  suite = load_and_validate_suite_from_pbtxt(args.registry_file)
  generator = MatrixGenerator()
  matrix = generator.generate(
    suite=suite,
    benchmark_filter=args.benchmark_filter,
    environment_filter=args.environment_filter,
    tag_filter=normalized_tags,
    github_event=args.github_event,
    ab_mode=args.ab_mode,
    baseline_ref=args.baseline_ref,
    experiment_ref=args.experiment_ref,
  )

  print(
    json.dumps(matrix)
  )  # Output is JSON array compatible with "fromJSON" in GitHub Actions


if __name__ == "__main__":
  main()
