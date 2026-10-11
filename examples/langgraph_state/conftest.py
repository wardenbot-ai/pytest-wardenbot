"""Expose the graph through the standard wardenbot chatbot fixture."""

import pytest
from chatbot import build_adapters


@pytest.fixture
def chatbot():
    sync_adapter, _ = build_adapters()
    return sync_adapter
