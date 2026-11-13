"""Errors raised by the model endpoint."""

from __future__ import annotations

from pytest_wardenbot._errors import WardenBotError


class ModelEndpointError(WardenBotError):
    """The model endpoint could not answer a request the way the test asked.

    Examples: a scripted case ran out of replies, a reply file doesn't fit the
    endpoint it was sent to, or the endpoint is used before ``install()``. The
    endpoint returns the error to the application as an HTTP 500 (marked as not
    retryable) and raises it again when the ``model_endpoint`` block exits, so
    the test fails even if the application swallows the HTTP error.
    """
