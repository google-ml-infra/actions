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
from benchmarking.gh_matrix_generator.gh_matrix_generator_lib import (
  MatrixGenerator,
  load_and_validate_suite_from_pbtxt,
)


def main():
  parser = argparse.ArgumentParser(description="Generate GitHub Actions matrix.")
  parser.add_argument(
    "--registry_file", required=True, help="Path to the .pbtxt registry file."
  )
  parser.add_argument(
    "--workflow_type", required=True, help="Workflow type (e.g. PRESUBMIT, POSTSUBMIT)."
  )
  parser.add_argument(
    "--ab_mode",
    type=lambda x: str(x).lower() == "true",  # Handles 'true'/'True' strings from YAML
    default=False,
    help="If true, generate A/B testing matrix (Baseline vs Experiment).",
  )
  parser.add_argument(
    "--baseline_ref",
    default="main",
    help="Git ref for the baseline (control).",
  )
  parser.add_argument(
    "--experiment_ref",
    default="",
    help="Git ref for the experiment (candidate).",
  )

  args = parser.parse_args()
  suite = load_and_validate_suite_from_pbtxt(args.registry_file)
  generator = MatrixGenerator()
  matrix = generator.generate(
    suite=suite,
    workflow_type_str=args.workflow_type,
    ab_mode=args.ab_mode,
    baseline_ref=args.baseline_ref,
    experiment_ref=args.experiment_ref,
  )

  print(
    json.dumps(matrix)
  )  # Output is JSON array compatible with "fromJSON" in GitHub Actions


if __name__ == "__main__":
  main()
