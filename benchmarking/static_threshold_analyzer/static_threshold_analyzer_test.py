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

"""Tests for the static threshold analyzer library."""

import sys
from typing import List
from unittest import mock
import pytest
from google.protobuf import timestamp_pb2
from benchmarking.proto import benchmark_result_pb2
from benchmarking.proto.common import metric_pb2
from benchmarking.static_threshold_analyzer.static_threshold_analyzer_lib import (
  StaticAnalyzer,
)

# --- Helper Functions ---


def _create_metric_specs(
  stats: List[metric_pb2.StatSpec],
) -> List[metric_pb2.MetricSpec]:
  """Helper to build a simple MetricSpecs list."""
  return [
    metric_pb2.MetricSpec(
      name="wall_time",
      unit="ms",
      stats=stats,
    )
  ]


def _create_benchmark_result(
  computed_stats: List[benchmark_result_pb2.ComputedStat],
) -> benchmark_result_pb2.BenchmarkResult:
  """Helper to build a simple BenchmarkResult."""
  ts = timestamp_pb2.Timestamp()
  ts.GetCurrentTime()
  return benchmark_result_pb2.BenchmarkResult(
    config_id="test_config_id",
    commit_sha="test_sha",
    run_timestamp=ts,
    stats=computed_stats,
    github_run_id=12345,
  )


def _create_computed_stat(
  name: str, stat: metric_pb2.Stat, value: float
) -> benchmark_result_pb2.ComputedStat:
  """Helper to build a single ComputedStat."""
  return benchmark_result_pb2.ComputedStat(
    metric_name=name,
    stat=stat,
    value={"value": value},
    unit="ms",
  )


# --- Tests for Regression Logic ---


@pytest.mark.parametrize(
  "current_value, direction, should_regress",
  [
    # --- LESS is better (e.g., latency) ---
    (111.0, metric_pb2.ImprovementDirection.LESS, True),
    (109.0, metric_pb2.ImprovementDirection.LESS, False),
    (90.0, metric_pb2.ImprovementDirection.LESS, False),
    # --- GREATER is better (e.g., throughput) ---
    (89.0, metric_pb2.ImprovementDirection.GREATER, True),
    (91.0, metric_pb2.ImprovementDirection.GREATER, False),
    (110.0, metric_pb2.ImprovementDirection.GREATER, False),
    # --- No direction ---
    (
      111.0,
      metric_pb2.ImprovementDirection.IMPROVEMENT_DIRECTION_UNSPECIFIED,
      True,
    ),
    (
      89.0,
      metric_pb2.ImprovementDirection.IMPROVEMENT_DIRECTION_UNSPECIFIED,
      True,
    ),
    (
      109.0,
      metric_pb2.ImprovementDirection.IMPROVEMENT_DIRECTION_UNSPECIFIED,
      False,
    ),
    (
      91.0,
      metric_pb2.ImprovementDirection.IMPROVEMENT_DIRECTION_UNSPECIFIED,
      False,
    ),
  ],
)
def test_is_regression_logic(current_value, direction, should_regress):
  """Verifies that the core _is_regression logic is correct."""
  # Test against a baseline of 100 with a 10% threshold
  metric_specs = [
    metric_pb2.MetricSpec(
      name="wall_time",
      unit="ms",
      stats=[
        metric_pb2.StatSpec(
          stat=metric_pb2.Stat.MEAN,
          comparison=metric_pb2.ComparisonSpec(
            baseline={"value": 100.0},
            threshold={"value": 0.1},
            improvement_direction=direction,
          ),
        )
      ],
    )
  ]

  result = _create_benchmark_result(
    computed_stats=[
      _create_computed_stat("wall_time", metric_pb2.Stat.MEAN, current_value)
    ]
  )

  analyzer = StaticAnalyzer(metric_specs)
  analyzer.run_analysis(result)

  assert (len(analyzer.regressions) == 1) == should_regress


def test_no_comparison_spec_is_skipped():
  """Tests that a stat with no comparison block is skipped."""
  metric_specs = _create_metric_specs(
    stats=[metric_pb2.StatSpec(stat=metric_pb2.Stat.MEAN)]  # No comparison
  )
  result = _create_benchmark_result(
    computed_stats=[_create_computed_stat("wall_time", metric_pb2.Stat.MEAN, 150.0)]
  )

  analyzer = StaticAnalyzer(metric_specs)
  analyzer.run_analysis(result)

  assert len(analyzer.regressions) == 0


def test_stat_not_found_in_result(capsys):
  """Tests that a stat in the specs but not in the result is skipped."""
  metric_specs = _create_metric_specs(
    stats=[
      metric_pb2.StatSpec(
        stat=metric_pb2.Stat.MEAN,  # This is missing from the result
        comparison=metric_pb2.ComparisonSpec(
          baseline={"value": 100.0},
          threshold={"value": 0.1},
          improvement_direction=metric_pb2.ImprovementDirection.LESS,
        ),
      )
    ]
  )
  result = _create_benchmark_result(
    computed_stats=[
      _create_computed_stat("wall_time", metric_pb2.Stat.P99, 150.0)
    ]  # Only P99
  )

  analyzer = StaticAnalyzer(metric_specs)
  analyzer.run_analysis(result)

  assert len(analyzer.regressions) == 0
  captured = capsys.readouterr()
  assert (
    "Skipping check for wall_time (MEAN): Computed statistic not found" in captured.err
  )


# --- Tests for Reporting Logic ---


def test_report_results_success(capsys):
  """Tests that a successful run prints the PASSED message to stdout."""
  analyzer = StaticAnalyzer(metric_specs=[])
  analyzer.run_analysis(_create_benchmark_result([]))
  analyzer.report_results()

  captured = capsys.readouterr()
  assert "PASSED" in captured.out
  assert "FAILED" not in captured.err


def test_report_results_failure(capsys):
  """Tests that a failed run prints error messages and exits with code 1."""
  metric_specs = _create_metric_specs(
    stats=[
      metric_pb2.StatSpec(
        stat=metric_pb2.Stat.MEAN,
        comparison=metric_pb2.ComparisonSpec(
          baseline={"value": 100.0},
          threshold={"value": 0.1},
          improvement_direction=metric_pb2.ImprovementDirection.LESS,
        ),
      )
    ]
  )
  result = _create_benchmark_result(
    computed_stats=[_create_computed_stat("wall_time", metric_pb2.Stat.MEAN, 150.0)]
  )

  analyzer = StaticAnalyzer(metric_specs)
  analyzer.run_analysis(result)

  # Mock sys.exit to prevent the test runner from stopping.
  with mock.patch("sys.exit") as mock_exit:
    analyzer.report_results()

  mock_exit.assert_called_with(1)
  captured = capsys.readouterr()
  assert "Regressed to 150.00ms (Baseline: 100.00ms ±10.00%)" in captured.err


if __name__ == "__main__":
  sys.exit(pytest.main(sys.argv))
