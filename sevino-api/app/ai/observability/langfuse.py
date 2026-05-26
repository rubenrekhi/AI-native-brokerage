"""Langfuse client — real instance when keys are set, no-op stub otherwise."""
from __future__ import annotations

import secrets
from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import Request
from langfuse import Langfuse

from app.config import Settings


class _NoopLangfuse:
    def create_trace_id(self, *, seed: str | None = None) -> str:
        # Match Langfuse's 32-char hex shape for downstream persistence.
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

    def update(self, *args: Any, **kwargs: Any) -> "_NoopLangfuse":
        # Real ``.update()`` returns the wrapper for chaining.
        return self

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
