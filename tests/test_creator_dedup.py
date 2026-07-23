from scripts.creator_dedup import (
    build_creator_event_id,
    classify_action,
    normalize_title,
    normalize_url,
    title_keywords,
)


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
