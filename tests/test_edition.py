from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.creator_profile import load_profile
from scripts.edition import append_edition_history, build_edition, resolve_edition_kind, story_fingerprint

NOW = datetime(2026, 7, 22, 12, 47, tzinfo=timezone.utc)


@pytest.fixture
def profile():
    return load_profile(Path("config/martin-ai-coding.json"))


def candidate(story_id: str, status: str, score: float = 80, source_count: int = 1, latest_at: str = "2026-07-22T12:00:00Z"):
    return {
        "story_id": story_id,
        "title": story_id,
        "creator_score": score,
        "verification_status": status,
        "source_count": source_count,
        "latest_at": latest_at,
        "creator_bucket": "ai_coding",
        "primary_entity": story_id,
    }


def test_evening_skips_unchanged_morning_story(profile):
    same = candidate("same", "confirmed")
    rows = [same, candidate("new", "early_signal")]
    state = {
        "stories": {
            "same": {
                "last_fingerprint": story_fingerprint(same),
                "last_status": "confirmed",
                "last_sent_at": "2026-07-22T00:17:00Z",
            }
        }
    }

    edition, _ = build_edition(rows, state, profile, NOW, "evening")

    assert [item["story_id"] for item in edition["items"]] == ["new"]
    assert edition["items"][0]["change_type"] == "new"


def test_transition_from_early_signal_to_confirmed_is_update(profile):
    rows = [candidate("upgrade", "confirmed", source_count=2)]
    state = {
        "stories": {
            "upgrade": {
                "last_fingerprint": "early_signal|1|upgrade|2026-07-22T02:00:00Z",
                "last_status": "early_signal",
                "last_sent_at": "2026-07-22T00:17:00Z",
            }
        }
    }

    edition, _ = build_edition(rows, state, profile, NOW, "evening")

    assert edition["items"][0]["change_type"] == "confirmed"


def test_filtering_happens_before_max_item_cap(profile):
    unchanged = [candidate(f"old-{idx}", "confirmed", score=100 - idx) for idx in range(12)]
    state = {
        "stories": {
            item["story_id"]: {
                "last_fingerprint": story_fingerprint(item),
                "last_status": "confirmed",
                "last_sent_at": "2026-07-22T00:17:00Z",
            }
            for item in unchanged
        }
    }
    rows = unchanged + [candidate("late-new", "confirmed", score=60)]

    edition, _ = build_edition(rows, state, profile, NOW, "evening")

    assert [item["story_id"] for item in edition["items"]] == ["late-new"]


def test_history_replaces_same_edition_and_honors_limit():
    history = {"editions": [{"edition_id": "same", "generated_at": "old"}, {"edition_id": "older"}]}
    updated = append_edition_history(history, {"edition_id": "same", "generated_at": "new"}, limit=2)

    assert updated["editions"] == [
        {"edition_id": "same", "generated_at": "new"},
        {"edition_id": "older"},
    ]


def test_resolve_edition_kind_uses_shanghai_dayparts():
    assert resolve_edition_kind(datetime(2026, 7, 22, 0, 17, tzinfo=timezone.utc), "Asia/Shanghai", "auto") == "morning"
    assert resolve_edition_kind(datetime(2026, 7, 22, 12, 47, tzinfo=timezone.utc), "Asia/Shanghai", "auto") == "evening"
