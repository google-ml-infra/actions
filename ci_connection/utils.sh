#!/usr/bin/env bash

# Copyright 2025 Google LLC

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     https://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


# Requires Bash 4.3+ (out in February 2014). Other shells likely will not work.
#
# These utils are focused on making sure a suitable Python is available, and
# used, for the ML CI connection backend and frontend.

MIN_PYTHON_MAJOR_VERSION=3
MIN_PYTHON_MINOR_VERSION=10

UV_VERSION="0.6.17"
UV_RELEASE_BASE_URL="https://github.com/astral-sh/uv/releases/download"
UV_PYTHON_TO_INSTALL="3.13"

# Checksums for uv 0.6.17
declare -A UV_CHECKSUMS=(
  ["aarch64-pc-windows-msvc"]="3a9468e90df970f75759da6caed7dfde2816e0f3842031235c3835fc0c4e7d09"
  ["aarch64-unknown-linux-gnu"]="6fb716c36e8ca9cf98b7cb347b0ced41679145837eb22890ee5fa9d8b68ce9f5"
  ["aarch64-unknown-linux-musl"]="98750f5c0cd9eb520799d10649efb18441b616150f07e6c1125f616a3fd137e8"
  ["x86_64-pc-windows-msvc"]="32882cf98f646cafca003e7a7c471b7ff4ba977b681c9fa3b12cf908ba64af82"
  ["x86_64-unknown-linux-gnu"]="720ec28f7a94aa8cd91d3d57dec1434d64b9ae13d1dd6a25f4c0cdb837ba9cf6"
  ["x86_64-unknown-linux-musl"]="28bd6b50be068cc09d8a46b76f8c4b72271d471c6673a5bdb47793622e62224d"
)

# Detect Windows shells
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) _IS_WINDOWS=1 ;;
  *)                    _IS_WINDOWS=0 ;;
esac

is_true_like_env() {
  local var_name var_val var_val_lower

  for var_name in "$@"; do
    # ! = indirect expansion - treat value of the variable as the variable name
    var_val="${!var_name:-}"

    [[ -z "$var_val" ]] && continue # Skip if raw value is empty

    var_val_lower="${var_val,,}" # lowercase
    case "$var_val_lower" in
      "0"|"false"|"n"|"no"|"none"|"null"|"n/a") ;; # negative value, continue to next
      *) return 0 ;;
    esac
  done

  return 1 # no true-like variables found
}

if is_true_like_env RUNNER_DEBUG HALT_DISPATCH_INPUT MLCI_ALLOW_PYTHON_INSTALL; then
  _WAIT_CHECK_ELIGIBLE=1
else
  _WAIT_CHECK_ELIGIBLE=0
fi

_normalize_path() {
  local input_path="$1"
  if (( _IS_WINDOWS )); then local output_type="${2:-windows}"
  else local output_type="${2:-posix}"
  fi
  local normalized_path

  # This handles cases like `HOME=/` leading to `//somepath`
  # While harmless on Linux, double forward slashes break conversion of
  # POSIX paths to Windows ones via `cygpath`.
  normalized_path=$(printf '%s' "$input_path" | sed 's#/\+#/#g')

  if (( _IS_WINDOWS )) && [[ "$output_type" == "windows" ]]; then
      cygpath -m "$normalized_path"
  else
    # On non-Windows, the path is already POSIX-like
    echo "$normalized_path"
  fi
}

detect_pm() {
  if command -v apt-get &>/dev/null; then echo 'apt-get update 1>/dev/null && apt-get install -y';
  elif command -v dnf &>/dev/null; then echo 'dnf install -y';
  elif command -v yum &>/dev/null; then echo 'yum install -y';
  elif command -v apk &>/dev/null; then echo 'apk add';
  elif command -v pacman &>/dev/null; then echo 'pacman -S --noconfirm';
  elif command -v brew &>/dev/null; then echo 'brew install';
  else echo ""; fi
}

ensure_packages_installed() {
  local missing=() pm cmd
  local pkg

  for pkg in "$@"; do
    command -v "$pkg" &>/dev/null || missing+=("$pkg")
  done

  [[ ${#missing[@]} -eq 0 ]] && return 0

  pm=$(detect_pm)
  if [[ -z "$pm" ]]; then
    printf "ERR: No package manager found. Cannot install missing packages: '%s'\n" "${missing[*]}" >&2
    return 1
  fi

  cmd="$pm ${missing[*]}"
  printf "INFO: Attempting to install missing packages: '%s'\n" "${missing[*]}" >&2

  if ! eval "$cmd 1>/dev/null"; then
    printf "ERR: Failed to install one or more packages: '%s'.\n" "${missing[*]}" >&2
    echo "ERR: Command executed: $cmd" >&2
    return 1
  fi

  echo "INFO: Packages installed successfully." >&2
  return 0
}

# Determines the Linux or Windows target triple for uv.
# Only specific triples in the UV_CHECKSUMS array above are supported, others
# working is unlikely, or incidental.
get_target_triple() {
  local arch os_type target_triple
  arch=$(uname -m)
  os_type=$(uname -s)

  if [[ "$os_type" == Linux* ]]; then
    local libc="gnu"
    if command -v ldd >/dev/null && ldd --version 2>/dev/null | grep -qi 'musl'; then
      libc="musl"
    elif command -v file >/dev/null && [ -e /bin/sh ] && file /bin/sh 2>/dev/null | grep -qi 'interpreter.*musl'; then
      libc="musl"
    fi
    target_triple="${arch}-unknown-linux-${libc}"
  elif (( _IS_WINDOWS )); then
    case "$arch" in
      x86_64) target_triple="x86_64-pc-windows-msvc" ;;
      aarch64) target_triple="aarch64-pc-windows-msvc" ;;
      *) echo "ERR: Unsupported architecture for Windows: ${arch}" >&2; return 1 ;;
    esac
  else
    echo "ERR: Unsupported OS type: ${os_type}" >&2; return 1
  fi
  echo "$target_triple"
}

# Downloads and verifies the uv archive.
download_and_verify_uv() {
  local dest_file="$1" target_triple="$2" download_tool="$3" # required
  local expected_checksum filename url tmp_file calculated_checksum
  local archive_extension=".tar.gz"
  [[ "$target_triple" == *windows* ]] && archive_extension=".zip"

  expected_checksum="${UV_CHECKSUMS[${target_triple}]}"
  [[ -z "$expected_checksum" ]] && { echo "ERR: Missing checksum for ${target_triple}." >&2; return 1; }

  filename="uv-${target_triple}${archive_extension}"
  url="${UV_RELEASE_BASE_URL}/${UV_VERSION}/${filename}"

  if (( _IS_WINDOWS )); then
    tmp_file=$(mktemp "uv-XXXXXX.zip") || { echo "ERR: mktemp failed." >&2; return 1; }
  else
    tmp_file=$(mktemp "uv-XXXXXX.tar.gz") || { echo "ERR: mktemp failed." >&2; return 1; }
  fi
  echo "INFO: Downloading uv from ${url}" >&2

  local download_cmd_array=()
  local attempt=1 max_attempts=3
  local sleep_seconds=1

  if [[ "$download_tool" == "curl" ]]; then
    download_cmd_array=(curl --proto '=https' --tlsv1.2 -sSfL -o "${tmp_file}" "${url}")
  else
    download_cmd_array=(wget --secure-protocol=TLSv1_2 -q -O "${tmp_file}" "${url}")
  fi

  while ! "${download_cmd_array[@]}"; do
    (( attempt++ ))
    if (( attempt > max_attempts )); then
      echo "ERR: Download failed after ${max_attempts} attempts for ${url} using ${download_tool}" >&2
      rm -f "${tmp_file}" # Clean up potential partial/empty file
      return 1
    fi
    echo "WARN: Retry ${attempt}/${max_attempts} for ${url} using ${download_tool}. Retrying in ${sleep_seconds}s..." >&2
    sleep "${sleep_seconds}"
    sleep_seconds=$(( sleep_seconds * 2 ))

  done

  calculated_checksum=$(sha256sum < "${tmp_file}" | awk '{print $1}')
  if [[ "$calculated_checksum" != "$expected_checksum" ]]; then
    echo "ERR: Checksum mismatch for downloaded uv." >&2
    rm -f "${tmp_file}"
    return 1
  fi

  mv "${tmp_file}" "${dest_file}"
}

# Unpacks the uv archive and adds it to PATH
unpack_and_setup_uv() {
  local archive_path="$1" target_triple="$2" uv_bin_dir env_script_path
  uv_bin_dir="$(_normalize_path "$HOME/.uv/bin" posix)"
  env_script_path="$(_normalize_path "$HOME/.uv/env")"
  mkdir -p "$uv_bin_dir"
  local unpack_dir
  unpack_dir="$(_normalize_path "$(mktemp -d)")"
  trap 'rm -rf "${unpack_dir}"' EXIT RETURN

  local extracted_uv_content_dir="${unpack_dir}"
  if (( _IS_WINDOWS )); then
    unzip -q "$archive_path" -d "$unpack_dir"
  else
    tar -xzf "$archive_path" -C "$unpack_dir"
    extracted_uv_content_dir="${unpack_dir}/uv-${target_triple}"
  fi

  local exe_suffix=""
  (( _IS_WINDOWS )) && exe_suffix=".exe"
  local uv_exe_name="uv${exe_suffix}" uvx_exe_name="uvx${exe_suffix}"

  mv "${extracted_uv_content_dir}/${uv_exe_name}" "${uv_bin_dir}/"
  mv "${extracted_uv_content_dir}/${uvx_exe_name}" "${uv_bin_dir}/"

  rm -rf "${unpack_dir}"
  trap - EXIT RETURN # Clear the trap for unpack_dir

  cat > "$env_script_path" << ENV_SCRIPT
#!/bin/sh
case ":\${PATH}:" in *:'${uv_bin_dir}':*) ;; *) export PATH="${uv_bin_dir}:\${PATH}" ;; esac
ENV_SCRIPT
  chmod +x "$env_script_path"

  local profile_files=("$HOME/.profile" "$HOME/.bash_profile" "$HOME/.bashrc" "$HOME/.zshrc")
  local source_line
  source_line=". '$(_normalize_path "$env_script_path" posix)'"
  local file_updated=false

  for rc_file in "${profile_files[@]}"; do
    if [[ -f "$rc_file" ]] && ! grep -qF -- "$source_line" "$rc_file" 2>/dev/null; then
      echo "" >> "$rc_file"
      echo "$source_line" >> "$rc_file"
      file_updated=true
    fi
  done

  local default_profile="$HOME/.profile"
  if [[ "$file_updated" = false && ! -f "$default_profile" ]]; then
    echo "INFO: Adding uv to PATH by creating/updating ${default_profile}" >&2
    echo "$source_line" >> "$default_profile" # Append rather than overwrite, in case it exists but was empty
  fi

  export PATH="${uv_bin_dir}:$PATH"
}

suitable_python_exists() {
  local py_exe py_maj_min_output major minor setup_py_loc canon_py_path
  py_exe=$(command -v python3 || command -v python)
  [[ -z "$py_exe" ]] && return 1
  py_maj_min_output=$("$py_exe" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
  major="${py_maj_min_output%%.*}"
  minor="${py_maj_min_output#*.}"
  if [[ "$major" -lt "$MIN_PYTHON_MAJOR_VERSION" ]] || \
     { [[ "$major" -eq "$MIN_PYTHON_MAJOR_VERSION" && "$minor" -lt "$MIN_PYTHON_MINOR_VERSION" ]]; }; then
    return 1
  fi

  # Check if the Python is a setup-python one
  # (variable pythonLocation is set), and if so, do not use it.

  # setup-python Python makes itself available via modifying various env
  # variables - something that's not reflected in a connecting session.
  # It also requires installing libssl-dev to ensure ability to make requests.

  # One of the variables it sets is `pythonLocation`, which appears to be unique
  # to the action. Here, it's used to check if the Python is a setup-python one.

  # There is a potential of false positives here, but it's very low and
  # thus acceptable.
  setup_py_loc="${pythonLocation:-}"
  if [[ -n "$setup_py_loc" ]]; then
    canon_py_path=$(readlink -f "$py_exe" 2>/dev/null || echo "$py_exe") # Fallback for readlink failure
    # Check if python executable path starts with setup_py_loc
    [[ "$canon_py_path" == "${setup_py_loc}"/* || "$canon_py_path" == "$setup_py_loc" ]] && return 1
  fi

  _normalize_path "$py_exe"
}

ensure_suitable_python_is_available() {
  local -n python_bin_path="$1" # nameref for output variable, used by caller
  local suitable_python_path
  if suitable_python_path=$(suitable_python_exists); then
    python_bin_path="${suitable_python_path}"
    return 0
  fi

  echo "INFO: Suitable Python not found..." >&2

  if (( ! _WAIT_CHECK_ELIGIBLE )); then
    echo >&2
    echo "INFO: No conditions were met to install Python at runtime." >&2
    echo "To allow installation, do one of:" >&2
    echo "1. Enable debug logging." >&2
    echo "2. Set MLCI_ALLOW_PYTHON_INSTALL or HALT_DISPATCH_INPUT somewhere in the workflow." >&2
    echo >&2

    return
  fi

  echo "INFO: Installing a standalone Python via uv." >&2

  local pkgs_to_ensure=()
  local download_tool="" # Specify which tool to use to download uv

  if command -v curl >/dev/null 2>&1; then download_tool="curl"
  elif command -v wget >/dev/null 2>&1; then download_tool="wget"
  else
    pkgs_to_ensure+=("curl")
    download_tool="curl"
  fi
  # Add other OS-specific packages
  if (( _IS_WINDOWS )); then
    pkgs_to_ensure+=("unzip")
  fi
  ensure_packages_installed "${pkgs_to_ensure[@]}" || return 1

  if ! command -v uv &>/dev/null; then
    local archive_extension=".tar.gz"
    (( _IS_WINDOWS )) && archive_extension=".zip"
    local tmp_archive
    tmp_archive="$(mktemp "uv-dl-XXXXXX${archive_extension}")"
    trap 'rm -f "${tmp_archive}"' EXIT

    local target_triple
    target_triple=$(get_target_triple) || return 1

    download_and_verify_uv "$tmp_archive" "$target_triple" "$download_tool" || return 1
    unpack_and_setup_uv "$tmp_archive" "$target_triple" || return 1

    rm -f "${tmp_archive}"
    trap - EXIT
  fi

  echo "INFO: Installing Python ${UV_PYTHON_TO_INSTALL} using uv." >&2
  if ! uv python install "$UV_PYTHON_TO_INSTALL"; then
    echo "ERR: uv failed to install Python ${UV_PYTHON_TO_INSTALL}." >&2
    return 1
  fi

  local found_python_path
  found_python_path="$(uv python find "$UV_PYTHON_TO_INSTALL")"
  if [[ -z "$found_python_path" ]]; then
    echo "ERR: uv installed Python ${UV_PYTHON_TO_INSTALL} but could not find it afterwards." >&2
    return 1
  fi
  # This is is a nameref, the shellcheck is wrong
  # shellcheck disable=SC2034
  python_bin_path="$found_python_path"
}

# This is exclusively for testing whether Python procurement works as expected
# Creates a temporary directory with mock python executables and prepends it to PATH.
# The temp directory and the PATH changes are not undone afterwards.
hide_existing_pythons() {
  local temp_dir
  temp_dir=$(mktemp -d "python_hider_temp_XXXXXX")

  unalias python >/dev/null 2>&1 || true
  unalias python3 >/dev/null 2>&1 || true

  # Create mock 'python' and 'python3' that exit with "command not found" status
  printf '#!/bin/sh\nexit 127' > "$temp_dir/python" && chmod +x "$temp_dir/python"
  printf '#!/bin/sh\nexit 127' > "$temp_dir/python3" && chmod +x "$temp_dir/python3"

  # Prepend the temporary directory to PATH for the current script's execution
  export PATH="$temp_dir:$PATH"

  echo "INFO: Python-less environment simulated. Mock executables in $temp_dir. PATH modified." >&2
}

# If the Python-based connection/connection check fails, do a much more basic
# check for whether the job should wait for a connection.
# This is just a quick fallback, the intended way is to have Python handle all the
# necessary checks.
print_basic_connection_command_if_requested() {
  if (( ! _WAIT_CHECK_ELIGIBLE )); then
    return
  fi

  local runner_name_val="${CONNECTION_POD_NAME}"
  local cluster_val="${CONNECTION_CLUSTER}"
  local location_val="${CONNECTION_LOCATION}"
  local ns_val="${CONNECTION_NS}"

  local connect_command_core="ml-actions-connect --runner=${runner_name_val} --ns=${ns_val} --loc=${location_val} --cluster=${cluster_val}"

  local fallback_command="${connect_command_core} --entrypoint=\"bash -i\""
  local bold_green='\033[1;32m' # bold and green
  local reset_color='\033[0m'   # reset the modifications

  echo >&2
  echo "Python-based connection failed. The Bash fallback command is printed below." >&2
  echo "Using this fallback will not let the runner know a connection " >&2
  echo "was made, and will not cause the runner to wait automatically." >&2
  echo "To fix this, do one of:" >&2
  echo "1. Ensure a suitable Python (3.10+, not installed via setup-python) is present under python/python3 on the VM/Docker container, prior to the waiting for connection step." >&2
  echo "2. Add a wait/sleep somewhere after the 'Wait for Connection' step in the workflow." >&2
  echo "For details, see go/ml-github-actions:connect." >&2

  echo -e "${bold_green}CONNECTION COMMAND (FALLBACK):${reset_color}" >&2
  echo -e "${bold_green}${fallback_command}${reset_color}" >&2
}
