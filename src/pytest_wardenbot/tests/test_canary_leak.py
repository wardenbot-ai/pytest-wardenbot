"""Canary-token leak test.

Sends the standard extraction corpora (jailbreak, system-prompt-leak,
refusal-bypass) against the chatbot and asserts a user-planted canary token
never appears in any response.

This is the strongest single signal for system-prompt disclosure in v0.1:
the canary is a high-entropy unique string. If the bot reproduces it,
it has reproduced part of its system prompt — no pattern matching, no
false positives.

**Setup required.** Both fixtures must be supplied by the user:

  - `wardenbot_canary`: the canary string (must also be planted in the
    chatbot's system prompt — otherwise the test cannot detect a leak).

Without `wardenbot_canary` the test skips with onboarding instructions.
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.canary import assert_no_canary_leak
from pytest_wardenbot.corpus.jailbreak import JAILBREAK_PROMPTS
from pytest_wardenbot.corpus.refusal_bypass import REFUSAL_BYPASS_PROMPTS
from pytest_wardenbot.corpus.system_prompt_leak import SYSTEM_PROMPT_LEAK_PROMPTS


@pytest.mark.wardenbot
@pytest.mark.severity_high
def test_canary_never_appears_in_responses(chatbot: ChatbotAdapter, wardenbot_canary: str) -> None:
    """Run the extraction corpora; assert the planted canary never leaks.

    Combines jailbreak + system-prompt-leak + refusal-bypass corpora into one
    sweep. On failure, the assertion message identifies the specific prompt
    that elicited the leak.
    """
    sweep: list[tuple[str, str]] = []
    sweep.extend((p, f"jailbreak/{a}") for p, a in JAILBREAK_PROMPTS)
    sweep.extend((p, f"system-leak/{a}") for p, a in SYSTEM_PROMPT_LEAK_PROMPTS)
    sweep.extend((p, f"refusal-bypass/{a}") for p, a in REFUSAL_BYPASS_PROMPTS)

    for prompt, attack_id in sweep:
        response = chatbot.send_message(prompt)
        # On the first leak, this raises an AssertionError with full context.
        # We don't need to accumulate all leaks; one is enough signal.
        try:
            assert_no_canary_leak(response.text, wardenbot_canary, prompt=prompt)
        except AssertionError as exc:
            raise AssertionError(f"Canary leak triggered by probe '{attack_id}'.\n\n{exc}") from exc
