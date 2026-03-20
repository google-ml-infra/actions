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

normalize_bool_input() {
  local var_name="$1"
  local raw_value="$2"
  local lowered_value
  lowered_value="$(printf '%s' "$raw_value" | tr '[:upper:]' '[:lower:]')"

  case "$lowered_value" in
    true|false)
      printf '%s' "$lowered_value"
      ;;
    *)
      echo "::error::$var_name must be 'true' or 'false' (got '$raw_value')."
      exit 1
      ;;
  esac
}

# setup-uv already handles Python install/restore. Simply re-installing here
# can fail on Windows when cached 'reparse' points already exist.
if ! MANAGED_PYTHON_BIN="$(uv python find "$UV_PYTHON_VERSION" 2>/dev/null)"; then
  uv python install "$UV_PYTHON_VERSION"
  MANAGED_PYTHON_BIN="$(uv python find "$UV_PYTHON_VERSION")"
fi

TEMP_ROOT="${RUNNER_TEMP:-/tmp}"
VENV_PATH=''
if command -v mktemp >/dev/null 2>&1; then
  VENV_PATH="$(mktemp -d "${TEMP_ROOT%/}/uv-ci-venv-XXXXXX" 2>/dev/null || true)"
fi
# On the offchance mktemp is not available or fails,
# fall back to using the PID and RANDOM.
if [ -z "$VENV_PATH" ]; then
  VENV_PATH="${TEMP_ROOT%/}/uv-ci-venv-$$-${RANDOM}"
fi

uv venv --python "$MANAGED_PYTHON_BIN" "$VENV_PATH"
if [ -x "$VENV_PATH/bin/python" ]; then
  PYTHON_BIN="$VENV_PATH/bin/python"
elif [ -x "$VENV_PATH/Scripts/python.exe" ]; then
  PYTHON_BIN="$VENV_PATH/Scripts/python.exe"
else
  echo "::error::Could not find Python executable in $VENV_PATH"
  exit 1
fi

# Ensure both python and python3 are available as binaries, for convenience.
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

EXPORT_PYTHON_ENV="$(
  normalize_bool_input 'EXPORT_PYTHON_ENV' "${EXPORT_PYTHON_ENV:-true}"
)"
ADD_PYTHON_TO_PATH="$(
  normalize_bool_input 'ADD_PYTHON_TO_PATH' "${ADD_PYTHON_TO_PATH:-true}"
)"

ensure_single_line 'PYTHON_BIN' "$PYTHON_BIN"
ensure_single_line 'VIRTUAL_ENV' "$VENV_PATH"
ensure_single_line 'PYTHON_DIR' "$PYTHON_DIR"

# Add the Python interpreter path to the GitHub output for explicit use as a step output.
printf 'python_bin=%s\n' "$PYTHON_BIN" >> "$GITHUB_OUTPUT"

if [ "$EXPORT_PYTHON_ENV" = 'true' ]; then
  printf 'PYTHON_BIN=%s\n' "$PYTHON_BIN" >> "$GITHUB_ENV"
  printf 'VIRTUAL_ENV=%s\n' "$VENV_PATH" >> "$GITHUB_ENV"
fi

# Add the binary dir to PATH for ease of access, if requested.
if [ "$ADD_PYTHON_TO_PATH" = 'true' ]; then
  printf '%s\n' "$PYTHON_DIR" >> "$GITHUB_PATH"
fi
