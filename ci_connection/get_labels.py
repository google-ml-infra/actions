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
import urllib.error

_GITHUB_API_VERSION = "2022-11-28"


def _get_label_request_headers() -> dict[str, str]:
  headers = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": _GITHUB_API_VERSION,
  }

  gh_token = os.getenv("GITHUB_TOKEN")
  if gh_token:
    logging.debug("Attached workflow token to headers")
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


def _log_rate_limit(response, log_state_dict: dict, authentication_type: str):
  if not log_state_dict[authentication_type]:
    rate_limit = response.headers.get("x-ratelimit-limit")
    log_state_dict[authentication_type] = True
    logging.debug(f"API rate limit ({authentication_type}): {rate_limit}")


def _get_labels_via_api(gh_issue: str) -> list | None:
  gh_api = os.getenv("GITHUB_API_URL", "https://api.github.com")
  gh_repo = os.getenv("GITHUB_REPOSITORY")
  labels_url = f"{gh_api}/repos/{gh_repo}/issues/{gh_issue}/labels"
  logging.debug(f"{gh_issue=!r}\n{gh_repo=!r}")

  rate_limit_logged = {"with_token": False, "public": False}

  data = None
  label_json = None
  total_attempts = 3
  cur_attempt = 1

  permissions_url = "go/ml-github-actions:connect#labels-read-permissions"

  headers = _get_label_request_headers()

  while cur_attempt <= total_attempts:
    request = urllib.request.Request(labels_url, headers=headers)
    logging.info(f"Retrieving PR labels via API - attempt {cur_attempt}...")

    is_authenticated = "Authorization" in headers
    authentication_type = "with_token" if is_authenticated else "public"

    # noinspection PyBroadException
    try:
      response = urllib.request.urlopen(request, timeout=10)
      _log_rate_limit(response, rate_limit_logged, authentication_type)

      if response.status == 200:
        data = response.read().decode("utf-8")
        logging.debug(f"API labels data: \n{data}")
        break

    except urllib.error.HTTPError as e:
      _log_rate_limit(e, rate_limit_logged, authentication_type)

      if e.code == 404:
        # A 404 means the repo/PR doesn't exist, or, the token has
        # zero access as the repo is private - no sense in retrying anonymously
        logging.error(
          f"Resource not found (404) for: {labels_url}\n"
          "The repository is likely private, and the workflow lacks permissions to "
          "read its pull requests.\n"
          f"Ensure the necessary permissions are set: {permissions_url}"
        )
        return None

      elif e.code in (401, 403, 429):
        rl_remaining = e.headers.get("x-ratelimit-remaining")

        if is_authenticated:
          # Check headers to distinguish between 'Forbidden' and 'Rate Limit'
          # 429 is always a rate limit; 403 is a rate limit if the remaining limit is
          # zero
          is_rate_limit = e.code == 429 or rl_remaining == "0"
          limit_blurb = ""
          if is_rate_limit:
            limit_blurb = f" (x-ratelimit-remaining: {rl_remaining})"

          error_type = "Rate Limit" if is_rate_limit else "Permission"
          error_msg = (
            f"{error_type} error ({e.code}) encountered with an authenticated "
            f"request{limit_blurb}. "
            f"Falling back to unauthenticated requests in the hopes this is a public "
            f"repo."
          )

          if e.code == 403 and rl_remaining != "0":
            error_msg += (
              f"\nThe workflow likely lacks correct permissions ({permissions_url}).\n"
              f"Follow {permissions_url} to avoid this in the future."
            )
          logging.warning(error_msg)

          # Remove the token and immediately retry without waiting
          del headers["Authorization"]
          cur_attempt += 1
          continue

        # Not authenticated
        if e.code == 403:
          if rl_remaining == "0":
            logging.error("GitHub API rate limit exceeded for unauthenticated request.")
          else:
            logging.error(
              "Request blocked by GitHub (Secondary Rate Limit or Abuse Detection)."
            )
          return None

        elif e.code == 401:
          logging.error("Unauthorized (401) on unauthenticated request.")
          return None

        elif e.code == 429:
          logging.warning("Secondary rate limit hit (429) on unauthenticated request.")

      else:
        logging.error(f"Request failed with HTTP status code: {e.code}")

      cur_attempt += 1
      _wait_before_repeat_request(cur_attempt, total_attempts)
      continue

    except Exception:
      logging.error(
        f"Failed to retrieve labels via API due to an unexpected "
        f"error (attempt {cur_attempt}): "
      )
      traceback.print_exc()
      cur_attempt += 1
      _wait_before_repeat_request(cur_attempt, total_attempts)
      continue

  if not data:
    logging.error("Retrieval of PR labels via API failed")
    return None

  try:
    label_json = json.loads(data)
  except json.JSONDecodeError:
    logging.warning(f"Failed to parse label JSON data received from API: {data}")
    traceback.print_exc()

  return label_json


def _get_labels_from_event_file() -> list | None:
  """Fall back on labels from the event's payload, if API failed."""
  event_payload_path = os.getenv("GITHUB_EVENT_PATH")
  # noinspection PyBroadException
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
  """Get the most up-to-date labels on the PR the workflow is running on.

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
  label_data = _get_labels_via_api(gh_issue)

  # Fall back on labels from the event's payload, if API failed (unlikely)
  if label_data is None:
    logging.info("Attempting to retrieve labels from the event file")
    label_data = _get_labels_from_event_file()

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
