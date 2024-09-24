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
import urllib.request


def retrieve_labels(print_to_stdout: bool = True) -> list[str]:
  """Get the most up-to-date labels.

  In case this is not a PR, return an empty list.
  """
  # Check if this is a PR (pull request)
  github_ref = os.getenv('GITHUB_REF', '')
  if not github_ref:
    raise TypeError('GITHUB_REF is not defined. '
                    'Is this being run outside of GitHub Actions?')

  # Outside a PR context - no labels to be found
  if not github_ref.startswith('refs/pull/'):
    logging.debug('Not a PR workflow run, returning an empty label list')
    if print_to_stdout:
      print([])
    return []

  # Get the PR number
  # Since passing the previous check confirms this is a PR, there's no need
  # to safeguard this regex
  gh_issue = re.search(r'refs/pull/(\d+)/merge', github_ref).group(1)
  gh_repo = os.getenv('GITHUB_REPOSITORY')
  labels_url = (
    f'https://api.github.com/repos/{gh_repo}/issues/{gh_issue}/labels'
  )
  logging.debug(f'{gh_issue=!r}\n'
                f'{gh_repo=!r}')

  wait_time = 3
  total_attempts = 3
  cur_attempt = 1
  data = None

  # Try retrieving the labels' info via API
  while cur_attempt <= total_attempts:
    request = urllib.request.Request(
      labels_url,
      headers={'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28'}
    )
    logging.info(f'Retrieving PR labels via API - attempt {cur_attempt}...')
    response = urllib.request.urlopen(request)

    if response.status == 200:
        data = response.read().decode('utf-8')
        logging.debug('API labels data: \n'
                      f'{data}')
        break
    else:
        logging.error(f'Request failed with status code: {response.status}')
        cur_attempt += 1
        if cur_attempt <= total_attempts:
          logging.info(f'Trying again in {wait_time} seconds')
          time.sleep(wait_time)

  # The null check is probably unnecessary, but rather be safe
  if data and data != 'null':
    data_json = json.loads(data)
  else:
    # Fall back on labels from the event's payload, if API failed (unlikely)
    event_payload_path = os.getenv('GITHUB_EVENT_PATH')
    with open(event_payload_path, 'r', encoding='utf-8') as event_payload:
      data_json = json.load(event_payload).get('pull_request',
                                               {}).get('labels', [])
      logging.info('Using fallback labels')
      logging.info(f'Fallback labels: \n'
                   f'{data_json}')

  labels = [label['name'] for label in data_json]
  logging.debug(f'Final labels: \n'
                f'{labels}')

  # Output the labels to stdout for further use elsewhere
  if print_to_stdout:
    print(labels)
  return labels


if __name__ == '__main__':
    retrieve_labels(print_to_stdout=True)
