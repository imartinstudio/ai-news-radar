from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.creator_profile import load_profile
from scripts.creator_rules import classify_verification, score_story, select_candidates

NOW = datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def profile():
    return load_profile(Path("config/martin-ai-coding.json"))


def story(
    idx: int,
    *,
    title: str,
    site_id: str = "official_ai",
    source_count: int = 1,
    hours: int = 1,
    score: float = 0.8,
):
    source = "OpenAI News" if site_id == "official_ai" else "Hacker News"
    return {
        "story_id": f"s-{idx}",
        "title": title,
        "site_id": site_id,
        "source": source,
        "source_name": source,
        "source_count": source_count,
        "score": score,
        "latest_at": (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z"),
        "primary_item": {"id": f"i-{idx}", "title": title, "site_id": site_id},
    }


def test_official_coding_release_scores_above_generic_business_news(profile):
    coding = score_story(story(1, title="Claude Code releases parallel agents"), profile, NOW)
    business = score_story(story(2, title="AI startup raises new funding"), profile, NOW)

    assert coding["creator_score"] > business["creator_score"]
    assert coding["creator_bucket"] == "ai_coding"
    assert coding["primary_entity"] == "claude-code"


def test_verification_status_separates_official_and_hn(profile):
    assert classify_verification(story(1, title="Codex update"), profile) == "confirmed"
    assert classify_verification(story(2, title="Codex rumor", site_id="hackernews"), profile) == "early_signal"


def test_verification_can_read_site_id_from_nested_source(profile):
    item = story(3, title="Cursor beta discussed on HN", site_id="")
    item.pop("site_id")
    item["primary_item"].pop("site_id")
    item["sources"] = [{"site_id": "hackernews", "source": "HN Algolia"}]

    assert classify_verification(item, profile) == "early_signal"


def test_selection_caps_one_product_and_keeps_general_ai_share(profile):
    rows = [story(i, title=f"Claude Code update {i}") for i in range(10)]
    rows += [
        story(20, title="Gemini model release benchmark"),
        story(21, title="DeepSeek reasoning model release"),
        story(30, title="Codex coding agent release"),
        story(31, title="Codex CLI API update"),
        story(32, title="Codex code review workflow"),
        story(40, title="Cursor IDE agent workflow"),
        story(41, title="Cursor code review update"),
        story(42, title="Cursor terminal agent release"),
        story(50, title="MCP server SDK release"),
        story(51, title="Model Context Protocol tooling update"),
    ]

    selected = select_candidates(rows, profile, NOW)

    assert len(selected) == 12
    claude_count = sum(item.get("primary_entity") == "claude-code" for item in selected)
    assert claude_count <= 3
    assert any(item["creator_bucket"] == "general_ai" for item in selected)
    assert all(item["creator_score"] >= profile["thresholds"]["signal"] for item in selected)
