from __future__ import annotations

import hashlib
from pathlib import Path
from typing import NamedTuple

from app.ai.runtime.types import ServerToolsConfig

_PROMPTS_DIR = Path(__file__).parent


class SystemPrompt(NamedTuple):
    text: str
    hash: str


def _load_prompt(path: Path) -> SystemPrompt:
    text = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return SystemPrompt(text=text, hash=digest)


SYSTEM_PROMPT_V1: SystemPrompt = _load_prompt(_PROMPTS_DIR / "sevino_v1.md")

_SERVER_TOOLS_ADDENDUM: str = (
    _PROMPTS_DIR / "sevino_v1_server_tools.md"
).read_text(encoding="utf-8")


def _compose_with_addendum(base: SystemPrompt, addendum: str) -> SystemPrompt:
    text = base.text + "\n" + addendum
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return SystemPrompt(text=text, hash=digest)


# Precomputed at import so the hash isn't re-derived on every turn; matches
# the import-time hash invariant SYSTEM_PROMPT_V1 already follows.
_SYSTEM_PROMPT_V1_WITH_SERVER_TOOLS: SystemPrompt = _compose_with_addendum(
    SYSTEM_PROMPT_V1, _SERVER_TOOLS_ADDENDUM
)


def system_prompt_for(server_tools: ServerToolsConfig) -> SystemPrompt:
    if not server_tools.any_enabled:
        return SYSTEM_PROMPT_V1
    return _SYSTEM_PROMPT_V1_WITH_SERVER_TOOLS
