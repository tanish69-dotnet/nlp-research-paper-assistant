"""Playwright fixtures for the static ResearchLens UI.

The UI tests serve ``app/static/index.html`` from a Playwright route and mock
only the ask HTTP boundary.  No API process, retrieval service, or Ollama
instance is needed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

playwright_sync_api = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync_api.sync_playwright


ROOT = Path(__file__).resolve().parents[2]
INDEX_HTML = ROOT / "app" / "static" / "index.html"
UI_ORIGIN = "http://researchlens.test"


@dataclass
class _Reply:
    """One deterministic response (or transport failure) for the ask route."""

    kind: str
    status: int = 200
    body: Any = ""
    content_type: str = "application/json"


class AskRoute:
    """Playwright route handler and request recorder for ``POST /api/v1/ask``."""

    def __init__(self) -> None:
        self.replies: deque[_Reply] = deque()
        self.requests: list[dict[str, Any]] = []
        self._html = INDEX_HTML.read_text(encoding="utf-8")

    def enqueue_json(self, body: dict[str, Any], *, status: int = 200) -> None:
        self.replies.append(_Reply("json", status=status, body=body))

    def enqueue_text(
        self,
        body: str,
        *,
        status: int = 502,
        content_type: str = "text/html",
    ) -> None:
        self.replies.append(
            _Reply("text", status=status, body=body, content_type=content_type)
        )

    def enqueue_network_error(self) -> None:
        self.replies.append(_Reply("abort"))

    def handle(self, route: Any) -> None:
        """Serve the document and answer only requests made by that document."""

        request = route.request
        parsed = urlparse(request.url)

        if parsed.netloc != urlparse(UI_ORIGIN).netloc:
            # This also prevents a regression from accidentally reaching a
            # developer's real service when a test sets the wrong-port input.
            route.abort()
            return

        if parsed.path == "/":
            route.fulfill(status=200, content_type="text/html", body=self._html)
            return

        if parsed.path != "/api/v1/ask":
            route.fulfill(status=404, body="not found")
            return

        if request.method == "OPTIONS":
            route.fulfill(
                status=204,
                headers={
                    "Access-Control-Allow-Origin": UI_ORIGIN,
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                },
            )
            return

        post_data = request.post_data or "{}"
        self.requests.append(json.loads(post_data))
        if not self.replies:
            route.fulfill(
                status=500,
                content_type="application/json",
                body=json.dumps({"detail": "test did not enqueue a reply"}),
            )
            return

        reply = self.replies.popleft()
        if reply.kind == "abort":
            route.abort()
        elif reply.kind == "json":
            route.fulfill(
                status=reply.status,
                content_type=reply.content_type,
                body=json.dumps(reply.body),
            )
        else:
            route.fulfill(
                status=reply.status,
                content_type=reply.content_type,
                body=str(reply.body),
            )


@pytest.fixture(scope="session")
def browser() -> Any:
    """Launch Chromium by default, with an optional installed Edge channel."""

    channel = os.environ.get("UI_BROWSER_CHANNEL", "").strip()
    launch_options: dict[str, Any] = {"headless": True}
    if channel:
        launch_options["channel"] = channel

    with sync_playwright() as playwright:
        browser_type = playwright.chromium
        browser_instance = browser_type.launch(**launch_options)
        yield browser_instance
        browser_instance.close()


@pytest.fixture
def ask_api() -> AskRoute:
    return AskRoute()


@pytest.fixture
def ui_page(browser: Any, ask_api: AskRoute) -> Any:
    """Open the real static document on a local routed origin."""

    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(5_000)
    page.set_default_navigation_timeout(5_000)
    page.route("**/*", ask_api.handle)
    page.goto(UI_ORIGIN + "/")
    yield page
    context.close()
