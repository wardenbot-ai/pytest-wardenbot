"""Deterministic tests for LLM pipelines: a local OpenAI-compatible model endpoint.

The endpoint lets an application's own SDK client run against scripted,
replayed or recorded replies, so prompt assembly and output handling can be
tested in CI without an API key. Nothing in this package imports pytest: it
works the same under pytest, ``unittest`` and Django's ``manage.py test``.
"""

from __future__ import annotations

__all__: list[str] = []
