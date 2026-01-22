"""Manages the state of the culprit finder to persist it across runs."""

from __future__ import annotations
import json
from pathlib import Path
from typing import TypedDict, Literal


_STATE_ROOT_DIRNAME = ".github_culprit_finder"

COMMIT_STATUS = Literal["PASS", "FAIL"]


class CulpritFinderState(TypedDict):
  repo: str
  workflow: str
  job: str | None
  original_start: str
  original_end: str
  current_good: str
  current_bad: str
  cache: dict[str, COMMIT_STATUS]


def _sanitize_component(value: str) -> str:
  """
  Sanitizes a string so it is safe to use as a filesystem path component.

  This is used when turning user-provided values like repository names
  (`owner/repo`) and workflow filenames into directory/file names.

  The sanitization is intentionally conservative and focuses on preventing:
  - path traversal (`..`)
  - accidental directory separators on Windows (`\\`)
  - characters that are problematic in filenames on common platforms (e.g. `:`)

  Args:
    value: Raw component string (e.g. repo owner, repo name, workflow file name).

  Returns:
    A sanitized string suitable for use as a single path component.
  """
  return (
    value.strip()
    .replace("..", ".")
    .replace("\\", "_")
    .replace("/", "_")
    .replace(" ", "_")
    .replace(":", "_")
    .replace("|", "_")
  )


class StatePersister:
  """Handles the persistence of the CulpritFinderState."""

  def __init__(self, repo: str, workflow: str, job: str | None = None):
    self._repo = repo
    self._workflow = workflow
    self._job = job

  def _get_base_dir(self) -> Path:
    """Returns the base directory for the repo state."""
    home = Path.home()
    root = home / _STATE_ROOT_DIRNAME

    repo_path = Path(*[
      _sanitize_component(p) for p in self._repo.split("/") if p.strip()
    ])

    return root / repo_path

  def _get_file_path(self) -> Path:
    """Returns the path to the state file."""
    safe_workflow = _sanitize_component(self._workflow) or "default"
    if self._job:
      safe_job = _sanitize_component(self._job)
      return self._get_base_dir() / f"{safe_workflow}_{safe_job}.json"
    return self._get_base_dir() / f"{safe_workflow}.json"

  def _ensure_directory_exists(self) -> None:
    """Creates the necessary directories for storage."""
    self._get_base_dir().mkdir(parents=True, exist_ok=True)

  def exists(self) -> bool:
    """Checks if the state file exists.

    Returns:
        bool: True if the state file exists, False otherwise.
    """
    return self._get_file_path().exists()

  def save(self, state: CulpritFinderState) -> None:
    """Saves the state to disk.

    Args:
        state: The CulpritFinderState object to save.
    """
    self._ensure_directory_exists()
    state_path = self._get_file_path()
    with state_path.open("w", encoding="utf-8") as f:
      json.dump(state, f)

  def load(self) -> CulpritFinderState:
    """Loads the state from disk.

    Returns:
        CulpritFinderState: The loaded CulpritFinderState object.
    """
    state_path = self._get_file_path()
    with state_path.open("r", encoding="utf-8") as f:
      data = json.load(f)
      return {
        "repo": data["repo"],
        "workflow": data["workflow"],
        "job": data.get("job", None),
        "original_start": data["original_start"],
        "original_end": data["original_end"],
        "current_good": data.get("current_good", ""),
        "current_bad": data.get("current_bad", ""),
        "cache": data.get("cache", {}),
      }

  def delete(self) -> None:
    """Deletes the state file."""
    state_path = self._get_file_path()
    state_path.unlink()
