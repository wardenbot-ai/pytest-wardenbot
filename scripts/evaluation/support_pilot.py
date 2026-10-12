"""Run the offline-default, bounded support-application control pilot."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from examples.support_agent.run_controls import main

if __name__ == "__main__":
    raise SystemExit(main())
