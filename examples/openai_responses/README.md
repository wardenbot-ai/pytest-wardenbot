# Example: OpenAI Responses

This example runs the shipped deterministic security tests, business facts,
canary disclosure checks, and multi-turn attacks against a text-only chatbot.
Replace the example instructions and facts with your chatbot's configuration.

Set `OPENAI_API_KEY` in your environment or secret manager, then run from this
directory:

```bash
python -m pip install 'pytest-wardenbot[openai]'
export OPENAI_MODEL='gpt-4o-mini'
pytest -v
```

Running the suite sends billable requests to OpenAI. Missing credentials fail
the run. No LLM judge or tool execution is configured in this example.

`OpenAIResponsesAdapter` sends the instructions on every request and keeps
session history locally, replaying complete output items, including reasoning.
It always sends `store=False`; reset clears local history and does not delete
remote records or change OpenAI's other retention policies. Temperature is
omitted unless supplied explicitly. The fixture closes its owned SDK client
after each test.

For async applications, `AsyncOpenAIResponsesAdapter` provides awaitable
`send_message` and `reset_session` methods on one event loop; use `await
adapter.aclose()` to close an internally created client. Injected clients
remain the caller's responsibility. Both adapters accept completed text or
refusals and report tool outputs and incomplete responses as infrastructure
errors. Streaming requests are unsupported. Applications with tool loops
should provide their own adapter around the complete application.

See OpenAI's [Responses migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses)
and [conversation state guide](https://developers.openai.com/api/docs/guides/conversation-state).
