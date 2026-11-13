"""A minimal Django project that runs pipeline tests with manage.py test."""

import multiprocessing
import os
import sys

if __name__ == "__main__":
    # The tests choose the parallel runner's start method (spawn, forkserver, fork).
    if os.environ.get("TEST_START_METHOD"):
        multiprocessing.set_start_method(os.environ["TEST_START_METHOD"], force=True)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings_test")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
