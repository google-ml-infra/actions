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
from pathlib import Path
from typing import Dict, Tuple
from google.protobuf import json_format
from benchmarking.proto import benchmark_job_pb2
from benchmarking.proto import benchmark_result_pb2
from benchmarking.proto.common import metric_pb2

# Map[config_id, Map[mode, BenchmarkResultProto]]
ResultPairs = Dict[str, Dict[str, benchmark_result_pb2.BenchmarkResult]]


def load_results(results_dir: Path) -> ResultPairs:
  """Scans the results directory and deserializes benchmark result artifacts into protos."""
  pairs = {}

  # Benchmark result artifact naming convention:
  # benchmark-result-{CONFIG}[-{AB_MODE}]-{JOB_ID}.json
  for path in results_dir.rglob("benchmark-result-*.json"):
    filename = path.stem
    base_idx = filename.rfind("-BASELINE-")
    exp_idx = filename.rfind("-EXPERIMENT-")

    if base_idx == -1 and exp_idx == -1:
      continue

    if base_idx > exp_idx:
      mode = "baseline"
      head = filename[:base_idx]
    else:
      mode = "experiment"
      head = filename[:exp_idx]

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
      raise ValueError(f"Error decoding JSON for {path}: {e}") from e
    except json_format.ParseError as e:
      raise ValueError(f"Error parsing proto for {path}: {e}") from e

  return pairs


def get_comparison_config(
  matrix_map: Dict[str, benchmark_job_pb2.BenchmarkJob],
  config_id: str,
  metric_name: str,
  stat_enum: int,
) -> Tuple[float, int]:
  """Retrieves threshold and improvement direction (Enum int)."""

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


def get_commit_link_markdown(
  result_proto: benchmark_result_pb2.BenchmarkResult, repo_url: str
) -> str:
  """Generates a Markdown link to the commit: [short_sha](repo_url/commit/full_sha)."""
  if not result_proto.commit_sha:
    return "unknown"

  full_sha = result_proto.commit_sha
  short_sha = full_sha[:7]

  # Remove trailing slashes from repo_url just in case
  clean_repo_url = repo_url.rstrip("/")

  return f"[{short_sha}]({clean_repo_url}/commit/{full_sha})"


def generate_report(
  pairs: ResultPairs,
  matrix_map: Dict[str, benchmark_job_pb2.BenchmarkJob],
  repo_url: str,
  workflow_name: str,
) -> Tuple[str, bool]:
  """Generates a Markdown report string and a success status."""
  lines = [f"## A/B Benchmark Results: {workflow_name}"]
  global_success = True

  if not pairs:
    lines.append("\n_No A/B benchmark results found._")
    return "\n".join(lines), True

  for config_id, pair in pairs.items():
    baseline_result = pair.get("baseline")
    experiment_result = pair.get("experiment")

    if not experiment_result:
      lines.append(f"\n### {config_id}: FAILED (Experiment Missing)")
      lines.append("The experiment benchmark job failed to produce results.")
      global_success = False
      continue

    if not baseline_result:
      lines.append(f"\n### {config_id}: Incomplete (Baseline Missing)")
      lines.append(
        "Valid comparison could not be made because the Baseline job failed."
      )
      continue

    # Extract commit links
    base_link = get_commit_link_markdown(baseline_result, repo_url)
    exp_link = get_commit_link_markdown(experiment_result, repo_url)

    lines.append(f"\n### {config_id}")

    # Header
    lines.append(
      f"| Metric | Baseline <br> ({base_link}) | Experiment <br> ({exp_link}) | Delta | Threshold | Status |"
    )
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

    base_stats = {(s.metric_name, s.stat): s.value.value for s in baseline_result.stats}
    exp_stats = {
      (s.metric_name, s.stat): s.value.value for s in experiment_result.stats
    }

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

        is_regression = False
        if direction == metric_pb2.ImprovementDirection.LESS:
          if delta > threshold:
            is_regression = True
        else:
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
