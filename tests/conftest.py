"""Pytest bootstrap that keeps automated checks out of the runtime log file."""

import os


os.environ["LOG_TO_FILE"] = "false"
