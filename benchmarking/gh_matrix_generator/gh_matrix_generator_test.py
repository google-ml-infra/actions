# Copyright 2026 Google LLC
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

"""Tests for the GitHub Actions matrix generator."""

import sys
from unittest import mock
import pytest
from google.protobuf import text_format
from benchmarking.gh_matrix_generator import gh_matrix_generator_lib
from benchmarking.proto import benchmark_registry_pb2

# --- Test Data ---

VALID_SUITE_PBTXT = """
    benchmarks {
      name: "cpu_benchmark"
      description: "A valid CPU benchmark."
      owner: "cpu-team"
      workload {
        action: "./ml_actions/benchmarking/actions/workload_executors/bazel"
        action_inputs { key: "target" value: "//b:cpu" }
        action_inputs { key: "runtime_flags" value: "--model_name=cpu_model" }
      }
      environment_configs {
        id: "basic_cpu"
        runner_label: "linux-x86-n2-32"
        container_image: "gcr.io/testing/cpu-container:latest"
        workflow_type: [PRESUBMIT, POSTSUBMIT]
        workload_action_inputs { key: "runtime_flags_hw" value: "--precision=fp32" }
      }
      update_frequency_policy: QUARTERLY
      metrics {
        name: "wall_time_ms"
        unit: "ms"
        stats {
          stat: MEDIAN
          comparison: {
            baseline { value: 500.0 }
            threshold { value: 0.05 }
            improvement_direction: LESS
          }
        }
      }
    }
    benchmarks {
      name: "gpu_benchmark"
      description: "A valid GPU benchmark."
      owner: "gpu-team"
      workload {
        action: "./user_repo/benchmarking/actions/hlo"
        action_inputs { key: "gcs_path" value: "gs://bucket/model.hlo" }
        action_inputs { key: "iterations" value: "100" }
      }
      environment_configs {
        id: "a100_4gpu"
        runner_label: "linux-x86-a2-48-a100-4gpu"
        container_image: "gcr.io/testing/gpu-container:latest"
        workflow_type: [PRESUBMIT]
      }
      update_frequency_policy: WEEKLY
    }
    """

INVALID_SUITE_MISSING_ID_PBTXT = """
    benchmarks {
      name: "broken_benchmark"
      description: "Missing environment_config ID."
      owner: "cpu-team"
      workload {
        action: "./ml_actions/benchmarking/actions/workload_executors/bazel"
      }
      environment_configs {
        runner_label: "linux-x86-n2-32"
        container_image: "gcr.io/testing/cpu-container:latest"
        workflow_type: [PRESUBMIT]
      }
      update_frequency_policy: QUARTERLY
    }
    """

# --- Tests for Validation Logic ---


@mock.patch("builtins.open", new_callable=mock.mock_open, read_data=VALID_SUITE_PBTXT)
@mock.patch("os.path.isabs", return_value=True)
def test_load_and_validate_suite_success(_mock_isabs, _mock_open):
  """Tests that a valid pbtxt file is loaded and validated correctly."""
  suite = gh_matrix_generator_lib.load_and_validate_suite_from_pbtxt("dummy_path.pbtxt")
  assert len(suite.benchmarks) == 2
  assert suite.benchmarks[0].name == "cpu_benchmark"


@mock.patch(
  "builtins.open",
  new_callable=mock.mock_open,
  read_data=INVALID_SUITE_MISSING_ID_PBTXT,
)
@mock.patch("os.path.isabs", return_value=True)
def test_load_and_validate_suite_fails_on_invalid_pbtxt(_mock_isabs, _mock_open):
  """Tests that an invalid pbtxt (missing required environment_config ID) fails validation."""
  with pytest.raises(ValueError) as excinfo:
    gh_matrix_generator_lib.load_and_validate_suite_from_pbtxt("invalid.pbtxt")

  error_msg = str(excinfo.value)
  assert "benchmarks.environment_configs.id" in error_msg
  assert "Registry file 'invalid.pbtxt' is invalid" in error_msg


# --- Tests for Matrix Generation Logic ---


@pytest.mark.parametrize(
  "workflow_type, expected_count, expected_names",
  [
    ("PRESUBMIT", 2, {"cpu_benchmark", "gpu_benchmark"}),
    ("POSTSUBMIT", 1, {"cpu_benchmark"}),
    ("SCHEDULED", 0, set()),
    ("MANUAL", 0, set()),
  ],
)
def test_generate_matrix_filtering(workflow_type, expected_count, expected_names):
  """Tests that the matrix is correctly filtered for different workflow types."""
  suite = text_format.Parse(VALID_SUITE_PBTXT, benchmark_registry_pb2.BenchmarkSuite())

  generator = gh_matrix_generator_lib.MatrixGenerator()
  matrix = generator.generate(suite, workflow_type)

  assert len(matrix) == expected_count
  generated_names = {entry["benchmark_name"] for entry in matrix}
  assert generated_names == expected_names


def test_generate_matrix_content_correctness():
  """Tests that the matrix entry contains the correct fields and config IDs."""
  suite = text_format.Parse(VALID_SUITE_PBTXT, benchmark_registry_pb2.BenchmarkSuite())

  generator = gh_matrix_generator_lib.MatrixGenerator()
  matrix = generator.generate(suite, "PRESUBMIT")

  cpu_entry = next(item for item in matrix if item["benchmark_name"] == "cpu_benchmark")

  assert cpu_entry["config_id"] == "cpu_benchmark_basic_cpu"
  assert cpu_entry["workflow_type"] == "PRESUBMIT"
  assert cpu_entry["runner_label"] == "linux-x86-n2-32"
  assert cpu_entry["container_image"] == "gcr.io/testing/cpu-container:latest"

  action_inputs = cpu_entry["workload"]["action_inputs"]
  assert action_inputs["target"] == "//b:cpu"
  assert action_inputs["runtime_flags_hw"] == "--precision=fp32"


def test_config_id_persistence_across_workflow_types():
  """Verifies that config_id remains the same across different workflow types."""
  suite = text_format.Parse(VALID_SUITE_PBTXT, benchmark_registry_pb2.BenchmarkSuite())
  generator = gh_matrix_generator_lib.MatrixGenerator()

  # Generate for PRESUBMIT
  matrix_pre = generator.generate(suite, "PRESUBMIT")
  cpu_pre = next(i for i in matrix_pre if i["benchmark_name"] == "cpu_benchmark")

  # Generate for POSTSUBMIT
  matrix_post = generator.generate(suite, "POSTSUBMIT")
  cpu_post = next(i for i in matrix_post if i["benchmark_name"] == "cpu_benchmark")

  # IDs match
  assert cpu_pre["config_id"] == cpu_post["config_id"]

  # Metadata differs
  assert cpu_pre["workflow_type"] == "PRESUBMIT"
  assert cpu_post["workflow_type"] == "POSTSUBMIT"


if __name__ == "__main__":
  sys.exit(pytest.main(sys.argv))
