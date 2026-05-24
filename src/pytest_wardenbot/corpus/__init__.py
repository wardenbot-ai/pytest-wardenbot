"""Canonical attack corpora used by the shipped tests.

v0.1 ships a small starter set per category. v0.2+ expands the corpora as we
learn from real-world findings (and from issues raised on the OSS repo).

Each corpus is a tuple of (prompt, optional_metadata) so we can parametrize
pytest cleanly without losing the rationale for each entry.
"""

from pytest_wardenbot.corpus.jailbreak import JAILBREAK_PROMPTS
from pytest_wardenbot.corpus.off_topic import OFF_TOPIC_PROMPTS
from pytest_wardenbot.corpus.refusal_bypass import REFUSAL_BYPASS_PROMPTS
from pytest_wardenbot.corpus.system_prompt_leak import SYSTEM_PROMPT_LEAK_PROMPTS

__all__ = [
    "JAILBREAK_PROMPTS",
    "OFF_TOPIC_PROMPTS",
    "REFUSAL_BYPASS_PROMPTS",
    "SYSTEM_PROMPT_LEAK_PROMPTS",
]
