# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Publishes benchmark results to Google Cloud Pub/Sub."""

import argparse
import glob
import os
from google.protobuf import json_format
from protovalidate import validate, ValidationError
from benchmarking.proto import benchmark_result_pb2
from benchmarking.publisher import publish_results_lib


def _format_validation_error(violation) -> str:
  """Formats a single protovalidate violation into a human-readable string."""
  field_path_str = ".".join(
    f"{elem.field_name}[{elem.index}]" if elem.index else elem.field_name
    for elem in violation.proto.field.elements
  )
  return f"  - Field: {field_path_str}\n    Error: {violation.proto.message}"


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--project_id", required=True)
  parser.add_argument("--topic_id", required=True)
  parser.add_argument("--benchmark_results_dir", required=True)
  parser.add_argument(
    "--repo_name",
    required=True,
    help="The repository name (e.g. owner/repo) for filtering.",
  )

  args = parser.parse_args()

  # Find benchmark result files
  files = glob.glob(
    os.path.join(args.benchmark_results_dir, "**/*.json"), recursive=True
  )
  if not files:
    print("WARNING: No benchmark result files found to publish.")
    return

  valid_messages = []

  # Parse and validate
  print(f"Found {len(files)} files. Validating.")
  for file_path in files:
    try:
      with open(file_path, "r") as f:
        json_data = f.read()

      message = benchmark_result_pb2.BenchmarkResult()
      json_format.Parse(json_data, message)
      validate(message)
      valid_messages.append(message)
    except json_format.ParseError as e:
      raise ValueError(f"File {file_path} is not valid JSON/Proto: {e}") from e
    except ValidationError as e:
      error_msg = "\n".join(_format_validation_error(v) for v in e.violations)
      raise ValueError(f"Validation failed for {file_path}:\n{error_msg}") from e
    except Exception as e:
      raise RuntimeError(f"Unexpected error reading {file_path}: {e}") from e

  # Publish valid benchmark results
  publish_results_lib.publish_messages(
    args.project_id, args.topic_id, valid_messages, repo_name=args.repo_name
  )


if __name__ == "__main__":
  main()
