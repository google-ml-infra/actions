"""Background keep-alive that dies when parent dies."""

import sys
import time

import utils

utils.setup_logging()

INTERVAL = 30


def main():
  if len(sys.argv) < 2:
    sys.exit(1)

  try:
    parent_pid = int(sys.argv[1])
  except ValueError:
    sys.exit(1)

  while utils.parent_alive(parent_pid):
    time.sleep(INTERVAL)
    if utils.parent_alive(parent_pid):
      utils.send_message(utils.ConnectionSignals.KEEP_ALIVE)

  # Parent died - send close signal
  utils.send_message(utils.ConnectionSignals.CONNECTION_CLOSED)


if __name__ == "__main__":
  main()
