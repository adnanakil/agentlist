"""Regression guard: budget_guard.py and metrics.py must include Meta spend.

ENG-005: budget_guard.py only summed Google Ads — Meta ad account 40885463 was
live and spending, causing an undetected $31.00 breach on 2026-08-07 ($25.57 Meta
+ $5.43 Google against a $30.00 cap).

These tests verify the source-code structure without requiring live API credentials.
"""
import pathlib

GUARD_PATH = pathlib.Path(__file__).parents[1] / "growth/scripts/budget_guard.py"
METRICS_PATH = pathlib.Path(__file__).parents[1] / "growth/scripts/metrics.py"


def _guard_src() -> str:
    return GUARD_PATH.read_text()


def _metrics_src() -> str:
    return METRICS_PATH.read_text()


# ---------------------------------------------------------------------------
# budget_guard.py checks
# ---------------------------------------------------------------------------

def test_guard_reads_meta_token():
    """budget_guard.py must read META_ACCESS_TOKEN from the environment."""
    src = _guard_src()
    assert "META_ACCESS_TOKEN" in src, (
        "budget_guard.py must read META_ACCESS_TOKEN from env"
    )


def test_guard_exits_nonzero_on_missing_token():
    """budget_guard.py must exit nonzero (not silently skip Meta) when token is absent."""
    src = _guard_src()
    # Must call sys.exit with a nonzero code near the missing-token check
    assert "sys.exit(1)" in src, (
        "budget_guard.py must call sys.exit(1) when META_ACCESS_TOKEN is missing — "
        "never show Google-only totals as if they were complete"
    )
    assert "Meta spend UNKNOWN" in src, (
        "budget_guard.py must print 'Meta spend UNKNOWN' when token is missing"
    )


def test_guard_uses_bearer_auth_not_query_param():
    """Token must travel via Authorization header, never as a URL query parameter."""
    src = _guard_src()
    assert "Authorization" in src and "Bearer" in src, (
        "budget_guard.py must use 'Authorization: Bearer ...' header for Graph API"
    )
    # Ensure access_token is not used as a URL query parameter
    assert "access_token=" not in src, (
        "budget_guard.py must NOT put access_token in the URL — use the Authorization header"
    )


def test_guard_includes_meta_in_cap_total():
    """budget_guard.py must sum Google + Meta into the combined cap check."""
    src = _guard_src()
    # The combined total must reference both google and meta components
    assert "meta_daily_projected" in src, (
        "budget_guard.py must compute meta_daily_projected for the cap check"
    )
    assert "google_total + meta_daily_projected" in src or (
        "meta_daily_projected" in src and "total" in src
    ), (
        "budget_guard.py must add Meta projected spend to Google total before checking the cap"
    )


def test_guard_applies_overdelivery_multiplier():
    """Meta daily budgets must use 1.25x multiplier — Meta overdelivers up to ~125%."""
    src = _guard_src()
    assert "1.25" in src, (
        "budget_guard.py must apply 1.25x multiplier to Meta daily budgets — "
        "Meta can overdeliver up to ~125% of the declared daily budget on any given day"
    )


def test_guard_reports_lifetime_campaigns_separately():
    """Lifetime-budget campaigns must be reported separately, not summed into the daily cap."""
    src = _guard_src()
    assert "meta_lifetime" in src, (
        "budget_guard.py must track lifetime-budget campaigns separately from daily-budget ones"
    )
    assert "LIFETIME" in src or "lifetime" in src.lower(), (
        "budget_guard.py must label lifetime campaigns in output so they are visible"
    )


def test_guard_uses_certifi_ssl():
    """budget_guard.py must use certifi for TLS — Homebrew python3 has no CA bundle."""
    src = _guard_src()
    assert "certifi" in src, (
        "budget_guard.py must use certifi.where() for TLS — "
        "Homebrew python3 on hal has no CA bundle and raises CERTIFICATE_VERIFY_FAILED otherwise"
    )


def test_guard_does_not_scale_meta_budgets():
    """When over cap, only Google budgets should be scaled — Meta is growth's lane."""
    src = _guard_src()
    assert "Meta budgets unchanged" in src or "growth's lane" in src, (
        "budget_guard.py must note that Meta budgets are not auto-scaled when clamping"
    )


# ---------------------------------------------------------------------------
# metrics.py checks
# ---------------------------------------------------------------------------

def test_metrics_includes_meta_spend_function():
    """metrics.py must have a meta_spend() function to pull Meta daily spend."""
    src = _metrics_src()
    assert "def meta_spend(" in src, (
        "metrics.py must define meta_spend() to pull Meta Ads daily spend data"
    )


def test_metrics_uses_bearer_auth_not_query_param():
    """Token must travel via Authorization header in metrics.py too."""
    src = _metrics_src()
    assert "Authorization" in src and "Bearer" in src, (
        "metrics.py must use 'Authorization: Bearer ...' header for Graph API calls"
    )
    assert "access_token=" not in src, (
        "metrics.py must NOT put access_token in the URL — use the Authorization header"
    )


def test_metrics_scoreboard_includes_meta_column():
    """The scoreboard table must include a meta spend column."""
    src = _metrics_src()
    assert "meta spend" in src or "meta_cost_usd" in src, (
        "metrics.py scoreboard must include Meta spend per day — "
        "previously the table showed only Google spend, making CPA calculations incomplete"
    )


def test_metrics_window_spend_includes_meta():
    """window_spend must sum both Google and Meta spend for accurate CPA."""
    src = _metrics_src()
    assert "window_meta_spend" in src or "meta_cost_usd" in src, (
        "metrics.py must include Meta spend in window_spend for CPA calculations — "
        "Google-only totals silently understate the true cost per acquisition"
    )


def test_metrics_degrades_gracefully_on_missing_token():
    """metrics.py must degrade gracefully (not exit) if META_ACCESS_TOKEN is absent."""
    src = _metrics_src()
    # meta_spend should return {} on error, not exit
    assert "return {}" in src, (
        "metrics.py meta_spend() must return {} on missing/expired token — "
        "metrics is a reporting script and should degrade gracefully, unlike budget_guard"
    )
