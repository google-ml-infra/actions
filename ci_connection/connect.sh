#!/bin/bash

set -ex

# Bootstraps Python setup
FILE_PATH="$1"
if [ -f "$FILE_PATH" ]; then
  source "$FILE_PATH"
  cat $FILE_PATH
fi

python notify_connection.py
