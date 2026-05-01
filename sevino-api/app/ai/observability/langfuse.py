"""Langfuse client singleton (AI v0 plan A3.1).

`create_langfuse_client` returns a real `Langfuse` instance when both
`LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are configured, and a
no-op stub otherwise. The stub keeps `app/ai/*` runtime code free of
``if langfuse:`` branches in dev environments without a Langfuse account.
"""
from __future__ import annotations

import secrets
from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import Request
from langfuse import Langfuse

from app.config import Settings


class _NoopLangfuse:
    """No-op stand-in matching the subset of `Langfuse` used by `app/ai/*`."""

    def create_trace_id(self, *, seed: str | None = None) -> str:
        # Match Langfuse's 32-char lowercase hex format so downstream code
        # that persists trace IDs sees a uniform shape.
        return secrets.token_hex(16)

    def get_current_trace_id(self) -> str | None:
        return None

    def get_current_observation_id(self) -> str | None:
        return None

    @contextmanager
    def start_as_current_observation(
        self, *args: Any, **kwargs: Any
    ) -> Iterator["_NoopLangfuse"]:
        yield self

    def update_current_span(self, *args: Any, **kwargs: Any) -> None:
        pass

    def update_current_generation(self, *args: Any, **kwargs: Any) -> None:
        pass

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


LangfuseClient = Langfuse | _NoopLangfuse


def create_langfuse_client(settings: Settings) -> LangfuseClient:
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return _NoopLangfuse()
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
        environment=settings.environment,
    )


def get_langfuse(request: Request) -> LangfuseClient:
    return request.app.state.langfuse
