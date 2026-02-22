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

"""Tests for the Artifact Bundler library."""

import json
import sys
from pathlib import Path
from unittest import mock
import pytest
from protovalidate import ValidationError
from benchmarking.artifact_bundler import artifact_bundler_lib
from benchmarking.proto import benchmark_job_pb2
from benchmarking.proto.common import environment_config_pb2


# --- Helper Functions ---


def create_shard(
  root_dir: Path, shard_name: str, filename: str, content: dict | str
) -> Path:
  """Creates a shard directory and a file within it.

  Args:
      root_dir: The root directory to create the shard in.
      shard_name: The name of the shard directory.
      filename: The name of the file to create.
      content: The content to write (dict for JSON, str for text).

  Returns:
      The path to the created shard directory.
  """
  shard_path = root_dir / shard_name
  shard_path.mkdir(parents=True, exist_ok=True)
  file_path = shard_path / filename

  if isinstance(content, dict) or isinstance(content, list):
    with open(file_path, "w") as f:
      json.dump(content, f)
  else:
    file_path.write_text(content)

  return shard_path


# --- Tests for Matrix Parsing & Validation ---


@mock.patch("benchmarking.artifact_bundler.artifact_bundler_lib.validate")
def test_parse_matrix_success(_mock_validate, tmp_path: Path):
  """Test parsing a valid matrix JSON file."""
  matrix_data = [
    {
      "benchmark_name": "bert",
      "config_id": "bert-gpu",
      "environment_config": {
        "id": "gpu",
        "runner_label": "linux-gpu",
        "container_image": "gcr.io/gpu-image",
      },
    },
    {
      "benchmark_name": "resnet",
      "config_id": "resnet-tpu",
      "environment_config": {
        "id": "tpu",
        "runner_label": "linux-tpu",
        "container_image": "gcr.io/tpu-image",
      },
      "ab_test_group": "BASELINE",
    },
  ]
  p = tmp_path / "matrix.json"
  p.write_text(json.dumps(matrix_data))

  jobs = artifact_bundler_lib._parse_and_validate_matrix(p)

  assert len(jobs) == 2
  assert jobs[0].benchmark_name == "bert"
  assert jobs[0].environment_config.id == "gpu"
  assert jobs[1].benchmark_name == "resnet"
  assert jobs[1].environment_config.id == "tpu"
  assert benchmark_job_pb2.AbTestGroup.Name(jobs[1].ab_test_group) == "BASELINE"


def test_parse_matrix_invalid_json(tmp_path: Path):
  """Test that malformed JSON raises a ValueError."""
  p = tmp_path / "matrix.json"
  p.write_text("{ incomplete json")

  with pytest.raises(ValueError, match="Failed to parse JSON"):
    artifact_bundler_lib._parse_and_validate_matrix(p)


def test_parse_matrix_missing_file(tmp_path: Path):
  """Test that a missing matrix file raises a FileNotFoundError."""
  p = tmp_path / "non_existent.json"

  with pytest.raises(FileNotFoundError, match="matrix.json missing"):
    artifact_bundler_lib._parse_and_validate_matrix(p)


@mock.patch("benchmarking.artifact_bundler.artifact_bundler_lib.validate")
def test_parse_matrix_validation_error(mock_validate, tmp_path: Path):
  """Test that protovalidate errors are caught and raised as ValueError."""
  # Mock validate to raise a ValidationError
  mock_validate.side_effect = ValidationError("Mocked error msg", [])

  p = tmp_path / "matrix.json"
  p.write_text(json.dumps([{"benchmark_name": "bad_job"}]))

  with pytest.raises(ValueError, match="Validation failed"):
    artifact_bundler_lib._parse_and_validate_matrix(p)


# --- Tests for Root Artifacts ---


def test_move_root_artifacts_success(tmp_path: Path):
  """Test moving matrix and report files successfully."""
  raw_dir = tmp_path / "raw"
  final_dir = tmp_path / "final"
  final_dir.mkdir()
  job_id = "123"

  # Setup artifacts
  create_shard(raw_dir, f"shard-matrix-{job_id}", "matrix.json", {})
  create_shard(raw_dir, f"shard-ab-report-{job_id}", "ab_report.md", "# Report")

  artifact_bundler_lib.move_root_artifacts(raw_dir, final_dir, job_id)

  assert (final_dir / "matrix.json").exists()
  assert (final_dir / "ab_report.md").exists()


def test_move_root_artifacts_missing_matrix(tmp_path: Path):
  """Test that missing matrix shard raises FileNotFoundError."""
  raw_dir = tmp_path / "raw"
  raw_dir.mkdir()
  final_dir = tmp_path / "final"
  job_id = "123"

  # Missing matrix shard completely
  with pytest.raises(FileNotFoundError, match="Matrix artifact"):
    artifact_bundler_lib.move_root_artifacts(raw_dir, final_dir, job_id)


def test_move_root_artifacts_missing_report(tmp_path: Path, capsys):
  """Test that missing report is optional and handled gracefully."""
  raw_dir = tmp_path / "raw"
  final_dir = tmp_path / "final"
  final_dir.mkdir()
  job_id = "123"

  # Only create matrix
  create_shard(raw_dir, f"shard-matrix-{job_id}", "matrix.json", {})

  artifact_bundler_lib.move_root_artifacts(raw_dir, final_dir, job_id)

  assert (final_dir / "matrix.json").exists()
  assert not (final_dir / "ab_report.md").exists()

  captured = capsys.readouterr()
  assert "No A/B report artifact found" in captured.out


# --- Tests for Benchmark Processing ---


@mock.patch(
  "benchmarking.artifact_bundler.artifact_bundler_lib._parse_and_validate_matrix"
)
def test_process_benchmarks_standard(mock_parse, tmp_path: Path):
  """Test processing a standard single-run benchmark."""
  raw_dir = tmp_path / "raw"
  final_dir = tmp_path / "final"
  job_id = "123"

  # Mock matrix return
  job = benchmark_job_pb2.BenchmarkJob(
    benchmark_name="bert",
    config_id="bert-gpu",
    environment_config=environment_config_pb2.EnvironmentConfig(
      id="gpu", runner_label="linux-gpu", container_image="gcr.io/testing/gpu-container"
    ),
  )
  mock_parse.return_value = [job]

  # Create temp artifact files
  suffix = f"bert-gpu-{job_id}"
  create_shard(raw_dir, f"shard-workload-artifacts-{suffix}", "log.txt", "logs")
  create_shard(
    raw_dir, f"shard-benchmark-result-{suffix}", "benchmark_result.json", {"score": 99}
  )

  artifact_bundler_lib.process_benchmarks(raw_dir, final_dir, job_id)

  target_dir = final_dir / "bert" / "gpu" / "single_run"
  assert target_dir.exists()
  assert (target_dir / "benchmark_result.json").exists()
  assert (target_dir / "workload_artifacts" / "log.txt").exists()


@mock.patch(
  "benchmarking.artifact_bundler.artifact_bundler_lib._parse_and_validate_matrix"
)
def test_process_benchmarks_ab_mode(mock_parse, tmp_path: Path):
  """Test processing an A/B benchmark (experiment group)."""
  raw_dir = tmp_path / "raw"
  final_dir = tmp_path / "final"
  job_id = "123"

  # Mock matrix return
  job = benchmark_job_pb2.BenchmarkJob(
    benchmark_name="resnet",
    config_id="resnet-tpu",
    environment_config=environment_config_pb2.EnvironmentConfig(
      id="tpu", runner_label="linux-tpu", container_image="gcr.io/testing/tpu-container"
    ),
    ab_test_group="EXPERIMENT",
  )
  mock_parse.return_value = [job]

  # Create temp artifact files
  suffix = f"resnet-tpu-EXPERIMENT-{job_id}"
  create_shard(
    raw_dir, f"shard-benchmark-result-{suffix}", "benchmark_result.json", {"score": 100}
  )

  artifact_bundler_lib.process_benchmarks(raw_dir, final_dir, job_id)

  target_dir = final_dir / "resnet" / "tpu" / "EXPERIMENT"
  assert target_dir.exists()
  assert (target_dir / "benchmark_result.json").exists()


if __name__ == "__main__":
  sys.exit(pytest.main(sys.argv))
