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

"""Library for extracting statistics from TensorFlow event files.

This library parses raw scalar data from TensorFlow event files (tfevents) and
computes summary statistics (e.g., Mean, P99) as defined in the provided
MetricSpecs. It outputs a list of ComputedStat protos.
"""

import sys
import re
from typing import List, Dict, Set
import numpy as np
import tensorflow as tf
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
from benchmarking.proto import benchmark_result_pb2
from benchmarking.proto.common import metric_pb2

MetricSpecs = List[metric_pb2.MetricSpec]

# A map from the Stat enum string name to the corresponding numpy function.
STAT_FN_MAP = {
  "MEAN": np.mean,
  "MEDIAN": np.median,
  "P90": lambda v: np.percentile(v, 90),
  "P95": lambda v: np.percentile(v, 95),
  "P99": lambda v: np.percentile(v, 99),
  "STDDEV": np.std,
  "LAST_VALUE": lambda v: v[-1],
}


class TensorBoardParser:
  """Parses TB logs based on metric specifications and creates a benchmark result artifact.

  Supported Summary Formats:
    1. V1 (Legacy/Scalar): Used by `tensorboardX`, and TF 1.x.
       Data is stored in the `simple_value` float field.
    2. V2 (TensorFlow 2.x): Used by native TensorFlow 2.x.
       Data is stored in the `tensor` field (serialized TensorProto).

  Note: This parser ONLY supports scalar metrics (single floating-point numbers).
  It ignores histograms, images, audio, and other complex data types.
  """

  def __init__(self, metric_specs: MetricSpecs):
    """Initializes the parser with the metric specifications.

    Args:
      metric_specs: A list of `MetricSpec` Protobuf messages.
    """
    self.metric_specs = metric_specs

  def _read_tensorboard_metrics(self, tblog_dir: str) -> Dict[str, List[float]]:
    """Reads scalar data for tracked metrics from both V1 and V2 buckets.

    We explicitly check both 'scalars' and 'tensors' buckets because:
    - `tensorboardX` (and TF 1.x) writes to the `simple_value` field -> 'scalars' bucket.
    - TF 2.x writes to the `tensor` field -> 'tensors' bucket.
    """
    raw_data = {}

    try:
      # Load both 'tensors' (TF V2) and 'scalars' (TBX/TF V1)
      accumulator = EventAccumulator(
        tblog_dir, size_guidance={"tensors": 0, "scalars": 0}
      )
      accumulator.Reload()
    except Exception as e:
      print(
        f"Error: EventAccumulator failed to load logs from '{tblog_dir}'. "
        f"Are event files present and valid? Error: {e}",
        file=sys.stderr,
      )
      sys.exit(1)

    # Get available tags from both sources
    tags = accumulator.Tags()
    available_scalars = set(tags.get("scalars", []))
    available_tensors = set(tags.get("tensors", []))
    all_available_tags = available_scalars | available_tensors

    # Resolve concrete tags to extract based on oneof identifier (name or pattern)
    tags_to_extract: Set[str] = set()
    for spec in self.metric_specs:
      id_type = spec.WhichOneof("identifier")
      if id_type == "name":
        if spec.name in all_available_tags:
          tags_to_extract.add(spec.name)
      elif id_type == "pattern":
        regex = re.compile(spec.pattern)
        matched = {t for t in all_available_tags if regex.search(t)}
        tags_to_extract.update(matched)

    for tag in tags_to_extract:
      try:
        # V1 / Legacy / tensorboardX
        # Stored in `simple_value` field, accessed via .Scalars()
        if tag in available_scalars:
          events = accumulator.Scalars(tag)
          raw_data[tag] = [e.value for e in events]
        # V2 / TensorFlow 2.x
        # Stored in `tensor` field, accessed via .Tensors()
        elif tag in available_tensors:
          events = accumulator.Tensors(tag)
          raw_data[tag] = [tf.make_ndarray(e.tensor_proto).item() for e in events]
      except Exception as e:
        print(f"Warning: Failed to parse metric '{tag}'. Error: {e}", file=sys.stderr)

    return raw_data

  def parse_and_compute(
    self, tblog_dir: str
  ) -> List[benchmark_result_pb2.ComputedStat]:
    """Reads event logs, computes stats, and returns a list of ComputedStat messages."""
    raw_data = self._read_tensorboard_metrics(tblog_dir)
    computed_stats = []
    all_resolved_tags = set(raw_data.keys())

    for metric in self.metric_specs:
      id_type = metric.WhichOneof("identifier")
      matched_tags = []

      if id_type == "name":
        if metric.name in all_resolved_tags:
          matched_tags = [metric.name]
      elif id_type == "pattern":
        regex = re.compile(metric.pattern)
        matched_tags = sorted([t for t in all_resolved_tags if regex.search(t)])

      if not matched_tags:
        failed_id = metric.pattern if id_type == "pattern" else metric.name
        print(
          f"Warning: Metric '{failed_id}' not found in logs. Skipping.", file=sys.stderr
        )
        continue

      for tag_name in matched_tags:
        data_vector = raw_data[tag_name]
        for stat_spec in metric.stats:
          stat_enum = stat_spec.stat
          stat_name = metric_pb2.Stat.Name(stat_enum)

          if stat_name not in STAT_FN_MAP:
            print(f"Warning: Unknown statistic {stat_name}. Skipping.", file=sys.stderr)
            continue

          computed_value = round(
            float(STAT_FN_MAP[stat_name](np.array(data_vector))), 2
          )
          computed_stats.append(
            benchmark_result_pb2.ComputedStat(
              metric_name=tag_name,
              stat=stat_enum,
              value={"value": computed_value},
              unit=metric.unit,
            )
          )

    return computed_stats
