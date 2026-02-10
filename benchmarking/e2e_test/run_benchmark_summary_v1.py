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

"""Fake benchmark script for E2E testing the reusable workflow. Logs metrics using TF 1.x Summary."""

import os
import sys
import time

from tensorboard.compat.proto import event_pb2
from tensorboard.compat.proto import summary_pb2
from tensorboard.summary.writer.event_file_writer import EventFileWriter


def main():
  """Runs a fake benchmark and writes TensorBoard logs + artifacts."""
  print("E2E test benchmark script starting.")
  tblog_dir = os.environ.get("TENSORBOARD_OUTPUT_DIR")
  artifact_dir = os.environ.get("WORKLOAD_ARTIFACTS_DIR")

  if not tblog_dir:
    print("Error: TENSORBOARD_OUTPUT_DIR env var not set.", file=sys.stderr)
    sys.exit(1)

  # Write TensorBoard metrics
  print(f"Received TENSORBOARD_OUTPUT_DIR: {tblog_dir}.")
  args = sys.argv[1:]
  print(f"Received runtime_flags: {args}.")
  fake_metrics = [101.2, 100.5, 102.1, 99.8, 101.5]

  try:
    writer = EventFileWriter(tblog_dir)

    for i, value in enumerate(fake_metrics):
      event = event_pb2.Event(
        step=i,
        wall_time=time.time(),
        summary=summary_pb2.Summary(
          value=[summary_pb2.Summary.Value(tag="wall_time", simple_value=value)]
        ),
      )
      writer.add_event(event)

    writer.close()

    print(f"Successfully wrote 5 wall_time metrics to {tblog_dir}")

    # Create workload wrtifact
    if artifact_dir:
      print(f"Received WORKLOAD_ARTIFACTS_DIR: {artifact_dir}")
      artifact_path = os.path.join(artifact_dir, "test_artifact.txt")
      with open(artifact_path, "w") as f:
        f.write("Hello from run_benchmark_summary_v1.")
      print(f"Successfully wrote artifact to {artifact_path}")
    else:
      print("Warning: WORKLOAD_ARTIFACTS_DIR env var not set.")

    print("E2E test benchmark script finished.")

  except Exception as e:
    print(f"Error executing benchmark: {e}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
  main()
