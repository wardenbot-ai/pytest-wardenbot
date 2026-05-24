# Example: basic HTTP chatbot

The simplest setup. Uses the bundled `HTTPChatbotAdapter` against any chatbot
endpoint that speaks JSON over HTTP POST.

## Run

```bash
pip install pytest-wardenbot
export CHATBOT_URL=https://your-chatbot.example.com/chat
export CHATBOT_TOKEN=sk-your-token    # optional; only if your endpoint needs auth
pytest -v
```

## What it tests

The 30 deterministic shipped tests, plus 3 user-supplied business-truth facts.
(Multi-turn jailbreak tests run but session memory is per-request on the
default `HTTPChatbotAdapter` — for true multi-turn, write an adapter that
honors `session_id`, or use the bundled OpenAI/Anthropic adapters.)

## Edit before running for real

`conftest.py` has TODO comments where you should:

1. Verify the `request_field` / `response_field` names match your endpoint's
   request/response JSON shape.
2. Replace the placeholder business-truth facts with your real ones.
