# Test a stateful LangGraph

A checkpointer-backed graph stores conversation state under
`configurable.thread_id`. WardenBot passes each probe's session ID into that key
when you set `session_config_key="thread_id"`. Give the adapter a reset hook
that deletes the corresponding checkpoint history before the next probe.
LangGraph documents [thread persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
and [checkpoint deletion](https://reference.langchain.com/python/langgraph.checkpoint/memory/InMemorySaver).

The executable recipe in `examples/langgraph_state/chatbot.py` uses
`MessagesState`, `StateGraph`, and `InMemorySaver`. It needs no API key:

```bash
pip install -e '.[langchain]' langgraph
python examples/langgraph_state/chatbot.py
```

The node counts user turns. The script asserts that two threads keep independent
histories and that resetting one thread clears its history while preserving the
other. Replace the node with your chatbot to run safety probes.

## Map prompts and assistant responses

Graphs commonly accept a messages state and return an entire state dictionary.
Map the prompt into a user message and extract only the final assistant text:

```python
from pytest_wardenbot.adapters.langchain_runnable import LangChainAdapter


def assistant_text(state):
    message = state["messages"][-1]
    if message.type != "ai" or not isinstance(message.content, str):
        raise ValueError("Expected a final assistant message with string content")
    return message.content


adapter = LangChainAdapter(
    graph,  # compiled with checkpointer=checkpointer
    stateful=True,
    session_config_key="thread_id",
    input_mapper=lambda prompt: {"messages": [("user", prompt)]},
    text_extractor=assistant_text,
    reset_hook=checkpointer.delete_thread,
)
```

`input_mapper` and `input_key` are alternatives. Use `input_key` when the input
is a simple dictionary such as `{"question": prompt}`; use a mapper for messages
or other state shapes. For async execution, use `AsyncLangChainAdapter` with
`reset_hook=checkpointer.adelete_thread` and await both `send_message` and
`reset_session`. The async adapter also accepts synchronous reset hooks; the
sync adapter requires a synchronous hook.

Do not put a fixed `thread_id` in the base config. The adapter rejects a fixed
value for its selected session key, preventing independent probes from sharing
one conversation. Other configurable keys and tags are preserved. Applications
with cross-thread stores, caches, or external memory must clear their additional
state in their own reset hook; checkpoint deletion clears checkpoint history.
Concurrent requests for the same thread remain the application's responsibility.

A call without `session_id` on a `stateful=True` adapter uses a unique temporary
session ID and invokes the reset hook in `finally`, including when invocation
or extraction fails. This lets the shipped single-turn probes run independently
against a checkpointer-backed graph. Cleanup failures raise an infrastructure
error. A reset hook is required before these calls can invoke the graph.
Explicit session IDs retain history until `reset_session` is called.

## Existing Runnable adapters

Stateless runnables keep their existing defaults: prompts pass through as strings,
`session_config_key` is `session_id`, and resetting is a no-op. For
`RunnableWithMessageHistory`, keep the default session key and provide a callback
that clears the history for the supplied session ID:

```python
def reset_history(session_id):
    get_history(session_id).clear()


adapter = LangChainAdapter(
    runnable_with_history,
    stateful=True,
    reset_hook=reset_history,
)
```

Existing `stateful=True` constructors still work, but `reset_session` raises an
actionable infrastructure error if no reset hook was supplied. Add the callback
before using stateful probes. A failing reset hook also raises an infrastructure
error instead of allowing a probe to proceed with stale state.

Extraction recognizes strings, message content with text blocks, and common
string-valued dictionary outputs. Unknown state dictionaries, numbers, and
image/tool-only responses now raise an infrastructure error. They are never
converted into a representation for grading. Custom extractors must return a
string; their errors and invalid return values also become infrastructure errors.
An empty string is valid extracted text and remains subject to probe grading.
Identifiable user, system, and tool messages, or assistant messages with pending
tool calls, are rejected by default even when they contain text. A custom
`text_extractor` is an explicit application-level override: it must select and
validate the completed assistant response. Generic content-bearing objects
without role metadata retain the existing duck typing behavior.

## Validation

The default test suite checks session mapping, config isolation, reset callbacks,
strict extraction, and sync/async behavior with deterministic stub runnables.
Real graph integration tests run when `langgraph` is installed:

```bash
pytest tests/test_langchain_adapter.py
```

The recipe and real graph tests were verified on Python 3.12 with
`langchain-core==1.6.9`, `langgraph==1.2.14`, and
`langgraph-checkpoint==4.2.0`, using pytest 9.1.1 and pytest-asyncio 1.4.0.
This records an observed combination; the LangChain extra does not install
LangGraph or claim compatibility with every historical checkpointer release.
