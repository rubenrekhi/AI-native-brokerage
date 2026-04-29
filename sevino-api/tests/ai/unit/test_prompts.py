import hashlib
from pathlib import Path

from app.ai.prompts import SYSTEM_PROMPT_V1, _load_prompt


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
