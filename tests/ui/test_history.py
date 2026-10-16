"""Bounded browser regressions for the request-history UI contract."""

from __future__ import annotations

from typing import Any


def _claim(
    text: str = "The method improved recall.",
    *,
    claim_id: str = "claim-1",
    verdict: str = "SUPPORTED",
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "agent": "text_reasoner",
        "kind": "author_claim",
        "text": text,
        "evidence_ids": ["e-1"],
        "confidence": 0.9,
        "verification": {
            "claim_id": claim_id,
            "verdict": verdict,
            "verifier": "deterministic",
            "rationale": "matched evidence",
        },
    }


def _citation(
    citation_id: str = "cite-1",
    *,
    reference: str = "Table 1, row 2",
) -> dict[str, Any]:
    return {
        "citation_id": citation_id,
        "evidence_id": "e-1",
        "paper_id": "paper-a",
        "page": 2,
        "type": "table",
        "reference": reference,
        "title": "Results",
    }


def _agent_output(
    *,
    message: str = "model timed out",
    code: str = "MODEL_TIMEOUT",
    status: str = "timeout",
) -> dict[str, Any]:
    return {
        "agent": "table_reasoner",
        "model": "mock-model",
        "provider": "mock",
        "prompt_version": "test-v1",
        "status": status,
        "latency_ms": 17,
        "evidence_ids_used": ["e-1"],
        "findings": [],
        "usage": {},
        "error": {
            "code": code,
            "message": message,
            "retriable": True,
            "attempts": 2,
        },
    }


def _answer(
    answer: str = "The answer is grounded in the paper.",
    *,
    request_id: str = "request-1",
    status: str = "ok",
    verification_status: str = "supported",
    citations: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
    degraded: list[str] | None = None,
    agent_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "status": status,
        "answer": answer,
        "confidence": 0.9 if verification_status == "supported" else 0.0,
        "citations": citations if citations is not None else [_citation()],
        "claims": claims if claims is not None else [_claim()],
        "verification": {
            "status": verification_status,
            "supported": 1 if verification_status == "supported" else 0,
            "partially_supported": 1 if verification_status == "partially_supported" else 0,
            "unsupported": 1 if verification_status == "unsupported" else 0,
            "contradicted": 0,
            "unsupported_claims": [],
            "contradicted_claims": [],
            "needs_more_evidence": verification_status != "supported",
        },
        "agent_outputs": agent_outputs or [],
        "metadata": {
            "timings_ms": {"total": 42},
            "agent_status": {"text_reasoner": "ok"},
            "degraded": degraded or [],
            "pipeline_version": "test-ui",
        },
    }


def _submit_json(
    page: Any,
    ask_api: Any,
    question: str,
    response: dict[str, Any],
    *,
    expected_card: str | None = None,
) -> None:
    """Submit through the visible controls and wait for the real DOM update."""

    ask_api.enqueue_json(response)
    page.locator("#query").fill(question)
    with page.expect_response("**/api/v1/ask"):
        page.locator("#ask-btn").click()
    page.wait_for_function(
        "() => document.getElementById('ask-btn') && !document.getElementById('ask-btn').disabled"
    )
    if expected_card is not None:
        page.locator(expected_card).wait_for(state="visible")


def _wait_until_enabled(page: Any) -> None:
    page.wait_for_function(
        "() => document.getElementById('ask-btn') && !document.getElementById('ask-btn').disabled"
    )


def _cards(page: Any) -> Any:
    return page.locator("#answer-result article.history-entry")


def _badge_texts(card: Any) -> list[str]:
    return [text.strip().lower() for text in card.locator(".badge").all_text_contents()]


def test_successive_answers_append_with_questions_statuses_and_citations(
    ui_page: Any,
    ask_api: Any,
) -> None:
    """Two accepted requests remain visible in chronological order."""

    first = _answer(
        "First answer",
        request_id="request-1",
        citations=[_citation("cite-first")],
        claims=[_claim("First claim")],
    )
    second = _answer(
        "Second answer",
        request_id="request-2",
        status="partial",
        verification_status="partially_supported",
        citations=[],
        claims=[_claim("Second claim", claim_id="claim-2", verdict="PARTIALLY_SUPPORTED")],
    )

    assert ui_page.locator("#history-empty").is_visible()
    _submit_json(ui_page, ask_api, "First question", first, expected_card="#answer-1")
    _submit_json(ui_page, ask_api, "Second question", second, expected_card="#answer-2")

    cards = _cards(ui_page)
    assert cards.count() == 2
    assert [cards.nth(index).get_attribute("id") for index in range(2)] == [
        "answer-1",
        "answer-2",
    ]
    assert cards.nth(0).inner_text().find("First question") < cards.nth(1).inner_text().find(
        "Second question"
    )
    assert cards.nth(0).locator(".answer").inner_text() == "First answer"
    assert cards.nth(1).locator(".answer").inner_text() == "Second answer"

    first_badges = _badge_texts(cards.nth(0))
    second_badges = _badge_texts(cards.nth(1))
    assert any("verification: supported" in text for text in first_badges)
    assert any("pipeline: ok" in text for text in first_badges)
    assert any("verification: partially_supported" in text for text in second_badges)
    assert any("pipeline: partial" in text for text in second_badges)

    assert "cite-first" in cards.nth(0).inner_text()
    assert "First claim" in cards.nth(0).inner_text()
    assert "No citations returned." in cards.nth(1).inner_text()
    assert "Second claim" in cards.nth(1).inner_text()
    assert not ui_page.locator("#history-empty").is_visible()
    assert ui_page.locator("#latest-answer").get_attribute("href") == "#answer-2"

    status = ui_page.locator("#ask-status")
    assert status.count() == 1
    assert status.evaluate("element => !element.closest('#answer-result')")


def test_partial_unsupported_unverified_and_unknown_are_explicit(
    ui_page: Any,
    ask_api: Any,
) -> None:
    cases = [
        ("partial", "partially_supported"),
        ("unsupported", "unsupported"),
        ("unverified", "unverified"),
        ("unknown", "unknown"),
    ]

    for index, (pipeline_status, verification_status) in enumerate(cases, start=1):
        _submit_json(
            ui_page,
            ask_api,
            f"Question {index}",
            _answer(
                f"Answer {index}",
                request_id=f"request-{index}",
                status=pipeline_status,
                verification_status=verification_status,
            ),
            expected_card=f"#answer-{index}",
        )

        card = ui_page.locator(f"#answer-{index}")
        badges = _badge_texts(card)
        assert any(f"verification: {verification_status}" in text for text in badges)
        assert any(f"pipeline: {pipeline_status}" in text for text in badges)
        assert all(text.strip() != "supported" for text in badges)


def test_problem_detail_agent_errors_and_degraded_metadata_stay_in_history(
    ui_page: Any,
    ask_api: Any,
) -> None:
    problem = {
        "type": "https://researchlens.local/errors/MODEL_TIMEOUT",
        "title": "Model timeout",
        "status": 504,
        "detail": "The reasoning model timed out.",
        "code": "MODEL_TIMEOUT",
        "request_id": "failed-request",
        "retryable": True,
    }
    ask_api.enqueue_json(problem, status=504)
    ui_page.locator("#query").fill("Problem detail question")
    with ui_page.expect_response("**/api/v1/ask"):
        ui_page.locator("#ask-btn").click()
    _wait_until_enabled(ui_page)

    degraded = _answer(
        "A partially degraded answer",
        request_id="degraded-request",
        status="partial",
        verification_status="unverified",
        degraded=["table_reasoner:timeout"],
        agent_outputs=[
            _agent_output(
                message="table model timed out after retry",
                code="MODEL_TIMEOUT",
                status="timeout",
            )
        ],
    )
    _submit_json(
        ui_page,
        ask_api,
        "Degraded question",
        degraded,
        expected_card="#answer-2",
    )

    cards = _cards(ui_page)
    assert cards.count() == 2
    problem_card = ui_page.locator("#answer-1")
    problem_text = problem_card.inner_text()
    assert "MODEL_TIMEOUT" in problem_text
    assert "The reasoning model timed out." in problem_text
    assert "failed-request" in problem_text
    assert "retryable" in problem_text.lower()

    degraded_text = ui_page.locator("#answer-2").inner_text()
    assert "table_reasoner:timeout" in degraded_text
    assert "table model timed out after retry" in degraded_text
    assert "MODEL_TIMEOUT" in degraded_text
    assert "attempts" in degraded_text.lower()


def test_network_and_non_json_failures_do_not_clear_previous_cards(
    ui_page: Any,
    ask_api: Any,
) -> None:
    _submit_json(
        ui_page,
        ask_api,
        "Stable question",
        _answer("Stable answer", request_id="stable-request"),
        expected_card="#answer-1",
    )

    ask_api.enqueue_network_error()
    ui_page.locator("#query").fill("Network failure")
    ui_page.locator("#ask-btn").click()
    _wait_until_enabled(ui_page)
    assert ui_page.locator("#answer-1 .answer").inner_text() == "Stable answer"
    assert "Stable question" in ui_page.locator("#answer-1").inner_text()

    ask_api.enqueue_text("<html>not JSON</html>", status=502)
    ui_page.locator("#query").fill("Non JSON failure")
    with ui_page.expect_response("**/api/v1/ask"):
        ui_page.locator("#ask-btn").click()
    _wait_until_enabled(ui_page)
    assert ui_page.locator("#answer-1 .answer").inner_text() == "Stable answer"
    assert "Stable question" in ui_page.locator("#answer-1").inner_text()


def test_blank_and_wrong_port_validation_preserve_history(
    ui_page: Any,
    ask_api: Any,
) -> None:
    _submit_json(
        ui_page,
        ask_api,
        "Already answered",
        _answer("Keep this answer"),
        expected_card="#answer-1",
    )

    ui_page.locator("#query").fill("   ")
    ui_page.locator("#ask-btn").click()
    _wait_until_enabled(ui_page)
    assert len(ask_api.requests) == 1
    assert ui_page.locator("#answer-1 .answer").inner_text() == "Keep this answer"
    assert "question" in ui_page.locator("#ask-status").inner_text().lower()

    ui_page.locator("#query").fill("Wrong port check")
    ui_page.locator("#nlpbase").fill("http://127.0.0.1:8000")
    ui_page.locator("#p2base").fill("http://127.0.0.1:8000")
    ui_page.locator("#ask-btn").click()
    _wait_until_enabled(ui_page)
    assert len(ask_api.requests) == 1
    assert ui_page.locator("#answer-1 .answer").inner_text() == "Keep this answer"
    assert "8000" in ui_page.locator("#ask-status").inner_text()


def test_request_payload_and_service_upload_controls_remain_compatible(
    ui_page: Any,
    ask_api: Any,
) -> None:
    assert ui_page.locator("#p2base").input_value() == "http://127.0.0.1:8000"
    assert ui_page.locator("#nlpbase").input_value() == ""
    assert ui_page.locator("#topk").input_value() == "8"
    assert ui_page.locator("#scope").input_value() == ""
    assert ui_page.locator("#pdf").get_attribute("type") == "file"
    assert ui_page.locator("#paper-id").count() == 1
    assert ui_page.locator("#paper-title").count() == 1
    assert ui_page.locator("#upload-btn").count() == 1
    assert ui_page.locator("#upload-progress").count() == 1

    ask_api.enqueue_json(_answer("Payload answer"))
    ui_page.locator("#query").fill("Payload question")
    ui_page.locator("#topk").fill("13")
    ui_page.locator("#scope").fill("paper-a, paper-b")
    with ui_page.expect_response("**/api/v1/ask"):
        ui_page.locator("#ask-btn").click()
    _wait_until_enabled(ui_page)

    assert ask_api.requests == [
        {
            "query": "Payload question",
            "top_k": 13,
            "paper_ids": ["paper-a", "paper-b"],
        }
    ]
    assert ui_page.locator("#p2base").input_value() == "http://127.0.0.1:8000"
    assert ui_page.locator("#nlpbase").input_value() == ""


def test_question_answer_error_and_citation_markup_is_literal_text(
    ui_page: Any,
    ask_api: Any,
) -> None:
    question = '<img src=x onerror="question()">'
    answer = '<script>alert("answer")</script>'
    citation = '<b onclick="citation()">citation</b>'
    claim = '<i onclick="claim()">claim</i>'
    error = '<svg onload="error()">error</svg>'
    response = _answer(
        answer,
        citations=[_citation(reference=citation)],
        claims=[_claim(claim)],
        degraded=[error],
        agent_outputs=[_agent_output(message=error)],
    )

    _submit_json(ui_page, ask_api, question, response, expected_card="#answer-1")

    card = ui_page.locator("#answer-1")
    rendered = card.inner_text()
    assert question in rendered
    assert answer in card.locator(".answer").inner_text()
    assert citation in rendered
    assert claim in rendered
    assert error in rendered
    assert card.locator("script, img, svg, b, i").count() == 0


def test_direct_ask_reentry_is_one_request_and_button_recovers_after_failures(
    ui_page: Any,
    ask_api: Any,
) -> None:
    ask_api.enqueue_json(_answer("Only one answer", request_id="one-request"))
    ui_page.locator("#query").fill("Double submission")

    state_during_request = ui_page.evaluate(
        """
        async () => {
          const first = ask();
          const during = {
            disabled: document.getElementById("ask-btn").disabled,
            label: document.getElementById("ask-btn").textContent.trim(),
            status: document.getElementById("ask-status").textContent,
          };
          const second = ask();
          await Promise.all([first, second]);
          return during;
        }
        """
    )

    assert state_during_request["disabled"] is True
    assert state_during_request["label"] == "Asking…"
    assert "asking" in state_during_request["status"].lower()
    assert len(ask_api.requests) == 1
    ui_page.locator("#answer-1").wait_for(state="visible")
    assert _cards(ui_page).count() == 1
    assert ui_page.locator("#ask-btn").is_enabled()
    assert ui_page.locator("#ask-btn").inner_text().strip() == "Ask"

    ask_api.enqueue_network_error()
    ui_page.locator("#query").fill("Failure then retry")
    ui_page.locator("#ask-btn").click()
    _wait_until_enabled(ui_page)
    assert len(ask_api.requests) == 2

    ask_api.enqueue_json(_answer("Retry answer", request_id="retry-request"))
    ui_page.locator("#query").fill("Retry after failure")
    with ui_page.expect_response("**/api/v1/ask"):
        ui_page.locator("#ask-btn").click()
    _wait_until_enabled(ui_page)
    assert len(ask_api.requests) == 3
    assert ui_page.locator(".answer").count() == 2
    assert ui_page.locator("#ask-btn").is_enabled()
