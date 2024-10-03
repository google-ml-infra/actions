import logging
import os
import sys

# Check if debug logging should be enabled for the scripts:
# WAIT_FOR_CONNECTION_DEBUG is a custom variable.
# RUNNER_DEBUG and ACTIONS_RUNNER_DEBUG are GH env vars, which can be set
# in various ways, one of them - enabling debug logging from the UI, when
# triggering a run:
# https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/store-information-in-variables#default-environment-variables
# https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/troubleshooting-workflows/enabling-debug-logging#enabling-runner-diagnostic-logging
_SHOW_DEBUG = bool(
  os.getenv(
    "WAIT_FOR_CONNECTION_DEBUG",
    os.getenv("RUNNER_DEBUG", os.getenv("ACTIONS_RUNNER_DEBUG")),
  )
)


def setup_logging():
  logging.basicConfig(
    level=logging.INFO if not _SHOW_DEBUG else logging.DEBUG,
    format="%(levelname)s: %(message)s",
    stream=sys.stderr,
  )
