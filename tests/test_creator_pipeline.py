import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.creator_pipeline import run_pipeline

NOW = datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def make_story(index: int) -> dict:
    salt = f"uniq{index:02d}z{index * 37:04d}"
    title = f"{salt} Codex {salt[::-1]}"
    return {
        "story_id": f"story-{index}",
        "title": title,
        "url": f"https://example.com/story-{index}-{salt}",
        "source": "OpenAI Codex Changelog",
        "source_name": "Official AI Updates",
        "source_count": 1,
        "score": 0.9,
        "latest_at": f"2026-07-21T{23 - (index % 10):02d}:{index % 60:02d}:00Z",
        "primary_item": {
            "id": f"item-{index}",
            "title": title,
            "summary": "",
            "recommend_reason_zh": "Codex 发布了面向开发者的新能力。",
            "url": f"https://example.com/story-{index}-{salt}",
            "source": "OpenAI Codex Changelog",
            "source_name": "Official AI Updates",
        },
        "sources": [
            {
                "id": f"item-{index}",
                "title": title,
                "url": f"https://example.com/story-{index}-{salt}",
                "source": "OpenAI Codex Changelog",
                "source_name": "Official AI Updates",
                "site_id": "official_ai",
                "published_at": f"2026-07-21T{23 - (index % 10):02d}:{index % 60:02d}:00Z",
            }
        ],
    }


def write_inputs(data: Path, count: int = 1) -> None:
    stories = [make_story(index) for index in range(count)]
    (data / "stories-merged.json").write_text(
        json.dumps({"generated_at": "2026-07-22T00:00:00Z", "window_hours": 24, "stories": stories}),
        encoding="utf-8",
    )
    (data / "daily-brief.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "story_id": "story-0",
                        "persona_id": "pragmatic",
                        "persona_score": 90,
                        "persona_review": "这会直接改变 Codex 的日常开发流程。",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_pipeline_writes_rule_fallback_without_api_key(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    write_inputs(data)

    with patch.dict("os.environ", {}, clear=True):
        edition = run_pipeline(
            data,
            ROOT / "config/martin-ai-coding.json",
            ROOT / "personas/martin-creator.md",
            requested_edition="morning",
            now=NOW,
        )

    assert edition["items"][0]["enrichment_mode"] == "rules_fallback"
    assert edition["items"][0]["why_it_matters"] == "这会直接改变 Codex 的日常开发流程。"
    for filename in (
        "creator-candidates.json",
        "creator-brief.json",
        "creator-editions.json",
        "edition-state.json",
        "creator-cache.json",
    ):
        assert (data / filename).is_file()
    assert not list(data.glob("*.tmp"))


def test_candidate_pool_is_capped_and_edition_keeps_product_cap(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    write_inputs(data, count=40)

    with patch.dict("os.environ", {"LLM_MAX_CALLS_PER_RUN": "0"}, clear=True):
        edition = run_pipeline(
            data,
            ROOT / "config/martin-ai-coding.json",
            ROOT / "personas/martin-creator.md",
            requested_edition="morning",
            now=NOW,
        )

    candidates = json.loads((data / "creator-candidates.json").read_text(encoding="utf-8"))
    assert candidates["total_items"] <= 20
    assert edition["total_items"] == 6
    assert all(item["primary_entity"] == "codex" for item in edition["items"])
    assert "dedup_meta" in candidates


def test_pipeline_deduplicates_before_final_selection(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    stories = {
        "stories": [
            {
                "story_id": "media",
                "title": "Claude Code adds parallel agents",
                "url": "https://media.example/parallel-agents",
                "source": "Tech Media",
                "site_id": "curated_media",
                "latest_at": "2026-07-23T01:00:00Z",
                "score": 0.9,
            },
            {
                "story_id": "official",
                "title": "Anthropic releases parallel agents in Claude Code",
                "url": "https://anthropic.com/news/parallel-agents",
                "source": "Anthropic",
                "site_id": "official_ai",
                "latest_at": "2026-07-23T01:10:00Z",
                "score": 0.85,
            },
        ]
    }
    (data / "stories-merged.json").write_text(json.dumps(stories), encoding="utf-8")
    (data / "daily-brief.json").write_text(json.dumps({"items": []}), encoding="utf-8")
    with patch.dict("os.environ", {"LLM_MAX_CALLS_PER_RUN": "0"}, clear=True):
        edition = run_pipeline(
            data,
            ROOT / "config/martin-ai-coding.json",
            ROOT / "personas/martin-creator.md",
            requested_edition="morning",
            now=NOW,
        )
    assert len(edition["items"]) == 1
    assert edition["items"][0]["source_count"] == 2
    assert edition["items"][0]["source"] == "Anthropic"


def test_public_outputs_do_not_copy_unknown_private_fields(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    write_inputs(data)
    payload = json.loads((data / "stories-merged.json").read_text(encoding="utf-8"))
    payload["stories"][0]["private_cookie"] = "do-not-publish"
    payload["stories"][0]["primary_item"]["raw_html"] = "<secret>"
    (data / "stories-merged.json").write_text(json.dumps(payload), encoding="utf-8")

    with patch.dict("os.environ", {}, clear=True):
        run_pipeline(
            data,
            ROOT / "config/martin-ai-coding.json",
            ROOT / "personas/martin-creator.md",
            requested_edition="morning",
            now=NOW,
        )

    public_text = (data / "creator-brief.json").read_text(encoding="utf-8")
    assert "do-not-publish" not in public_text
    assert "<secret>" not in public_text
