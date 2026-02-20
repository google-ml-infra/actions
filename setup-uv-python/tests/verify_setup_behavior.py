#!/usr/bin/env python3
"""Checks runtime behavior of the setup-uv-python action in CI."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PYTHON_BIN_VAR = "PYTHON_BIN"
VENV_VAR = "VIRTUAL_ENV"


def _require_env(name: str) -> str:
  value = os.environ.get(name)
  if not value:
    raise RuntimeError(f"{name} is not set")
  return value


def _version_text() -> str:
  return f"{sys.version_info.major}.{sys.version_info.minor}"


def _norm_path(path: str) -> str:
  return os.path.normcase(os.path.normpath(path))


def _check_python_mode(expected_minor: str, setup_python_bin: str) -> None:
  py_bin_raw = Path(_require_env(PYTHON_BIN_VAR))
  py_bin = py_bin_raw.resolve()
  venv_path = Path(_require_env(VENV_VAR)).resolve()
  output_bin = Path(setup_python_bin).resolve()
  sys_executable = Path(sys.executable).resolve()

  if not py_bin.exists():
    raise RuntimeError(f"{PYTHON_BIN_VAR} does not exist: {py_bin}")
  if not venv_path.exists():
    raise RuntimeError(f"{VENV_VAR} does not exist: {venv_path}")
  if py_bin != output_bin:
    raise RuntimeError(
      f"{PYTHON_BIN_VAR} and output python-bin differ: {py_bin} != {output_bin}"
    )
  if sys_executable != py_bin:
    raise RuntimeError(
      f"sys.executable and {PYTHON_BIN_VAR} differ: {sys_executable} != {py_bin}"
    )

  major_minor = _version_text()
  if major_minor != expected_minor:
    raise RuntimeError(
      f"python version mismatch: got {major_minor}, expected {expected_minor}"
    )

  # PYTHON_BIN points to the venv executable path (which can be a symlink).
  # PATH should include the venv bin/Scripts directory.
  py_dir_raw = str(py_bin_raw.parent)
  py_dir_resolved = str(py_bin.parent)
  path_entries = [
    entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry
  ]
  path_norm = {_norm_path(entry) for entry in path_entries}
  py_dir_in_path = (
    _norm_path(py_dir_raw) in path_norm or _norm_path(py_dir_resolved) in path_norm
  )
  if not py_dir_in_path:
    raise RuntimeError(
      f"{py_dir_raw} not present in PATH (resolved: {py_dir_resolved})"
    )

  print(f"python executable: {sys_executable}")
  print(f"python version: {major_minor}")
  print(f"PATH contains: {py_dir_raw}")


def _check_python3_mode(expected_minor: str) -> None:
  py_bin = Path(_require_env(PYTHON_BIN_VAR)).resolve()
  exe = Path(sys.executable).resolve()

  if exe.parent != py_bin.parent:
    raise RuntimeError(
      f"python3 executable is not in the venv bin dir: {exe} vs {py_bin}"
    )

  major_minor = _version_text()
  if major_minor != expected_minor:
    raise RuntimeError(
      f"python3 version mismatch: got {major_minor}, expected {expected_minor}"
    )

  print(f"python3 executable: {exe}")
  print(f"python3 version: {major_minor}")


def _read_text_if_exists(path: Path) -> str:
  try:
    if path.exists():
      return path.read_text(encoding="utf-8", errors="ignore")
  except OSError:
    return ""
  return ""


def _check_summary_mode(summary_label: str) -> None:
  summary_path = Path(_require_env("GITHUB_STEP_SUMMARY")).resolve()
  summary_dir = summary_path.parent

  parts: list[str] = []
  direct_summary = _read_text_if_exists(summary_path)
  if direct_summary:
    parts.append(direct_summary)

  for summary_file in summary_dir.glob("step_summary_*"):
    text = _read_text_if_exists(summary_file)
    if text:
      parts.append(text)

  summary_text = "\n".join(parts)
  required_fragments = [
    f"### {summary_label} Python setup",
    "- duration: ",
    "- uv cache hit: ",
    "- python cache hit: ",
  ]
  missing = [
    fragment for fragment in required_fragments if fragment not in summary_text
  ]
  if missing:
    raise RuntimeError(f"Missing summary content: {missing}")

  print("Debug summary output verified")


def _parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Verify setup-uv-python behavior.")
  parser.add_argument(
    "--mode",
    required=True,
    choices=("python", "python3", "summary"),
    help="Check mode to run.",
  )
  parser.add_argument(
    "--expected-minor",
    default="",
    help="Expected major.minor version (for python/python3 modes).",
  )
  parser.add_argument(
    "--setup-python-bin",
    default="",
    help="Value of the setup action python-bin output (for python mode).",
  )
  parser.add_argument(
    "--summary-label",
    default="",
    help="Expected summary label (for summary mode).",
  )
  return parser.parse_args()


def main() -> int:
  args = _parse_args()

  if args.mode in ("python", "python3") and not args.expected_minor:
    raise RuntimeError("--expected-minor is required for python/python3 modes")
  if args.mode == "python" and not args.setup_python_bin:
    raise RuntimeError("--setup-python-bin is required for python mode")
  if args.mode == "summary" and not args.summary_label:
    raise RuntimeError("--summary-label is required for summary mode")

  if args.mode == "python":
    _check_python_mode(args.expected_minor, args.setup_python_bin)
  elif args.mode == "python3":
    _check_python3_mode(args.expected_minor)
  else:
    _check_summary_mode(args.summary_label)
  return 0


if __name__ == "__main__":
  try:
    raise SystemExit(main())
  except RuntimeError as error:
    print(error, file=sys.stderr)
    raise SystemExit(1)
