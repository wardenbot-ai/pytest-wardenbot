# Examples

Three worked examples for `pytest-wardenbot`. Each is self-contained — `cd` into
the directory, follow its README, run `pytest`.

| Example | What it shows |
|---|---|
| [`basic_http/`](./basic_http/) | The default `HTTPChatbotAdapter` against an HTTP chatbot endpoint. The quickest starting point. |
| [`custom_openai_adapter/`](./custom_openai_adapter/) | Writing your own `ChatbotAdapter` to drive an OpenAI Chat Completions endpoint. Pattern applies to any vendor SDK. |
| [`github_actions/`](./github_actions/) | A GitHub Actions workflow that runs the wardenbot tests on every push. |

## When to use each

- **Have a chatbot behind an HTTP endpoint?** Start with `basic_http/`. Most cases.
- **Using OpenAI / Anthropic / LangChain / MCP directly?** Use `custom_openai_adapter/` as the template for your own adapter (built-in adapters for these land in v0.2).
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
