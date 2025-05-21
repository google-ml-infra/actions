# Copyright 2024 Google LLC

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     https://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Retrieve PR labels, if any.

While these labels are also available via GH context, and the event payload
file, they may be stale:
https://github.com/orgs/community/discussions/39062

Thus, the API is used as the main source, with the event payload file
being the fallback.

The script is only geared towards use within a GH Action run.
"""

import json
import logging
import os
import re
import time
import traceback
import urllib.request


def _get_label_request_headers() -> dict[str, str]:
  gh_token = os.getenv("GITHUB_TOKEN")
  headers = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
  }
  if gh_token:
    headers["Authorization"] = f"Bearer {gh_token}"
  return headers


def _wait_before_repeat_request(cur_attempt: int, total_attempts: int):
  if cur_attempt > total_attempts:
    return
  wait_time = 2 * (2 ** (cur_attempt - 2))
  logging.info(
    f"Trying again in {wait_time} seconds (Attempt {cur_attempt}/{total_attempts})"
  )
  time.sleep(wait_time)


def _get_label_data_via_api(gh_issue: str) -> list | None:
  gh_repo = os.getenv("GITHUB_REPOSITORY")
  labels_url = f"https://api.github.com/repos/{gh_repo}/issues/{gh_issue}/labels"
  logging.debug(f"{gh_issue=!r}\n{gh_repo=!r}")

  data = None
  label_json = None
  total_attempts = 3
  cur_attempt = 1

  while cur_attempt <= total_attempts:
    request = urllib.request.Request(labels_url, headers=_get_label_request_headers())
    logging.info(f"Retrieving PR labels via API - attempt {cur_attempt}...")
    try:
      response = urllib.request.urlopen(request, timeout=10)
    except Exception:
      logging.error(
        f"Failed to retrieve labels via API due to an unexpected "
        f"error (attempt {cur_attempt}): "
      )
      traceback.print_exc()
      cur_attempt += 1
      _wait_before_repeat_request(cur_attempt, total_attempts)
      continue

    if response.status == 200:
      data = response.read().decode("utf-8")
      logging.debug(f"API labels data: \n{data}")
      break
    else:
      logging.error(f"Request failed with status code: {response.status}")
      cur_attempt += 1
      _wait_before_repeat_request(cur_attempt, total_attempts)

  if not data:
    logging.error("Retrieval of PR labels via API failed")
    return None

  try:
    label_json = json.loads(data)
  except json.JSONDecodeError:
    logging.warning(f"Failed to parse label JSON data received from API: {data}")
    traceback.print_exc()

  return label_json


def _get_label_data_from_event_file() -> list | None:
  """Fall back on labels from the event's payload, if API failed"""
  event_payload_path = os.getenv("GITHUB_EVENT_PATH")
  try:
    with open(event_payload_path, "r", encoding="utf-8") as event_payload:
      label_json = json.load(event_payload).get("pull_request", {}).get("labels", [])
      logging.info("Using fallback labels from event file")
      logging.info(f"Fallback labels: \n{label_json}")
  except Exception:
    logging.error(
      "Failed to retrieve labels from the event file due to an unexpected error: "
    )
    traceback.print_exc()
    return None

  return label_json


def _extract_labels(data: list) -> list | None:
  labels = []
  if isinstance(data, list):
    try:
      labels = [label["name"] for label in data]
    except (TypeError, KeyError):
      logging.error(f"Failed to extract label names from relevant JSON: {data}")
      traceback.print_exc()
      return None
  elif data is not None:
    logging.error(f"Received label data is not a list, cannot extract labels: {data}")
    return None

  return labels


def retrieve_labels(print_to_stdout: bool = True) -> list[str] | None:
  """Get the most up-to-date labels.

  In case this is not a PR, return an empty list.
  """
  # Check if this is a PR (pull request)
  github_ref = os.getenv("GITHUB_REF", "")
  if not github_ref:
    raise EnvironmentError(
      "GITHUB_REF is not defined. Is this being run outside of GitHub Actions?"
    )

  # Outside a PR context - no labels to be found
  if not github_ref.startswith("refs/pull/"):
    logging.debug("Not a PR workflow run, returning an empty label list")
    if print_to_stdout:
      print([])
    return []

  # Get the PR number
  ref_match = re.search(r"refs/pull/(\d+)/", github_ref)
  if not ref_match:
    logging.error(f"Could not extract PR number from GITHUB_REF: {github_ref}")
    return None
  gh_issue = ref_match.group(1)

  # Try retrieving the labels info via API
  label_data = _get_label_data_via_api(gh_issue)

  # Fall back on labels from the event's payload, if API failed (unlikely)
  if label_data is None:
    logging.info("Attempting to retrieve labels from the event file")
    label_data = _get_label_data_from_event_file()

  if label_data is None:
    return None

  labels = _extract_labels(data=label_data)
  if labels is None:
    return None

  logging.debug(f"Final labels: \n{labels}")

  # Output the labels to stdout for further use elsewhere, if desired
  if print_to_stdout:
    print(labels)
  return labels


if __name__ == "__main__":
  retrieve_labels(print_to_stdout=True)
