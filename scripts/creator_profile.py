from __future__ import annotations

import json
from pathlib import Path

REQUIRED_WEIGHT_KEYS = {"relevance", "freshness", "source", "impact", "novelty", "heat"}


def validate_profile(profile: dict) -> None:
    if profile.get("version") != 1:
        raise ValueError("profile_version")

    edition = profile.get("edition") or {}
    if not 1 <= int(edition.get("min_items", 0)) <= int(edition.get("max_items", 0)) <= 20:
        raise ValueError("edition_item_range")

    candidate_limit = int(edition.get("candidate_limit", 0))
    max_items = int(edition.get("max_items", 0))
    if candidate_limit < max_items or candidate_limit > 100:
        raise ValueError("candidate_limit")

    if max_items != 20:
        raise ValueError("edition_max_items")

    ratio = float(edition.get("ai_coding_ratio", 0))
    if not 0.5 <= ratio <= 1.0:
        raise ValueError("ai_coding_ratio")

    product_cap = float(edition.get("product_cap_ratio", 0))
    if not 0.1 <= product_cap <= 1.0:
        raise ValueError("product_cap_ratio")

    dedup = profile.get("dedup") or {}
    if not isinstance(dedup.get("enabled"), bool):
        raise ValueError("dedup_enabled")
    if not 1 <= int(dedup.get("time_window_hours", 0)) <= 168:
        raise ValueError("dedup_time_window_hours")
    if not 0.0 <= float(dedup.get("jaccard_threshold", -1)) <= 1.0:
        raise ValueError("dedup_jaccard_threshold")
    if not 0.0 <= float(dedup.get("sequence_threshold", -1)) <= 1.0:
        raise ValueError("dedup_sequence_threshold")
    if not 1 <= int(dedup.get("min_shared_keywords", 0)) <= 10:
        raise ValueError("dedup_min_shared_keywords")

    weights = profile.get("weights") or {}
    if set(weights) != REQUIRED_WEIGHT_KEYS:
        raise ValueError("weight_keys")
    if sum(int(weights[key]) for key in REQUIRED_WEIGHT_KEYS) != 100:
        raise ValueError("weights_total")

    thresholds = profile.get("thresholds") or {}
    if not int(thresholds.get("focus", 0)) > int(thresholds.get("quick", 0)) > int(thresholds.get("signal", 0)):
        raise ValueError("threshold_order")

    entity_ids = [str(item.get("id") or "") for item in profile.get("entities", [])]
    if not all(entity_ids) or len(entity_ids) != len(set(entity_ids)):
        raise ValueError("entity_ids")


def load_profile(path: Path) -> dict:
    profile = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(profile, dict):
        raise ValueError("profile_shape")
    validate_profile(profile)
    return profile


def normalized_aliases(profile: dict) -> list[tuple[str, str, str, float]]:
    aliases: list[tuple[str, str, str, float]] = []
    for entity in profile.get("entities", []):
        entity_id = str(entity["id"])
        bucket = str(entity.get("bucket") or "ai_coding")
        weight = float(entity.get("weight") or 1.0)
        for alias in entity.get("aliases", []):
            value = " ".join(str(alias).lower().split())
            if value:
                aliases.append((value, entity_id, bucket, weight))
    return sorted(aliases, key=lambda item: len(item[0]), reverse=True)
