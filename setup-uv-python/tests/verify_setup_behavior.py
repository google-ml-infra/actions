#!/usr/bin/env python3
"""Checks runtime behavior of the setup-uv-python action in CI.

Each invocation is meant to test exactly one aspect of the action's behavior.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_PYTHON_BIN_VAR = "PYTHON_BIN"
_VENV_VAR = "VIRTUAL_ENV"


def _require_env(name: str) -> str:
  """Get environment variable and raise if not set."""
  value = os.environ.get(name)
  if not value:
    raise RuntimeError(f"{name} is not set")
  return value


def _version_text() -> str:
  return f"{sys.version_info.major}.{sys.version_info.minor}"


def _norm_path(path: str) -> str:
  return os.path.normcase(os.path.normpath(path))


def _require_unset_env(name: str) -> None:
  value = os.environ.get(name, "")
  if value:
    raise RuntimeError(f"{name} is unexpectedly set: {value}")


def _verify_python_runtime(
  expected_minor: str,
  setup_python_bin: str,
  export_python_env: bool,
  add_python_to_path: bool,
) -> None:
  """Verify setup output/env/path behavior for the active python executable."""
  output_bin_raw = Path(setup_python_bin)
  output_bin = output_bin_raw.resolve()
  sys_executable = Path(sys.executable).resolve()

  if not output_bin.exists():
    raise RuntimeError(f"output python-bin does not exist: {output_bin}")
  if sys_executable != output_bin:
    raise RuntimeError(
      f"sys.executable and output python-bin differ: {sys_executable} != {output_bin}"
    )

  if export_python_env:
    py_bin_raw = Path(_require_env(_PYTHON_BIN_VAR))
    py_bin = py_bin_raw.resolve()

    if not py_bin.exists():
      raise RuntimeError(f"{_PYTHON_BIN_VAR} does not exist: {py_bin}")

    if py_bin != output_bin:
      raise RuntimeError(
        f"{_PYTHON_BIN_VAR} and output python-bin differ:\n{py_bin}\n!=\n{output_bin}"
      )

    venv_path = Path(_require_env(_VENV_VAR)).resolve()
    if not venv_path.exists():
      raise RuntimeError(f"{_VENV_VAR} does not exist: {venv_path}")

  else:
    _require_unset_env(_PYTHON_BIN_VAR)
    _require_unset_env(_VENV_VAR)

  major_minor = _version_text()
  if major_minor != expected_minor:
    raise RuntimeError(
      f"python version mismatch: got {major_minor}, expected {expected_minor}"
    )

  py_dir = str(output_bin_raw.parent)

  path_entries = [
    entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry
  ]
  path_norm = {_norm_path(entry) for entry in path_entries}
  py_dir_in_path = _norm_path(py_dir) in path_norm

  if add_python_to_path and not py_dir_in_path:
    raise RuntimeError(f"{py_dir} not present in PATH")

  if not add_python_to_path and py_dir_in_path:
    raise RuntimeError(f"{py_dir} unexpectedly present in PATH")

  print(f"python executable: {sys_executable}")
  print(f"python version: {major_minor}")
  print(f"PATH contains python dir: {py_dir_in_path}")


def _verify_python3_alias(expected_minor: str, setup_python_bin: str) -> None:
  """Verify python3 resolves to the same venv interpreter directory/version."""
  output_bin = Path(setup_python_bin).resolve()
  exe = Path(sys.executable).resolve()

  if exe.parent != output_bin.parent:
    raise RuntimeError(
      f"python3 executable is not in the venv bin dir: {exe} vs {output_bin}"
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


def _verify_summary_output(summary_label: str) -> None:
  """Verify that summary output contains expected setup metadata."""
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
    "--check",
    required=True,
    choices=("python-runtime", "python3-alias", "summary-output"),
    help="Check to run.",
  )
  parser.add_argument(
    "--expected-minor",
    default="",
    help="Expected major.minor version (for python-runtime/python3-alias checks).",
  )
  parser.add_argument(
    "--setup-python-bin",
    default="",
    help="Value of the setup action python-bin output "
    "(for python-runtime/python3-alias checks).",
  )
  parser.add_argument(
    "--export-python-env",
    default="true",
    help="Whether PYTHON_BIN and VIRTUAL_ENV are expected to be exported.",
  )
  parser.add_argument(
    "--add-python-to-path",
    default="true",
    help="Whether the interpreter directory is expected to be added to PATH.",
  )
  parser.add_argument(
    "--summary-label",
    default="",
    help="Expected summary label (for summary-output check).",
  )
  return parser.parse_args()


def main() -> int:
  args = _parse_args()

  export_python_env = args.export_python_env == "true"
  add_python_to_path = args.add_python_to_path == "true"

  if args.check in ("python-runtime", "python3-alias"):
    if not args.expected_minor:
      raise RuntimeError(
        "--expected-minor is required for python-runtime/python3-alias checks"
      )
    if not args.setup_python_bin:
      raise RuntimeError(
        "--setup-python-bin is required for python-runtime/python3-alias checks"
      )

  if args.check == "summary-output" and not args.summary_label:
    raise RuntimeError("--summary-label is required for summary-output check")

  if args.check == "python-runtime":
    _verify_python_runtime(
      expected_minor=args.expected_minor,
      setup_python_bin=args.setup_python_bin,
      export_python_env=export_python_env,
      add_python_to_path=add_python_to_path,
    )
  elif args.check == "python3-alias":
    _verify_python3_alias(args.expected_minor, args.setup_python_bin)
  else:
    _verify_summary_output(args.summary_label)
  return 0


if __name__ == "__main__":
  try:
    raise SystemExit(main())
  except RuntimeError as error:
    print(error, file=sys.stderr)
    raise SystemExit(1)
