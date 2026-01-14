# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Library for publishing benchmark results to Google Cloud Pub/Sub."""

import sys
from typing import List
from google.cloud import pubsub_v1
from benchmarking.proto import benchmark_result_pb2
from google.protobuf import json_format


def publish_messages(
  project_id: str,
  topic_id: str,
  messages: List[benchmark_result_pb2.BenchmarkResult],
  repo_name: str,
):
  """Publishes a list of BenchmarkResult messages to Pub/Sub."""

  publisher = pubsub_v1.PublisherClient()
  topic_path = publisher.topic_path(project_id, topic_id)

  print(f"Targeting Pub/Sub topic: {topic_path}")
  print(f"Publishing {len(messages)} messages with repo attribute: {repo_name}...")

  futures = []
  success_count = 0

  for message in messages:
    try:
      data = json_format.MessageToJson(message).encode("utf-8")
      future = publisher.publish(topic_path, data, repo=repo_name)
      futures.append(future)
    except Exception as e:
      print(f"ERROR: Failed to prepare message for publishing: {e}", file=sys.stderr)

  # Wait for all publications to complete
  for i, future in enumerate(futures):
    try:
      message_id = future.result(timeout=30)
      print(f"Published message {i + 1}/{len(messages)} (Message ID: {message_id})")
      success_count += 1
    except Exception as e:
      print(f"ERROR: Failed to publish message {i + 1}: {e}", file=sys.stderr)

  if success_count < len(messages):
    print(
      f"ERROR: Only published {success_count}/{len(messages)} messages successfully.",
      file=sys.stderr,
    )
    sys.exit(1)
