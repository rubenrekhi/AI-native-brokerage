"""Tests for ``app.ai.observability.langfuse`` (SEV-474, AI v0 plan A3.1)."""
import re

from langfuse import Langfuse

from app.ai.observability.langfuse import (
    _NoopLangfuse,
    create_langfuse_client,
)
from app.config import Settings

_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _make_settings(**overrides) -> Settings:
    defaults = {
        "environment": "dev",
        "database_url": "postgresql://localhost/test",
        "redis_url": "redis://localhost",
        "supabase_url": "http://localhost",
        "supabase_anon_key": "sb_publishable_test",
        "supabase_service_role_key": "sb_service_role_test",
        "alpaca_api_key": "x",
        "alpaca_secret_key": "x",
        "plaid_client_id": "x",
        "plaid_secret": "x",
        "plaid_env": "sandbox",
        "plaid_fernet_key": "test-key",
        "anthropic_api_key": "sk-ant-test",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestNoopFallback:
    """When creds are missing the factory returns a stub so dev-without-Langfuse
    works without ``if langfuse:`` branches at the call site."""

    def test_returns_stub_when_both_keys_empty(self):
        client = create_langfuse_client(_make_settings())
        assert isinstance(client, _NoopLangfuse)

    def test_returns_stub_when_only_public_key_set(self):
        client = create_langfuse_client(
            _make_settings(langfuse_public_key="pk-test")
        )
        assert isinstance(client, _NoopLangfuse)

    def test_returns_stub_when_only_secret_key_set(self):
        client = create_langfuse_client(
            _make_settings(langfuse_secret_key="sk-test")
        )
        assert isinstance(client, _NoopLangfuse)


class TestNoopBehavior:
    """Stub mirrors the subset of Langfuse used by ``app/ai/*``."""

    def test_create_trace_id_returns_32_char_hex(self):
        # A3.1 acceptance: a manual trace-id call produces an ID without erroring.
        # Match Langfuse's wire format (32 lowercase hex chars) so persisted
        # IDs look the same regardless of which branch produced them.
        trace_id = _NoopLangfuse().create_trace_id()
        assert _TRACE_ID_RE.match(trace_id), trace_id

    def test_create_trace_id_returns_unique_ids(self):
        stub = _NoopLangfuse()
        assert stub.create_trace_id() != stub.create_trace_id()

    def test_get_current_trace_id_returns_none(self):
        assert _NoopLangfuse().get_current_trace_id() is None

    def test_start_as_current_observation_is_context_manager(self):
        stub = _NoopLangfuse()
        with stub.start_as_current_observation(name="x") as obs:
            assert obs is stub

    def test_yielded_observation_has_update_method(self):
        # ``run_agent_turn`` calls ``gen.update(output=..., level=...)`` on
        # the yielded observation; the noop must accept the same shape so
        # dev environments without Langfuse don't blow up.
        stub = _NoopLangfuse()
        with stub.start_as_current_observation(
            as_type="generation", name="x"
        ) as gen:
            result = gen.update(
                output=[{"type": "text", "text": "hi"}],
                level="ERROR",
                status_message="x",
            )
            # The real LangfuseSpan.update() returns the wrapper for chaining;
            # mirror that here so call sites that rely on it don't break.
            assert result is gen

    def test_update_methods_are_no_op(self):
        stub = _NoopLangfuse()
        stub.update_current_span(input="x", output="y")
        stub.update_current_generation(usage={"input_tokens": 1})

    def test_flush_and_shutdown_do_not_raise(self):
        stub = _NoopLangfuse()
        stub.flush()
        stub.shutdown()


class TestRealClientConstruction:
    """When both keys are set the factory hands back a real Langfuse client.

    We don't make a live HTTP call — the SDK constructor wires up tracing
    state without contacting the API."""

    def test_returns_langfuse_when_both_keys_set(self):
        client = create_langfuse_client(
            _make_settings(
                langfuse_public_key="pk-test",
                langfuse_secret_key="sk-test",
            )
        )
        assert isinstance(client, Langfuse)
        # Manual trace-id creation works on the real client too — A3.1 smoke.
        assert _TRACE_ID_RE.match(client.create_trace_id())
        client.shutdown()
