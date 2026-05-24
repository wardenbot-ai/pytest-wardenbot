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

The 18 deterministic shipped tests, plus 3 user-supplied business-truth facts.

## Edit before running for real

`conftest.py` has TODO comments where you should:

1. Verify the `request_field` / `response_field` names match your endpoint's
   request/response JSON shape.
2. Replace the placeholder business-truth facts with your real ones.
