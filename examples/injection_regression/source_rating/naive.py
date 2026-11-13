"""Naive: page text goes inline, and whatever the model returns is kept."""

from __future__ import annotations

from typing import Any

from llm import ask_model


def rate_sources(sources: list[dict[str, str]]) -> list[dict[str, Any]]:
    prompt = "Rate each source for relevance:\n" + "\n".join(
        f"{source['url']}\n{source['text']}" for source in sources
    )
    return ask_model([{"role": "user", "content": prompt}])["ratings"]
