"""Regression guard: metrics.py must exclude verify-test events from all counts.

ENG-003: growth team misread EXP-006 as 0.91% tap rate because verify-test
smoke events were counted as real user taps. These assertions fail if the
filter is removed.
"""
import pathlib

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
