from pathlib import Path

import pytest

from scripts.creator_dedup import (
    are_duplicate_events,
    build_creator_event_id,
    classify_action,
    deduplicate_candidates,
    normalize_title,
    normalize_url,
    title_keywords,
)
from scripts.creator_profile import load_profile


@pytest.fixture
def profile():
    return load_profile(Path("config/martin-ai-coding.json"))


def test_normalize_url_removes_tracking_fragment_and_trailing_slash():
    left = "https://Example.com/post/?utm_source=x&ref=feed#section"
    right = "https://example.com/post"
    assert normalize_url(left) == normalize_url(right)


def test_action_classifier_separates_release_pricing_and_security():
    assert classify_action({"title": "Claude Code launches parallel agents"}) == "release"
    assert classify_action({"title": "OpenAI cuts Codex API pricing"}) == "pricing"
    assert classify_action({"title": "Claude Code fixes sandbox escape vulnerability"}) == "security"


def test_event_id_is_stable_across_source_wording():
    first = {
        "primary_entity": "claude-code",
        "title": "Claude Code launches parallel agents",
    }
    second = {
        "primary_entity": "claude-code",
        "title": "Anthropic 发布 Claude Code 并行代理功能",
    }
    assert build_creator_event_id(first) == build_creator_event_id(second)


def test_keywords_remove_generic_marketing_words():
    words = title_keywords("重磅！Claude Code 正式发布全新并行代理功能")
    assert "重磅" not in words
    assert "全新" not in words
    assert "并行" in words
    assert "代理" in words


def candidate(
    story_id: str,
    title: str,
    *,
    entity: str = "claude-code",
    site_id: str = "curated_media",
    source: str = "Tech Media",
    url: str | None = None,
    latest_at: str = "2026-07-23T01:00:00Z",
    score: float = 80.0,
):
    return {
        "story_id": story_id,
        "title": title,
        "url": url or f"https://example.com/{story_id}",
        "source": source,
        "site_id": site_id,
        "latest_at": latest_at,
        "creator_score": score,
        "primary_entity": entity,
        "verification_status": "confirmed" if site_id == "official_ai" else "single_source",
    }


def test_same_event_from_official_and_media_merges_with_official_primary(profile):
    rows = [
        candidate("media", "Claude Code adds parallel agents", source="Tech Media"),
        candidate(
            "official",
            "Anthropic releases parallel agents in Claude Code",
            site_id="official_ai",
            source="Anthropic",
            url="https://anthropic.com/news/parallel-agents",
            score=78.0,
        ),
    ]
    merged, meta = deduplicate_candidates(rows, profile)
    assert len(merged) == 1
    assert merged[0]["story_id"] == "official"
    assert merged[0]["source"] == "Anthropic"
    assert merged[0]["source_count"] == 2
    assert merged[0]["merged_story_ids"] == ["official", "media"]
    assert meta["secondary_dedup_merge_count"] == 1


def test_same_product_different_actions_do_not_merge(profile):
    release = candidate("release", "Claude Code launches parallel agents")
    pricing = candidate("pricing", "Claude Code introduces a new enterprise price")
    assert are_duplicate_events(release, pricing, profile) is False


def test_same_product_different_features_do_not_merge(profile):
    agents = candidate("agents", "Claude Code launches parallel agents")
    simulator = candidate("sim", "Claude Code integrates iOS simulator testing")
    assert are_duplicate_events(agents, simulator, profile) is False


def test_similar_event_outside_48_hours_does_not_merge(profile):
    old = candidate("old", "Claude Code launches parallel agents", latest_at="2026-07-20T01:00:00Z")
    new = candidate("new", "Anthropic releases parallel agents in Claude Code")
    assert are_duplicate_events(old, new, profile) is False


def test_exact_normalized_url_always_merges(profile):
    left = candidate("a", "First wording", url="https://example.com/post?utm_source=x")
    right = candidate("b", "Different wording", url="https://example.com/post#top")
    assert are_duplicate_events(left, right, profile) is True
