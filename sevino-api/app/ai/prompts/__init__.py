from __future__ import annotations

import hashlib
from pathlib import Path
from typing import NamedTuple

_PROMPTS_DIR = Path(__file__).parent


class SystemPrompt(NamedTuple):
    text: str
    hash: str


def _load_prompt(path: Path) -> SystemPrompt:
    text = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return SystemPrompt(text=text, hash=digest)


SYSTEM_PROMPT_V1: SystemPrompt = _load_prompt(_PROMPTS_DIR / "sevino_v1.md")
