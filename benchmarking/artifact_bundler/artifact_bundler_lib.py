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
Artifact Bundler Library

This library provides logic to collect individual artifacts produced by parallel
benchmark runs and bundle them into a single, structured directory tree.
"""

import json
import shutil
from pathlib import Path
from typing import Sequence

from google.protobuf import json_format
from protovalidate import validate, ValidationError
from buf.validate.validate_pb2 import Violation
from benchmarking.proto import benchmark_job_pb2


def _format_validation_error(violation: Violation) -> str:
  """Formats a single protovalidate violation into a human-readable string.

  Args:
      violation: A violation object from protovalidate.

  Returns:
      A formatted string describing the field and the error.
  """
  field_path_str = ".".join(
    f"{elem.field_name}[{elem.index}]" if elem.index else elem.field_name
    for elem in violation.proto.field.elements
  )
  return f"  - Field: {field_path_str}\n    Error: {violation.proto.message}"


def _parse_and_validate_matrix(
  matrix_path: Path,
) -> Sequence[benchmark_job_pb2.BenchmarkJob]:
  """Parses matrix.json into a sequence of validated BenchmarkJob protos.

  Args:
      matrix_path: Path to the matrix.json file.

  Returns:
      A sequence of validated BenchmarkJob objects.

  Raises:
      FileNotFoundError: If the matrix.json file is missing.
      ValueError: If JSON parsing, Proto parsing, or Proto validation fails.
  """
  if not matrix_path.exists():
    raise FileNotFoundError(f"matrix.json missing from bundle at {matrix_path}")

  try:
    with open(matrix_path, "r") as f:
      raw_data = json.load(f)
  except json.JSONDecodeError as e:
    raise ValueError(f"Failed to parse JSON from {matrix_path}: {e}") from e

  validated_jobs = []

  print(f"Validating {len(raw_data)} matrix entries.")
  for i, item in enumerate(raw_data):
    try:
      # Parse
      job = benchmark_job_pb2.BenchmarkJob()
      json_format.ParseDict(item, job, ignore_unknown_fields=True)

      # Validate
      validate(job)
      validated_jobs.append(job)

    except json_format.ParseError as e:
      raise ValueError(
        f"Matrix entry #{i} is not a valid BenchmarkJob proto: {e}"
      ) from e
    except ValidationError as e:
      error_msg = "\n".join(_format_validation_error(v) for v in e.violations)
      raise ValueError(f"Validation failed for matrix entry #{i}:\n{error_msg}") from e

  return validated_jobs


def move_root_artifacts(raw_dir: Path, final_dir: Path, job_id: str) -> None:
  """Locates and moves top-level artifacts (matrix, report) to the bundle root.

  Args:
      raw_dir: The directory containing the downloaded artifact folders.
      final_dir: The destination directory for the bundle.
      job_id: The top-level job ID.

  Raises:
      FileNotFoundError: If the matrix artifact is missing.
  """

  # Move matrix JSON
  matrix_dir_match = list(raw_dir.glob(f"shard-matrix-{job_id}"))
  if not matrix_dir_match:
    raise FileNotFoundError(
      f"Matrix artifact 'shard-matrix-{job_id}' not found in {raw_dir}"
    )

  src_matrix = matrix_dir_match[0] / "matrix.json"
  dest_matrix = final_dir / "matrix.json"
  if src_matrix.exists():
    shutil.move(str(src_matrix), str(dest_matrix))
    print(f"Created {dest_matrix}")

  # Move A/B report (if exists)
  report_dir_match = list(raw_dir.glob(f"shard-ab-report-{job_id}"))
  if not report_dir_match:
    print("No A/B report artifact found.")
  else:
    src_report = report_dir_match[0] / "ab_report.md"
    dest_report = final_dir / "ab_report.md"
    if src_report.exists():
      shutil.move(str(src_report), str(dest_report))
      print(f"Created {dest_report}")


def process_benchmarks(raw_dir: Path, final_dir: Path, job_id: str) -> None:
  """Reads the matrix and moves benchmark-specific artifacts into their hierarchy.

  Args:
      raw_dir: The directory containing the downloaded artifact folders.
      final_dir: The destination directory.
      job_id: The top-level job ID.
  """

  # Parse and validate matrix
  jobs = _parse_and_validate_matrix(final_dir / "matrix.json")

  # Organize artifacts
  for job in jobs:
    # Access the A/B group (if exists)
    group: str = (
      benchmark_job_pb2.AbTestGroup.Name(job.ab_test_group)
      if job.ab_test_group
      else "single_run"
    )

    # Construct destination path
    # Structure: <benchmark_name>/<environment_config_id>/<group|single_run>/
    dest_dir = final_dir / job.benchmark_name / job.environment_config.id / group
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Reconstruct the suffix used for the temporary artifact directories
    if job.ab_test_group:
      artifact_suffix = f"{job.config_id}-{group}-{job_id}"
    else:
      artifact_suffix = f"{job.config_id}-{job_id}"

    # Move benchmark result
    res_src = (
      raw_dir / f"shard-benchmark-result-{artifact_suffix}" / "benchmark_result.json"
    )
    dest_res = dest_dir / "benchmark_result.json"
    if res_src.exists():
      shutil.move(str(res_src), str(dest_res))
      print(f"Created {dest_res}")

    # Move workload artifacts
    art_src = raw_dir / f"shard-workload-artifacts-{artifact_suffix}"
    dest_art = dest_dir / "workload_artifacts"
    if art_src.is_dir():
      shutil.move(str(art_src), str(dest_art))
      print(f"Created {dest_art}")
