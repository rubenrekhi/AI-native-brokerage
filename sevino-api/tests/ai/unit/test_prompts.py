import hashlib
from pathlib import Path

from app.ai.prompts import SYSTEM_PROMPT_V1, _load_prompt, system_prompt_for
from app.ai.runtime.types import ServerToolsConfig


def test_system_prompt_v1_exposes_text_and_hash():
    assert SYSTEM_PROMPT_V1.text
    assert len(SYSTEM_PROMPT_V1.hash) == 64


def test_hash_matches_sha256_of_text():
    expected = hashlib.sha256(SYSTEM_PROMPT_V1.text.encode("utf-8")).hexdigest()
    assert SYSTEM_PROMPT_V1.hash == expected


def test_hash_is_deterministic_across_loads(tmp_path: Path):
    p = tmp_path / "prompt.md"
    p.write_text("placeholder", encoding="utf-8")

    first = _load_prompt(p)
    second = _load_prompt(p)

    assert first == second


def test_hash_changes_when_content_changes(tmp_path: Path):
    a = tmp_path / "a.md"
    a.write_text("hello", encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("hello world", encoding="utf-8")

    assert _load_prompt(a).hash != _load_prompt(b).hash


class TestSystemPromptFor:
    def test_returns_base_prompt_when_no_server_tools_enabled(self):
        prompt = system_prompt_for(ServerToolsConfig())
        assert prompt is SYSTEM_PROMPT_V1

    def test_addendum_appended_when_web_search_enabled(self):
        prompt = system_prompt_for(
            ServerToolsConfig(web_search_enabled=True)
        )
        assert prompt.text.startswith(SYSTEM_PROMPT_V1.text)
        assert "web_search" in prompt.text
        assert prompt.text != SYSTEM_PROMPT_V1.text

    def test_addendum_appended_when_web_fetch_enabled(self):
        prompt = system_prompt_for(
            ServerToolsConfig(web_fetch_enabled=True)
        )
        assert prompt.text.startswith(SYSTEM_PROMPT_V1.text)
        assert prompt.text != SYSTEM_PROMPT_V1.text

    def test_hash_differs_from_base_when_addendum_appended(self):
        with_tools = system_prompt_for(
            ServerToolsConfig(web_search_enabled=True)
        )
        assert with_tools.hash != SYSTEM_PROMPT_V1.hash

    def test_hash_is_sha256_of_composed_text(self):
        prompt = system_prompt_for(
            ServerToolsConfig(web_search_enabled=True)
        )
        expected = hashlib.sha256(prompt.text.encode("utf-8")).hexdigest()
        assert prompt.hash == expected
