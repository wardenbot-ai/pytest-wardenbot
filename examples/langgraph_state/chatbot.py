"""Executable stateful LangGraph recipe, with no provider or credentials."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import AIMessage  # type: ignore[import-not-found]
from langgraph.checkpoint.memory import InMemorySaver  # type: ignore[import-not-found]
from langgraph.graph import END, START, MessagesState, StateGraph  # type: ignore[import-not-found]

from pytest_wardenbot.adapters.langchain_runnable import (
    AsyncLangChainAdapter,
    LangChainAdapter,
)


def assistant_text(state: Any) -> str:
    """Read only the final assistant message, never serialize the graph state."""
    message = state["messages"][-1]
    if message.type != "ai" or not isinstance(message.content, str):
        raise ValueError("Expected a final assistant message with string content.")
    return message.content


def build_adapters() -> tuple[LangChainAdapter, AsyncLangChainAdapter]:
    """Create independent per-thread history with explicit checkpoint cleanup."""
    checkpointer = InMemorySaver()

    def reply(state: MessagesState) -> dict[str, Any]:
        users = [message for message in state["messages"] if message.type == "human"]
        return {"messages": [AIMessage(content=f"Seen {len(users)} user messages.")]}

    builder = StateGraph(MessagesState)
    builder.add_node("reply", reply)
    builder.add_edge(START, "reply")
    builder.add_edge("reply", END)
    graph = builder.compile(checkpointer=checkpointer)

    def input_mapper(prompt: str) -> dict[str, Any]:
        return {"messages": [("user", prompt)]}

    return (
        LangChainAdapter(
            graph,
            stateful=True,
            session_config_key="thread_id",
            input_mapper=input_mapper,
            text_extractor=assistant_text,
            reset_hook=checkpointer.delete_thread,
        ),
        AsyncLangChainAdapter(
            graph,
            stateful=True,
            session_config_key="thread_id",
            input_mapper=input_mapper,
            text_extractor=assistant_text,
            reset_hook=checkpointer.adelete_thread,
        ),
    )


async def demonstrate_async(adapter: AsyncLangChainAdapter) -> None:
    assert (await adapter.send_message("one-shot")).text == "Seen 1 user messages."
    assert (await adapter.send_message("another one-shot")).text == "Seen 1 user messages."
    assert (
        await adapter.send_message("one", session_id="async-first")
    ).text == "Seen 1 user messages."
    assert (
        await adapter.send_message("two", session_id="async-first")
    ).text == "Seen 2 user messages."
    assert (
        await adapter.send_message("one", session_id="async-second")
    ).text == "Seen 1 user messages."
    await adapter.reset_session("async-first")
    assert (
        await adapter.send_message("fresh", session_id="async-first")
    ).text == "Seen 1 user messages."
    assert (
        await adapter.send_message("two", session_id="async-second")
    ).text == "Seen 2 user messages."


def demonstrate_sync(adapter: LangChainAdapter) -> None:
    assert adapter.send_message("one-shot").text == "Seen 1 user messages."
    assert adapter.send_message("another one-shot").text == "Seen 1 user messages."
    assert adapter.send_message("one", session_id="first").text == "Seen 1 user messages."
    assert adapter.send_message("two", session_id="first").text == "Seen 2 user messages."
    assert adapter.send_message("one", session_id="second").text == "Seen 1 user messages."
    adapter.reset_session("first")
    assert adapter.send_message("fresh", session_id="first").text == "Seen 1 user messages."
    assert adapter.send_message("two", session_id="second").text == "Seen 2 user messages."


if __name__ == "__main__":
    sync_adapter, async_adapter = build_adapters()
    demonstrate_sync(sync_adapter)
    asyncio.run(demonstrate_async(async_adapter))
