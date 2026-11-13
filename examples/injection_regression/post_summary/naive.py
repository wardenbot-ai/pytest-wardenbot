"""Naive: posts JSON-encoded straight into the user message, no fence, no data rule."""

from __future__ import annotations

import json

from llm import ask_model

from post_summary.models import PostSummary


def summarize_posts(posts: list[dict[str, str]]) -> PostSummary:
    prompt = "Summarize these posts and flag the ones that break the rules:\n" + json.dumps(posts)
    return PostSummary.model_validate(ask_model([{"role": "user", "content": prompt}]))
