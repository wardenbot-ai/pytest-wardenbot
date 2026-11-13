"""Test settings: start the model endpoint before Django imports the applications."""

from pytest_wardenbot.model import install

install()  # mode and folder come from [tool.wardenbot.model] and WARDENBOT_* variables

from project.settings import *  # noqa: E402, F403
