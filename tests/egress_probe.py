"""Run pytest or a script with every network destination recorded.

Usage: python egress_probe.py OUTPUT.json pytest [ARGS...]
       python egress_probe.py OUTPUT.json script FILE.py

A Python audit hook records each ``socket.connect``, ``socket.sendto`` and
``socket.getaddrinfo`` in this process, including calls a library makes and
swallows (telemetry, update checks). Each destination is appended to OUTPUT
as one JSON line the moment it happens, so connections made while the
interpreter shuts down (atexit flushes, background threads) are kept too. The
exit status is the run's. Child processes are not covered; the CI egress job
runs the same tests inside a network namespace for that.
"""

from __future__ import annotations

import json
import runpy
import sys
from typing import Any

_log: Any = None


def _destination(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    if isinstance(value, tuple):
        return [_destination(item) for item in value]
    return value if isinstance(value, str | int | type(None)) else repr(value)


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if _log is None:
        return
    if event in {"socket.connect", "socket.sendto"}:
        record = [event, _destination(args[1])]
    elif event == "socket.getaddrinfo":
        record = [event, _destination((args[0], args[1]))]
    else:
        return
    _log.write(json.dumps(record) + "\n")
    _log.flush()


def main() -> int:
    global _log
    output, mode, *rest = sys.argv[1:]
    # Unbuffered and never closed explicitly: the OS closes it after the last
    # shutdown-time connection has been written.
    _log = open(output, "a", encoding="utf-8")  # noqa: SIM115
    sys.addaudithook(_hook)
    if mode == "pytest":
        import pytest

        return int(pytest.main(rest))
    if mode == "script":
        sys.argv = rest
        runpy.run_path(rest[0], run_name="__main__")
        return 0
    raise SystemExit(f"unknown mode {mode!r}")


if __name__ == "__main__":
    raise SystemExit(main())
