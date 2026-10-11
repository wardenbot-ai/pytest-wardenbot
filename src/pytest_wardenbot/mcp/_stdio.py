"""Private entry point for an owned, isolated stdio harness subprocess."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from pytest_wardenbot.mcp._server import build_server
from pytest_wardenbot.mcp._wire import scenario_from_dict


def main() -> None:
    directory = Path(sys.argv[1])
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    (directory / "pid").write_text(str(os.getpid()), encoding="ascii")
    scenario = scenario_from_dict(config["scenario"])
    build_server(scenario, config["trial_id"], directory / "events.jsonl").run()


if __name__ == "__main__":
    main()
