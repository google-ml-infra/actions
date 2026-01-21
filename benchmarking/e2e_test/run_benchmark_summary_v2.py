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

"""Fake benchmark script for E2E testing the reusable workflow. Logs metrics using TF 2.x Summary."""

import os
import sys
import tensorflow as tf


def main():
  """Runs a fake benchmark and writes TensorBoard logs."""
  print("E2E test benchmark script starting.")
  tblog_dir = os.environ.get("TENSORBOARD_OUTPUT_DIR")

  if not tblog_dir:
    print("Error: TENSORBOARD_OUTPUT_DIR env var not set.", file=sys.stderr)
    sys.exit(1)

  print(f"Received TENSORBOARD_OUTPUT_DIR: {tblog_dir}.")
  args = sys.argv[1:]
  print(f"Received runtime_flags: {args}.")
  fake_metrics = [101.2, 100.5, 102.1, 99.8, 101.5]
  print(f"Fake metrics generated: {fake_metrics}.")

  try:
    writer = tf.summary.create_file_writer(tblog_dir)

    with writer.as_default():
      for i, value in enumerate(fake_metrics):
        tf.summary.scalar("wall_time", value, step=i)

    writer.flush()
    writer.close()

    print(f"Successfully wrote 5 wall_time metrics to {tblog_dir}")
    print("E2E test benchmark script finished.")

  except Exception as e:
    print(f"Error writing TensorBoard logs: {e}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
  main()
