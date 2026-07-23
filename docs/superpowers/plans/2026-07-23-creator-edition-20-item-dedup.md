# Creator Edition 20-Item Dedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AI Coding 创作者日报从最多 12 条提升为最多 20 条，并在最终版次选择前增加确定性的二次事件去重，把同一事件的多个出处合并成一个“多源 N”记录。

**Architecture:** 保持上游 `scripts/update_news.py` 和 `data/stories-merged.json` 不变。创作者管线先对故事评分，再通过新增的 `scripts/creator_dedup.py` 做 URL 规范化、实体/动作/标题相似度判定与来源合并，随后执行 70/30 多样性选择、早晚版次状态判断和 LLM 增强。版次状态改用稳定的 `creator_event_id`，避免主来源升级时被当成新事件。

**Tech Stack:** Python 3.11、标准库 `urllib.parse` / `difflib` / `hashlib`、pytest 8.3、原生 HTML/CSS/JavaScript、GitHub Actions、Telegram Bot API。

## Global Constraints

- 每期最多 20 条，不为了凑数降低 `thresholds.signal`。
- 候选池最多 50 条；高质量候选不足时允许少于 20 条。
- AI Coding / 通用 AI 目标比例约 70% / 30%。
- 单一产品每期最多 30%，20 条版次中最多 6 条。
- LLM 单轮最大调用量默认 20；缓存命中不消耗调用额度。
- 二次去重仅处理创作者管线，不修改上游 `scripts/update_news.py`。
- 同一事件合并后优先官方来源；其余出处必须保存在 `sources[]`。
- 模糊去重要求核心实体相同、动作桶相同、时间差不超过 48 小时，并达到配置相似度阈值。
- 同一产品的不同功能、不同动作、漏洞披露与修复、官方发布与后续独立实测不得误合并。
- 早晚版状态优先使用 `creator_event_id`，新增官方来源时标记 `confirmed` 或 `updated`，不得标记成全新事件。
- 所有远程标题和来源名称在页面渲染时必须转义；来源 URL 仅允许 HTTP/HTTPS。
- 每个任务使用 TDD：失败测试 → 最小实现 → 回归测试 → Conventional Commit。

---

## File Structure

### Create

- `scripts/creator_dedup.py`：URL/标题规范化、动作识别、近重复判定、稳定事件 ID、来源合并。
- `tests/test_creator_dedup.py`：精确 URL、模糊事件、误合并边界和官方来源优先测试。
- `docs/superpowers/specs/2026-07-23-creator-edition-20-item-dedup-design.md`：已确认规格。
- `docs/superpowers/plans/2026-07-23-creator-edition-20-item-dedup.md`：本实施计划。

### Modify

- `config/martin-ai-coding.json`：20 条上限、50 条候选池、二次去重阈值。
- `scripts/creator_profile.py`：校验 `dedup` 配置和 20 条版次约束。
- `scripts/creator_rules.py`：拆出已评分候选选择函数，允许去重后再执行多样性选择。
- `scripts/creator_pipeline.py`：评分 → 二次去重 → 选择 → 版次 → LLM；写入去重指标和多源字段。
- `scripts/edition.py`：使用 `creator_event_id` 作为状态键和指纹主体。
- `scripts/llm_provider.py`：默认最大调用量改为 20。
- `scripts/telegram_publish.py`：显示“多源 N”。
- `creator/assets/app.js`：渲染可展开的来源列表。
- `creator/assets/styles.css`：多源按钮与来源列表样式。
- `scripts/audit_creator_editions.py`：增加二次去重指标。
- `.github/workflows/update-news.yml`：默认 `LLM_MAX_CALLS_PER_RUN` 改为 20。
- `docs/CREATOR_PIPELINE.md`：更新数量、去重规则、Variables 和验收说明。
- `README.md`：将“8–12 条”改为“最多 20 条，不硬凑”。
- 现有相关测试文件：更新旧的 12 条断言并加入集成契约。

---

### Task 1: 更新版次容量与去重配置契约

**Files:**
- Modify: `config/martin-ai-coding.json`
- Modify: `scripts/creator_profile.py`
- Modify: `tests/test_creator_profile.py`
- Modify: `tests/test_creator_docs_contract.py`

**Interfaces:**
- Consumes: `load_profile(path: Path) -> dict`
- Produces: 经过校验的 `profile["edition"]` 和 `profile["dedup"]`。

- [ ] **Step 1: 写配置失败测试**

在 `tests/test_creator_profile.py` 增加：

```python
from copy import deepcopy

import pytest

from scripts.creator_profile import validate_profile


def test_profile_accepts_20_item_edition_and_dedup_settings(profile):
    validate_profile(profile)
    assert profile["edition"]["max_items"] == 20
    assert profile["edition"]["candidate_limit"] == 50
    assert profile["dedup"]["time_window_hours"] == 48


def test_profile_rejects_invalid_dedup_threshold_order(profile):
    broken = deepcopy(profile)
    broken["dedup"]["jaccard_threshold"] = 1.1
    with pytest.raises(ValueError, match="dedup_jaccard_threshold"):
        validate_profile(broken)


def test_profile_rejects_candidate_limit_smaller_than_max_items(profile):
    broken = deepcopy(profile)
    broken["edition"]["candidate_limit"] = 19
    with pytest.raises(ValueError, match="candidate_limit"):
        validate_profile(broken)
```

在 `tests/test_creator_docs_contract.py` 增加：

```python
def test_docs_describe_20_item_non_filling_policy():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs/CREATOR_PIPELINE.md").read_text(encoding="utf-8")
    assert "最多 20 条" in readme
    assert "不硬凑" in readme
    assert "LLM_MAX_CALLS_PER_RUN=20" in runbook
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest tests/test_creator_profile.py tests/test_creator_docs_contract.py -q
```

Expected: FAIL because the profile still uses 12/30 and has no validated `dedup` block.

- [ ] **Step 3: 更新正式配置**

将 `config/martin-ai-coding.json` 的相关部分改为：

```json
{
  "edition": {
    "min_items": 8,
    "max_items": 20,
    "candidate_limit": 50,
    "ai_coding_ratio": 0.7,
    "product_cap_ratio": 0.3,
    "history_limit": 60
  },
  "dedup": {
    "enabled": true,
    "time_window_hours": 48,
    "jaccard_threshold": 0.55,
    "sequence_threshold": 0.72,
    "min_shared_keywords": 2
  }
}
```

- [ ] **Step 4: 增加配置校验**

在 `scripts/creator_profile.py` 的 `validate_profile()` 中加入：

```python
candidate_limit = int(edition.get("candidate_limit", 0))
max_items = int(edition.get("max_items", 0))
if candidate_limit < max_items or candidate_limit > 100:
    raise ValueError("candidate_limit")

if max_items != 20:
    raise ValueError("edition_max_items")

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
```

- [ ] **Step 5: 运行配置测试**

Run:

```bash
python -m pytest tests/test_creator_profile.py -q
```

Expected: PASS.

- [ ] **Step 6: 提交**

```bash
git add config/martin-ai-coding.json scripts/creator_profile.py tests/test_creator_profile.py
git commit -m "feat: configure 20 item creator editions"
```

---

### Task 2: 实现 URL、标题和动作规范化

**Files:**
- Create: `scripts/creator_dedup.py`
- Create: `tests/test_creator_dedup.py`

**Interfaces:**
- Produces: `normalize_url(value: str) -> str`
- Produces: `normalize_title(value: str) -> str`
- Produces: `title_keywords(value: str) -> frozenset[str]`
- Produces: `classify_action(item: dict) -> str`
- Produces: `build_creator_event_id(item: dict) -> str`

- [ ] **Step 1: 写规范化失败测试**

创建 `tests/test_creator_dedup.py`：

```python
from scripts.creator_dedup import (
    build_creator_event_id,
    classify_action,
    normalize_title,
    normalize_url,
    title_keywords,
)


def test_normalize_url_removes_tracking_fragment_and_trailing_slash():
    left = "https://Example.com/post/?utm_source=x&ref=feed#section"
    right = "https://example.com/post"
    assert normalize_url(left) == normalize_url(right)


def test_action_classifier_separates_release_pricing_and_security():
    assert classify_action({"title": "Claude Code launches parallel agents"}) == "release"
    assert classify_action({"title": "OpenAI cuts Codex API pricing"}) == "pricing"
    assert classify_action({"title": "Claude Code fixes sandbox escape vulnerability"}) == "security"


def test_event_id_is_stable_across_source_wording():
    first = {
        "primary_entity": "claude-code",
        "title": "Claude Code launches parallel agents",
    }
    second = {
        "primary_entity": "claude-code",
        "title": "Anthropic 发布 Claude Code 并行代理功能",
    }
    assert build_creator_event_id(first) == build_creator_event_id(second)


def test_keywords_remove_generic_marketing_words():
    words = title_keywords("重磅！Claude Code 正式发布全新并行代理功能")
    assert "重磅" not in words
    assert "全新" not in words
    assert "并行" in words
    assert "代理" in words
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest tests/test_creator_dedup.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.creator_dedup'`.

- [ ] **Step 3: 创建规范化模块**

创建 `scripts/creator_dedup.py`，先写以下完整基础实现：

```python
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


def title_keywords(value: str) -> frozenset[str]:
    tokens = TOKEN_RE.findall(normalize_title(value))
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
    words = sorted(title_keywords(str(item.get("title") or "")) - ignored)
    return tuple(words[:8])


def build_creator_event_id(item: dict) -> str:
    entity = str(item.get("primary_entity") or "unknown")
    action = classify_action(item)
    payload = "|".join([entity, action, *event_object_keywords(item)])
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"creator-{digest}"
```

为保证中英文测试稳定，在 `event_object_keywords()` 中加入明确别名折叠：

```python
EVENT_ALIASES = {
    "parallel": "parallel-agents",
    "agents": "parallel-agents",
    "并行": "parallel-agents",
    "代理": "parallel-agents",
}
```

并在返回前执行：

```python
words = sorted({EVENT_ALIASES.get(word, word) for word in words})
```

- [ ] **Step 4: 运行规范化测试**

Run:

```bash
python -m pytest tests/test_creator_dedup.py -q
```

Expected: PASS for the four normalization tests.

- [ ] **Step 5: 提交**

```bash
git add scripts/creator_dedup.py tests/test_creator_dedup.py
git commit -m "feat: normalize creator events for dedup"
```

---

### Task 3: 实现近重复判定、官方来源优先和多源合并

**Files:**
- Modify: `scripts/creator_dedup.py`
- Modify: `tests/test_creator_dedup.py`

**Interfaces:**
- Consumes: `normalize_url()`, `title_keywords()`, `classify_action()`, `build_creator_event_id()`。
- Produces: `are_duplicate_events(left: dict, right: dict, profile: dict) -> bool`
- Produces: `merge_duplicate_group(items: list[dict], profile: dict) -> dict`
- Produces: `deduplicate_candidates(items: list[dict], profile: dict) -> tuple[list[dict], dict]`

- [ ] **Step 1: 写合并与误合并测试**

在 `tests/test_creator_dedup.py` 增加：

```python
from datetime import datetime, timezone

from scripts.creator_dedup import are_duplicate_events, deduplicate_candidates


def candidate(
    story_id: str,
    title: str,
    *,
    entity: str = "claude-code",
    site_id: str = "curated_media",
    source: str = "Tech Media",
    url: str | None = None,
    latest_at: str = "2026-07-23T01:00:00Z",
    score: float = 80.0,
):
    return {
        "story_id": story_id,
        "title": title,
        "url": url or f"https://example.com/{story_id}",
        "source": source,
        "site_id": site_id,
        "latest_at": latest_at,
        "creator_score": score,
        "primary_entity": entity,
        "verification_status": "confirmed" if site_id == "official_ai" else "single_source",
    }


def test_same_event_from_official_and_media_merges_with_official_primary(profile):
    rows = [
        candidate("media", "Claude Code adds parallel agents", source="Tech Media"),
        candidate(
            "official",
            "Anthropic releases parallel agents in Claude Code",
            site_id="official_ai",
            source="Anthropic",
            url="https://anthropic.com/news/parallel-agents",
            score=78.0,
        ),
    ]
    merged, meta = deduplicate_candidates(rows, profile)
    assert len(merged) == 1
    assert merged[0]["story_id"] == "official"
    assert merged[0]["source"] == "Anthropic"
    assert merged[0]["source_count"] == 2
    assert merged[0]["merged_story_ids"] == ["official", "media"]
    assert meta["secondary_dedup_merge_count"] == 1


def test_same_product_different_actions_do_not_merge(profile):
    release = candidate("release", "Claude Code launches parallel agents")
    pricing = candidate("pricing", "Claude Code introduces a new enterprise price")
    assert are_duplicate_events(release, pricing, profile) is False


def test_same_product_different_features_do_not_merge(profile):
    agents = candidate("agents", "Claude Code launches parallel agents")
    simulator = candidate("sim", "Claude Code integrates iOS simulator testing")
    assert are_duplicate_events(agents, simulator, profile) is False


def test_similar_event_outside_48_hours_does_not_merge(profile):
    old = candidate("old", "Claude Code launches parallel agents", latest_at="2026-07-20T01:00:00Z")
    new = candidate("new", "Anthropic releases parallel agents in Claude Code")
    assert are_duplicate_events(old, new, profile) is False


def test_exact_normalized_url_always_merges(profile):
    left = candidate("a", "First wording", url="https://example.com/post?utm_source=x")
    right = candidate("b", "Different wording", url="https://example.com/post#top")
    assert are_duplicate_events(left, right, profile) is True
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest tests/test_creator_dedup.py -q
```

Expected: FAIL because duplicate and merge functions are not defined.

- [ ] **Step 3: 实现近重复判定**

在 `scripts/creator_dedup.py` 增加：

```python
from datetime import datetime
from difflib import SequenceMatcher


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
```

- [ ] **Step 4: 实现来源选择和合并**

在同一文件增加：

```python
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

    story_ids = sorted({str(item.get("story_id") or "") for item in ordered if item.get("story_id")})
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
```

- [ ] **Step 5: 实现候选聚类**

```python
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
```

- [ ] **Step 6: 运行去重测试**

Run:

```bash
python -m pytest tests/test_creator_dedup.py -q
```

Expected: PASS.

- [ ] **Step 7: 提交**

```bash
git add scripts/creator_dedup.py tests/test_creator_dedup.py
git commit -m "feat: merge duplicate creator events"
```

---

### Task 4: 将二次去重接入评分、20 条选择和 LLM 管线

**Files:**
- Modify: `scripts/creator_rules.py`
- Modify: `scripts/creator_pipeline.py`
- Modify: `scripts/llm_provider.py`
- Modify: `tests/test_creator_rules.py`
- Modify: `tests/test_creator_pipeline.py`
- Modify: `tests/test_llm_provider.py`

**Interfaces:**
- Consumes: `score_story()`, `deduplicate_candidates()`。
- Produces: `select_scored_candidates(items: list[dict], profile: dict) -> list[dict]`
- Produces: `prepare_creator_candidates(stories: list[dict], profile: dict, now: datetime) -> tuple[list[dict], dict]`

- [ ] **Step 1: 写 20 条和集成去重失败测试**

在 `tests/test_creator_rules.py` 增加：

```python
def test_selection_allows_20_items_without_lowering_threshold(profile):
    rows = []
    for index in range(25):
        rows.append(
            {
                "story_id": f"s-{index}",
                "title": f"Coding agent release feature {index}",
                "creator_score": 80 - index / 10,
                "creator_bucket": "ai_coding" if index < 16 else "general_ai",
                "primary_entity": f"product-{index}",
                "latest_at": f"2026-07-23T00:{index:02d}:00Z",
            }
        )
    selected = select_scored_candidates(rows, profile)
    assert len(selected) == 20


def test_selection_does_not_fill_with_below_threshold_items(profile):
    rows = [
        {
            "story_id": f"s-{index}",
            "title": f"Story {index}",
            "creator_score": 80 if index < 9 else 49,
            "creator_bucket": "ai_coding",
            "primary_entity": f"product-{index}",
            "latest_at": "2026-07-23T00:00:00Z",
        }
        for index in range(20)
    ]
    selected = select_scored_candidates(rows, profile)
    assert len(selected) == 9
```

在 `tests/test_creator_pipeline.py` 增加：

```python
def test_pipeline_deduplicates_before_final_selection(tmp_path, profile_path, persona_path):
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
    edition = run_pipeline(data, profile_path, persona_path, requested_edition="morning")
    assert len(edition["items"]) == 1
    assert edition["items"][0]["source_count"] == 2
    assert edition["items"][0]["source"] == "Anthropic"
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest tests/test_creator_rules.py tests/test_creator_pipeline.py tests/test_llm_provider.py -q
```

Expected: FAIL because the selection helper and dedup integration do not exist, and LLM default is still 12.

- [ ] **Step 3: 拆出已评分候选选择函数**

在 `scripts/creator_rules.py` 中实现：

```python
def select_scored_candidates(items: list[dict], profile: dict) -> list[dict]:
    edition = profile["edition"]
    thresholds = profile["thresholds"]
    max_items = int(edition["max_items"])
    candidate_limit = int(edition["candidate_limit"])
    product_limit = max(1, int(max_items * float(edition["product_cap_ratio"])))
    coding_target = round(max_items * float(edition["ai_coding_ratio"]))

    eligible = [
        item for item in items
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

    selected: list[dict] = []
    counts: dict[str, int] = {}

    def append_allowed(item: dict) -> bool:
        entity = str(item.get("primary_entity") or item.get("creator_event_id") or "unknown")
        if counts.get(entity, 0) >= product_limit:
            return False
        selected.append(item)
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
        if item in selected:
            continue
        if item.get("creator_bucket") == "general_ai":
            append_allowed(item)

    for item in eligible:
        if len(selected) >= max_items:
            break
        if item not in selected:
            append_allowed(item)

    return selected
```

保留兼容包装：

```python
def select_candidates(stories: list[dict], profile: dict, now: datetime) -> list[dict]:
    scored = [score_story(story, profile, now) for story in stories]
    return select_scored_candidates(scored, profile)
```

- [ ] **Step 4: 在 Pipeline 中接入二次去重**

在 `scripts/creator_pipeline.py` 增加：

```python
from scripts.creator_dedup import deduplicate_candidates
from scripts.creator_rules import score_story, select_scored_candidates


def prepare_creator_candidates(stories: list[dict], profile: dict, now: datetime) -> tuple[list[dict], dict]:
    scored = [score_story(story, profile, now) for story in stories]
    deduped, dedup_meta = deduplicate_candidates(scored, profile)
    selected = select_scored_candidates(deduped, profile)
    return selected, dedup_meta
```

把原来的候选生成替换为：

```python
selected, dedup_meta = prepare_creator_candidates(stories, profile, now)
```

写入 `creator-candidates.json`：

```python
candidate_payload = {
    "version": 1,
    "generated_at": iso_z(now),
    "total_items": len(selected),
    "dedup_meta": dedup_meta,
    "items": selected,
}
```

在 `creator-brief.json` 的 `llm_meta` 同级增加：

```python
edition["dedup_meta"] = dedup_meta
```

公开字段白名单必须保留：

```python
"creator_event_id",
"merged_story_ids",
"source_count",
"source_names",
"sources",
```

- [ ] **Step 5: 将 LLM 默认预算改为 20**

在 `scripts/llm_provider.py`：

```python
max_calls = max(0, min(int(os.environ.get("LLM_MAX_CALLS_PER_RUN") or 20), 40))
```

在 `tests/test_llm_provider.py` 增加：

```python
def test_default_call_budget_matches_20_item_edition():
    with patch.dict("os.environ", {}, clear=True):
        settings = LLMSettings.from_env()
    assert settings.max_calls == 20
```

- [ ] **Step 6: 运行集成测试**

Run:

```bash
python -m pytest \
  tests/test_creator_rules.py \
  tests/test_creator_dedup.py \
  tests/test_creator_pipeline.py \
  tests/test_llm_provider.py -q
```

Expected: PASS.

- [ ] **Step 7: 提交**

```bash
git add \
  scripts/creator_rules.py scripts/creator_pipeline.py scripts/llm_provider.py \
  tests/test_creator_rules.py tests/test_creator_pipeline.py tests/test_llm_provider.py
git commit -m "feat: build 20 item deduplicated creator briefs"
```

---

### Task 5: 使用稳定事件 ID 管理早晚版状态迁移

**Files:**
- Modify: `scripts/edition.py`
- Modify: `tests/test_edition.py`

**Interfaces:**
- Produces: `event_state_key(item: dict) -> str`
- Existing: `story_fingerprint(item: dict) -> str`
- Existing: `build_edition(...) -> tuple[dict, dict]`

- [ ] **Step 1: 写状态迁移失败测试**

在 `tests/test_edition.py` 增加：

```python
def test_official_source_upgrade_uses_same_event_state(profile):
    morning = candidate("media", "early_signal", source_count=1)
    morning["creator_event_id"] = "creator-event-1"
    morning["url"] = "https://media.example/event"
    morning_edition, morning_state = build_edition([morning], {}, profile, NOW, "morning")
    assert morning_edition["items"][0]["change_type"] == "new"

    official = candidate("official", "confirmed", source_count=2)
    official["creator_event_id"] = "creator-event-1"
    official["url"] = "https://official.example/event"
    official["sources"] = [
        {"url": "https://official.example/event", "official": True},
        {"url": "https://media.example/event", "official": False},
    ]
    evening_edition, _ = build_edition([official], morning_state, profile, NOW, "evening")
    assert len(evening_edition["items"]) == 1
    assert evening_edition["items"][0]["change_type"] == "confirmed"


def test_source_reordering_without_content_change_is_not_new(profile):
    item = candidate("story-a", "confirmed", source_count=2)
    item["creator_event_id"] = "creator-event-2"
    item["sources"] = [
        {"url": "https://official.example/a", "official": True},
        {"url": "https://media.example/a", "official": False},
    ]
    _, state = build_edition([item], {}, profile, NOW, "morning")
    reordered = dict(item)
    reordered["story_id"] = "story-b"
    reordered["sources"] = list(reversed(item["sources"]))
    evening, _ = build_edition([reordered], state, profile, NOW, "evening")
    assert evening["items"] == []
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest tests/test_edition.py -q
```

Expected: FAIL because state is keyed only by `story_id` and fingerprint depends on source ordering.

- [ ] **Step 3: 实现稳定状态键与来源指纹**

在 `scripts/edition.py` 增加：

```python
def event_state_key(item: dict) -> str:
    return str(item.get("creator_event_id") or item.get("story_id") or "")


def normalized_source_urls(item: dict) -> list[str]:
    sources = item.get("sources") if isinstance(item.get("sources"), list) else []
    values = {
        str(source.get("url") or "").strip()
        for source in sources
        if isinstance(source, dict) and source.get("url")
    }
    if item.get("url"):
        values.add(str(item["url"]).strip())
    return sorted(values)


def story_fingerprint(item: dict) -> str:
    return "|".join(
        [
            str(item.get("verification_status") or ""),
            str(int(item.get("source_count") or 1)),
            " ".join(str(item.get("title") or "").lower().split()),
            ",".join(normalized_source_urls(item)),
        ]
    )
```

在 `build_edition()` 中把所有：

```python
story_id = str(item.get("story_id") or "")
```

替换为：

```python
state_key = event_state_key(item)
```

状态结构保存：

```python
next_state["stories"][state_key] = {
    "last_fingerprint": story_fingerprint(item),
    "last_status": item.get("verification_status"),
    "last_sent_at": iso_z(now),
    "last_story_id": item.get("story_id"),
    "last_primary_url": item.get("url"),
}
```

- [ ] **Step 4: 运行版次测试**

Run:

```bash
python -m pytest tests/test_edition.py -q
```

Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add scripts/edition.py tests/test_edition.py
git commit -m "fix: track creator editions by stable event id"
```

---

### Task 6: 在 Telegram 和 GitHub Pages 展示多源信息

**Files:**
- Modify: `scripts/telegram_publish.py`
- Modify: `creator/assets/app.js`
- Modify: `creator/assets/styles.css`
- Modify: `tests/test_telegram_publish.py`
- Modify: `tests/test_creator_page_contract.py`

**Interfaces:**
- Consumes: `item.source_count`, `item.sources[]`。
- Produces: `source_count_label(item: dict) -> str`
- Produces: 浏览器中的可展开来源列表。

- [ ] **Step 1: 写 Telegram 与页面失败测试**

在 `tests/test_telegram_publish.py` 增加：

```python
def test_render_shows_multi_source_count():
    edition = {
        "edition_id": "2026-07-23-morning",
        "edition_kind": "morning",
        "items": [
            {
                "title": "Claude Code parallel agents",
                "url": "https://anthropic.com/news/parallel-agents",
                "verification_status": "confirmed",
                "change_type": "new",
                "summary_zh": "摘要",
                "why_it_matters": "影响",
                "creator_score": 90,
                "source_count": 2,
                "sources": [
                    {"source": "Anthropic", "url": "https://anthropic.com/news/parallel-agents", "official": True},
                    {"source": "Tech Media", "url": "https://media.example/story", "official": False},
                ],
                "angles": [],
            }
        ],
    }
    message = "\n".join(render_messages(edition))
    assert "多源 2" in message
```

在 `tests/test_creator_page_contract.py` 增加：

```python
def test_creator_page_supports_expandable_sources():
    app = read("creator/assets/app.js")
    styles = read("creator/assets/styles.css")
    assert "function renderSources" in app
    assert "source_count" in app
    assert "source-list" in styles
    assert "noopener noreferrer" in app
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest tests/test_telegram_publish.py tests/test_creator_page_contract.py -q
```

Expected: FAIL because multi-source labels and source expansion are absent.

- [ ] **Step 3: 更新 Telegram 标签**

在 `scripts/telegram_publish.py` 增加：

```python
def source_count_label(item: dict) -> str:
    count = int(item.get("source_count") or 1)
    return f" · 多源 {count}" if count > 1 else ""
```

在每条新闻状态行中组合：

```python
status_line = (
    f"{STATUS_ICON.get(status, '◻️')} "
    f"{html.escape(status_text(status))}"
    f"{html.escape(source_count_label(item))}"
)
```

Telegram 仍只输出主链接，不展开 `sources[]`。

- [ ] **Step 4: 更新页面来源渲染**

在 `creator/assets/app.js` 增加：

```javascript
function renderSources(item) {
  const sources = Array.isArray(item.sources) ? item.sources : [];
  if (sources.length <= 1) return "";
  const rows = sources.map((source, index) => {
    const url = safeUrl(source.url);
    const label = source.official ? "官方" : index === 0 ? "主来源" : "来源";
    const title = escapeHtml(source.title || source.source || "未命名来源");
    const name = escapeHtml(source.source || "未知来源");
    const content = url
      ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
      : title;
    return `<li><span class="source-kind">${escapeHtml(label)}</span><div>${content}<small>${name}</small></div></li>`;
  }).join("");
  return `
    <details class="source-list">
      <summary>多源 ${sources.length}</summary>
      <ul>${rows}</ul>
    </details>`;
}
```

在 `renderItem(item)` 的卡片中，放在摘要之后：

```javascript
${renderSources(item)}
```

- [ ] **Step 5: 增加页面样式**

在 `creator/assets/styles.css` 增加：

```css
.source-list {
  margin-top: 12px;
  border-top: 1px solid var(--line);
  padding-top: 10px;
}

.source-list summary {
  cursor: pointer;
  font-weight: 700;
}

.source-list ul {
  display: grid;
  gap: 8px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.source-list li {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 8px;
  align-items: start;
}

.source-list small {
  display: block;
  margin-top: 2px;
  color: var(--muted);
}

.source-kind {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 7px;
  font-size: 12px;
}
```

- [ ] **Step 6: 运行展示测试**

Run:

```bash
python -m pytest tests/test_telegram_publish.py tests/test_creator_page_contract.py -q
```

Expected: PASS.

- [ ] **Step 7: 提交**

```bash
git add \
  scripts/telegram_publish.py creator/assets/app.js creator/assets/styles.css \
  tests/test_telegram_publish.py tests/test_creator_page_contract.py
git commit -m "feat: show multi source creator stories"
```

---

### Task 7: 增加去重审计、Workflow 默认值与文档

**Files:**
- Modify: `scripts/audit_creator_editions.py`
- Modify: `tests/test_creator_audit.py`
- Modify: `.github/workflows/update-news.yml`
- Modify: `tests/test_creator_workflow_contract.py`
- Modify: `docs/CREATOR_PIPELINE.md`
- Modify: `README.md`
- Add: `docs/superpowers/specs/2026-07-23-creator-edition-20-item-dedup-design.md`
- Add: `docs/superpowers/plans/2026-07-23-creator-edition-20-item-dedup.md`

**Interfaces:**
- Consumes: `edition.dedup_meta`, `item.creator_event_id`, `item.source_count`。
- Produces: `secondary_dedup_merge_count`, `secondary_dedup_source_count`, `suspected_duplicate_rate`。

- [ ] **Step 1: 写审计与 Workflow 失败测试**

在 `tests/test_creator_audit.py` 增加：

```python
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
```

在 `tests/test_creator_workflow_contract.py` 增加或更新：

```python
def test_workflow_defaults_to_20_llm_calls():
    assert "LLM_MAX_CALLS_PER_RUN: ${{ vars.LLM_MAX_CALLS_PER_RUN || 20 }}" in WORKFLOW
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
python -m pytest tests/test_creator_audit.py tests/test_creator_workflow_contract.py tests/test_creator_docs_contract.py -q
```

Expected: FAIL because metrics and documentation still describe 12 items.

- [ ] **Step 3: 更新审计指标**

在 `calculate_metrics()` 中增加：

```python
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
    seen_in_edition = set()
    for item in edition.get("items", []):
        event_id = str(item.get("creator_event_id") or item.get("story_id") or "")
        if event_id and event_id in seen_in_edition:
            event_occurrences[event_id] = event_occurrences.get(event_id, 0) + 1
        seen_in_edition.add(event_id)

total_displayed = sum(len(edition.get("items", [])) for edition in editions)
suspected_duplicates = sum(event_occurrences.values())
metrics["secondary_dedup_merge_count"] = merge_count
metrics["secondary_dedup_source_count"] = source_count
metrics["suspected_duplicate_rate"] = (
    round(suspected_duplicates / total_displayed, 4) if total_displayed else 0.0
)
```

- [ ] **Step 4: 更新 Workflow**

在 `.github/workflows/update-news.yml`：

```yaml
LLM_MAX_CALLS_PER_RUN: ${{ vars.LLM_MAX_CALLS_PER_RUN || 20 }}
```

- [ ] **Step 5: 更新文档**

`README.md` 的创作者版说明改为：

```markdown
每天北京时间 **08:17 / 20:47** 生成早报和晚报，每期最多 20 条；质量不足时不硬凑。系统会在上游故事合并之后再次识别同一事件的多个出处，优先展示官方来源，并以“多源 N”保留全部出处。
```

`docs/CREATOR_PIPELINE.md` 必须包含：

```text
LLM_MAX_CALLS_PER_RUN=20
```

并新增章节：

```markdown
## 二次事件去重

创作者管线在 `stories-merged.json` 之后再次执行确定性去重：同一核心实体、同一事件动作、48 小时内且标题核心内容相似的记录会合并。官方来源优先成为主链接，其他出处保存在 `sources[]`。同一产品的不同功能或不同动作不会合并。
```

- [ ] **Step 6: 保存规格与计划**

```bash
mkdir -p docs/superpowers/specs docs/superpowers/plans
cp /path/to/approved/2026-07-23-creator-edition-20-item-dedup-design.md \
  docs/superpowers/specs/2026-07-23-creator-edition-20-item-dedup-design.md
cp /path/to/approved/2026-07-23-creator-edition-20-item-dedup.md \
  docs/superpowers/plans/2026-07-23-creator-edition-20-item-dedup.md
```

执行者应使用本计划文件的实际内容写入仓库，不得提交 `/path/to/approved` 字面路径。

- [ ] **Step 7: 运行任务测试**

Run:

```bash
python -m pytest \
  tests/test_creator_audit.py \
  tests/test_creator_workflow_contract.py \
  tests/test_creator_docs_contract.py -q
```

Expected: PASS.

- [ ] **Step 8: 提交**

```bash
git add \
  scripts/audit_creator_editions.py tests/test_creator_audit.py \
  .github/workflows/update-news.yml tests/test_creator_workflow_contract.py \
  README.md docs/CREATOR_PIPELINE.md docs/superpowers
git commit -m "docs: document 20 item creator dedup"
```

---

### Task 8: 全量回归、真实样例和部署验收

**Files:**
- Verify all modified files.
- Optional local fixture only: `tmp/creator-dedup-sample.json`（不得提交）。

**Interfaces:**
- Verifies the complete creator pipeline.

- [ ] **Step 1: 运行 Python 编译**

```bash
python -m py_compile \
  scripts/creator_profile.py \
  scripts/creator_rules.py \
  scripts/creator_dedup.py \
  scripts/creator_pipeline.py \
  scripts/edition.py \
  scripts/llm_provider.py \
  scripts/telegram_publish.py \
  scripts/audit_creator_editions.py
```

Expected: no output, exit code 0.

- [ ] **Step 2: 运行全仓测试**

```bash
python -m pytest -q
```

Expected: all tests PASS.

- [ ] **Step 3: 运行无 Key 端到端测试**

```bash
LLM_MAX_CALLS_PER_RUN=0 python scripts/creator_pipeline.py \
  --data-dir data \
  --profile config/martin-ai-coding.json \
  --persona personas/martin-creator.md \
  --edition morning

python scripts/telegram_publish.py \
  --edition-file data/creator-brief.json \
  --state-file data/telegram-state.json \
  --dry-run
```

Expected:

- `creator-brief.json.total_items <= 20`。
- 不存在低于 `thresholds.signal` 的条目。
- 所有条目都有 `creator_event_id`。
- 多源条目有 `sources[]` 且主来源为最高可信来源。
- Telegram Dry Run 显示“多源 N”。

- [ ] **Step 4: 对用户指出的重复样例做定向验收**

从实际日报中取原第 10、11 条对应的两个原始故事，构造临时 JSON：

```json
{
  "stories": [
    {"story_id":"duplicate-a","title":"原第10条标题","url":"原第10条URL","source":"原第10条来源","latest_at":"同一时间窗口"},
    {"story_id":"duplicate-b","title":"原第11条标题","url":"原第11条URL","source":"原第11条来源","latest_at":"同一时间窗口"}
  ]
}
```

运行管线后确认：

```python
assert len(matching_items) == 1
assert matching_items[0]["source_count"] >= 2
assert len(matching_items[0]["sources"]) >= 2
```

不要把临时样例中的私人或付费来源内容提交到仓库。

- [ ] **Step 5: GitHub Actions 手动验收**

Actions → `Update AI News Snapshot` → Run workflow：

```text
edition: morning
publish_telegram: false
Force TikHub refresh: false
```

检查：

- `Build creator brief` 成功。
- `data/creator-brief.json` 最多 20 条。
- `dedup_meta.secondary_dedup_merge_count` 存在。
- `/creator/` 可以展开“多源 N”。

- [ ] **Step 6: Telegram 验收**

修复并确认 `TELEGRAM_BOT_TOKEN` 和私人 `TELEGRAM_CHANNEL_ID` 后再次运行：

```text
edition: morning
publish_telegram: true
```

检查 Telegram 收到日报，多源条目显示“多源 N”，且同一事件只出现一次。

- [ ] **Step 7: 最终提交状态检查**

```bash
git status --short
git log --oneline --decorate -8
```

Expected: working tree clean; recent commits correspond to Tasks 1–7.

---

## Self-Review

### Spec coverage

- 20 条上限、不硬凑：Task 1、Task 4、Task 8。
- 候选池 50 条：Task 1、Task 4。
- LLM 最大调用 20：Task 4、Task 7。
- URL 精确去重：Task 2、Task 3。
- 实体、动作、48 小时、相似度：Task 2、Task 3。
- 官方来源优先和 `sources[]`：Task 3。
- 稳定 `creator_event_id`：Task 2、Task 5。
- Telegram“多源 N”：Task 6。
- GitHub Pages 来源展开：Task 6。
- 审计指标：Task 7。
- 用户指出的第 10/11 条实际样例：Task 8。

### Placeholder scan

计划中没有 `TBD`、`TODO`、`implement later` 或未定义函数。Task 7 的复制命令明确要求执行者替换为实际已确认文件内容，不允许提交占位路径。

### Type consistency

- `creator_event_id: str`
- `sources: list[dict]`
- `deduplicate_candidates(...) -> tuple[list[dict], dict]`
- `select_scored_candidates(...) -> list[dict]`
- `prepare_creator_candidates(...) -> tuple[list[dict], dict]`
- `dedup_meta.secondary_dedup_merge_count: int`
- `dedup_meta.secondary_dedup_source_count: int`
