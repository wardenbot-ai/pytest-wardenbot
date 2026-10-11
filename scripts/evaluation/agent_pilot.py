"""Run the bounded paired reference-agent pilot; no .env files are loaded."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from examples.mcp_agent.run_controls import main

if __name__ == "__main__":
    raise SystemExit(main())
