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
from typing import TypeAlias
from collections.abc import Mapping
from google.protobuf import json_format
from benchmarking.proto import benchmark_job_pb2
from benchmarking.proto import benchmark_result_pb2
from benchmarking.proto.common import metric_pb2

# Maps A/B group to benchmark result.
AbGroupResultMap: TypeAlias = Mapping[
  benchmark_job_pb2.AbTestGroup, benchmark_result_pb2.BenchmarkResult
]

# Maps config_id to a set of A/B groups.
ResultMapping: TypeAlias = Mapping[str, AbGroupResultMap]


def load_results(results_dir: Path) -> ResultMapping:
  """Scans the results directory and deserializes benchmark result artifacts into protos.

  Expected benchmark result file naming convention:
      benchmark-result-{CONFIG_ID}-{MODE}-{JOB_ID}.json

  Parsing Logic:
      1. Scans for filenames matching "benchmark-result-*.json".
      2. Identifies the mode ("BASELINE" or "EXPERIMENT") by finding the last occurrence
         of the keyword.
      3. Extracts the Config ID from the segment between the prefix and the mode.

  Args:
      results_dir: The directory path containing downloaded benchmark artifacts.

  Returns:
      A mapping where keys are configuration IDs and values are dictionaries mapping
      the A/B mode ('baseline' or 'experiment') to the deserialized BenchmarkResult proto.

  Raises:
      ValueError: If a result file contains invalid JSON or cannot be parsed into
          the expected protobuf format.
  """
  results = {}

  # Benchmark result artifact naming convention:
  # benchmark-result-{CONFIG}[-{AB_MODE}]-{JOB_ID}.json
  for path in results_dir.rglob("benchmark-result-*.json"):
    filename = path.stem
    base_idx = filename.rfind("-BASELINE-")
    exp_idx = filename.rfind("-EXPERIMENT-")

    if base_idx == -1 and exp_idx == -1:
      continue

    if base_idx > exp_idx:
      mode = benchmark_job_pb2.AbTestGroup.BASELINE
      head = filename[:base_idx]
    else:
      mode = benchmark_job_pb2.AbTestGroup.EXPERIMENT
      head = filename[:exp_idx]

    prefix = "benchmark-result-"
    config_id = head[len(prefix) :]

    if config_id not in results:
      results[config_id] = {}

    try:
      with open(path, "r") as f:
        json_data = json.load(f)

      result_proto = benchmark_result_pb2.BenchmarkResult()
      json_format.ParseDict(json_data, result_proto, ignore_unknown_fields=True)
      results[config_id][mode] = result_proto

    except json.JSONDecodeError as e:
      raise ValueError(f"Error decoding JSON for {path}: {e}") from e
    except json_format.ParseError as e:
      raise ValueError(f"Error parsing proto for {path}: {e}") from e

  return results


def get_comparison_config(
  matrix_map: Mapping[str, benchmark_job_pb2.BenchmarkJob],
  config_id: str,
  metric_name: str,
  stat: metric_pb2.Stat,
) -> tuple[float, metric_pb2.ImprovementDirection]:
  """Retrieves the comparison threshold and improvement direction for a specific metric.

  Args:
      matrix_map: A mapping of configuration IDs to BenchmarkJob definitions.
      config_id: The unique identifier for the benchmark configuration.
      metric_name: The name of the metric to look up (e.g., 'latency').
      stat: The specific statistic (e.g., MEDIAN, P99) to look up.

  Returns:
      A tuple containing:
      - threshold (float): The allowed regression threshold (e.g., 0.05 for 5%).
      - direction (ImprovementDirection): The direction that indicates improvement.
  """

  default_threshold = 0.05
  default_direction = metric_pb2.ImprovementDirection.LESS

  job = matrix_map.get(config_id)
  if not job:
    return default_threshold, default_direction

  metric_spec = next((m for m in job.metrics if m.name == metric_name), None)
  if not metric_spec:
    return default_threshold, default_direction

  stat_spec = next((s for s in metric_spec.stats if s.stat == stat), None)
  if not stat_spec or not stat_spec.HasField("comparison"):
    return default_threshold, default_direction

  comp = stat_spec.comparison
  threshold = comp.threshold.value if comp.HasField("threshold") else default_threshold
  direction = (
    comp.improvement_direction
    if comp.improvement_direction
    != metric_pb2.ImprovementDirection.IMPROVEMENT_DIRECTION_UNSPECIFIED
    else default_direction
  )

  return threshold, direction


def get_commit_link_markdown(
  result_proto: benchmark_result_pb2.BenchmarkResult, repo_url: str
) -> str:
  """Generates a Markdown-formatted link to a specific commit.

  Args:
      result_proto: The benchmark result protobuf containing the commit SHA.
      repo_url: The base URL of the source repository (e.g., "https://github.com/org/repo").

  Returns:
      A Markdown string linking to the commit (e.g., "[abcdef1](.../commit/abcdef1...)").
      Returns "unknown" if the commit SHA is missing from the result.
  """
  if not result_proto.commit_sha:
    return "unknown"

  full_sha = result_proto.commit_sha
  short_sha = full_sha[:7]

  # Remove trailing slashes from repo_url just in case
  clean_repo_url = repo_url.rstrip("/")

  return f"[{short_sha}]({clean_repo_url}/commit/{full_sha})"


def generate_report(
  results: ResultMapping,
  matrix_map: Mapping[str, benchmark_job_pb2.BenchmarkJob],
  repo_url: str,
  workflow_name: str,
) -> tuple[str, bool]:
  """Generates a Markdown report string and a success status.

  Args:
      results: A mapping of configuration IDs to A/B groups (baseline/experiment).
      matrix_map: A mapping of configuration IDs to BenchmarkJob definitions, used to
        retrieve threshold and comparison settings.
      repo_url: The base URL of the repository, used to generate commit links.
      workflow_name: The name of the workflow to display in the report header.

  Returns:
      A tuple containing:
      - report_content (str): The full Markdown report string.
      - success (bool): True if no regressions or failures were detected, False otherwise.

  Raises:
      ValueError: If the results mapping is empty.
  """
  lines: list[str] = [f"## A/B Benchmark Results: {workflow_name}"]
  global_success: bool = True

  if not results:
    raise ValueError("No A/B benchmark results found.")

  for config_id, result in results.items():
    baseline_result = result.get(benchmark_job_pb2.AbTestGroup.BASELINE)
    experiment_result = result.get(benchmark_job_pb2.AbTestGroup.EXPERIMENT)

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

    base_stats: Mapping[tuple[str, metric_pb2.Stat], float] = {
      (s.metric_name, s.stat): s.value.value for s in baseline_result.stats
    }
    exp_stats: Mapping[tuple[str, metric_pb2.Stat], float] = {
      (s.metric_name, s.stat): s.value.value for s in experiment_result.stats
    }

    for (metric_name, stat), exp_val in exp_stats.items():
      base_val = base_stats.get((metric_name, stat))
      stat_name = metric_pb2.Stat.Name(stat)
      display_name = f"{metric_name} <small>({stat_name})</small>"
      threshold, direction = get_comparison_config(
        matrix_map, config_id, metric_name, stat
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
