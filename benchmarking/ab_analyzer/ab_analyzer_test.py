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

"""Tests for the A/B Analyzer library."""

import json
from pathlib import Path
from collections.abc import Mapping
import sys
import pytest
from google.protobuf import wrappers_pb2
from benchmarking.ab_analyzer import ab_analyzer_lib
from benchmarking.proto import benchmark_job_pb2
from benchmarking.proto import benchmark_result_pb2
from benchmarking.proto.common import metric_pb2

# --- Helper Functions ---


def make_result(
  config_id: str,
  metrics_dict: Mapping[str, Mapping[metric_pb2.Stat, float]],
  commit_sha: str = "",
) -> benchmark_result_pb2.BenchmarkResult:
  """Creates a BenchmarkResult proto from a dictionary of metrics.

  Args:
      config_id: The configuration ID for the benchmark result.
      metrics_dict: A nested mapping of {metric_name: {stat_enum: value}}.
      commit_sha: Optional commit SHA to include in the result.

  Returns:
      A populated BenchmarkResult protobuf.
  """
  res = benchmark_result_pb2.BenchmarkResult(config_id=config_id)
  if commit_sha:
    res.commit_sha = commit_sha
  for name, stats in metrics_dict.items():
    for stat_enum, val in stats.items():
      res.stats.append(
        benchmark_result_pb2.ComputedStat(
          metric_name=name, stat=stat_enum, value=wrappers_pb2.DoubleValue(value=val)
        )
      )
  return res


def make_job_with_spec(
  config_id: str,
  metric_name: str,
  stat: metric_pb2.Stat,
  threshold: float | None = None,
  direction: metric_pb2.ImprovementDirection | None = None,
):
  """Creates a BenchmarkJob proto with specific threshold config.

  Args:
      config_id: The unique identifier for the benchmark job.
      metric_name: The name of the metric to track (e.g., 'latency').
      stat: The statistic to track (e.g., metric_pb2.Stat.MEAN).
      threshold: Optional regression threshold (e.g., 0.05 for 5%).
      direction: Optional improvement direction (e.g., SMALLER_IS_BETTER).

  Returns:
      A BenchmarkJob protobuf configured with the specified metric and comparison specs.
  """
  job = benchmark_job_pb2.BenchmarkJob(config_id=config_id)

  # Create StatSpec
  stat_spec = metric_pb2.StatSpec(stat=stat)
  if threshold is not None or direction is not None:
    comp = metric_pb2.ComparisonSpec()
    if threshold is not None:
      comp.threshold.value = threshold
    if direction is not None:
      comp.improvement_direction = direction
    stat_spec.comparison.CopyFrom(comp)

  # Create MetricSpec
  metric_spec = metric_pb2.MetricSpec(name=metric_name, unit="ms")
  metric_spec.stats.append(stat_spec)

  job.metrics.append(metric_spec)
  return job


# --- Tests for File Loading ---


def test_load_results_parsing(tmp_path: Path, subtests) -> None:
  """Tests that filenames are correctly parsed into Config ID and Mode."""

  # Case 1: Happy path
  # Config: BERT-LARGE, Mode: BASELINE, JobID: 123
  p1 = tmp_path / "benchmark-result-BERT-LARGE-BASELINE-123.json"
  p1.write_text(json.dumps({"config_id": "BERT-LARGE"}))

  # Case 2: Config ID contains the word "BASELINE"
  # Config: MY-BASELINE-MODEL, Mode: EXPERIMENT, JobID: abc
  p2 = tmp_path / "benchmark-result-MY-BASELINE-MODEL-EXPERIMENT-abc.json"
  p2.write_text(json.dumps({"config_id": "MY-BASELINE-MODEL"}))

  # Case 3: Ignored File: Does not match prefix
  p4 = tmp_path / "random-file.json"
  p4.write_text("{}")

  # Run the loader
  results = ab_analyzer_lib.load_results(tmp_path)

  # Verify case 1
  with subtests.test(msg="BERT-LARGE"):
    assert "BERT-LARGE" in results
    assert benchmark_job_pb2.AbTestGroup.BASELINE in results["BERT-LARGE"]

  # Verify case 2
  with subtests.test(msg="MY-BASELINE-MODEL"):
    assert "MY-BASELINE-MODEL" in results
    assert benchmark_job_pb2.AbTestGroup.EXPERIMENT in results["MY-BASELINE-MODEL"]
    assert benchmark_job_pb2.AbTestGroup.BASELINE not in results["MY-BASELINE-MODEL"]


# --- Tests for Comparison Config Logic ---


def test_get_comparison_config_defaults():
  """Test fallback to defaults when config is missing."""
  matrix = {}
  threshold, direction = ab_analyzer_lib.get_comparison_config(
    matrix, "foo", "bar", metric_pb2.Stat.MEAN
  )

  assert threshold == 0.05
  assert direction == metric_pb2.ImprovementDirection.LESS


def test_get_comparison_config_specific():
  """Test retrieving specific thresholds from matrix map."""
  job = make_job_with_spec(
    "my_model",
    "accuracy",
    metric_pb2.Stat.MEAN,
    threshold=0.01,
    direction=metric_pb2.ImprovementDirection.GREATER,
  )
  matrix = {"my_model": job}

  threshold, direction = ab_analyzer_lib.get_comparison_config(
    matrix, "my_model", "accuracy", metric_pb2.Stat.MEAN
  )

  assert threshold == 0.01
  assert direction == metric_pb2.ImprovementDirection.GREATER


# --- Tests for Report Generation ---


def test_generate_report_pass():
  """Test a clean pass case (LESS is better, value decreased)."""
  # Baseline=100, Experiment=99 (1% improvement)
  base = make_result("test", {"latency": {metric_pb2.Stat.MEAN: 100.0}}, "sha1")
  exp = make_result("test", {"latency": {metric_pb2.Stat.MEAN: 99.0}}, "sha2")

  results = {
    "test": {
      benchmark_job_pb2.AbTestGroup.BASELINE: base,
      benchmark_job_pb2.AbTestGroup.EXPERIMENT: exp,
    }
  }
  matrix = {}  # Defaults: 5% threshold, LESS

  report, success = ab_analyzer_lib.generate_report(
    results, matrix, "http://repo", "TestFlow"
  )

  assert success is True
  assert "PASS" in report
  assert "**Global Status:** PASS" in report


def test_generate_report_fail_latency():
  """Test regression in latency (LESS is better, value increased > 5%)."""
  # Baseline=100, Experiment=110 (10% regression)
  base = make_result("test", {"latency": {metric_pb2.Stat.P99: 100.0}}, "sha1")
  exp = make_result("test", {"latency": {metric_pb2.Stat.P99: 110.0}}, "sha2")

  results = {
    "test": {
      benchmark_job_pb2.AbTestGroup.BASELINE: base,
      benchmark_job_pb2.AbTestGroup.EXPERIMENT: exp,
    }
  }
  matrix = {}  # Defaults: 5% threshold, LESS

  report, success = ab_analyzer_lib.generate_report(
    results, matrix, "http://repo", "TestFlow"
  )

  assert success is False
  assert "REGRESSION" in report
  assert "**Global Status:** FAIL" in report


def test_generate_report_fail_accuracy():
  """Test regression in accuracy (GREATER is better, value decreased)."""
  # Baseline=0.90, Experiment=0.80
  base = make_result("test", {"accuracy": {metric_pb2.Stat.MEAN: 0.90}}, "sha1")
  exp = make_result("test", {"accuracy": {metric_pb2.Stat.MEAN: 0.80}}, "sha2")

  results = {
    "test": {
      benchmark_job_pb2.AbTestGroup.BASELINE: base,
      benchmark_job_pb2.AbTestGroup.EXPERIMENT: exp,
    }
  }
  job = make_job_with_spec(
    "test",
    "accuracy",
    metric_pb2.Stat.MEAN,
    direction=metric_pb2.ImprovementDirection.GREATER,
  )
  matrix = {"test": job}

  report, success = ab_analyzer_lib.generate_report(
    results, matrix, "http://repo", "TestFlow"
  )

  assert success is False
  assert "REGRESSION" in report


def test_generate_report_undetermined():
  """Test the zero-baseline edge case (Undetermined)."""
  # Baseline=0, Experiment=1
  base = make_result("test", {"errors": {metric_pb2.Stat.MEAN: 0.0}}, "sha1")
  exp = make_result("test", {"errors": {metric_pb2.Stat.MEAN: 1.0}}, "sha2")

  results = {
    "test": {
      benchmark_job_pb2.AbTestGroup.BASELINE: base,
      benchmark_job_pb2.AbTestGroup.EXPERIMENT: exp,
    }
  }
  matrix = {}

  report, success = ab_analyzer_lib.generate_report(
    results, matrix, "http://repo", "TestFlow"
  )

  # Should warn but not fail
  assert success is True
  assert "UNDETERMINED" in report
  assert "∞" in report


def test_missing_experiment_fails():
  """Test that missing experiment data causes a global FAIL."""
  base = make_result("broken_exp", {"latency": {metric_pb2.Stat.MEAN: 100.0}}, "sha1")
  results = {
    "broken_exp": {
      benchmark_job_pb2.AbTestGroup.BASELINE: base
      # Missing experiment
    }
  }

  report, success = ab_analyzer_lib.generate_report(
    results, {}, "http://repo", "TestFlow"
  )

  assert success is False
  assert "FAILED (Experiment Missing)" in report
  assert "**Global Status:** FAIL" in report


def test_missing_baseline_warns():
  """Test that missing baseline data causes a PASS with warning."""
  exp = make_result("broken_base", {"latency": {metric_pb2.Stat.MEAN: 100.0}}, "sha2")
  results = {
    "broken_base": {
      # Missing baseline
      benchmark_job_pb2.AbTestGroup.EXPERIMENT: exp
    }
  }

  report, success = ab_analyzer_lib.generate_report(
    results, {}, "http://repo", "TestFlow"
  )

  assert success is True
  assert "Incomplete (Baseline Missing)" in report
  assert "**Global Status:** PASS" in report


def test_link_generation():
  """Test that commit links are generated correctly."""
  res = benchmark_result_pb2.BenchmarkResult()
  res.commit_sha = "abcdef1234567890"
  res.run_url = "https://github.com/org/repo/actions/runs/123"

  link = ab_analyzer_lib.get_commit_link_markdown(res, "https://github.com/org/repo")
  assert link == "[abcdef1](https://github.com/org/repo/commit/abcdef1234567890)"


if __name__ == "__main__":
  sys.exit(pytest.main(sys.argv))
