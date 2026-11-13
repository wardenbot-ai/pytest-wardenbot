"""Test settings: start the model endpoint before Django imports the applications."""

import os

from pytest_wardenbot.model import install

install()  # mode and folder come from [tool.wardenbot.model] and WARDENBOT_* variables
# Parallel workers inherit this, so a test can tell it runs in a worker process.
os.environ.setdefault("PIPELINE_MAIN_PID", str(os.getpid()))

from project.settings import *  # noqa: E402, F403
