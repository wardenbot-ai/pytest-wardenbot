# LangGraph checkpoint state

This executable example uses an in-memory graph and deterministic node. It needs
no API key. The node counts turns so isolation and reset behavior are visible.
Replace the node with your application to run actual safety probes.

```bash
pip install -e '.[langchain]' langgraph
python examples/langgraph_state/chatbot.py
```

The script asserts sync and async turn history, two independent thread IDs,
and checkpoint deletion that resets one thread while preserving the other.
The conftest exposes a fresh graph as the standard `chatbot` fixture.
In this directory, `pytest --pyargs pytest_wardenbot.tests` runs the packaged
probes; the counting demo is not designed to answer business-truth questions.

See [the full recipe](../../docs/how-to/langgraph-state.md).
