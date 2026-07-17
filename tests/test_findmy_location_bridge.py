"""Contract tests for the Mac-side Find My roster and privacy boundary."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "hal_findmy_location.py"
SPEC = importlib.util.spec_from_file_location("hal_findmy_location", MODULE_PATH)
assert SPEC and SPEC.loader
findmy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(findmy)


def test_location_relevance_is_conservative() -> None:
    assert findmy.location_relevant("What's good near me?")
    assert findmy.location_relevant("How far is the airport from here?")
    assert findmy.location_relevant("How long would it take me to get downtown?")
    assert findmy.location_relevant("Directions to the airport")
    assert not findmy.location_relevant("What's the weather tomorrow?")
    assert not findmy.location_relevant("Where is the best ramen in Tokyo?")
    # A self-anchor in a LATER sentence must not turn a general distance
    # question into a location lookup.
    assert not findmy.location_relevant("How far is Rome from Paris? Let me know")
    # An explicit origin means no lookup is needed.
    assert not findmy.location_relevant("Directions from JFK to LGA?")


def test_roster_maps_phone_without_exposing_other_relationships(tmp_path) -> None:
    roster = {
        "following": [
            {
                "id": "+15551234567",
                "invitationFromHandles": ["tel:+1 (555) 123-4567"],
            },
            {
                "id": "someone@example.com",
                "invitationFromHandles": ["someone@example.com"],
            },
        ],
        "contacts": {
            "+15551234567": {"displayName": "Alice Example"},
            "someone@example.com": {"displayName": "Bob Example"},
        },
    }
    path = tmp_path / "FriendCacheData.data"
    path.write_text(json.dumps(roster))

    with patch.object(findmy, "OVERRIDE_MAP", str(tmp_path / "missing.json")):
        assert findmy.find_display_name("+1 555 123 4567", str(path)) == "Alice Example"
        assert findmy.find_display_name("unknown@example.com", str(path)) is None


def test_roster_maps_the_accepting_handle_of_a_multi_line_user(tmp_path) -> None:
    # Real shape seen in production: the share was created from the user's
    # primary number but ACCEPTED from the number they text HAL with.
    roster = {
        "following": [
            {
                "id": "MTEzMDA5MzExMw~~",
                "invitationFromHandles": ["+16465550000"],
                "invitationAcceptedHandles": ["+12015551111"],
                "invitationFromHandle": None,
                "invitationSentToHandle": None,
            }
        ],
        "contacts": {"MTEzMDA5MzExMw~~": {"displayName": "Adnan"}},
    }
    path = tmp_path / "FriendCacheData.data"
    path.write_text(json.dumps(roster))

    with patch.object(findmy, "OVERRIDE_MAP", str(tmp_path / "missing.json")):
        assert findmy.find_display_name("+12015551111", str(path)) == "Adnan"
        assert findmy.find_display_name("+16465550000", str(path)) == "Adnan"


def test_lookup_returns_only_selected_location_fields() -> None:
    findmy._cache.clear()
    helper_result = {
        "status": "ok",
        "label": "  123 Example Street, Example City  ",
        "updated": "Now",
        "approximate": True,
        "unrelated_debug_data": "must not cross the bridge",
    }
    with (
        patch.object(findmy, "find_display_name", return_value="Alice Example"),
        patch.object(findmy, "_run_helper", return_value=helper_result),
    ):
        result = findmy.lookup_location("+15551234567")

    assert result["status"] == "ok"
    assert result["label"] == "123 Example Street, Example City"
    assert result["updated"] == "Now"
    assert result["approximate"] is True
    assert "unrelated_debug_data" not in result


def test_lookup_strips_invisible_direction_marks_from_address() -> None:
    # The More Info card's street address arrives with a leading U+200E
    # left-to-right mark, which str.split() does not treat as whitespace.
    findmy._cache.clear()
    helper_result = {
        "status": "ok",
        "label": "‎456 W 22nd St, New York NY, United States",
        "updated": "Now",
        "approximate": False,
    }
    with (
        patch.object(findmy, "find_display_name", return_value="Adnan Akil"),
        patch.object(findmy, "_run_helper", return_value=helper_result),
    ):
        result = findmy.lookup_location("+12015551111")

    assert result["label"] == "456 W 22nd St, New York NY, United States"
    assert result["approximate"] is False


def test_lookup_rejects_map_compass_control_as_location() -> None:
    findmy._cache.clear()
    with (
        patch.object(findmy, "find_display_name", return_value="Alice Example"),
        patch.object(
            findmy,
            "_run_helper",
            return_value={"status": "ok", "label": "Heading: 0 degrees, North"},
        ),
    ):
        result = findmy.lookup_location("+15551234567")

    assert result == {
        "status": "location_label_unavailable",
        "source": "find_my",
    }


def test_lookup_rejects_more_info_card_buttons_with_stray_punctuation() -> None:
    # The More Info card exposes button titles like "Directions," whose
    # trailing comma defeats an exact-match control filter.
    for junk in ("Directions,", "Contact,", "Add Adnan to Favorites", "Remove Adnan", "More Info"):
        findmy._cache.clear()
        with (
            patch.object(findmy, "find_display_name", return_value="Adnan Akil"),
            patch.object(findmy, "_run_helper", return_value={"status": "ok", "label": junk}),
        ):
            result = findmy.lookup_location("+12017570419")
        assert result["status"] == "location_label_unavailable", junk


def test_lookup_rejects_find_my_button_label_as_location() -> None:
    # A person with no location fix yet leaves only chrome in the pane; the
    # weak fallback must not emit a button ("show in 3d") as an address.
    findmy._cache.clear()
    with (
        patch.object(findmy, "find_display_name", return_value="Adnan Akil"),
        patch.object(
            findmy,
            "_run_helper",
            return_value={"status": "ok", "label": "Show in 3D"},
        ),
    ):
        result = findmy.lookup_location("+12017570419")

    assert result == {
        "status": "location_label_unavailable",
        "source": "find_my",
    }


def test_pending_share_answers_once_mapped_and_located(tmp_path) -> None:
    pending = str(tmp_path / "pending.json")
    with patch.object(findmy, "PENDING_PATH", pending):
        findmy.note_pending_share("+1 (201) 555-1111", "Any good pie places around me")

        # Not in the roster yet: no actions, question stays parked.
        with patch.object(findmy, "find_display_name", return_value=None):
            assert findmy.poll_pending_shares() == []
        entries = findmy._load_pending()
        assert len(entries) == 1

        # Share landed and Find My has a fix: answer action, entry consumed.
        findmy._cache.clear()
        with (
            patch.object(findmy, "find_display_name", return_value="Pie Fan"),
            patch.object(
                findmy,
                "_run_helper",
                return_value={"status": "ok", "label": "5 Main St, Example City"},
            ),
            patch.object(findmy.time, "time", return_value=findmy.time.time() + 60),
        ):
            actions = findmy.poll_pending_shares()
        assert actions == [
            {
                "kind": "answer",
                "handle": "+1 (201) 555-1111",
                "text": "Any good pie places around me",
            }
        ]
        assert findmy._load_pending() == {}


def test_pending_share_acks_exactly_once_while_awaiting_first_fix(tmp_path) -> None:
    pending = str(tmp_path / "pending.json")
    findmy._cache.clear()
    with patch.object(findmy, "PENDING_PATH", pending):
        findmy.note_pending_share("+12015551111", "coffee near me?")
        with (
            patch.object(findmy, "find_display_name", return_value="Pie Fan"),
            patch.object(findmy, "_run_helper", return_value={"status": "no_location_found"}),
        ):
            first = findmy.poll_pending_shares()
            # Second poll inside the backoff window: no lookup, no repeat ack.
            second = findmy.poll_pending_shares()
        assert first == [{"kind": "ack", "handle": "+12015551111"}]
        assert second == []
        entry = next(iter(findmy._load_pending().values()))
        assert entry["acked"] is True


def test_pending_share_expires_and_clears(tmp_path) -> None:
    pending = str(tmp_path / "pending.json")
    with patch.object(findmy, "PENDING_PATH", pending):
        findmy.note_pending_share("+12015551111", "coffee near me?")
        # A newer inbound message supersedes the parked question.
        findmy.clear_pending_share("+1 201 555 1111")
        assert findmy._load_pending() == {}

        findmy.note_pending_share("+12015551111", "coffee near me?")
        with patch.object(
            findmy.time, "time", return_value=findmy.time.time() + findmy.PENDING_TTL_SECONDS + 5
        ):
            assert findmy.poll_pending_shares() == []
        assert findmy._load_pending() == {}


def test_helper_timeout_kills_orphan_and_removes_scratch_dir(tmp_path) -> None:
    created = {}
    real_mkdtemp = findmy.tempfile.mkdtemp

    def tracking_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(dir=str(tmp_path))
        created["path"] = path
        return path

    def raise_timeout(*_args, **_kwargs):
        raise findmy.subprocess.TimeoutExpired(cmd="open", timeout=1)

    with (
        patch.object(findmy, "HELPER_APP", str(tmp_path)),
        patch.object(findmy.tempfile, "mkdtemp", tracking_mkdtemp),
        patch.object(findmy.subprocess, "run", raise_timeout),
        patch.object(findmy, "_kill_stale_helper") as kill,
    ):
        result = findmy._run_helper("Alice Example")

    assert result == {"status": "helper_timeout"}
    kill.assert_called_once()
    # The whole scratch dir is gone, so an orphaned helper that writes late
    # has no surviving path — no location JSON can linger on disk.
    assert not Path(created["path"]).exists()


def test_lookup_cache_prunes_expired_entries() -> None:
    findmy._cache.clear()
    stale_stamp = findmy.time.monotonic() - (findmy.CACHE_TTL_SECONDS + 5)
    findmy._cache["staleuser@example.com"] = (
        stale_stamp,
        {"status": "ok", "label": "Old Place"},
    )
    with (
        patch.object(findmy, "find_display_name", return_value="Alice Example"),
        patch.object(
            findmy,
            "_run_helper",
            return_value={"status": "ok", "label": "5 Main Street"},
        ),
    ):
        result = findmy.lookup_location("+15551234567")

    assert result["status"] == "ok"
    assert "staleuser@example.com" not in findmy._cache
