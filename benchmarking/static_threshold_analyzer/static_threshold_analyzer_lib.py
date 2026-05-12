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
import re
from typing import Dict, List, Union, TypedDict
from benchmarking.proto import benchmark_result_pb2
from benchmarking.proto.common import metric_pb2

ResultMap = Dict[tuple[str, str], benchmark_result_pb2.ComputedStat]
MetricSpecs = List[metric_pb2.MetricSpec]


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
  direction: metric_pb2.ImprovementDirection,
) -> bool:
  """Checks if a metric value constitutes a performance regression."""
  tolerance = baseline * threshold

  if direction == metric_pb2.ImprovementDirection.LESS:
    return current_value > (baseline + tolerance)

  elif direction == metric_pb2.ImprovementDirection.GREATER:
    return current_value < (baseline - tolerance)

  else:
    # If direction is unspecified, we treat it as a strict equality check with tolerance
    return abs(current_value - baseline) > tolerance


class StaticAnalyzer:
  """Performs static threshold analysis on a benchmark result."""

  def __init__(self, metric_specs: MetricSpecs):
    """Initializes the analyzer with the metric specifications."""
    self.metric_specs = metric_specs
    self.regressions: List[Regression] = []

  def run_analysis(self, benchmark_result: benchmark_result_pb2.BenchmarkResult):
    """Run the threshold comparison."""
    result_map: ResultMap = {
      (stat.metric_name, metric_pb2.Stat.Name(stat.stat)): stat
      for stat in benchmark_result.stats
    }

    for metric_spec in self.metric_specs:
      id_type = metric_spec.WhichOneof("identifier")

      for stat_spec in metric_spec.stats:
        # Only perform the check if comparison rules are defined.
        if stat_spec.HasField("comparison"):
          comparison = stat_spec.comparison
          stat_name = metric_pb2.Stat.Name(stat_spec.stat)

          # Find all matching concrete metric names from the parsed results
          matched_concrete_metrics = []
          if id_type == "name":
            if (metric_spec.name, stat_name) in result_map:
              matched_concrete_metrics.append(metric_spec.name)
          elif id_type == "pattern":
            regex = re.compile(metric_spec.pattern)
            for res_metric_name, res_stat_name in result_map.keys():
              if res_stat_name == stat_name and regex.search(res_metric_name):
                matched_concrete_metrics.append(res_metric_name)

          if not matched_concrete_metrics:
            identifier = (
              metric_spec.pattern if id_type == "pattern" else metric_spec.name
            )
            print(
              f"Warning: Skipping check for {identifier} ({stat_name}): Computed statistic not found in artifact.",
              file=sys.stderr,
            )
            continue

          for concrete_metric in matched_concrete_metrics:
            result_stat = result_map[(concrete_metric, stat_name)]
            current_value = result_stat.value.value
            unit = result_stat.unit

            baseline = comparison.baseline.value
            threshold = comparison.threshold.value
            direction = comparison.improvement_direction

            if _is_regression(current_value, baseline, threshold, direction):
              self.regressions.append({
                "config_id": benchmark_result.config_id,
                "metric": concrete_metric,
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
