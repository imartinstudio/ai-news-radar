from __future__ import annotations

import hashlib
import re
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
    "release": ("launch", "release", "introduce", "发布", "上线", "推出"),
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
