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

"""Library for analyzing A/B benchmark results."""

import json
import sys
from pathlib import Path
from typing import Dict, Tuple
from google.protobuf import json_format
from benchmarking.proto import benchmark_job_pb2
from benchmarking.proto import benchmark_result_pb2
from benchmarking.proto.common import metric_pb2

# Type definition: Map[config_id, Map[mode, BenchmarkResultProto]]
ResultPairs = Dict[str, Dict[str, benchmark_result_pb2.BenchmarkResult]]


def load_results(results_dir: str) -> ResultPairs:
  """Scans the results directory and deserializes benchmark artifacts into protos.

  Expected benchmark result file naming convention:
    benchmark-result-{CONFIG_ID}-{MODE}-{JOB_ID}.json

  Parsing Logic:
    1. We strictly scan for filenames matching "benchmark-result-*.json".
    2. We assume {JOB_ID} (the suffix) does NOT contain "-BASELINE-" or "-EXPERIMENT-".
    3. We split the string at the last occurrence of the mode keyword.
  """
  pairs = {}
  root = Path(results_dir)

  for path in root.rglob("benchmark-result-*.json"):
    filename = path.stem

    # Find the last index of both keywords
    base_idx = filename.rfind("-BASELINE-")
    exp_idx = filename.rfind("-EXPERIMENT-")

    if base_idx == -1 and exp_idx == -1:
      continue

    # Determine mode based on which keyword is furthest to the right
    if base_idx > exp_idx:
      mode = "baseline"
      head = filename[:base_idx]
    else:
      mode = "experiment"
      head = filename[:exp_idx]

    # Strictly strip the prefix (guaranteed to exist by rglob)
    prefix = "benchmark-result-"
    config_id = head[len(prefix) :]

    if config_id not in pairs:
      pairs[config_id] = {}

    try:
      with open(path, "r") as f:
        json_data = json.load(f)

      result_proto = benchmark_result_pb2.BenchmarkResult()
      json_format.ParseDict(json_data, result_proto, ignore_unknown_fields=True)
      pairs[config_id][mode] = result_proto

    except json.JSONDecodeError as e:
      print(f"Error decoding JSON for {path}: {e}", file=sys.stderr)
    except json_format.ParseError as e:
      print(f"Error parsing Proto for {path}: {e}", file=sys.stderr)

  return pairs


def get_comparison_config(
  matrix_map: Dict[str, benchmark_job_pb2.BenchmarkJob],
  config_id: str,
  metric_name: str,
  stat_enum: int,
) -> Tuple[float, int]:
  """Retrieves threshold and improvement direction (Enum int) for a specific Metric + Stat pair."""

  DEFAULT_THRESHOLD = 0.05
  DEFAULT_DIRECTION = metric_pb2.ImprovementDirection.LESS

  job = matrix_map.get(config_id)
  if not job:
    return DEFAULT_THRESHOLD, DEFAULT_DIRECTION

  metric_spec = next((m for m in job.metrics if m.name == metric_name), None)
  if not metric_spec:
    return DEFAULT_THRESHOLD, DEFAULT_DIRECTION

  stat_spec = next((s for s in metric_spec.stats if s.stat == stat_enum), None)
  if not stat_spec or not stat_spec.HasField("comparison"):
    return DEFAULT_THRESHOLD, DEFAULT_DIRECTION

  comp = stat_spec.comparison
  threshold = comp.threshold.value if comp.HasField("threshold") else DEFAULT_THRESHOLD
  direction = (
    comp.improvement_direction
    if comp.improvement_direction
    != metric_pb2.ImprovementDirection.IMPROVEMENT_DIRECTION_UNSPECIFIED
    else DEFAULT_DIRECTION
  )

  return threshold, direction


def generate_report(
  pairs: ResultPairs, matrix_map: Dict[str, benchmark_job_pb2.BenchmarkJob]
) -> Tuple[str, bool]:
  """Generates a Markdown report string and a success status."""
  lines = ["## A/B Benchmark Results"]
  global_success = True

  if not pairs:
    lines.append("\n_No A/B benchmark results found._")
    return "\n".join(lines), True

  for config_id, pair in pairs.items():
    baseline_result = pair.get("baseline")
    experiment_result = pair.get("experiment")

    # Critical failure: Experiment missing
    if not experiment_result:
      lines.append(f"\n### {config_id}: FAILED (Experiment Missing)")
      lines.append("The experiment benchmark job failed to produce results.")
      global_success = False
      continue

    # Warning: Baseline missing
    if not baseline_result:
      lines.append(f"\n### {config_id}: Incomplete (Baseline Missing)")
      lines.append(
        "Valid comparison could not be made because the Baseline job failed."
      )
      continue

    lines.append(f"\n### {config_id}")
    lines.append("| Metric | Baseline | Experiment | Delta | Threshold | Status |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

    # Convert stats list to map
    base_stats = {(s.metric_name, s.stat): s.value.value for s in baseline_result.stats}
    exp_stats = {
      (s.metric_name, s.stat): s.value.value for s in experiment_result.stats
    }

    # Iterate through experiment stats
    for (metric_name, stat_enum), exp_val in exp_stats.items():
      base_val = base_stats.get((metric_name, stat_enum))
      stat_name = metric_pb2.Stat.Name(stat_enum)
      display_name = f"{metric_name} <small>({stat_name})</small>"
      threshold, direction = get_comparison_config(
        matrix_map, config_id, metric_name, stat_enum
      )

      if base_val is None:
        delta_str = "N/A"
        base_str = "-"
        status = "NEW"

      elif base_val == 0:
        base_str = "0"
        if exp_val == 0:
          delta_str = "0.00%"
          status = "PASS"
        else:
          delta_str = "∞"
          status = "UNDETERMINED"

      else:
        delta = (exp_val - base_val) / base_val
        delta_str = f"{delta:+.2%}"
        base_str = f"{base_val:.4f}"

        # Check for regression
        is_regression = False
        if direction == metric_pb2.ImprovementDirection.LESS:
          # Lower is better: Fail if we increased by more than threshold
          if delta > threshold:
            is_regression = True
        else:
          # Higher is better: Fail if we decreased by more than threshold
          if delta < -threshold:
            is_regression = True

        if is_regression:
          status = "REGRESSION"
          global_success = False
        else:
          status = "PASS"

      lines.append(
        f"| {display_name} | {base_str} | {exp_val:.4f} | {delta_str} | {threshold:.0%} | {status} |"
      )

  status_msg = "PASS" if global_success else "FAIL"
  lines.append(f"\n**Global Status:** {status_msg}")

  return "\n".join(lines), global_success
