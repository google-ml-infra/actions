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

"""Library for parsing TensorBoard benchmark results."""

import sys
from typing import List
import numpy as np
import tensorflow as tf
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
from benchmarking.proto import benchmark_registry_pb2
from benchmarking.proto import benchmark_result_pb2
from benchmarking.proto.common import stat_pb2

MetricManifest = List[benchmark_registry_pb2.MetricSpec]

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
  """Parses TB logs based on a metric manifest and creates a benchmark result artifact.

  Supported Summary Formats:
    1. V1 (Legacy/Scalar): Used by `tensorboardX`, and TF 1.x.
       Data is stored in the `simple_value` float field.
    2. V2 (TensorFlow 2.x): Used by native TensorFlow 2.x.
       Data is stored in the `tensor` field (serialized TensorProto).

  Note: This parser ONLY supports scalar metrics (single floating-point numbers).
  It ignores histograms, images, audio, and other complex data types.
  """

  def __init__(self, metric_manifest: MetricManifest):
    """Initializes the parser with the metric manifest.

    Args:
      metric_manifest: A list of `MetricSpec` Protobuf messages.
    """
    self.metric_manifest = metric_manifest
    self.metric_names_to_track = {m.name for m in metric_manifest}

  def _read_tensorboard_metrics(self, tblog_dir: str) -> dict[str, list[float]]:
    """Reads scalar data for tracked metrics from both V1 and V2 buckets.

    We explicitly check both 'scalars' and 'tensors' buckets because:
    - `tensorboardX` (and TF 1.x) writes to the `simple_value` field -> 'scalars' bucket.
    - TF 2.x writes to the `tensor` field -> 'tensors' bucket.
    """
    raw_data = {name: [] for name in self.metric_names_to_track}

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

    for metric_name in self.metric_names_to_track:
      try:
        # V1 / Legacy / tensorboardX
        # Stored in `simple_value` field, accessed via .Scalars()
        if metric_name in available_scalars:
          events = accumulator.Scalars(metric_name)
          raw_data[metric_name] = [e.value for e in events]

        # V2 / TensorFlow 2.x
        # Stored in `tensor` field, accessed via .Tensors()
        elif metric_name in available_tensors:
          events = accumulator.Tensors(metric_name)
          # Must deserialize the TensorProto to get the scalar value
          raw_data[metric_name] = [
            tf.make_ndarray(e.tensor_proto).item() for e in events
          ]

      except Exception as e:
        print(
          f"Warning: Failed to parse metric '{metric_name}' from logs. Error: {e}",
          file=sys.stderr,
        )
        continue

    return raw_data

  def parse_and_compute(
    self, tblog_dir: str
  ) -> list[benchmark_result_pb2.ComputedStat]:
    """Reads event logs, computes stats, and returns a list of ComputedStat messages."""
    raw_data = self._read_tensorboard_metrics(tblog_dir)
    computed_stats = []

    for metric in self.metric_manifest:
      metric_name = metric.name
      metric_unit = metric.unit
      data_vector = raw_data.get(metric_name)

      if not data_vector:
        print(
          f"Warning: Metric {metric_name} defined in registry but not found in logs. Skipping.",
          file=sys.stderr,
        )
        continue

      for stat in metric.stats:
        stat_enum = stat.stat
        stat_name = stat_pb2.Stat.Name(stat_enum)

        if stat_name not in STAT_FN_MAP:
          print(f"Warning: Unknown statistic {stat_name}. Skipping.", file=sys.stderr)
          continue

        computed_value = STAT_FN_MAP[stat_name](np.array(data_vector))
        computed_value = round(computed_value, 2)
        computed_stats.append(
          benchmark_result_pb2.ComputedStat(
            metric_name=metric_name,
            stat=stat_enum,
            value={"value": computed_value},
            unit=metric_unit,
          )
        )

    return computed_stats
