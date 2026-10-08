"""Prompt package: versioned templates, loader, and three-zone assembly.

Zone A (system) comes from a versioned template file. Zones B (question) and
C (evidence) are supplied per request and delimited — never concatenated into
the system zone (SECURITY.md §2).
"""

from app.prompts.assembly import EvidenceContext, assemble_three_zone
from app.prompts.loader import PromptNotFoundError, PromptTemplate, load_prompt

__all__ = [
    "EvidenceContext",
    "PromptNotFoundError",
    "PromptTemplate",
    "assemble_three_zone",
    "load_prompt",
]
