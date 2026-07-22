from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:  # direct `python scripts/creator_pipeline.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.creator_profile import load_profile
from scripts.creator_rules import rank_candidates
from scripts.edition import append_edition_history, build_edition
from scripts.llm_provider import LLMSettings, OpenAICompatibleProvider

UTC = timezone.utc
CACHE_VERSION = 1
CACHE_MAX_AGE_DAYS = 21
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
ALLOWED_PLATFORMS = {"x", "xiaohongshu", "wechat"}

PUBLIC_STORY_FIELDS = (
    "story_id",
    "title",
    "url",
    "primary_url",
    "source",
    "source_name",
    "source_count",
    "source_names",
    "score",
    "importance",
    "importance_score",
    "importance_label",
    "importance_breakdown",
    "category",
    "reasons",
    "earliest_at",
    "latest_at",
    "persona_id",
    "persona_score",
    "persona_review",
    "creator_score",
    "creator_breakdown",
    "creator_bucket",
    "primary_entity",
    "verification_status",
    "creator_reasons",
    "change_type",
)
PUBLIC_SOURCE_FIELDS = (
    "id",
    "title",
    "title_zh",
    "title_en",
    "title_original",
    "summary",
    "recommend_reason_zh",
    "url",
    "source",
    "source_name",
    "site_id",
    "published_at",
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


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


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return deepcopy(default)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_stories(data_dir: Path) -> list[dict[str, Any]]:
    merged = _load_json(data_dir / "stories-merged.json", {"stories": []})
    stories = [dict(item) for item in merged.get("stories", []) if isinstance(item, dict)] if isinstance(merged, dict) else []

    brief = _load_json(data_dir / "daily-brief.json", {"items": []})
    brief_items = brief.get("items", []) if isinstance(brief, dict) else []
    overlay = {
        str(item.get("story_id")): item
        for item in brief_items
        if isinstance(item, dict) and item.get("story_id")
    }
    for story in stories:
        extra = overlay.get(str(story.get("story_id") or ""))
        if not isinstance(extra, dict):
            continue
        for key in ("persona_id", "persona_score", "persona_review", "recommend_reason_zh"):
            if key in extra:
                story[key] = extra[key]
    return stories


def _clean_text(value: Any, limit: int) -> str:
    text = CONTROL_CHARS_RE.sub("", str(value or ""))
    text = " ".join(text.split()).strip()
    return text[:limit]


def _public_source(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    output = {key: value.get(key) for key in PUBLIC_SOURCE_FIELDS if key in value and value.get(key) is not None}
    return output or None


def public_story_record(item: dict[str, Any]) -> dict[str, Any]:
    output = {key: deepcopy(item.get(key)) for key in PUBLIC_STORY_FIELDS if key in item and item.get(key) is not None}
    primary = _public_source(item.get("primary_item"))
    if primary:
        output["primary_item"] = primary
    sources = item.get("sources")
    if isinstance(sources, list):
        cleaned = [record for record in (_public_source(source) for source in sources) if record]
        if cleaned:
            output["sources"] = cleaned
    return output


def fallback_enrichment(item: dict[str, Any]) -> dict[str, Any]:
    primary = item.get("primary_item") if isinstance(item.get("primary_item"), dict) else {}
    summary = _clean_text(
        primary.get("summary")
        or primary.get("recommend_reason_zh")
        or item.get("recommend_reason_zh")
        or item.get("title"),
        90,
    )
    why = _clean_text(
        item.get("persona_review")
        or "该信息可能影响开发工具选择、工作流或模型能力判断。",
        70,
    )
    entity = _clean_text(item.get("primary_entity") or "AI Coding", 30)
    return {
        "summary_zh": summary,
        "why_it_matters": why,
        "angles": [
            {
                "platform": "x",
                "title": _clean_text(f"{entity} 这次更新真正改变了什么", 60),
                "angle": "先核对原始发布，再结合自己的开发体验给出判断。",
                "needs_hands_on": True,
                "risk": "未亲测前不要把官方描述写成实际效果。",
            }
        ],
        "enrichment_mode": "rules_fallback",
    }


def sanitize_enrichment(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    summary = _clean_text(payload.get("summary_zh"), 90)
    why = _clean_text(payload.get("why_it_matters"), 70)
    if not summary or not why:
        return None
    raw_angles = payload.get("angles")
    if not isinstance(raw_angles, list):
        return None
    angles: list[dict[str, Any]] = []
    for raw in raw_angles[:3]:
        if not isinstance(raw, dict):
            continue
        platform = _clean_text(raw.get("platform"), 20).lower()
        title = _clean_text(raw.get("title"), 60)
        angle = _clean_text(raw.get("angle"), 120)
        if platform not in ALLOWED_PLATFORMS or not title or not angle:
            continue
        angles.append(
            {
                "platform": platform,
                "title": title,
                "angle": angle,
                "needs_hands_on": bool(raw.get("needs_hands_on")),
                "risk": _clean_text(raw.get("risk"), 100),
            }
        )
    return {"summary_zh": summary, "why_it_matters": why, "angles": angles}


def _load_persona_prompt(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    prompt = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            prompt = parts[2].strip()
    return prompt, hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def _cache_key(item: dict[str, Any], persona_sha8: str) -> str:
    raw = "|".join(
        [
            str(item.get("story_id") or ""),
            str(item.get("title") or ""),
            str(item.get("verification_status") or ""),
            persona_sha8,
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _load_cache(path: Path, now: datetime) -> dict[str, Any]:
    cache = _load_json(path, {"version": CACHE_VERSION, "entries": {}})
    if not isinstance(cache, dict) or cache.get("version") != CACHE_VERSION:
        cache = {"version": CACHE_VERSION, "entries": {}}
    entries = cache.get("entries") if isinstance(cache.get("entries"), dict) else {}
    cutoff = (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(UTC) - timedelta(days=CACHE_MAX_AGE_DAYS)
    kept: dict[str, Any] = {}
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        generated = _parse_datetime(entry.get("generated_at"))
        if generated is not None and generated >= cutoff and isinstance(entry.get("enrichment"), dict):
            kept[str(key)] = entry
    return {"version": CACHE_VERSION, "entries": kept}


def _llm_payload(item: dict[str, Any]) -> dict[str, Any]:
    record = public_story_record(item)
    return {
        key: record.get(key)
        for key in (
            "story_id",
            "title",
            "url",
            "source",
            "source_name",
            "source_count",
            "creator_score",
            "creator_bucket",
            "primary_entity",
            "verification_status",
            "change_type",
            "primary_item",
            "sources",
        )
        if record.get(key) is not None
    }


def _provider_meta(provider: Any) -> tuple[str, str, int]:
    settings = getattr(provider, "settings", None)
    provider_name = str(getattr(settings, "provider", "unknown"))
    model = str(getattr(settings, "model", "unknown"))
    calls_used = int(getattr(provider, "calls_used", 0) or 0)
    return provider_name, model, calls_used


def run_pipeline(
    data_dir: Path,
    profile_path: Path,
    persona_path: Path,
    *,
    requested_edition: str = "auto",
    now: datetime | None = None,
    provider: Any | None = None,
) -> dict[str, Any]:
    current = now or _utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    data_dir.mkdir(parents=True, exist_ok=True)

    profile = load_profile(profile_path)
    stories = load_stories(data_dir)
    candidate_limit = int(profile["edition"].get("candidate_limit") or 30)
    ranked = rank_candidates(stories, profile, current, limit=candidate_limit)

    state_path = data_dir / "edition-state.json"
    history_path = data_dir / "creator-editions.json"
    cache_path = data_dir / "creator-cache.json"
    state = _load_json(state_path, {"version": 1, "stories": {}})
    history = _load_json(history_path, {"version": 1, "editions": []})
    cache = _load_cache(cache_path, current)

    edition, next_state = build_edition(ranked, state, profile, current, requested_edition)
    prompt, persona_sha8 = _load_persona_prompt(persona_path)
    llm_provider = provider or OpenAICompatibleProvider(LLMSettings.from_env())

    enriched_items: list[dict[str, Any]] = []
    cache_hits = 0
    fallback_count = 0
    for raw_item in edition.get("items", []):
        item = dict(raw_item)
        key = _cache_key(item, persona_sha8)
        cached = cache["entries"].get(key)
        enrichment: dict[str, Any] | None = None
        if isinstance(cached, dict):
            enrichment = sanitize_enrichment(cached.get("enrichment"))
            if enrichment:
                enrichment["enrichment_mode"] = "cache"
                cache_hits += 1
        if enrichment is None:
            generated = llm_provider.complete_json(prompt, _llm_payload(item))
            enrichment = sanitize_enrichment(generated)
            if enrichment:
                enrichment["enrichment_mode"] = "llm"
                cache["entries"][key] = {
                    "generated_at": _iso(current),
                    "enrichment": {
                        "summary_zh": enrichment["summary_zh"],
                        "why_it_matters": enrichment["why_it_matters"],
                        "angles": deepcopy(enrichment["angles"]),
                    },
                }
            else:
                enrichment = fallback_enrichment(item)
                fallback_count += 1
        public_item = public_story_record(item)
        public_item.update(enrichment)
        enriched_items.append(public_item)

    edition["items"] = enriched_items
    edition["total_items"] = len(enriched_items)
    provider_name, model, calls_used = _provider_meta(llm_provider)
    edition["llm_meta"] = {
        "provider": provider_name,
        "model": model,
        "calls_used": calls_used,
        "cache_hits": cache_hits,
        "fallback_count": fallback_count,
    }

    candidate_payload = {
        "generated_at": _iso(current),
        "total_items": len(ranked),
        "items": [public_story_record(item) for item in ranked],
    }
    next_history = append_edition_history(
        history,
        edition,
        limit=int(profile["edition"].get("history_limit") or 60),
    )
    cache["updated_at"] = _iso(current)

    write_json_atomic(data_dir / "creator-candidates.json", candidate_payload)
    write_json_atomic(data_dir / "creator-brief.json", edition)
    write_json_atomic(history_path, next_history)
    write_json_atomic(state_path, next_state)
    write_json_atomic(cache_path, cache)
    return edition


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build personal AI Coding creator editions")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--profile", default="config/martin-ai-coding.json")
    parser.add_argument("--persona", default="personas/martin-creator.md")
    parser.add_argument("--edition", choices=("auto", "morning", "evening"), default="auto")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    edition = run_pipeline(
        Path(args.data_dir),
        Path(args.profile),
        Path(args.persona),
        requested_edition=args.edition,
    )
    print(
        "creator: edition={edition} items={items} calls={calls} fallback={fallback}".format(
            edition=edition.get("edition_id"),
            items=edition.get("total_items", 0),
            calls=edition.get("llm_meta", {}).get("calls_used", 0),
            fallback=edition.get("llm_meta", {}).get("fallback_count", 0),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
