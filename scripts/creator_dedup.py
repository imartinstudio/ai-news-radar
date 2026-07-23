from __future__ import annotations

import hashlib
import re
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_KEYS = {"ref", "source", "campaign", "from", "spm"}
GENERIC_WORDS = {
    "ai", "人工智能", "重磅", "全新", "最新", "正式", "功能", "消息",
    "announces", "announcement", "new", "official", "today", "update",
}
ACTION_TERMS = {
    "security": ("vulnerability", "sandbox escape", "attack", "security", "漏洞", "攻击", "安全", "修复漏洞"),
    "pricing": ("pricing", "price", "plan", "subscription", "降价", "涨价", "价格", "套餐"),
    "benchmark": ("benchmark", "leaderboard", "score", "评测", "榜单", "基准"),
    "open_source": ("open source", "weights", "开源", "权重"),
    "acquisition": ("acquire", "acquisition", "merger", "收购", "合并"),
    "policy": ("policy", "license", "terms", "规则", "许可", "条款"),
    "integration": ("integrates", "integration", "support for", "接入", "集成", "支持"),
    "release": ("launch", "release", "introduce", "adds", "add ", "发布", "上线", "推出"),
    "update": ("upgrade", "improve", "更新", "升级", "改进"),
}
ACTION_ORDER = (
    "security", "pricing", "benchmark", "open_source", "acquisition",
    "policy", "integration", "release", "update",
)
EVENT_ALIASES = {
    "parallel": "parallel-agents",
    "agents": "parallel-agents",
    "并行": "parallel-agents",
    "代理": "parallel-agents",
}
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._+-]*|[\u4e00-\u9fff]{1,}", re.IGNORECASE)


def normalize_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = []
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_KEYS:
            continue
        query.append((key, val))
    query.sort()
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def normalize_title(value: str) -> str:
    text = str(value or "").lower()
    text = text.replace("claude-code", "claude code")
    text = re.sub(r"[|｜:：—–_]+", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff.+# ]+", " ", text)
    return " ".join(text.split())


def _expand_tokens(raw_tokens: list[str]) -> list[str]:
    tokens: list[str] = []
    for token in raw_tokens:
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) >= 2:
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
        else:
            tokens.append(token)
    return tokens


def title_keywords(value: str) -> frozenset[str]:
    tokens = _expand_tokens(TOKEN_RE.findall(normalize_title(value)))
    return frozenset(token for token in tokens if token not in GENERIC_WORDS and len(token) > 1)


def classify_action(item: dict) -> str:
    text = normalize_title(
        " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("summary_zh") or ""),
                str(item.get("recommend_reason_zh") or ""),
            ]
        )
    )
    for bucket in ACTION_ORDER:
        if any(term in text for term in ACTION_TERMS[bucket]):
            return bucket
    return "other"


def event_object_keywords(item: dict) -> tuple[str, ...]:
    entity = str(item.get("primary_entity") or "unknown")
    action = classify_action(item)
    ignored = set(title_keywords(entity))
    ignored.update(title_keywords(action))
    for terms in ACTION_TERMS.values():
        for term in terms:
            ignored.update(title_keywords(term))
    words = title_keywords(str(item.get("title") or "")) - ignored
    mapped = {EVENT_ALIASES.get(word, word) for word in words}
    canonical_values = set(EVENT_ALIASES.values())
    canonical = sorted(word for word in mapped if word in canonical_values)
    if canonical:
        return tuple(canonical[:8])
    return tuple(sorted(mapped)[:8])


def build_creator_event_id(item: dict) -> str:
    entity = str(item.get("primary_entity") or "unknown")
    action = classify_action(item)
    payload = "|".join([entity, action, *event_object_keywords(item)])
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"creator-{digest}"


def parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def jaccard_similarity(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def shared_keyword_count(left: dict, right: dict) -> int:
    return len(title_keywords(left.get("title", "")) & title_keywords(right.get("title", "")))


def within_time_window(left: dict, right: dict, hours: int) -> bool:
    left_at = parse_datetime(left.get("latest_at", ""))
    right_at = parse_datetime(right.get("latest_at", ""))
    if left_at is None or right_at is None:
        return False
    return abs((left_at - right_at).total_seconds()) <= hours * 3600


def are_duplicate_events(left: dict, right: dict, profile: dict) -> bool:
    left_url = normalize_url(left.get("url", ""))
    right_url = normalize_url(right.get("url", ""))
    if left_url and left_url == right_url:
        return True

    if str(left.get("primary_entity") or "") != str(right.get("primary_entity") or ""):
        return False
    if classify_action(left) != classify_action(right):
        return False

    config = profile["dedup"]
    if not within_time_window(left, right, int(config["time_window_hours"])):
        return False

    left_words = title_keywords(left.get("title", ""))
    right_words = title_keywords(right.get("title", ""))
    shared = len(left_words & right_words)
    jaccard = jaccard_similarity(left_words, right_words)
    sequence = SequenceMatcher(
        None,
        normalize_title(left.get("title", "")),
        normalize_title(right.get("title", "")),
    ).ratio()
    same_event_id = build_creator_event_id(left) == build_creator_event_id(right)

    if same_event_id and shared >= int(config["min_shared_keywords"]):
        return True
    if jaccard >= float(config["jaccard_threshold"]):
        return True
    return sequence >= float(config["sequence_threshold"]) and shared >= int(config["min_shared_keywords"])


def source_tier(item: dict, profile: dict) -> float:
    site_id = str(item.get("site_id") or item.get("primary_item", {}).get("site_id") or "")
    return float(profile.get("source_tiers", {}).get(site_id, 0.0))


def is_official(item: dict, profile: dict) -> bool:
    site_id = str(item.get("site_id") or item.get("primary_item", {}).get("site_id") or "")
    source_text = " ".join(
        [str(item.get("source") or ""), str(item.get("source_name") or "")]
    ).lower()
    return site_id == "official_ai" or any(
        pattern in source_text for pattern in profile.get("official_source_patterns", [])
    )


def source_rank(item: dict, profile: dict) -> tuple[int, float, float, str]:
    return (
        1 if is_official(item, profile) else 0,
        source_tier(item, profile),
        float(item.get("creator_score") or 0),
        str(item.get("latest_at") or ""),
    )


def public_source(item: dict, profile: dict) -> dict:
    return {
        "story_id": str(item.get("story_id") or ""),
        "title": str(item.get("title") or ""),
        "url": str(item.get("url") or item.get("primary_url") or ""),
        "source": str(item.get("source") or item.get("source_name") or ""),
        "site_id": str(item.get("site_id") or ""),
        "official": is_official(item, profile),
    }


def merge_duplicate_group(items: list[dict], profile: dict) -> dict:
    ordered = sorted(items, key=lambda item: source_rank(item, profile), reverse=True)
    primary = dict(ordered[0])
    sources = []
    seen_urls = set()
    for item in ordered:
        source = public_source(item, profile)
        normalized = normalize_url(source["url"])
        key = normalized or f"{source['source']}|{source['title']}"
        if key in seen_urls:
            continue
        seen_urls.add(key)
        sources.append(source)

    story_ids = []
    for item in ordered:
        story_id = str(item.get("story_id") or "")
        if story_id and story_id not in story_ids:
            story_ids.append(story_id)
    source_names = []
    for source in sources:
        if source["source"] and source["source"] not in source_names:
            source_names.append(source["source"])

    primary["creator_event_id"] = build_creator_event_id(primary)
    primary["merged_story_ids"] = story_ids
    primary["sources"] = sources
    primary["source_names"] = source_names
    primary["source_count"] = len(sources)
    primary["verification_status"] = (
        "confirmed"
        if any(source["official"] for source in sources) or len(sources) >= 2
        else str(primary.get("verification_status") or "single_source")
    )
    primary["creator_score"] = max(float(item.get("creator_score") or 0) for item in ordered)
    return primary


def deduplicate_candidates(items: list[dict], profile: dict) -> tuple[list[dict], dict]:
    if not profile.get("dedup", {}).get("enabled", True):
        rows = [dict(item, creator_event_id=build_creator_event_id(item)) for item in items]
        return rows, {
            "secondary_dedup_merge_count": 0,
            "secondary_dedup_source_count": len(rows),
        }

    groups: list[list[dict]] = []
    for item in sorted(items, key=lambda row: float(row.get("creator_score") or 0), reverse=True):
        for group in groups:
            if any(are_duplicate_events(item, member, profile) for member in group):
                group.append(item)
                break
        else:
            groups.append([item])

    merged = [merge_duplicate_group(group, profile) for group in groups]
    merged.sort(key=lambda row: float(row.get("creator_score") or 0), reverse=True)
    return merged, {
        "secondary_dedup_merge_count": sum(1 for group in groups if len(group) > 1),
        "secondary_dedup_source_count": sum(len(group) for group in groups),
    }
