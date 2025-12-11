"""Tests for culprit_finder_state."""

import pytest

from culprit_finder import culprit_finder_state


def _isolate_state_home(monkeypatch, tmp_path):
  """
  Ensure state read/write happens under a temp directory rather than the real HOME.
  """
  monkeypatch.setattr(culprit_finder_state.Path, "home", lambda: tmp_path)


@pytest.mark.parametrize(
  "job",
  [
    None,
    "test/job",
  ],
)
def test_save_then_load_state_round_trip(monkeypatch, tmp_path, job: str | None):
  """Tests that saving and loading state works correctly."""
  _isolate_state_home(monkeypatch, tmp_path)

  state: culprit_finder_state.CulpritFinderState = {
    "repo": "owner/repo",
    "workflow": "workflow.yml",
    "original_start": "start",
    "original_end": "end",
    "current_good": "good",
    "current_bad": "bad",
    "cache": {
      "good": "PASS",
      "bad": "FAIL",
    },
    "job": job,
  }

  persister = culprit_finder_state.StatePersister(
    repo="owner/repo", workflow="workflow.yml"
  )
  persister.save(state)

  loaded = persister.load()
  assert loaded is not None
  assert loaded == state


def test_delete_state_removes_file(monkeypatch, tmp_path):
  """Tests that deleting state removes the file."""
  _isolate_state_home(monkeypatch, tmp_path)

  state = culprit_finder_state.CulpritFinderState(
    repo="owner/repo",
    workflow="workflow.yml",
    original_start="start",
    original_end="end",
    cache={},
    current_good="",
    current_bad="",
    job=None,
  )
  persister = culprit_finder_state.StatePersister(
    repo="owner/repo", workflow="workflow.yml"
  )
  persister.save(state)

  # Ensure it's gone after delete
  persister.delete()
  assert persister.exists() is False
