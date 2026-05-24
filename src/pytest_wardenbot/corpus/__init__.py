"""Canonical attack corpora used by the shipped tests.

v0.1 ships a starter set per category. v0.2+ expands the corpora as we learn
from real-world findings (and from issues raised on the OSS repo).

Single-turn:
    JAILBREAK_PROMPTS          (prompt, attack_id)
    SYSTEM_PROMPT_LEAK_PROMPTS (prompt, attack_id)
    REFUSAL_BYPASS_PROMPTS     (prompt, attack_id)
    OFF_TOPIC_PROMPTS          (prompt, attack_id)
    INDIRECT_INJECTION_PROMPTS (prompt, attack_id) — XPIA via embedded directives

Encoded payloads:
    ENCODED_PAYLOAD_PROMPTS    (prompt, trigger_words, attack_id) — smuggles
                                 a directive through Base64/ROT13/leet/hex

Multi-turn (requires session-aware adapter):
    MULTI_TURN_JAILBREAK_PROMPTS (priming_turns, payload_prompt, attack_id)
"""

from pytest_wardenbot.corpus.encoded_payloads import ENCODED_PAYLOAD_PROMPTS
from pytest_wardenbot.corpus.indirect_injection import INDIRECT_INJECTION_PROMPTS
from pytest_wardenbot.corpus.jailbreak import JAILBREAK_PROMPTS
from pytest_wardenbot.corpus.multi_turn import MULTI_TURN_JAILBREAK_PROMPTS
from pytest_wardenbot.corpus.off_topic import OFF_TOPIC_PROMPTS
from pytest_wardenbot.corpus.refusal_bypass import REFUSAL_BYPASS_PROMPTS
from pytest_wardenbot.corpus.system_prompt_leak import SYSTEM_PROMPT_LEAK_PROMPTS

__all__ = [
    "ENCODED_PAYLOAD_PROMPTS",
    "INDIRECT_INJECTION_PROMPTS",
    "JAILBREAK_PROMPTS",
    "MULTI_TURN_JAILBREAK_PROMPTS",
    "OFF_TOPIC_PROMPTS",
    "REFUSAL_BYPASS_PROMPTS",
    "SYSTEM_PROMPT_LEAK_PROMPTS",
]
