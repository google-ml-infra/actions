#!/bin/bash

# Bootstraps Python setup
FILE_PATH="python"
if [ -f "$FILE_PATH" ]; then
  source "$FILE_PATH"
fi

python notify_connection.py
