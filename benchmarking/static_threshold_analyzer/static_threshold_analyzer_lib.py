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

"""
Library for performing static threshold analysis on a benchmark result.
"""

import sys
from typing import Dict, List, Union, TypedDict
from benchmarking.proto import benchmark_registry_pb2
from benchmarking.proto import benchmark_result_pb2
from benchmarking.proto.common import stat_pb2

ResultMap = Dict[tuple[str, str], benchmark_result_pb2.ComputedStat]
MetricManifest = List[benchmark_registry_pb2.MetricSpec]


class Regression(TypedDict):
  """Defines the structure for a reported regression."""

  config_id: str
  metric: str
  stat: str
  current: Union[int, float]
  baseline: Union[int, float]
  threshold: float
  unit: str


def _is_regression(
  current_value: float,
  baseline: float,
  threshold: float,
  direction: benchmark_registry_pb2.ImprovementDirection,
) -> bool:
  """Checks if a metric value constitutes a performance regression."""
  tolerance = baseline * threshold

  if direction == benchmark_registry_pb2.ImprovementDirection.LESS:
    return current_value > (baseline + tolerance)

  elif direction == benchmark_registry_pb2.ImprovementDirection.GREATER:
    return current_value < (baseline - tolerance)

  else:
    return abs(current_value - baseline) > tolerance


class StaticAnalyzer:
  """Performs static threshold analysis on a benchmark result."""

  def __init__(self, metric_manifest: MetricManifest):
    """Initializes the analyzer with the metric manifest."""
    self.metric_manifest = metric_manifest
    self.regressions: List[Regression] = []

  def run_analysis(self, benchmark_result: benchmark_result_pb2.BenchmarkResult):
    """Run the threshold comparison."""
    result_map: ResultMap = {
      (stat.metric_name, stat_pb2.Stat.Name(stat.stat)): stat
      for stat in benchmark_result.stats
    }

    for metric_spec in self.metric_manifest:
      for stat_spec in metric_spec.stats:
        # Only perform the check if comparison rules are defined.
        if stat_spec.HasField("comparison"):
          comparison = stat_spec.comparison
          stat_name = stat_pb2.Stat.Name(stat_spec.stat)
          key = (metric_spec.name, stat_name)

          if key not in result_map:
            print(
              f"Warning: Skipping check for {metric_spec.name} ({stat_name}): Computed statistic not found in artifact.",
              file=sys.stderr,
            )
            continue

          result_stat = result_map[key]
          current_value = result_stat.value.value
          unit = result_stat.unit

          baseline = comparison.baseline.value
          threshold = comparison.threshold.value
          direction = comparison.improvement_direction

          if _is_regression(current_value, baseline, threshold, direction):
            self.regressions.append({
              "config_id": benchmark_result.config_id,
              "metric": metric_spec.name,
              "stat": stat_name,
              "current": current_value,
              "baseline": baseline,
              "threshold": threshold * 100,
              "unit": unit,
            })

  def report_results(self):
    """Reports results to stdout/stderr and terminates with failure if regressions were found."""
    if self.regressions:
      print(
        "Static threshold check FAILED. Performance regressions detected.",
        file=sys.stderr,
      )
      for r in self.regressions:
        msg = (
          f"[{r['config_id']}] {r['metric']} ({r['stat']}): "
          f"Regressed to {r['current']:.2f}{r['unit']} "
          f"(Baseline: {r['baseline']:.2f}{r['unit']} ±{r['threshold']:.2f}%)."
        )
        print(f"{msg}", file=sys.stderr)
      sys.exit(1)
    else:
      print(
        "Static threshold check PASSED. No performance regressions detected.",
        file=sys.stdout,
      )
