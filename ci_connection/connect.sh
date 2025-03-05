#!/bin/bash

set -ex

# Bootstraps Python setup
FILE_PATH="$1"
if [ -f "$FILE_PATH" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    # Skip empty lines and lines starting with a #
    [[ -z "$line" || "$line" =~ ^# ]] && continue
    # Export the variable (the line should be in the form KEY='value')
    export "${line}"
  done < "$FILE_PATH"

fi

python notify_connection.py
