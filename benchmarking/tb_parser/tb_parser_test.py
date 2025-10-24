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

"""Tests for the TensorBoard parser library."""

from unittest import mock
import sys
import pytest
import numpy as np
import tensorflow as tf
from tensorboard.backend.event_processing.event_accumulator import TensorEvent
from benchmarking.proto import benchmark_registry_pb2
from benchmarking.proto.common import stat_pb2
from benchmarking.tb_parser import tb_parser_lib

# --- Helper Functions ---


def _create_metric_manifest(
  name: str, unit: str, stats: list[stat_pb2.Stat.ValueType]
) -> list[benchmark_registry_pb2.MetricSpec]:
  """Helper to create a MetricManifest list for a single metric."""
  return [
    benchmark_registry_pb2.MetricSpec(
      name=name,
      unit=unit,
      stats=[benchmark_registry_pb2.StatSpec(stat=stat) for stat in stats],
    )
  ]


def _create_fake_tensor_event(value: float) -> TensorEvent:
  """Creates a fake TensorEvent, mocking the object returned by EventAccumulator."""
  return TensorEvent(
    wall_time=0.0,
    step=0,
    tensor_proto=tf.make_tensor_proto(value, dtype=tf.float32),
  )


# --- Pytest Fixtures ---


@pytest.fixture
def mock_event_accumulator():
  """Mocks the EventAccumulator and its methods."""
  with mock.patch(
    "benchmarking.tb_parser.tb_parser_lib.EventAccumulator"
  ) as mock_accumulator_cls:
    mock_accumulator = mock_accumulator_cls.return_value
    mock_accumulator.Reload.return_value = None
    mock_accumulator.Tags.return_value = {"tensors": []}
    mock_accumulator.Tensors.return_value = []
    yield mock_accumulator


# --- Tests ---


def test_parse_and_compute_success(mock_event_accumulator):
  """Tests the full end-to-end parsing and computation logic."""
  manifest = _create_metric_manifest(
    name="wall_time",
    unit="ms",
    stats=[stat_pb2.Stat.MEAN, stat_pb2.Stat.LAST_VALUE],
  )

  mock_event_accumulator.Tags.return_value = {"tensors": ["wall_time"]}
  mock_event_accumulator.Tensors.return_value = [
    _create_fake_tensor_event(10.0),
    _create_fake_tensor_event(20.0),
    _create_fake_tensor_event(30.0),
  ]

  parser = tb_parser_lib.TensorBoardParser(manifest)
  results = parser.parse_and_compute("fake_log_dir")

  assert len(results) == 2

  mean_stat = next(s for s in results if s.stat == stat_pb2.Stat.MEAN)
  last_val_stat = next(s for s in results if s.stat == stat_pb2.Stat.LAST_VALUE)

  assert mean_stat.metric_name == "wall_time"
  assert mean_stat.unit == "ms"
  assert mean_stat.value.value == 20.0  # Mean of (10, 20, 30).

  assert last_val_stat.metric_name == "wall_time"
  assert last_val_stat.value.value == 30.0  # Last value.


@pytest.mark.parametrize(
  "stat_enum, stat_name, expected_value",
  [
    (stat_pb2.Stat.MEAN, "MEAN", 3.0),
    (stat_pb2.Stat.MEDIAN, "MEDIAN", 3.0),
    (stat_pb2.Stat.P90, "P90", 4.6),
    (stat_pb2.Stat.P95, "P95", 4.8),
    (stat_pb2.Stat.P99, "P99", 4.96),
    (stat_pb2.Stat.STDDEV, "STDDEV", round(np.std(np.array([1, 2, 3, 4, 5])), 2)),
    (stat_pb2.Stat.LAST_VALUE, "LAST_VALUE", 5.0),
  ],
)
def test_all_stats_computed_correctly(
  mock_event_accumulator, stat_enum, stat_name, expected_value
):
  """Verifies that every statistic in the STAT_FN_MAP is computed correctly."""
  manifest = _create_metric_manifest("test_metric", "units", [stat_enum])

  # Create a simple [1, 2, 3, 4, 5] data vector.
  fake_data = [_create_fake_tensor_event(float(i)) for i in range(1, 6)]
  mock_event_accumulator.Tags.return_value = {"tensors": ["test_metric"]}
  mock_event_accumulator.Tensors.return_value = fake_data

  parser = tb_parser_lib.TensorBoardParser(manifest)
  results = parser.parse_and_compute("fake_log_dir")

  assert len(results) == 1
  stat_result = results[0]
  assert stat_result.stat == stat_enum
  assert stat_result.metric_name == "test_metric"
  assert pytest.approx(stat_result.value.value) == expected_value


def test_read_metrics_handles_io_error(mock_event_accumulator, capsys):
  """Tests that the script exits if EventAccumulator.Reload() fails."""
  mock_event_accumulator.Reload.side_effect = Exception("Fake I/O error")

  parser = tb_parser_lib.TensorBoardParser([])
  with pytest.raises(SystemExit):
    parser._read_tensorboard_metrics("log_dir_with_io_error")

  captured = capsys.readouterr()
  assert "Error: EventAccumulator failed to load logs" in captured.err
  assert "Fake I/O error" in captured.err


def test_read_metrics_handles_key_error(mock_event_accumulator, capsys):
  """Tests that the script exits if the tensors key is missing."""
  mock_event_accumulator.Tags.return_value = {"scalars": []}  # Missing tensors key.

  parser = tb_parser_lib.TensorBoardParser([])
  with pytest.raises(SystemExit):
    parser._read_tensorboard_metrics("log_dir_with_no_tensors")

  captured = capsys.readouterr()
  assert "Error: No tensors data found in TensorBoard logs" in captured.err


def test_parse_and_compute_skips_missing_metric(mock_event_accumulator, capsys):
  """Tests that a metric in the manifest but not the logs is skipped."""
  # Manifest asks for metric_a and metric_b.
  manifest = _create_metric_manifest("metric_a", "ms", [stat_pb2.Stat.MEAN])
  manifest.append(
    benchmark_registry_pb2.MetricSpec(
      name="metric_b",
      unit="ms",
      stats=[benchmark_registry_pb2.StatSpec(stat=stat_pb2.Stat.MEAN)],
    )
  )

  # Logs only contain data for metric_a.
  mock_event_accumulator.Tags.return_value = {"tensors": ["metric_a"]}
  mock_event_accumulator.Tensors.return_value = [_create_fake_tensor_event(10.0)]

  parser = tb_parser_lib.TensorBoardParser(manifest)
  results = parser.parse_and_compute("fake_log_dir")

  # The parser should successfully compute stats for metric_a.
  assert len(results) == 1
  assert results[0].metric_name == "metric_a"

  # It should also print a clear warning for the missing metric_b.
  captured = capsys.readouterr()
  assert "Warning: Metric metric_b defined in registry but not found" in captured.err


if __name__ == "__main__":
  sys.exit(pytest.main(sys.argv))
