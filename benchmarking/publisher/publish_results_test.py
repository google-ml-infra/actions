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

"""Tests for the benchmark results publisher library."""

import sys
from unittest import mock
import pytest
from benchmarking.proto import benchmark_result_pb2
from benchmarking.publisher import publish_results_lib
from google.protobuf import json_format


@pytest.fixture
def mock_publisher_client():
  """Mocks the pubsub_v1.PublisherClient."""
  with mock.patch(
    "benchmarking.publisher.publish_results_lib.pubsub_v1.PublisherClient"
  ) as mock_client_cls:
    mock_instance = mock_client_cls.return_value
    mock_instance.topic_path.side_effect = lambda project, topic: (
      f"projects/{project}/topics/{topic}"
    )
    yield mock_instance


def test_publish_messages_success(mock_publisher_client, capsys):
  """Tests that a list of valid messages is published."""
  project_id = "test-project"
  topic_id = "test-topic"
  repo_name = "test-owner/test-repo"
  expected_topic_path = f"projects/{project_id}/topics/{topic_id}"

  # Create benchmark result
  msg = benchmark_result_pb2.BenchmarkResult()
  msg.config_id = "test_config"
  messages = [msg]

  # Mock successful future
  mock_future = mock.Mock()
  mock_future.result.return_value = "msg_id_123"
  mock_publisher_client.publish.return_value = mock_future

  with mock.patch(
    "benchmarking.publisher.publish_results_lib.as_completed",
    side_effect=lambda futures: iter(futures),
  ):
    publish_results_lib.publish_messages(project_id, topic_id, messages, repo_name)

  expected_data = json_format.MessageToJson(msg).encode("utf-8")
  mock_publisher_client.publish.assert_called_once_with(
    expected_topic_path, expected_data, repo=repo_name
  )

  captured = capsys.readouterr()
  assert "Published message 1/1" in captured.out
  assert "msg_id_123" in captured.out


def test_publish_messages_all_fail(mock_publisher_client, capsys):
  """Tests behavior when all messages fail to publish."""
  project_id = "test-project"
  topic_id = "test-topic"
  repo_name = "test-owner/test-repo"

  # Create 2 benchmark results
  messages = [
    benchmark_result_pb2.BenchmarkResult(),
    benchmark_result_pb2.BenchmarkResult(),
  ]

  # Mock Future raising an exception for every call
  mock_future = mock.Mock()
  mock_future.result.side_effect = Exception("Cloud Error")
  mock_publisher_client.publish.return_value = mock_future

  with mock.patch(
    "benchmarking.publisher.publish_results_lib.as_completed",
    side_effect=lambda futures: iter(futures),
  ):
    with pytest.raises(RuntimeError) as e:
      publish_results_lib.publish_messages(project_id, topic_id, messages, repo_name)

  assert "Only 0/2 messages were sent successfully" in str(e.value)
  captured = capsys.readouterr()
  assert captured.err.count("Failed to publish message") == 2


def test_publish_messages_one_fail(mock_publisher_client, capsys):
  """Tests behavior when exactly one message fails."""
  project_id = "test-project"
  topic_id = "test-topic"
  repo_name = "test-owner/test-repo"

  # Create 3 benchmark results
  messages = [benchmark_result_pb2.BenchmarkResult() for _ in range(3)]

  # Futures: 2 Success, 1 Failure
  f_success = mock.Mock()
  f_success.result.return_value = "msg_id_ok"

  f_fail = mock.Mock()
  f_fail.result.side_effect = Exception("Single Failure")

  mock_publisher_client.publish.side_effect = [f_success, f_success, f_fail]

  with mock.patch(
    "benchmarking.publisher.publish_results_lib.as_completed",
    side_effect=lambda futures: iter(futures),
  ):
    with pytest.raises(RuntimeError) as e:
      publish_results_lib.publish_messages(project_id, topic_id, messages, repo_name)

  assert "Only 2/3 messages were sent successfully" in str(e.value)
  captured = capsys.readouterr()
  assert captured.out.count("Published message") == 2
  assert captured.err.count("Failed to publish message") == 1


def test_publish_messages_half_fail(mock_publisher_client, capsys):
  """Tests behavior when half of the messages fail (e.g. 2 out of 4)."""
  project_id = "test-project"
  topic_id = "test-topic"
  repo_name = "test-owner/test-repo"

  # Create 4 benchmark results
  messages = [benchmark_result_pb2.BenchmarkResult() for _ in range(4)]

  # Create Futures: 2 Success, 2 Failure
  f_success = mock.Mock()
  f_success.result.return_value = "msg_id_ok"

  f_fail = mock.Mock()
  f_fail.result.side_effect = Exception("Oops")

  mock_publisher_client.publish.side_effect = [f_success, f_fail, f_success, f_fail]

  with mock.patch(
    "benchmarking.publisher.publish_results_lib.as_completed",
    side_effect=lambda futures: iter(futures),
  ):
    with pytest.raises(RuntimeError) as e:
      publish_results_lib.publish_messages(project_id, topic_id, messages, repo_name)

  assert "Only 2/4 messages were sent successfully" in str(e.value)
  captured = capsys.readouterr()
  assert captured.out.count("Published message") == 2
  assert captured.err.count("Failed to publish message") == 2


if __name__ == "__main__":
  sys.exit(pytest.main(sys.argv))
