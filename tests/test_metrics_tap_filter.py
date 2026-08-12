"""Regression guard: metrics.py must exclude verify-test events and monitor
probe UAs from all counts.

ENG-003: growth team misread EXP-006 as 0.91% tap rate because verify-test
smoke events were counted as real user taps. These assertions fail if the
filter is removed.

ENG-017: verify_prod.py UAs (UA_IOS, UA_ANDROID) pass is_bot=False and
inflated landing views 10x+, poisoning every derived rate including the
SMS tap rate that gates the Reddit rollout (decision D4).
"""
import pathlib
import types

METRICS_PATH = pathlib.Path(__file__).parents[1] / "growth/scripts/metrics.py"


def _source() -> str:
    return METRICS_PATH.read_text()


def test_sms_tap_excludes_verify_test():
    src = _source()
    # Both queries use the IS NULL OR pattern so organic events with no utm_source
    # are not accidentally excluded (bare != 'verify-test' drops NULL rows in SQL)
    assert src.count("utm_source IS NULL OR utm_source != 'verify-test'") >= 2, (
        "metrics.py sms_tap query must use (utm_source IS NULL OR utm_source != 'verify-test') — "
        "bare != drops NULL-source organic taps"
    )


def test_page_hits_excludes_verify_test():
    src = _source()
    # The hal_page_hits landing view query must also filter out verify-test hits
    assert "utm_source IS NULL OR utm_source != 'verify-test'" in src, (
        "metrics.py landing-view query is missing the verify-test filter — "
        "engineer smoke-test page hits would inflate landing view counts"
    )


def test_sms_tap_filter_in_correct_query():
    """Confirm the IS NULL OR filter appears inside the hal_funnel_events block."""
    src = _source()
    funnel_block_start = src.index("hal_funnel_events")
    # find the second occurrence (first is in hal_page_hits block)
    first = src.index("utm_source IS NULL OR utm_source != 'verify-test'")
    second = src.index("utm_source IS NULL OR utm_source != 'verify-test'", first + 1)
    assert second > funnel_block_start, (
        "utm_source IS NULL OR filter not found inside the hal_funnel_events query"
    )


# ── ENG-017: probe-UA exclusion ──────────────────────────────────────────────

UA_IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17.0 Mobile Safari"
UA_ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120 Mobile"


def _load_metrics_module():
    """Import metrics.py as a module without executing main() or touching env."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("metrics", METRICS_PATH)
    mod = importlib.util.module_from_spec(spec)
    # Stub heavy imports so the module loads in test context without credentials.
    import sys
    import unittest.mock as mock
    with mock.patch.dict(sys.modules, {
        "asyncpg": mock.MagicMock(),
        "certifi": mock.MagicMock(),
        "google.ads.googleads.client": mock.MagicMock(),
        "google": mock.MagicMock(),
        "google.ads": mock.MagicMock(),
        "google.ads.googleads": mock.MagicMock(),
    }):
        spec.loader.exec_module(mod)
    return mod


def test_probe_ua_exact_contains_verify_prod_uas():
    mod = _load_metrics_module()
    assert UA_IOS in mod._PROBE_UA_EXACT, (
        "UA_IOS (verify_prod.py) missing from _PROBE_UA_EXACT — "
        "these hits inflate landing views and corrupt SMS tap rate"
    )
    assert UA_ANDROID in mod._PROBE_UA_EXACT, (
        "UA_ANDROID (verify_prod.py) missing from _PROBE_UA_EXACT"
    )


def test_probe_ua_ilike_contains_required_patterns():
    mod = _load_metrics_module()
    patterns = mod._PROBE_UA_ILIKE
    assert any("Verify/" in p for p in patterns), (
        "No Verify/ pattern in _PROBE_UA_ILIKE — arm-checker hits would be counted"
    )
    assert any("facebookexternalhit" in p for p in patterns), (
        "No facebookexternalhit pattern in _PROBE_UA_ILIKE"
    )
    assert any("eng-verify-bot" in p for p in patterns), (
        "No eng-verify-bot pattern in _PROBE_UA_ILIKE"
    )


def test_view_rows_query_excludes_probe_uas():
    src = _source()
    assert "user_agent IS NULL OR NOT" in src, (
        "view_rows query must exclude probe UAs with: "
        "user_agent IS NULL OR NOT (...) — null UA rows must still be counted"
    )


def test_load_growth_env_called_before_ad_spend():
    src = _source()
    assert "_load_growth_env" in src, (
        "_load_growth_env() helper is missing — META_ACCESS_TOKEN won't be loaded "
        "when metrics.py runs outside the supervisor context"
    )
    # Verify it is called inside ad_spend() (belt-and-suspenders guard for direct callers)
    ad_spend_start = src.index("def ad_spend()")
    ad_spend_body = src[ad_spend_start: src.index("\ndef ", ad_spend_start + 1)]
    assert "_load_growth_env()" in ad_spend_body, (
        "_load_growth_env() must be called inside ad_spend() so META_ACCESS_TOKEN "
        "is available even when ad_spend() is called directly without going through main()"
    )
    # Also verify ordering in main(): _load_growth_env() must precede ad_spend()
    main_start = src.index("def main():")
    main_body = src[main_start:]
    load_pos = main_body.index("_load_growth_env()")
    ad_spend_call_pos = main_body.index("ad_spend()")
    assert load_pos < ad_spend_call_pos, (
        "_load_growth_env() must be called before ad_spend() in main()"
    )
