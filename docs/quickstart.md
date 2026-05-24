# Quickstart

Get from `pip install` to a green test run in under 60 seconds.

## 1. Install

```bash
pip install pytest-wardenbot
```

## 2. Generate starter files

```bash
pytest --wardenbot-quickstart
```

This creates two files in the current directory:

- `conftest.py` — registers the `chatbot` fixture and a placeholder
  `business_truth_fact` fixture
- `test_my_bot.py` — re-exports the shipped tests so plain `pytest` finds them

Choose an industry template if you want richer placeholders:

```bash
pytest --wardenbot-quickstart=ecommerce       # refund / shipping facts
pytest --wardenbot-quickstart=saas-support    # plan / trial facts
pytest --wardenbot-quickstart=generic         # minimal (default)
```

## 3. Point at your chatbot

The generated `conftest.py` reads two environment variables:

```bash
export CHATBOT_URL=https://your-chatbot.example.com/chat
export CHATBOT_TOKEN=sk-your-token              # optional
```

If your chatbot's HTTP shape isn't `{"message": "..."}` request and
`{"response": "..."}` response, edit the `request_field` / `response_field`
arguments in the generated `conftest.py`.

For non-HTTP chatbots (OpenAI Assistants, Anthropic, LangChain, MCP, Slack
bots, etc.), see [Add your chatbot](how-to/add-chatbot.md) for the
custom-adapter pattern.

## 4. Replace the placeholder facts

The generated `conftest.py` includes a `business_truth_fact` fixture with
placeholder facts about a fictional business. Replace them with your real
facts:

```python
from pytest_wardenbot.business_truth import BusinessTruthFact

@pytest.fixture(params=[
    BusinessTruthFact(
        label="Standard plan price",
        question="How much does the Standard plan cost per month?",
        expected_answer="$49",
        match_type="substring",
        acceptable_variations=("49/mo", "forty-nine dollars"),
    ),
    BusinessTruthFact(
        label="Business hours",
        question="What are your business hours?",
        expected_answer="9 AM to 5 PM EST",
        match_type="substring",
    ),
], ids=lambda f: f.parametrize_id())
def business_truth_fact(request):
    return request.param
```

Each entry becomes a parametrized test run. If your chatbot answers wrong,
the test fails with a message naming the fact and what it said instead.

## 5. Run the tests

```bash
pytest
```

You should see all the shipped tests run against your chatbot. The
deterministic tests are free (no LLM API spend).

## What to do with failures

Every failure includes a structured Markdown block at the bottom of the
message labeled `Agent-ready remediation (paste into Cursor / Claude Code)`.
Copy that block, paste it into your IDE's AI assistant, and let it propose
the fix. Re-run `pytest` to verify.

## Next steps

- **Add LLM-judge tests** for subjective checks (brand voice, semantic
  equivalence, hallucination grounding). See [Enable LLM-judge
  tests](how-to/llm-judge-setup.md).
- **Wire into CI.** See [CI integration](how-to/ci-integration.md) for
  a GitHub Actions example.
- **Write a custom adapter** if your chatbot isn't a JSON-over-HTTP endpoint.
  See [Add your chatbot](how-to/add-chatbot.md).
