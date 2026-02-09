#!/bin/bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Installs a specific Python version, sets it as system default, and bootstraps pip.
set -euo pipefail

VERSION=$1
if [ -z "$VERSION" ]; then
  echo "Error: No Python version specified." >&2
  exit 1
fi

echo "Installing Python $VERSION."

setup_ppa() {
  export DEBIAN_FRONTEND=noninteractive

  # Check if deadsnakes is already configured
  if grep -r -q "deadsnakes" /etc/apt/sources.list /etc/apt/sources.list.d/; then
    apt-get update -qq >/dev/null
    return
  fi

  apt-get update -qq >/dev/null
  apt-get install -y -qq gnupg curl lsb-release >/dev/null

  mkdir -p /etc/apt/keyrings
  curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xF23C5A6CF475977595C89F51BA6932366A755776" \
    | gpg --dearmor -o /etc/apt/keyrings/deadsnakes.gpg --yes

  echo "deb [signed-by=/etc/apt/keyrings/deadsnakes.gpg] http://ppa.launchpad.net/deadsnakes/ppa/ubuntu $(lsb_release -cs) main" \
    > /etc/apt/sources.list.d/deadsnakes.list

  apt-get update -qq >/dev/null
}

# Configure PPA
setup_ppa

# Install Python + distutils
apt-get install -y -qq "python${VERSION}" "python${VERSION}-distutils" "python${VERSION}-venv" >/dev/null

# Set newly installed Python version as system default
update-alternatives --install /usr/bin/python python "/usr/bin/python${VERSION}" 1 >/dev/null
update-alternatives --set python "/usr/bin/python${VERSION}" >/dev/null

# Prioritize /usr/bin in PATH to avoid shadowing by runner defaults
if [ -n "${GITHUB_PATH:-}" ]; then
  echo "/usr/bin" >> "$GITHUB_PATH"
fi
export PATH="/usr/bin:$PATH"

# Install pip with root warning suppressed
curl -sS https://bootstrap.pypa.io/get-pip.py -o get-pip.py
python get-pip.py --root-user-action=ignore --quiet
rm get-pip.py

echo "Installation complete:"
echo "----------------------------------------------------------------"
python --version
python -m pip --version
echo "Which Python:  $(command -v python)"
echo "Resolved Path: $(readlink -f $(command -v python))"
echo "----------------------------------------------------------------"
