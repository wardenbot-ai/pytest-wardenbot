"""The model endpoint's envelopes parse with the real OpenAI SDK.

Runs in the real-SDK contract lanes at the OpenAI floor and the current
release. No provider request is made: every client talks to the local endpoint.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from pytest_wardenbot.model import Endpoint, Script, install, model_endpoint, uninstall
from tests.model_support import clean_environment

openai = pytest.importorskip("openai")


class PostSummary(BaseModel):
    themes: list[str]
    summary: str
    flagged_post_ids: list[str]


SUMMARY = {"themes": ["pricing"], "summary": "Posts discuss pricing.", "flagged_post_ids": ["2"]}
LONG_TEXT = "A wrapped reply that is long enough to arrive in several stream deltas."


@pytest.fixture
def endpoint(monkeypatch: pytest.MonkeyPatch) -> Iterator[Endpoint]:
    clean_environment(monkeypatch)
    uninstall()
    installed = install(mode="scripted")
    try:
        yield installed
    finally:
        uninstall()


def _client() -> Any:
    # Built after install(), with no base_url or api_key: it reads the environment.
    return openai.OpenAI(max_retries=0)


def test_responses_create(endpoint: Endpoint) -> None:
    with model_endpoint("sdk", script=LONG_TEXT) as block:
        response = _client().responses.create(model="gpt-x", input="hi")
    assert response.output_text == LONG_TEXT
    assert response.model == "gpt-x"
    assert response.usage is not None and response.usage.total_tokens == 0
    assert block.requests[0].body["input"] == "hi"


def test_responses_raw_stream(endpoint: Endpoint) -> None:
    with model_endpoint("sdk", script=LONG_TEXT):
        events = list(_client().responses.create(model="gpt-x", input="hi", stream=True))
    kinds = [event.type for event in events]
    assert kinds[0] == "response.created" and kinds[-1] == "response.completed"
    deltas = [event.delta for event in events if event.type == "response.output_text.delta"]
    assert len(deltas) > 1 and "".join(deltas) == LONG_TEXT


def test_responses_stream_helper(endpoint: Endpoint) -> None:
    with (
        model_endpoint("sdk", script=LONG_TEXT),
        _client().responses.stream(model="gpt-x", input="hi") as stream,
    ):
        streamed = "".join(
            event.delta for event in stream if event.type == "response.output_text.delta"
        )
        final = stream.get_final_response()
    assert streamed == LONG_TEXT
    assert final.output_text == LONG_TEXT


def test_responses_parse_and_stream_with_text_format(endpoint: Endpoint) -> None:
    client = _client()
    with model_endpoint("sdk", script=Script(SUMMARY, then="repeat_last")):
        parsed = client.responses.parse(model="gpt-x", input="summarize", text_format=PostSummary)
        with client.responses.stream(
            model="gpt-x", input="summarize", text_format=PostSummary
        ) as stream:
            for _ in stream:
                pass
            streamed = stream.get_final_response()
    assert parsed.output_parsed == PostSummary(**SUMMARY)
    assert streamed.output_parsed == PostSummary(**SUMMARY)


def test_chat_json_object_and_parse(endpoint: Endpoint) -> None:
    client = _client()
    messages = [{"role": "user", "content": "summarize"}]
    with model_endpoint("sdk", script=Script(SUMMARY, then="repeat_last")):
        completion = client.chat.completions.create(
            model="gpt-x", messages=messages, response_format={"type": "json_object"}
        )
        # Chat parse moved out of the beta namespace after the 1.66.3 floor.
        completions = getattr(client.chat.completions, "parse", None)
        parse = completions or client.beta.chat.completions.parse
        parsed = parse(model="gpt-x", messages=messages, response_format=PostSummary)
    assert json.loads(completion.choices[0].message.content or "") == SUMMARY
    assert parsed.choices[0].message.parsed == PostSummary(**SUMMARY)


def test_chat_stream_with_usage(endpoint: Endpoint) -> None:
    with model_endpoint("sdk", script=LONG_TEXT):
        chunks = list(
            _client().chat.completions.create(
                model="gpt-x",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
                stream_options={"include_usage": True},
            )
        )
    text = "".join(chunk.choices[0].delta.content or "" for chunk in chunks if chunk.choices)
    assert text == LONG_TEXT
    assert chunks[-1].usage is not None and chunks[-1].usage.total_tokens == 0


def test_async_client(endpoint: Endpoint) -> None:
    async def run() -> str:
        client = openai.AsyncOpenAI(max_retries=0)
        try:
            response = await client.responses.create(model="gpt-x", input="hi")
            return response.output_text
        finally:
            await client.close()

    with model_endpoint("sdk", script="async reply"):
        assert asyncio.run(run()) == "async reply"


def test_client_built_at_import_time_reaches_the_endpoint(
    endpoint: Endpoint, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pipeline_at_import.py").write_text(
        "import openai\n"
        "CLIENT = openai.OpenAI(max_retries=0)\n"
        "def summarize(text):\n"
        "    return CLIENT.responses.create(model='gpt-x', input=text).output_text\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    module = importlib.import_module("pipeline_at_import")
    try:
        with model_endpoint("import-time", script="imported reply") as block:
            assert module.summarize("page text") == "imported reply"
        assert block.requests[0].text("user") == "page text"
    finally:
        sys.modules.pop("pipeline_at_import", None)


def test_cached_client_across_blocks(endpoint: Endpoint) -> None:
    client = _client()
    with model_endpoint("first", script="one") as first:
        assert client.responses.create(model="gpt-x", input="a").output_text == "one"
    with model_endpoint("second", script="two") as second:
        assert client.responses.create(model="gpt-x", input="b").output_text == "two"
    assert [r.text() for r in first.requests] == ["a"]
    assert [r.text() for r in second.requests] == ["b"]


def test_errors_are_not_retried(endpoint: Endpoint) -> None:
    client = openai.OpenAI()  # default retries: the endpoint must disable them itself
    with pytest.raises(Exception, match="has 1 reply"), model_endpoint("once", script="x") as block:
        client.responses.create(model="gpt-x", input="a")
        with pytest.raises(openai.InternalServerError, match="has 1 reply"):
            client.responses.create(model="gpt-x", input="b")
    assert len(block.requests) == 2
