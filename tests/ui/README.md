# UI regression tests

These tests exercise the real static document in `app/static/index.html` with
the synchronous Python Playwright API. Playwright routes serve the document
locally and mock only `POST /api/v1/ask`, so no reasoning, retrieval, Ollama,
or upload service is needed.

Install the optional dependencies and browser once in an environment where UI
tests are wanted:

```powershell
pip install -e ".[dev,ui]"
playwright install chromium
```

Run only the browser regressions:

```powershell
pytest tests/ui -q
```

The UI suite uses headless Chromium by default. To use an already installed
Microsoft Edge channel instead:

```powershell
$env:UI_BROWSER_CHANNEL = "msedge"
pytest tests/ui -q
```

Without the optional `playwright` package, `tests/ui` is skipped by
`pytest.importorskip("playwright.sync_api")`; the existing backend suite keeps
its current dependency set.
