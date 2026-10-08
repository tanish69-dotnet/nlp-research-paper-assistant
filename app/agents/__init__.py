"""Agent package: specialized reasoning agents (Phases 2+).

Agents depend only on the :class:`ModelProvider` abstraction — never on a
provider SDK — and communicate through validated Pydantic schemas.
"""

from app.agents.base import (
    Agent,
    AgentContext,
    complete_json,
    new_agent_run,
)
from app.agents.query_analyzer import (
    QueryAnalyzer,
    detect_reference_hints,
    default_plan,
)
from app.agents.text_agent import TextAgent

__all__ = [
    "Agent",
    "AgentContext",
    "QueryAnalyzer",
    "TextAgent",
    "complete_json",
    "default_plan",
    "detect_reference_hints",
    "new_agent_run",
]
