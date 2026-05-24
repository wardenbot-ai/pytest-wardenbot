# Examples

Worked examples for `pytest-wardenbot`. Each is self-contained — `cd` into the
directory, follow its README, run `pytest`.

| Example | What it shows |
|---|---|
| [`basic_http/`](./basic_http/) | The bundled `HTTPChatbotAdapter` against any HTTP chatbot endpoint. The quickest starting point. |
| [`openai_chat/`](./openai_chat/) | The bundled `OpenAIChatAdapter` against the OpenAI Chat Completions API. Requires the `[openai]` extra. |
| [`anthropic_messages/`](./anthropic_messages/) | The bundled `AnthropicMessagesAdapter` against the Anthropic Messages API. Requires the `[anthropic]` extra. |
| [`custom_openai_adapter/`](./custom_openai_adapter/) | Writing your own `ChatbotAdapter` for chatbots with middleware (RAG, agents, prompt rewriting). Pattern applies to any vendor SDK. |
| [`github_actions/`](./github_actions/) | A GitHub Actions workflow that runs the wardenbot tests on every push. |

## When to use each

- **Have a chatbot behind an HTTP endpoint?** `basic_http/`. Most common case.
- **Calling OpenAI Chat directly?** `openai_chat/`. Bundled adapter, no custom code.
- **Calling Anthropic directly?** `anthropic_messages/`. Bundled adapter, no custom code.
- **Chatbot has middleware between the user and the model** (RAG, function calling with custom side effects, prompt rewriting)? `custom_openai_adapter/` — same template applies to any vendor SDK.
- **Want to test on every commit?** Drop the workflow from `github_actions/` into your repo.

## Faster path

If you don't want to copy from these examples, run:

```bash
pip install pytest-wardenbot
pytest --wardenbot-quickstart            # generic template
pytest --wardenbot-quickstart=ecommerce  # or ecommerce / saas-support
```

That generates `conftest.py` + `test_my_bot.py` in the current directory with
placeholder values you replace inline.
