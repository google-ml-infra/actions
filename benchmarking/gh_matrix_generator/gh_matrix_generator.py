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

"""Script for generating GitHub Actions matrices from benchmark registries.

Environment variables:

GITHUB_REPOSITORY (REQUIRED): Name of repo where the workflow is running. This is used to select GHA runners.
"""

import os
import sys
import argparse
import json
from runfiles import Runfiles
from benchmarking.gh_matrix_generator.gh_matrix_generator_lib import (
  MatrixGenerator,
  load_and_validate_suite_from_pbtxt,
)

# Global constants for the runfiles paths to the configuration files.
# The path is the full path from the workspace root, prefixed with the workspace name.
GHA_RUNNERS_CONFIG_PATH = "google_ml_actions/benchmarking/config/gha_runners.json"
CONTAINERS_CONFIG_PATH = "google_ml_actions/benchmarking/config/containers.json"


def load_json_from_runfiles(rfiles: Runfiles, path: str) -> dict:
  """Loads a JSON config file via runfiles."""
  location = rfiles.Rlocation(path)
  if not location or not os.path.exists(location):
    print(f"Error: Could not find config file for path '{path}'", file=sys.stderr)
    sys.exit(1)
  try:
    with open(location, "r") as f:
      return json.load(f)
  except (FileNotFoundError, json.JSONDecodeError) as e:
    print(f"Error loading config file '{location}': {e}", file=sys.stderr)
    sys.exit(1)


def main():
  parser = argparse.ArgumentParser(description="Generate GitHub Actions matrix.")
  parser.add_argument("--registry_file", required=True)
  parser.add_argument("--workflow_type", required=True)
  args = parser.parse_args()

  repo_name = os.environ.get("GITHUB_REPOSITORY")
  if not repo_name:
    print("Error: GITHUB_REPOSITORY environment variable not set.", file=sys.stderr)
    sys.exit(1)

  rfiles = Runfiles.Create()
  gha_runners = load_json_from_runfiles(rfiles, GHA_RUNNERS_CONFIG_PATH)
  containers = load_json_from_runfiles(rfiles, CONTAINERS_CONFIG_PATH)
  generator = MatrixGenerator(gha_runners, containers)
  suite = load_and_validate_suite_from_pbtxt(args.registry_file)

  matrix = generator.generate(suite, args.workflow_type, repo_name)
  print(
    json.dumps(matrix)
  )  # Output is JSON array compatible with "fromJSON" in GitHub Actions


if __name__ == "__main__":
  main()
