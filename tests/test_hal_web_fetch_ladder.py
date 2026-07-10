"""Pure contract tests for HAL's HTTP-first browser escalation rules."""

from hal_orchestrator.tools.web_search import (
    _extract_page_text,
    _needs_browser_fallback,
)


def test_static_html_is_extracted_without_browser_escalation() -> None:
    body = "<html><body><h1>Events</h1><p>" + ("Useful details " * 50) + "</p></body></html>"
    assert not _needs_browser_fallback(200, body, "text/html")
    assert _extract_page_text(body, "text/html").startswith("Events Useful details")


def test_challenge_and_js_shell_escalate() -> None:
    assert _needs_browser_fallback(403, "Just a moment... cf-chl-bypass", "text/html")
    assert _needs_browser_fallback(
        200,
        '<html><body><div id="root"></div><script src="app.js"></script></body></html>',
        "text/html",
    )


def test_real_non_html_content_stays_on_http_tier() -> None:
    assert not _needs_browser_fallback(200, '{"events":[1,2,3]}', "application/json")
