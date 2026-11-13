"""Naive: the documents go in instructions, and every link and image is rendered."""

from __future__ import annotations

from llm import stream_answer

from doc_chat.render import render_everything


def answer(question: str, documents: list[dict[str, str]]) -> str:
    sources = "\n\n".join(f"{doc['title']} ({doc['url']}):\n{doc['text']}" for doc in documents)
    instructions = "Answer the user's question using these documents.\n\n" + sources
    return render_everything(stream_answer(instructions, question))
