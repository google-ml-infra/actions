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

from unittest import mock
import sys
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
  """Tests that a list of valid messages is published with attributes."""
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

  publish_results_lib.publish_messages(project_id, topic_id, messages, repo_name)

  expected_data = json_format.MessageToJson(msg).encode("utf-8")
  mock_publisher_client.publish.assert_called_once_with(
    expected_topic_path, expected_data, repo=repo_name
  )

  captured = capsys.readouterr()
  assert "Published message 1/1" in captured.out


def test_publish_messages_failure(mock_publisher_client, capsys):
  """Tests that the library raises RuntimeError if publication fails."""

  # Create benchmark result
  msg = benchmark_result_pb2.BenchmarkResult()
  messages = [msg]
  repo_name = "test-owner/test-repo"

  # Mock Future raising an exception
  mock_future = mock.Mock()
  mock_future.result.side_effect = Exception("Cloud Error")
  mock_publisher_client.publish.return_value = mock_future

  with pytest.raises(RuntimeError) as e:
    publish_results_lib.publish_messages("p", "t", messages, repo_name)

  assert "Publishing failed" in str(e.value)
  assert "ERROR: Failed to publish message 1: Cloud Error" in capsys.readouterr().err


if __name__ == "__main__":
  sys.exit(pytest.main(sys.argv))
