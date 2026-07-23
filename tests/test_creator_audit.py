import json
from pathlib import Path

from scripts.audit_creator_editions import calculate_metrics, run_audit


def test_metrics_count_duplicates_noise_and_content_conversion():
    history = {
        "editions": [
            {
                "edition_id": "d1",
                "items": [
                    {"story_id": "a", "verification_status": "confirmed", "source": "OpenAI", "primary_entity": "codex", "enrichment_mode": "llm"},
                    {"story_id": "b", "verification_status": "early_signal", "source": "HN", "primary_entity": "cursor", "enrichment_mode": "rules_fallback"},
                ],
            },
            {
                "edition_id": "d2",
                "items": [
                    {"story_id": "a", "verification_status": "confirmed", "source": "OpenAI", "primary_entity": "codex", "enrichment_mode": "cache"},
                    {"story_id": "c", "verification_status": "confirmed", "source": "Anthropic", "primary_entity": "claude-code", "enrichment_mode": "llm"},
                ],
            },
        ]
    }
    feedback = {"items": {"b": {"noise": True}, "c": {"published": True}}}

    metrics = calculate_metrics(history, feedback)

    assert metrics["editions_count"] == 2
    assert metrics["average_items_per_edition"] == 2.0
    assert metrics["duplicate_display_rate"] == 0.25
    assert metrics["noise_feedback_rate"] == 0.25
    assert metrics["content_conversion_count"] == 1
    assert metrics["confirmed_ratio"] == 0.75
    assert metrics["early_signal_ratio"] == 0.25
    assert metrics["llm_fallback_ratio"] == 0.25
    assert metrics["source_distribution"] == {"OpenAI": 2, "Anthropic": 1, "HN": 1}
    assert metrics["entity_distribution"] == {"codex": 2, "claude-code": 1, "cursor": 1}


def test_audit_report_never_copies_feedback_notes(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    history = {"generated_at": "2026-07-22T00:00:00Z", "editions": [{"edition_id": "d1", "items": [{"story_id": "a"}]}]}
    feedback = {"version": 1, "items": {"a": {"useful": True, "notes": "private editorial note"}}}
    (data / "creator-editions.json").write_text(json.dumps(history), encoding="utf-8")
    feedback_path = tmp_path / "feedback.json"
    feedback_path.write_text(json.dumps(feedback), encoding="utf-8")
    output = tmp_path / "reports" / "latest.json"

    report = run_audit(data, feedback_path, output)

    assert output.is_file()
    assert "private editorial note" not in output.read_text(encoding="utf-8")
    assert "metrics" in report
    assert report["feedback_summary"]["useful_count"] == 1


def test_audit_reports_secondary_dedup_metrics():
    history = {
        "editions": [
            {
                "edition_id": "d1",
                "dedup_meta": {
                    "secondary_dedup_merge_count": 2,
                    "secondary_dedup_source_count": 12,
                },
                "items": [
                    {"creator_event_id": "e1", "source_count": 2},
                    {"creator_event_id": "e2", "source_count": 1},
                ],
            }
        ]
    }
    metrics = calculate_metrics(history, {"items": {}})
    assert metrics["secondary_dedup_merge_count"] == 2
    assert metrics["secondary_dedup_source_count"] == 12
    assert metrics["suspected_duplicate_rate"] == 0.0
