# Injection regression: deterministic tests for LLM pipelines

Reference examples for the local model endpoint (`pytest_wardenbot.model`) and
the pipeline graders. Each pattern has a naive and a fixed implementation, a
small response folder, and tests for every deterministic layer:

1. **Prompt checks**: where the untrusted text landed in the request.
2. **Compromised-model checks**: a scripted hostile reply, as if the injection worked.
3. **Replay**: realistic replies from `llm_responses/`, and hostile mutations of them.

No API key is needed. Attack cases are strict `xfail` on the naive implementation
and pass on the fixed one; benign controls pass on both.

```bash
pip install "pytest-wardenbot[openai]>=0.8.0"
cd examples/injection_regression
pytest
```

| Pattern | What it shows |
|---|---|
| `source_rating/` | A batch of web pages rated in one call: fencing and escaping, a data rule, and binding ratings to the ids the app issued. Includes a recording matched by request hash, which goes stale when the prompt changes. |
| `post_summary/` | Social posts summarized into a pydantic model. The naive prompt JSON-encodes untrusted posts, which the `json` encoding finds outside any fence. Layer 3 replays exported application logs (`exports/posts.jsonl`, built by `make_exports.py`), picked per case by manifest rules. |
| `doc_chat/` | A streaming Responses answer over retrieved documents, rendered as HTML. The fixed version fences the documents in the user turn, renders images as text and links only to the documents' own hosts. Layer 3 replays a hand-written `.sse` stream byte for byte. |

`pyproject.toml` turns the endpoint on (`[tool.wardenbot.model]`) before any
test module is imported, so the cached client in `llm.py` talks to it.
`record_offline.py` regenerates the hash-matched recording with record mode
against a local stand-in for the API, and `make_exports.py` rebuilds the
exported log from the hand-written replies.

Response folders hold model replies exactly: exclude them from whitespace
fixers such as pre-commit's `end-of-file-fixer` (see this repository's
`.pre-commit-config.yaml`), so an `.sse` stream keeps its final blank line.
