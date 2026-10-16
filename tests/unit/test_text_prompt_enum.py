"""Prompt templates must not teach the model a schema-invalid enum.

Regression: the v1 templates once showed ``"kind": "a | b | ..."`` — a
small local model copies that verbatim, the schema rejects it, and the
finding is dropped (``text_agent_filtered_findings`` / ``text_reasoner=error``
on real papers).
"""

from __future__ import annotations

import pytest

from app.prompts.loader import load_prompt


@pytest.mark.parametrize(
    "name", ["text_agent", "table_agent", "vision_agent", "judge_agent", "query_analyzer"]
)
def test_no_template_shows_piped_enum(name: str):
    template = load_prompt(name, "v1")

    if name == "query_analyzer":
        assert '"kind":' not in template.text
        return
    assert " | " not in template.text
    assert "exactly one of" in template.text
