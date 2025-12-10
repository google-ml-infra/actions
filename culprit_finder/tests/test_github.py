"""Tests for the github module."""

import json
from culprit_finder import github


def test_compare_commits_multiple_pages(mocker):
  """Test fetching commits spanning multiple pages."""
  mock_run_command = mocker.patch("culprit_finder.github.GithubClient._run_command")

  repo = "owner/repo"
  base_sha = "base"
  head_sha = "head"

  page1_commits = [
    {"sha": f"sha{i}", "commit": {"message": f"msg{i}"}} for i in range(3)
  ]
  response_page_1 = json.dumps({"commits": page1_commits})

  page2_commits = [{"sha": "sha3", "commit": {"message": "msg3"}}]
  response_page_2 = json.dumps({"commits": page2_commits})

  response_page_3 = json.dumps({"commits": []})

  mock_run_command.side_effect = [response_page_1, response_page_2, response_page_3]

  client = github.GithubClient(repo)
  commits = client.compare_commits(base_sha, head_sha)

  assert len(commits) == 4
  assert commits[0]["sha"] == "sha0"
  assert commits[3]["sha"] == "sha3"

  assert mock_run_command.call_count == 3
