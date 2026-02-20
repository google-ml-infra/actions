#!/usr/bin/env bash

set -euo pipefail

# A safety check used to protect against injecting potential unrelated
# additional variables.
ensure_single_line() {
  local var_name="$1"
  local var_value="$2"
  case "$var_value" in
    *$'\n'*|*$'\r'*)
      echo "::error::$var_name contains a newline; refusing to write to GitHub environment files."
      exit 1
      ;;
  esac
}

# setup-uv already handles Python install/restore. Simply re-installing here
# can fail on Windows when cached reparse points already exist.
if ! MANAGED_PYTHON_BIN="$(uv python find "$UV_PYTHON_VERSION" 2>/dev/null)"; then
  uv python install "$UV_PYTHON_VERSION"
  MANAGED_PYTHON_BIN="$(uv python find "$UV_PYTHON_VERSION")"
fi

VENV_PATH="${RUNNER_TEMP:-/tmp}/uv-ci-venv"
uv venv --clear --python "$MANAGED_PYTHON_BIN" "$VENV_PATH"
if [ -x "$VENV_PATH/bin/python" ]; then
  PYTHON_BIN="$VENV_PATH/bin/python"
elif [ -x "$VENV_PATH/Scripts/python.exe" ]; then
  PYTHON_BIN="$VENV_PATH/Scripts/python.exe"
else
  echo "::error::Could not find Python executable in $VENV_PATH"
  exit 1
fi

# Ensure both python and python3 are available in PATH.
PYTHON_DIR="$(dirname "$PYTHON_BIN")"
if [ "${RUNNER_OS:-}" = "Windows" ]; then
  if [ ! -e "$PYTHON_DIR/python3.exe" ] && [ -e "$PYTHON_DIR/python.exe" ]; then
    cp "$PYTHON_DIR/python.exe" "$PYTHON_DIR/python3.exe"
  fi
else
  if [ ! -e "$PYTHON_DIR/python" ] && [ -x "$PYTHON_DIR/python3" ]; then
    ln -s python3 "$PYTHON_DIR/python"
  fi
  if [ ! -e "$PYTHON_DIR/python3" ] && [ -x "$PYTHON_DIR/python" ]; then
    ln -s python "$PYTHON_DIR/python3"
  fi
fi

ensure_single_line 'PYTHON_BIN' "$PYTHON_BIN"
ensure_single_line 'VIRTUAL_ENV' "$VENV_PATH"
ensure_single_line 'PYTHON_DIR' "$PYTHON_DIR"
printf 'python_bin=%s\n' "$PYTHON_BIN" >> "$GITHUB_OUTPUT"
printf 'PYTHON_BIN=%s\n' "$PYTHON_BIN" >> "$GITHUB_ENV"
printf 'VIRTUAL_ENV=%s\n' "$VENV_PATH" >> "$GITHUB_ENV"
printf '%s\n' "$PYTHON_DIR" >> "$GITHUB_PATH"
