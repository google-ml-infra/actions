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

"""Tests for the GitHub Actions matrix generator."""

import sys
from unittest import mock
import pytest
from google.protobuf import text_format
from benchmarking.gh_matrix_generator import gh_matrix_generator_lib
from benchmarking.proto import benchmark_registry_pb2

# --- Test Data ---

TEST_RUNNERS_CONFIG = {
  "openxla/xla": {
    "CPU_X86": [
      {"label": "linux-x86-n2-16", "os": "LINUX", "vcpu": 16},
      {"label": "linux-x86-n2-32", "os": "LINUX", "vcpu": 32},
    ],
    "GPU_A100": [
      {"label": "linux-x86-a2-48-a100-4gpu", "os": "LINUX", "gpu_count": 4, "vcpu": 48},
    ],
  },
  "google-ml-infra/actions": {
    "CPU_X86": [
      {"label": "windows-x86-n2-16", "os": "WINDOWS", "vcpu": 16},
    ]
  },
}

TEST_CONTAINERS_CONFIG = {
  "CPU_X86": "gcr.io/testing/cpu-container:latest",
  "GPU_A100": "gcr.io/testing/gpu-container:latest",
}

VALID_SUITE_PBTXT = """
    benchmarks {
      name: "cpu_benchmark"
      description: "A valid CPU benchmark."
      owner: "cpu-team"
      workload {
        bazel_workload: {
          execution_target: "//b:cpu"
        }
        runtime_flags: "--model_name=cpu_model"
      }
      hardware_configs {
        hardware_category: CPU_X86
        topology { num_hosts: 1, num_devices_per_host: 1 }
        workflow_type: [PRESUBMIT, POSTSUBMIT]
        resource_spec { min_vcpu_count: 32, os: LINUX }
        runtime_flags: "--precision=fp32"
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
        hlo_workload: {
          gcs_path: "gs://bucket/model.hlo"
        }
        runtime_flags: "--iterations=100"
      }
      hardware_configs {
        hardware_category: GPU_A100
        topology { num_hosts: 1, num_devices_per_host: 4 }
        workflow_type: [PRESUBMIT]
        resource_spec { gpu_count: 4 }
        runtime_flags: "--use_gpu"
      }
      update_frequency_policy: WEEKLY
    }
    benchmarks {
        name: "windows_benchmark"
        description: "A valid Windows benchmark."
        owner: "windows-team"
        workload {
          bazel_workload: {
            execution_target: "//b:win"
          }
        }
        hardware_configs {
            hardware_category: CPU_X86
            topology { num_hosts: 1, num_devices_per_host: 1 }
            workflow_type: [SCHEDULED]
            resource_spec { os: WINDOWS }
        }
        update_frequency_policy: MONTHLY
    }
    """

INVALID_SUITE_MISSING_NAME_PBTXT = """
    benchmarks {
      description: "A benchmark with a missing name."
      owner: "cpu-team"
      workload {
        bazel_workload: {
          execution_target: "//b:cpu"
        }
      }
      hardware_configs {
        hardware_category: CPU_X86
        topology { num_hosts: 1, num_devices_per_host: 1 }
        workflow_type: [PRESUBMIT]
      }
      update_frequency_policy: QUARTERLY
    }
    """

# --- Pytest Fixtures ---


@pytest.fixture
def generator() -> gh_matrix_generator_lib.MatrixGenerator:
  """Returns a MatrixGenerator instance initialized with test data."""
  return gh_matrix_generator_lib.MatrixGenerator(
    gha_runners=TEST_RUNNERS_CONFIG,
    containers=TEST_CONTAINERS_CONFIG,
  )


# --- Tests for Validation Logic ---


@mock.patch("builtins.open", new_callable=mock.mock_open, read_data=VALID_SUITE_PBTXT)
@mock.patch("os.path.isabs", return_value=True)
def test_load_and_validate_suite_success(_mock_isabs, _mock_open):
  """Tests that a valid pbtxt file is loaded and validated correctly."""
  suite = gh_matrix_generator_lib.load_and_validate_suite_from_pbtxt("dummy_path.pbtxt")
  assert len(suite.benchmarks) == 3
  assert suite.benchmarks[0].name == "cpu_benchmark"


@mock.patch(
  "builtins.open",
  new_callable=mock.mock_open,
  read_data=INVALID_SUITE_MISSING_NAME_PBTXT,
)
@mock.patch("os.path.isabs", return_value=True)
def test_load_and_validate_suite_fails_on_invalid_pbtxt(
  _mock_isabs, _mock_open, capsys
):
  """Tests that an invalid pbtxt (missing a required field) fails validation."""
  with pytest.raises(SystemExit):
    gh_matrix_generator_lib.load_and_validate_suite_from_pbtxt("invalid.pbtxt")

  captured = capsys.readouterr()
  assert "benchmarks.name" in captured.err


# --- Tests for Matrix Generation Logic ---


@pytest.mark.parametrize(
  "repo_name, workflow_type, expected_count, expected_names",
  [
    ("openxla/xla", "PRESUBMIT", 2, {"cpu_benchmark", "gpu_benchmark"}),
    ("openxla/xla", "POSTSUBMIT", 1, {"cpu_benchmark"}),
    ("google-ml-infra/actions", "SCHEDULED", 1, {"windows_benchmark"}),
    ("openxla/xla", "MANUAL", 0, set()),
  ],
)
def test_generate_matrix_for_workflows(
  generator, repo_name, workflow_type, expected_count, expected_names
):
  """Tests that the matrix is correctly filtered for different workflow types."""
  suite = text_format.Parse(VALID_SUITE_PBTXT, benchmark_registry_pb2.BenchmarkSuite())
  matrix = generator.generate(suite, workflow_type, repo_name)

  assert len(matrix) == expected_count
  generated_names = {entry["benchmark_name"] for entry in matrix}
  assert generated_names == expected_names


def test_generate_matrix_selects_correct_runner(generator):
  """Tests that the correct runner and config are selected based on resource_spec."""
  suite = text_format.Parse(VALID_SUITE_PBTXT, benchmark_registry_pb2.BenchmarkSuite())
  matrix = generator.generate(suite, "PRESUBMIT", "openxla/xla")

  cpu_entry = next(item for item in matrix if item["benchmark_name"] == "cpu_benchmark")

  assert cpu_entry["runner_label"] == "linux-x86-n2-32"
  assert cpu_entry["config_id"] == "cpu_benchmark_x86_1h1d_presubmit"
  assert cpu_entry["container_image"] == "gcr.io/testing/cpu-container:latest"


def test_generate_matrix_fails_on_unmatchable_runner(generator, capsys):
  """Tests that the script exits if no runner matches a resource spec."""
  unmatchable_suite_pbtxt = """
      benchmarks {
        name: "unmatchable_gpu_benchmark"
        description: "A benchmark that requires 8 GPUs."
        owner: "gpu-team"
        workload {
          hlo_workload {
            gcs_path: "gs://b/m.hlo"
          }
        }
        hardware_configs {
          hardware_category: GPU_A100
          topology { num_hosts: 1, num_devices_per_host: 8 }
          workflow_type: [PRESUBMIT]
          resource_spec { gpu_count: 8 } # No 8-GPU runner in our test data
        }
        update_frequency_policy: WEEKLY
      }
  """
  suite = text_format.Parse(
    unmatchable_suite_pbtxt, benchmark_registry_pb2.BenchmarkSuite()
  )

  with pytest.raises(SystemExit):
    # We test against a valid repo that has GPU_A100 runners, but none
    # thatcan satisfy the gpu_count: 8 requirement.
    generator.generate(suite, "PRESUBMIT", "openxla/xla")

  captured = capsys.readouterr()
  assert "Error: Could not find a matching runner" in captured.err
  assert "GPU_A100" in captured.err


def test_generate_matrix_fails_on_unknown_repo(generator, capsys):
  """Tests that the script exits if the repo is not in the runner config."""
  suite = text_format.Parse(VALID_SUITE_PBTXT, benchmark_registry_pb2.BenchmarkSuite())
  with pytest.raises(SystemExit):
    generator.generate(suite, "PRESUBMIT", "unknown/repo")

  captured = capsys.readouterr()
  assert "Error: No runner pool defined for repository 'unknown/repo'" in captured.err


if __name__ == "__main__":
  sys.exit(pytest.main(sys.argv))
