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
  args = parser.parse_args()
  suite = load_and_validate_suite_from_pbtxt(args.registry_file)
  generator = MatrixGenerator()
  matrix = generator.generate(suite, args.workflow_type)
  print(
    json.dumps(matrix)
  )  # Output is JSON array compatible with "fromJSON" in GitHub Actions


if __name__ == "__main__":
  main()
