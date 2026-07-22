from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

UTC = timezone.utc
VALID_EDITION_KINDS = {"morning", "evening"}


def _iso(value: datetime) -> str:
    current = value if value.tzinfo else value.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def resolve_edition_kind(now: datetime, timezone_name: str, requested: str) -> str:
    choice = str(requested or "auto").strip().lower()
    if choice in VALID_EDITION_KINDS:
        return choice
    if choice != "auto":
        raise ValueError("edition_kind")
    current = now if now.tzinfo else now.replace(tzinfo=UTC)
    local = current.astimezone(ZoneInfo(timezone_name))
    return "morning" if local.hour < 14 else "evening"


def story_fingerprint(item: dict[str, Any]) -> str:
    try:
        source_count = int(item.get("source_count") or 1)
    except (TypeError, ValueError):
        source_count = 1
    title = " ".join(str(item.get("title") or "").lower().split())
    return "|".join(
        [
            str(item.get("verification_status") or ""),
            str(source_count),
            title,
            str(item.get("latest_at") or ""),
        ]
    )


def _change_type(item: dict[str, Any], previous: dict[str, Any] | None) -> str | None:
    if previous is None:
        return "new"
    old_status = str(previous.get("last_status") or "")
    new_status = str(item.get("verification_status") or "")
    if old_status in {"early_signal", "rumor", "single_source"} and new_status == "confirmed":
        return "confirmed"
    if previous.get("last_fingerprint") != story_fingerprint(item):
        return "updated"
    return None


def _prune_state(state: dict[str, Any], now: datetime, days: int = 30) -> dict[str, Any]:
    cutoff = (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(UTC) - timedelta(days=days)
    stories = state.get("stories") if isinstance(state.get("stories"), dict) else {}
    kept: dict[str, Any] = {}
    for story_id, entry in stories.items():
        if not isinstance(entry, dict):
            continue
        sent_at = _parse_datetime(entry.get("last_sent_at"))
        if sent_at is None or sent_at >= cutoff:
            kept[str(story_id)] = entry
    state["stories"] = kept
    return state


def build_edition(
    candidates: list[dict[str, Any]],
    state: dict[str, Any],
    profile: dict[str, Any],
    now: datetime,
    kind: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    edition_kind = resolve_edition_kind(now, str(profile.get("timezone") or "Asia/Shanghai"), kind)
    current = now if now.tzinfo else now.replace(tzinfo=UTC)
    local = current.astimezone(ZoneInfo(str(profile.get("timezone") or "Asia/Shanghai")))
    generated_at = _iso(current)
    edition_id = f"{local.date().isoformat()}-{edition_kind}"
    max_items = int(profile["edition"]["max_items"])

    new_state = deepcopy(state) if isinstance(state, dict) else {}
    new_state.setdefault("version", 1)
    new_state.setdefault("stories", {})
    new_state = _prune_state(new_state, current)

    changed: list[dict[str, Any]] = []
    for candidate in candidates:
        story_id = str(candidate.get("story_id") or "").strip()
        if not story_id:
            continue
        previous = new_state["stories"].get(story_id)
        change = _change_type(candidate, previous if isinstance(previous, dict) else None)
        if change is None:
            continue
        item = dict(candidate)
        item["change_type"] = change
        changed.append(item)

    items = changed[:max_items]
    for item in items:
        story_id = str(item["story_id"])
        new_state["stories"][story_id] = {
            "last_fingerprint": story_fingerprint(item),
            "last_status": str(item.get("verification_status") or ""),
            "last_sent_at": generated_at,
            "last_edition_id": edition_id,
        }
    new_state["updated_at"] = generated_at

    summary = {
        "confirmed": sum(item.get("verification_status") == "confirmed" for item in items),
        "single_source": sum(item.get("verification_status") == "single_source" for item in items),
        "early_signal": sum(item.get("verification_status") == "early_signal" for item in items),
        "rumor": sum(item.get("verification_status") == "rumor" for item in items),
        "new": sum(item.get("change_type") == "new" for item in items),
        "updated": sum(item.get("change_type") == "updated" for item in items),
        "confirmed_updates": sum(item.get("change_type") == "confirmed" for item in items),
    }
    edition = {
        "edition_id": edition_id,
        "edition_kind": edition_kind,
        "generated_at": generated_at,
        "timezone": str(profile.get("timezone") or "Asia/Shanghai"),
        "total_items": len(items),
        "summary": summary,
        "items": items,
    }
    return edition, new_state


def append_edition_history(history: dict[str, Any], edition: dict[str, Any], limit: int) -> dict[str, Any]:
    output = deepcopy(history) if isinstance(history, dict) else {}
    existing = output.get("editions") if isinstance(output.get("editions"), list) else []
    edition_id = str(edition.get("edition_id") or "")
    remaining = [item for item in existing if isinstance(item, dict) and str(item.get("edition_id") or "") != edition_id]
    output["version"] = 1
    output["generated_at"] = edition.get("generated_at")
    output["editions"] = [deepcopy(edition), *remaining][: max(1, int(limit))]
    output["total_editions"] = len(output["editions"])
    return output
