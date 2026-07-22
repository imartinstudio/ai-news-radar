from pathlib import Path

import pytest

from scripts.creator_profile import load_profile, normalized_aliases


def test_load_profile_rejects_weights_not_equal_to_100(tmp_path: Path):
    path = tmp_path / "profile.json"
    path.write_text(
        '{"version":1,"timezone":"Asia/Shanghai",'
        '"edition":{"min_items":8,"max_items":12,"ai_coding_ratio":0.7,'
        '"product_cap_ratio":0.3,"history_limit":60},'
        '"thresholds":{"focus":78,"quick":62,"signal":50},'
        '"weights":{"relevance":30,"freshness":20,"source":20,'
        '"impact":15,"novelty":10,"heat":4},'
        '"entities":[],"ai_coding_terms":[],"general_ai_terms":[],'
        '"negative_terms":[],"high_impact_terms":[],"source_tiers":{},'
        '"official_source_patterns":[],"early_signal_site_ids":[]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="weights_total"):
        load_profile(path)


def test_load_profile_accepts_checked_in_profile():
    profile = load_profile(Path("config/martin-ai-coding.json"))
    assert profile["edition"]["max_items"] == 12
    assert profile["weights"]["heat"] == 5


def test_normalized_aliases_are_lowercase_and_longest_first():
    profile = {
        "entities": [
            {"id": "cursor", "bucket": "ai_coding", "weight": 1, "aliases": ["Cursor", "Cursor IDE"]},
        ]
    }
    aliases = normalized_aliases(profile)
    assert aliases == [
        ("cursor ide", "cursor", "ai_coding", 1.0),
        ("cursor", "cursor", "ai_coding", 1.0),
    ]
