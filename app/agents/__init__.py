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
from app.agents.judge_answer import AnswerGenerator, JudgeAgent
from app.agents.query_analyzer import (
    QueryAnalyzer,
    detect_reference_hints,
    default_plan,
    has_table_intent,
)
from app.agents.table_agent import TableAgent
from app.agents.table_ops import (
    best_in_column,
    delta_between,
    infer_metric_direction,
    lookup_cell,
    numeric_ranking,
)
from app.agents.text_agent import TextAgent
from app.agents.vision_agent import VisionAgent

__all__ = [
    "Agent",
    "AgentContext",
    "AnswerGenerator",
    "JudgeAgent",
    "QueryAnalyzer",
    "TableAgent",
    "TextAgent",
    "VisionAgent",
    "best_in_column",
    "complete_json",
    "default_plan",
    "delta_between",
    "detect_reference_hints",
    "has_table_intent",
    "infer_metric_direction",
    "lookup_cell",
    "new_agent_run",
    "numeric_ranking",
]
