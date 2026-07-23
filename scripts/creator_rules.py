from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from scripts.creator_profile import normalized_aliases

UTC = timezone.utc


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


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


def _contains_phrase(text: str, phrase: str) -> bool:
    phrase = " ".join(str(phrase).lower().split())
    if not phrase:
        return False
    if re.search(r"[a-z0-9]", phrase):
        pattern = rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])"
        return re.search(pattern, text, flags=re.IGNORECASE) is not None
    return phrase in text


def _story_text(story: dict[str, Any]) -> str:
    parts = [story.get("title"), story.get("source"), story.get("source_name")]
    primary = story.get("primary_item")
    if isinstance(primary, dict):
        parts.extend(
            [
                primary.get("title"),
                primary.get("summary"),
                primary.get("recommend_reason_zh"),
                primary.get("source"),
                primary.get("source_name"),
            ]
        )
    return " ".join(" ".join(str(part or "").split()) for part in parts if part).lower()


def _site_id(story: dict[str, Any]) -> str:
    direct = str(story.get("site_id") or "").strip()
    if direct:
        return direct
    primary = story.get("primary_item")
    if isinstance(primary, dict):
        nested = str(primary.get("site_id") or "").strip()
        if nested:
            return nested
    for key in ("sources", "items"):
        values = story.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, dict) and value.get("site_id"):
                return str(value["site_id"]).strip()
    return ""


def _source_text(story: dict[str, Any]) -> str:
    parts = [story.get("source"), story.get("source_name")]
    for key in ("sources", "items"):
        values = story.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict):
                    parts.extend([value.get("source"), value.get("source_name")])
    return " ".join(str(part or "") for part in parts).lower()


def _primary_entity(text: str, profile: dict[str, Any]) -> tuple[str | None, str, float]:
    for alias, entity_id, bucket, weight in normalized_aliases(profile):
        if _contains_phrase(text, alias):
            return entity_id, bucket, _clamp(weight)
    return None, "general_ai", 0.0


def _has_any(text: str, terms: list[str]) -> bool:
    return any(_contains_phrase(text, term) for term in terms)


def _count_terms(text: str, terms: list[str]) -> int:
    return sum(1 for term in terms if _contains_phrase(text, term))


def _freshness_score(story: dict[str, Any], now: datetime) -> float:
    timestamp = _parse_datetime(story.get("latest_at") or story.get("published_at"))
    if timestamp is None:
        return 0.3
    current = now if now.tzinfo else now.replace(tzinfo=UTC)
    hours = max(0.0, (current.astimezone(UTC) - timestamp).total_seconds() / 3600)
    if hours <= 6:
        return 1.0
    if hours <= 24:
        return 1.0 - ((hours - 6) / 18) * 0.45
    if hours <= 48:
        return 0.55 - ((hours - 24) / 24) * 0.55
    return 0.0


def classify_verification(story: dict[str, Any], profile: dict[str, Any]) -> str:
    try:
        source_count = int(story.get("source_count") or 1)
    except (TypeError, ValueError):
        source_count = 1
    site_id = _site_id(story)
    source_text = _source_text(story)
    official = site_id == "official_ai" or any(
        str(pattern).lower() in source_text for pattern in profile.get("official_source_patterns", [])
    )
    if official or source_count >= 2:
        return "confirmed"
    if site_id in set(profile.get("early_signal_site_ids", [])):
        try:
            score = float(story.get("score") or story.get("importance_score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        return "early_signal" if score >= 0.58 else "rumor"
    return "single_source"


def score_story(story: dict[str, Any], profile: dict[str, Any], now: datetime) -> dict[str, Any]:
    text = _story_text(story)
    entity_id, entity_bucket, entity_weight = _primary_entity(text, profile)
    ai_coding_hit = _has_any(text, list(profile.get("ai_coding_terms", [])))
    general_ai_hit = _has_any(text, list(profile.get("general_ai_terms", [])))
    negative_hits = _count_terms(text, list(profile.get("negative_terms", [])))
    impact_hits = _count_terms(text, list(profile.get("high_impact_terms", [])))

    try:
        upstream_score = _clamp(float(story.get("score") or story.get("importance_score") or 0))
    except (TypeError, ValueError):
        upstream_score = 0.0

    if entity_id and entity_bucket == "ai_coding":
        relevance = max(0.88, entity_weight)
        bucket = "ai_coding"
    elif ai_coding_hit:
        relevance = 0.88
        bucket = "ai_coding"
    elif entity_id:
        relevance = max(0.62, entity_weight * 0.85)
        bucket = entity_bucket
    elif general_ai_hit:
        relevance = 0.65
        bucket = "general_ai"
    else:
        relevance = min(0.55, 0.2 + upstream_score * 0.35)
        bucket = "general_ai"
    if negative_hits:
        relevance *= max(0.25, 1.0 - 0.45 * negative_hits)

    site_id = _site_id(story)
    source_text = _source_text(story)
    source_tier = float(profile.get("source_tiers", {}).get(site_id, 0.5))
    if site_id == "official_ai" or any(
        str(pattern).lower() in source_text for pattern in profile.get("official_source_patterns", [])
    ):
        source_tier = 1.0
    source_score = _clamp(source_tier)

    freshness = _freshness_score(story, now)

    impact = 0.25
    if impact_hits:
        impact = min(1.0, 0.5 + 0.13 * impact_hits)
    if bucket == "ai_coding":
        impact += 0.18
    if negative_hits:
        impact -= min(0.7, 0.45 * negative_hits)
    impact = _clamp(impact)

    novelty = 0.55
    if impact_hits:
        novelty += 0.2
    if entity_id:
        novelty += 0.1
    if negative_hits:
        novelty -= min(0.5, 0.3 * negative_hits)
    novelty = _clamp(novelty)

    creator_hot = story.get("creator_hot_score")
    if creator_hot is not None:
        try:
            heat_value = float(creator_hot)
            heat = _clamp(heat_value / 100 if heat_value > 1 else heat_value)
        except (TypeError, ValueError):
            heat = 0.0
    else:
        try:
            source_count = max(1, int(story.get("source_count") or 1))
        except (TypeError, ValueError):
            source_count = 1
        heat = _clamp(upstream_score * 0.35 + min(0.45, source_count * 0.15))

    breakdown = {
        "relevance": relevance,
        "freshness": freshness,
        "source": source_score,
        "impact": impact,
        "novelty": novelty,
        "heat": heat,
    }
    weights = profile["weights"]
    total = sum(breakdown[key] * float(weights[key]) for key in breakdown)
    if negative_hits:
        total -= min(20.0, negative_hits * 10.0)
    total = max(0.0, min(100.0, total))

    reasons: list[str] = []
    if entity_id:
        reasons.append(f"entity:{entity_id}")
    if ai_coding_hit:
        reasons.append("ai_coding_terms")
    if impact_hits:
        reasons.append("workflow_impact")
    if source_score >= 0.9:
        reasons.append("official_or_tier0_source")
    if negative_hits:
        reasons.append("negative_topic_penalty")

    enriched = dict(story)
    enriched.update(
        {
            "creator_score": round(total, 1),
            "creator_breakdown": {key: round(value, 4) for key, value in breakdown.items()},
            "creator_bucket": bucket,
            "primary_entity": entity_id,
            "verification_status": classify_verification(story, profile),
            "creator_reasons": reasons,
        }
    )
    return enriched


def rank_candidates(
    stories: list[dict[str, Any]],
    profile: dict[str, Any],
    now: datetime,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    threshold = float(profile["thresholds"]["signal"])
    ranked = [score_story(story, profile, now) for story in stories]
    ranked = [item for item in ranked if float(item.get("creator_score") or 0) >= threshold]
    ranked.sort(
        key=lambda item: (
            float(item.get("creator_score") or 0),
            _parse_datetime(item.get("latest_at")) or datetime.min.replace(tzinfo=UTC),
            str(item.get("story_id") or ""),
        ),
        reverse=True,
    )
    if limit is None:
        return ranked
    return ranked[: max(0, int(limit))]


def select_scored_candidates(
    items: list[dict[str, Any]],
    profile: dict[str, Any],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    edition = profile["edition"]
    thresholds = profile["thresholds"]
    max_items = int(limit if limit is not None else edition["max_items"])
    max_items = max(0, max_items)
    if max_items == 0:
        return []

    candidate_limit = int(edition.get("candidate_limit") or max_items)
    product_limit = max(1, int(max_items * float(edition["product_cap_ratio"])))
    coding_target = max(0, min(max_items, round(max_items * float(edition["ai_coding_ratio"]))))

    eligible = [
        item
        for item in items
        if float(item.get("creator_score") or 0) >= float(thresholds["signal"])
    ]
    eligible.sort(
        key=lambda item: (
            float(item.get("creator_score") or 0),
            str(item.get("latest_at") or ""),
        ),
        reverse=True,
    )
    eligible = eligible[:candidate_limit]

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    counts: dict[str, int] = {}

    def append_allowed(item: dict[str, Any]) -> bool:
        story_id = str(item.get("story_id") or "")
        if not story_id or story_id in selected_ids:
            return False
        entity = str(item.get("primary_entity") or item.get("creator_event_id") or "unknown")
        if counts.get(entity, 0) >= product_limit:
            return False
        selected.append(item)
        selected_ids.add(story_id)
        counts[entity] = counts.get(entity, 0) + 1
        return True

    for item in eligible:
        if len(selected) >= coding_target:
            break
        if item.get("creator_bucket") == "ai_coding":
            append_allowed(item)

    for item in eligible:
        if len(selected) >= max_items:
            break
        if str(item.get("story_id") or "") in selected_ids:
            continue
        if item.get("creator_bucket") == "general_ai":
            append_allowed(item)

    for item in eligible:
        if len(selected) >= max_items:
            break
        if str(item.get("story_id") or "") not in selected_ids:
            append_allowed(item)

    return selected


def select_candidates(
    stories: list[dict[str, Any]],
    profile: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    scored = [score_story(story, profile, now) for story in stories]
    return select_scored_candidates(scored, profile)
