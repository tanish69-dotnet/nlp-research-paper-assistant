"""Versioned prompt loading.

Prompts live as files so they are reviewable, diffable and ablatable
(ARCHITECTURE §10, principle 10). Every load returns the template's version
and SHA-256 so run records can pin exactly what the model saw.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.config import PROJECT_ROOT

PROMPTS_ROOT = PROJECT_ROOT / "app" / "prompts" / "templates"

ALLOWED_NAMES = frozenset({"query_analyzer", "text_agent", "table_agent", "vision_agent", "judge_agent", "answer_generator"})


class PromptNotFoundError(FileNotFoundError):
    """Raised when a prompt template is missing or outside the template root."""


@dataclass(frozen=True)
class PromptTemplate:
    """One loaded system-prompt template."""

    name: str
    version: str
    text: str
    sha256: str


def _safe_name(name: str) -> str:
    if name not in ALLOWED_NAMES:
        raise PromptNotFoundError(f"unknown prompt template: {name!r}")
    return name


def load_prompt(name: str, version: str = "v1") -> PromptTemplate:
    """Load ``templates/<version>/<name>.md`` deterministically.

    Each template file starts with a ``version: <version>`` front-matter line.
    The file's SHA-256 is recorded in agent run records and evaluation
    manifests (reproducibility, NFR-9).
    """
    name = _safe_name(name)
    if not version.replace("_", "").replace("-", "").isalnum():
        raise PromptNotFoundError(f"invalid prompt version: {version!r}")

    path = (PROMPTS_ROOT / version / f"{name}.md").resolve()
    if PROMPTS_ROOT.resolve() not in path.parents:
        raise PromptNotFoundError(f"prompt path escapes template root: {name!r}")
    if not path.is_file():
        raise PromptNotFoundError(f"prompt template not found: {name}@{version}")

    text = path.read_text(encoding="utf-8")
    header, _, body = text.partition("\n")
    file_version = "unknown"
    if header.strip().startswith("version:"):
        file_version = header.split(":", 1)[1].strip()
        text = body.lstrip("\n")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return PromptTemplate(
        name=name, version=file_version or version, text=text, sha256=digest
    )
