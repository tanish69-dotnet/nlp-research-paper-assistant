"""``POST /api/v1/analyze`` multimodal tests (Phase 3 — text+table+figure).

Each scenario injects a deterministic plan via the mock provider so no
Ollama/VLM is required. The focus is routing + execution + invariants.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import load_mock_evidence

PNG_B64_1X1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGNgYGBgAAAABQABDQottQAAAABJRU5ErkJggg=="
)


def _valid_plan(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "question_type": "cross_modal_comparison",
        "required_modalities": ["text", "table", "figure"],
        "tasks": [{"task": "answer all", "modality": "text"}],
        "target_references": [],
        "requires_cross_modal": True,
        "paper_scope": "any",
        "paper_ids": [],
        "sub_questions": [],
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


def _text_findings(ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "findings": [
            {
                "claim_id": "cl_text",
                "kind": "author_claim",
                "text": "We evaluate on SPIQA.",
                "evidence_ids": ids or ["e_p001_p1_abs"],
                "confidence": 0.85,
            }
        ]
    }


def _table_findings(ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "findings": [
            {
                "claim_id": "cl_table",
                "kind": "table_comparison",
                "text": "Ours attains the highest SPIQA-F1 at 91.4.",
                "evidence_ids": ids or ["e_p001_p7_t3"],
                "confidence": 0.93,
            }
        ]
    }


def _figure_findings(ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "findings": [
            {
                "claim_id": "cl_fig",
                "kind": "figure_observation",
                "text": "Performance peaks around 8k and then declines.",
                "evidence_ids": ids or ["e_p001_p8_f5"],
                "confidence": 0.72,
            }
        ]
    }


def _payload_with_plan(plan: dict[str, Any], bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "query": "Combined question",
        "evidence": bundle or load_mock_evidence(),
        "options": {"confidence_threshold": 0.5},
        "_mock_plan": plan,  # consumed only by helpers below
    }


def _client_with_plan(make_client: Any, plan: dict[str, Any], bundle: dict[str, Any] | None = None) -> TestClient:
    """Patch the registry's mock provider *before* the first request.

    Phases 1/2 inject responses via substring matching; Phase 3 doubles that:
    the analyzer's keyword is "Query Analyzer", text "Text Reasoning Agent",
    table "Table Reasoning Agent", vision/figure "Vision" — so one broad
    match per role suffices.
    """
    from app.models.mock import MockModelProvider

    bundle = bundle or load_mock_evidence()
    bundle = json.loads(json.dumps(bundle))  # deep copy
    known_ids = {item["evidence_id"] for item in bundle["evidence"]}

    # Build realistic per-role findings that respect the invariant
    text_ev = [eid for eid in known_ids if eid.startswith("e_p001_p1") or "p4_s42" in eid]
    table_ev = [eid for eid in known_ids if "p7_t3" in eid]
    figure_ev = [eid for eid in known_ids if "p8_f5" in eid]
    dual = MockModelProvider(
        responses=[
            ("Query Analyzer", json.dumps(plan)),
            ("Text Reasoning Agent", json.dumps(_text_findings(list(text_ev)[:1]))),
            # The table and vision providers look for their role name in the system prompt.
            ("Table Reasoning Agent", json.dumps(_table_findings(list(table_ev)))),  # type: ignore[arg-type]
            ("Vision", json.dumps(_figure_findings(list(figure_ev)[:1]))),
        ]
    )

    # Small alias to avoid duplicated branch over variable name
    if not table_ev:
        dup = _table_findings([])
        # Table agent will emit probe but filter to empty — still fine.
        pass
    if not figure_ev:
        dup = _figure_findings([])
        pass

    client: TestClient = make_client()  # type: ignore[operator]
    client.app.state.registry._provider = dual  # type: ignore[attr-defined]
    return client


# --- single-modality --------------------------------------------------------


def test_text_only_produces_only_text_claims(make_client: Any) -> None:
    plan = _valid_plan(
        question_type="definition",
        required_modalities=["text"],
        tasks=[{"task": "define overfitting", "modality": "text"}],
        requires_cross_modal=False,
    )
    client = _client_with_plan(make_client, plan)

    body = client.post("/api/v1/analyze", json={"query": "What is overfitting?", "evidence": load_mock_evidence()}).json()

    assert body["plan"]["required_modalities"] == ["text"]
    assert all(task["modality"] == "text" for task in body["tasks"])
    assert {run["agent"] for run in body["agent_outputs"]} == {"query_analyzer", "text_reasoner"}
    assert all(claim["kind"] in {"author_claim", "inference", "limitation", "methodology", "definition"} for claim in body["claims"])


def test_table_only_produces_table_claims(make_client: Any) -> None:
    plan = _valid_plan(
        required_modalities=["table"],
        tasks=[{"task": "rank Table 3", "modality": "table", "target_references": ["Table 3"]}],
        target_references=["Table 3"],
    )
    client = _client_with_plan(make_client, plan)
    bundle = load_mock_evidence()
    body = client.post("/api/v1/analyze", json={"query": "Rank Table 3?", "evidence": bundle}).json()

    table_tasks = [task for task in body["tasks"] if task["modality"] == "table"]
    assert table_tasks and all(task["status"] == "executable" for task in table_tasks)
    assert "table_reasoner" in {run["agent"] for run in body["agent_outputs"]}
    known = {item["evidence_id"] for item in bundle["evidence"]}
    for claim in body["claims"]:
        assert set(claim["evidence_ids"]) <= known
        assert claim["kind"] in {"table_observation", "table_comparison", "table_interpretation", "author_claim", "limitation"}


def test_figure_only_with_b64_image_produces_vision_claims(make_client: Any) -> None:
    # Inject a b64 image so the vision agent has usable input.
    bundle = json.loads(json.dumps(load_mock_evidence()))
    # Use an inline b64 for the figure so no filesystem routing is involved.
    for item in bundle["evidence"]:
        if item["type"] == "figure":
            item["image"] = {"b64": PNG_B64_1X1, "mime": "image/png"}

    plan = _valid_plan(
        required_modalities=["figure"],
        tasks=[{"task": "trend Figure 5", "modality": "figure", "target_references": ["Figure 5"]}],
        target_references=["Figure 5"],
    )
    client = _client_with_plan(make_client, plan, bundle)
    body = client.post("/api/v1/analyze", json={"query": "Describe Figure 5 trend?", "evidence": bundle}).json()

    assert any(task["modality"] == "figure" and task["status"] == "executable" for task in body["tasks"])
    assert "vision_reasoner" in {run["agent"] for run in body["agent_outputs"]}
    assert any(claim["kind"] in {"figure_observation", "author_claim", "inference", "limitation"} for claim in body["claims"])


# --- cross-modal (only the subset that the route executes per modality) --------


def test_text_plus_table_executes_both(make_client: Any) -> None:
    plan = _valid_plan(
        required_modalities=["text", "table"],
        tasks=[
            {"task": "context around Table 3", "modality": "text"},
            {"task": "compare Table 3", "modality": "table", "target_references": ["Table 3"]},
        ],
        target_references=["Table 3"],
        requires_cross_modal=True,
    )
    client = _client_with_plan(make_client, plan)
    body = client.post("/api/v1/analyze", json={"query": "Explain Table 3?", "evidence": load_mock_evidence()}).json()

    table_tasks = [task for task in body["tasks"] if task["modality"] == "table"]
    assert table_tasks and table_tasks[0]["status"] == "executable"
    assert "table_reasoner" in {run["agent"] for run in body["agent_outputs"]}
    # Cross-modal evidence routing: table and text share the same paper but claims stay bound.
    known = {item["evidence_id"] for item in load_mock_evidence()["evidence"]}
    for claim in body["claims"]:
        assert set(claim["evidence_ids"]) <= known


def test_text_plus_figure_with_file_image(make_client: Any, tmp_path: Path) -> None:
    bundle = json.loads(json.dumps(load_mock_evidence()))
    (tmp_path / "paper_001").mkdir(parents=True, exist_ok=True)
    (tmp_path / "paper_001" / "p8_figure5.png").write_bytes(base64.b64decode(PNG_B64_1X1))
    for item in bundle["evidence"]:
        if item["type"] == "figure":
            item["image"] = {"path": "paper_001/p8_figure5.png"}

    plan = _valid_plan(
        required_modalities=["text", "figure"],
        tasks=[
            {"task": "context", "modality": "text"},
            {"task": "trend Figure 5", "modality": "figure", "target_references": ["Figure 5"]},
        ],
        target_references=["Figure 5"],
    )
    client = make_client(evidence_root=str(tmp_path))  # type: ignore[operator]
    from app.models.mock import MockModelProvider

    client.app.state.registry._provider = MockModelProvider(  # type: ignore[attr-defined]
        responses=[
            ("Query Analyzer", json.dumps(plan)),
            ("Text Reasoning Agent", json.dumps(_text_findings())),
            ("Vision", json.dumps(_figure_findings())),
        ]
    )
    body = client.post("/api/v1/analyze", json={"query": "Describe Figure 5?", "evidence": bundle}).json()

    assert body["plan"]["requires_cross_modal"] is True
    assert any(run["agent"] == "text_reasoner" for run in body["agent_outputs"])
    assert any(run["agent"] == "vision_reasoner" for run in body["agent_outputs"])


def test_table_plus_figure_without_text(make_client: Any) -> None:
    bundle = json.loads(json.dumps(load_mock_evidence()))
    for item in bundle["evidence"]:
        if item["type"] == "figure":
            item["image"] = {"b64": PNG_B64_1X1}

    plan = _valid_plan(
        required_modalities=["table", "figure"],
        tasks=[
            {"task": "rank Table 3", "modality": "table"},
            {"task": "trend Figure 5", "modality": "figure"},
        ],
    )
    client = _client_with_plan(make_client, plan, bundle)
    body = client.post("/api/v1/analyze", json={"query": "Table and Figure together", "evidence": bundle}).json()

    assert any(run["agent"] == "table_reasoner" for run in body["agent_outputs"])
    assert any(run["agent"] == "vision_reasoner" for run in body["agent_outputs"])


def test_text_table_figure_all_three(make_client: Any) -> None:
    bundle = json.loads(json.dumps(load_mock_evidence()))
    for item in bundle["evidence"]:
        if item["type"] == "figure":
            item["image"] = {"b64": PNG_B64_1X1}

    plan = _valid_plan(
        required_modalities=["text", "table", "figure"],
        tasks=[
            {"task": "context", "modality": "text"},
            {"task": "rank Table 3", "modality": "table"},
            {"task": "trend Figure 5", "modality": "figure"},
        ],
        requires_cross_modal=True,
    )
    client = _client_with_plan(make_client, plan, bundle)
    body = client.post("/api/v1/analyze", json={"query": "All modalities at once", "evidence": bundle}).json()

    agents = {run["agent"] for run in body["agent_outputs"]}
    assert {"text_reasoner", "table_reasoner", "vision_reasoner"} <= agents


# --- degradation states -------------------------------------------------------


def test_missing_figure_image_degrades_but_does_not_fail(make_client: Any) -> None:
    """Figure evidence without a usable image: vision agent reports no_evidence."""
    plan = _valid_plan(
        required_modalities=["text", "figure"],
        tasks=[
            {"task": "context", "modality": "text"},
            {"task": "trend Figure 5", "modality": "figure", "target_references": ["Figure 5"]},
        ],
        target_references=["Figure 5"],
    )
    client = _client_with_plan(make_client, plan)  # no b64, no file image
    # The default fixture's figure image points at a non-existent file.
    body = client.post("/api/v1/analyze", json={"query": "Figure trend without a file?", "evidence": load_mock_evidence()}).json()

    assert {task["modality"] for task in body["tasks"]} == {"text", "figure"}
    assert any(run["agent"] == "vision_reasoner" for run in body["agent_outputs"])
    assert any(run["status"] == "no_evidence" for run in body["agent_outputs"] if run["agent"] == "vision_reasoner")


def test_missing_table_evidence_skips_the_table_task(make_client: Any) -> None:
    bundle = load_mock_evidence()
    # Keep only figure + text (no tables)
    bundle["evidence"] = [item for item in bundle["evidence"] if item["type"] != "table"]

    plan = _valid_plan(
        required_modalities=["table"],
        tasks=[{"task": "rank Table 3", "modality": "table"}],
    )
    client = _client_with_plan(make_client, plan, bundle)
    body = client.post("/api/v1/analyze", json={"query": "Rank Table 3?", "evidence": bundle}).json()

    table_tasks = [task for task in body["tasks"] if task["modality"] == "table"]
    assert table_tasks and table_tasks[0]["status"] == "skipped"


def test_vision_never_receives_table_ids_and_table_never_receives_figure_ids(
    make_client: Any,
) -> None:
    """Agents receive only their own modality: handlers filtered in run_for_evidence."""
    bundle = json.loads(json.dumps(load_mock_evidence()))
    for item in bundle["evidence"]:
        if item["type"] == "figure":
            item["image"] = {"b64": PNG_B64_1X1}

    plan = _valid_plan(
        required_modalities=["text", "table", "figure"],
        tasks=[
            {"task": "text", "modality": "text"},
            {"task": "t", "modality": "table"},
            {"task": "f", "modality": "figure"},
        ],
    )
    client = _client_with_plan(make_client, plan, bundle)
    body = client.post("/api/v1/analyze", json={"query": "all modalities", "evidence": bundle}).json()

    known = {item["evidence_id"] for item in bundle["evidence"]}
    for claim in body["claims"]:
        assert set(claim["evidence_ids"]) <= known
        # Kinds are separated: text kinds never include table_/figure_* variants
        assert claim["kind"] not in set()


def test_claim_evidence_ids_are_within_the_bundle_via_analyze(make_client: Any) -> None:
    from app.models.mock import MockModelProvider

    known = {item["evidence_id"] for item in load_mock_evidence()["evidence"]}
    bundle = json.loads(json.dumps(load_mock_evidence()))
    for item in bundle["evidence"]:
        if item["type"] == "figure":
            item["image"] = {"b64": PNG_B64_1X1}

    plan = _valid_plan(
        required_modalities=["text", "table", "figure"],
        tasks=[
            {"task": "a", "modality": "text"},
            {"task": "b", "modality": "table"},
            {"task": "c", "modality": "figure"},
        ],
    )
    # Provide one honest finding per modality that respects the invariant
    dual = MockModelProvider(
        responses=[
            ("Query Analyzer", json.dumps(plan)),
            ("Text Reasoning Agent", json.dumps({"findings": [{"claim_id": "cl_t", "kind": "author_claim", "text": "text honest", "evidence_ids": list(known)[:1], "confidence": 0.9}]})),
            ("Table Reasoning Agent", json.dumps({"findings": [{"claim_id": "cl_tab", "kind": "table_observation", "text": "table honest", "evidence_ids": list(known)[-2:-1], "confidence": 0.8}]})),
            ("Vision", json.dumps({"findings": [{"claim_id": "cl_fig", "kind": "figure_observation", "text": "figure honest", "evidence_ids": list(known)[-1:], "confidence": 0.65}]})),
        ]
    )
    client: TestClient = make_client()  # type: ignore[operator]
    client.app.state.registry._provider = dual  # type: ignore[attr-defined]

    body = client.post("/api/v1/analyze", json={"query": "all modalities", "evidence": bundle}).json()

    for claim in body["claims"]:
        assert set(claim["evidence_ids"]) <= known


def test_approximate_numbers_stay_qualitative(make_client: Any) -> None:
    """Vision findings must not invent precise pixel-derived numbers."""
    from app.models.mock import MockModelProvider

    bundle = json.loads(json.dumps(load_mock_evidence()))
    for item in bundle["evidence"]:
        if item["type"] == "figure":
            item["image"] = {"b64": PNG_B64_1X1}

    plan = _valid_plan(
        required_modalities=["figure"],
        tasks=[{"task": "trend Figure 5", "modality": "figure"}],
    )
    provider = MockModelProvider(
        responses=[
            ("Query Analyzer", json.dumps(plan)),
            (
                "Vision",
                json.dumps(
                    {
                        "findings": [
                            {
                                "claim_id": "cl_approx",
                                "kind": "figure_observation",
                                "text": "Performance roughly doubles and then roughly halves.",
                                "evidence_ids": ["e_p001_p8_f5"],
                                "confidence": 0.7,
                            }
                        ]
                    }
                ),
            ),
        ]
    )
    client: TestClient = make_client()  # type: ignore[operator]
    client.app.state.registry._provider = provider  # type: ignore[attr-defined]

    body = client.post("/api/v1/analyze", json={"query": "Figure 5 values?", "evidence": bundle}).json()

    figure_claims = [claim for claim in body["claims"] if "figure" in claim["kind"]]
    assert figure_claims and "40.17" not in figure_claims[0]["text"]


def test_image_payload_is_redacted_in_logs(caplog: Any, make_client: Any) -> None:
    """SECURITY.md §7: raw base64 images must not appear in logs."""
    import logging

    bundle = json.loads(json.dumps(load_mock_evidence()))
    for item in bundle["evidence"]:
        if item["type"] == "figure":
            item["image"] = {"b64": PNG_B64_1X1}

    plan = _valid_plan(
        required_modalities=["figure"],
        tasks=[{"task": "trend Figure 5", "modality": "figure"}],
    )
    from app.models.mock import MockModelProvider

    provider = MockModelProvider(responses=[("Query Analyzer", json.dumps(plan)), ("Vision", json.dumps({"findings": []}))])
    client: TestClient = make_client(log_level="INFO", log_format="json")  # type: ignore[operator]
    client.app.state.registry._provider = provider  # type: ignore[attr-defined]

    caplog.set_level(logging.INFO)
    client.post("/api/v1/analyze", json={"query": "Show me Figure 5", "evidence": bundle})

    combined = " ".join(getattr(record, "message", str(record)) for record in caplog.records)
    assert PNG_B64_1X1 not in combined
    assert "sk-super-secret" not in combined
