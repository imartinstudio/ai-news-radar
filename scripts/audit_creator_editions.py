from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return default


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _ordered_counts(counter: Counter[str]) -> dict[str, int]:
    return {key: count for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))}


def _edition_items(history: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    editions = history.get("editions") if isinstance(history, dict) else []
    valid_editions = [edition for edition in editions if isinstance(edition, dict)] if isinstance(editions, list) else []
    items: list[dict[str, Any]] = []
    for edition in valid_editions:
        rows = edition.get("items")
        if isinstance(rows, list):
            items.extend(item for item in rows if isinstance(item, dict))
    return valid_editions, items


def calculate_metrics(history: dict[str, Any], feedback: dict[str, Any]) -> dict[str, Any]:
    editions, items = _edition_items(history)
    feedback_items = feedback.get("items") if isinstance(feedback, dict) else {}
    if not isinstance(feedback_items, dict):
        feedback_items = {}

    total_items = len(items)
    story_ids = [str(item.get("story_id") or "") for item in items if item.get("story_id")]
    duplicate_displays = len(story_ids) - len(set(story_ids))
    confirmed_count = sum(item.get("verification_status") == "confirmed" for item in items)
    early_signal_count = sum(item.get("verification_status") == "early_signal" for item in items)
    fallback_count = sum(item.get("enrichment_mode") == "rules_fallback" for item in items)
    noise_displays = sum(
        bool(feedback_items.get(str(item.get("story_id") or ""), {}).get("noise"))
        for item in items
        if isinstance(feedback_items.get(str(item.get("story_id") or ""), {}), dict)
    )
    published_ids = {
        str(story_id)
        for story_id, record in feedback_items.items()
        if isinstance(record, dict) and record.get("published")
    }

    sources = Counter(
        str(item.get("source") or item.get("source_name") or "unknown")
        for item in items
    )
    entities = Counter(
        str(item.get("primary_entity") or "unclassified")
        for item in items
    )

    merge_count = sum(
        int((edition.get("dedup_meta") or {}).get("secondary_dedup_merge_count") or 0)
        for edition in editions
    )
    source_count = sum(
        int((edition.get("dedup_meta") or {}).get("secondary_dedup_source_count") or 0)
        for edition in editions
    )

    event_occurrences: dict[str, int] = {}
    for edition in editions:
        seen_in_edition: set[str] = set()
        for item in edition.get("items", []):
            if not isinstance(item, dict):
                continue
            event_id = str(item.get("creator_event_id") or item.get("story_id") or "")
            if event_id and event_id in seen_in_edition:
                event_occurrences[event_id] = event_occurrences.get(event_id, 0) + 1
            if event_id:
                seen_in_edition.add(event_id)

    total_displayed = sum(
        len([item for item in edition.get("items", []) if isinstance(item, dict)])
        for edition in editions
    )
    suspected_duplicates = sum(event_occurrences.values())

    return {
        "editions_count": len(editions),
        "total_item_displays": total_items,
        "average_items_per_edition": round(total_items / len(editions), 2) if editions else 0.0,
        "confirmed_ratio": _ratio(confirmed_count, total_items),
        "early_signal_ratio": _ratio(early_signal_count, total_items),
        "duplicate_display_rate": _ratio(duplicate_displays, total_items),
        "noise_feedback_rate": _ratio(noise_displays, total_items),
        "content_conversion_count": len(published_ids),
        "llm_fallback_ratio": _ratio(fallback_count, total_items),
        "source_distribution": _ordered_counts(sources),
        "entity_distribution": _ordered_counts(entities),
        "secondary_dedup_merge_count": merge_count,
        "secondary_dedup_source_count": source_count,
        "suspected_duplicate_rate": (
            round(suspected_duplicates / total_displayed, 4) if total_displayed else 0.0
        ),
    }


def _feedback_summary(feedback: dict[str, Any]) -> dict[str, Any]:
    items = feedback.get("items") if isinstance(feedback, dict) else {}
    if not isinstance(items, dict):
        items = {}
    valid = [record for record in items.values() if isinstance(record, dict)]
    platforms = Counter(
        str(record.get("platform"))
        for record in valid
        if record.get("published") and record.get("platform")
    )
    return {
        "reviewed_count": len(valid),
        "useful_count": sum(bool(record.get("useful")) for record in valid),
        "noise_count": sum(bool(record.get("noise")) for record in valid),
        "published_count": sum(bool(record.get("published")) for record in valid),
        "published_platforms": _ordered_counts(platforms),
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_audit(data_dir: Path, feedback_path: Path, output_path: Path) -> dict[str, Any]:
    history = _load_json(data_dir / "creator-editions.json", {"editions": []})
    feedback = _load_json(feedback_path, {"version": 1, "items": {}})
    report = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "history_generated_at": history.get("generated_at") if isinstance(history, dict) else None,
        "metrics": calculate_metrics(history if isinstance(history, dict) else {}, feedback if isinstance(feedback, dict) else {}),
        "feedback_summary": _feedback_summary(feedback if isinstance(feedback, dict) else {}),
    }
    _write_json_atomic(output_path, report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit creator edition quality")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--feedback", default="config/creator-feedback.json")
    parser.add_argument("--output", default="reports/creator-quality/latest.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_audit(Path(args.data_dir), Path(args.feedback), Path(args.output))
    metrics = report["metrics"]
    print(
        "creator-audit: editions={editions} avg_items={average} duplicate={duplicate:.1%} noise={noise:.1%} published={published}".format(
            editions=metrics["editions_count"],
            average=metrics["average_items_per_edition"],
            duplicate=metrics["duplicate_display_rate"],
            noise=metrics["noise_feedback_rate"],
            published=metrics["content_conversion_count"],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
