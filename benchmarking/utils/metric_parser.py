"""Utility library for parsing metric specifications from JSON."""

import collections.abc
import json
from google.protobuf import json_format
from benchmarking.proto.common import metric_pb2


def parse_metric_specs_from_json(
  metric_specs_json: str,
) -> collections.abc.Sequence[metric_pb2.MetricSpec]:
  """Parses a JSON string into a list of MetricSpec protos.

  Gracefully handles "null" or empty inputs by returning an empty list.
  Raises ValueError if the input string is not valid JSON.
  """
  try:
    metric_specs_list = json.loads(metric_specs_json)
  except json.JSONDecodeError as e:
    raise ValueError(f"Failed to parse metric_specs_json: {e}") from e

  metric_specs = []
  if not metric_specs_list:
    return metric_specs

  for metric_dict in metric_specs_list:
    metric_spec = metric_pb2.MetricSpec()
    json_format.ParseDict(metric_dict, metric_spec)
    metric_specs.append(metric_spec)

  return metric_specs
