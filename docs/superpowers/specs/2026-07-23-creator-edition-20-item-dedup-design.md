# AI Coding 创作者版：20 条上限与版次级二次去重设计

**日期：** 2026-07-23  
**状态：** 已确认  
**仓库：** `imartinstudio/ai-news-radar`  
**目标分支：** `feat/ai-coding-intelligence-v1`
**确认日期：** 2026-07-23

## 1. 背景与目标

当前创作者日报每期最多输出 12 条。实际运行中还发现，同一事件可能因标题、语言和出处不同，被上游识别为不同 `story_id`，最终在同一期日报中重复出现。

本次调整解决两个问题：

1. 每期容量从最多 12 条提高到最多 20 条，但不为了凑数降低质量门槛。
2. 在上游 `stories-merged.json` 之后增加“版次级二次去重”，将同一事件的多个出处合并为一条，并优先展示官方或最高可信来源。

## 2. 已确认规则

### 2.1 条目数量

- 每期最多输出 20 条。
- 保持现有最低质量门槛，不要求固定达到 20 条。
- 高质量候选不足时，允许输出 8–19 条。
- 候选池从 30 条扩大到 50 条，避免二次去重后候选不足。
- AI Coding 与重要通用 AI 的目标比例仍为约 70% / 30%。
- 单一产品每期最多约 30%，20 条版次中最多 6 条。

### 2.2 LLM 调用

- 单轮 LLM 最大处理量从 12 条提高到 20 条。
- 缓存命中不消耗调用额度。
- API Key 缺失、超限或请求失败时，继续使用规则降级，不阻断日报生成。
- 不为了达到 20 条而对低于评分门槛的候选调用 LLM。

### 2.3 同一事件展示

采用方案 A：

- 同一事件只展示一条。
- 官方来源优先成为主链接。
- 没有官方来源时，选择可信度最高的来源。
- 其他出处保存在 `sources[]` 中。
- 页面和 Telegram 显示“多源 N”。
- 所有来源仍可追溯，不丢失出处。

## 3. 数据流程

```text
stories-merged.json
  ↓
确定性评分与排序
  ↓
版次级二次去重
  ├─ URL 精确归一化
  ├─ 核心实体识别
  ├─ 事件动作识别
  ├─ 标题关键词相似度
  └─ 48 小时时间窗口
  ↓
多样性选择
  ├─ 最多 20 条
  ├─ 约 70% AI Coding
  └─ 单产品最多 6 条
  ↓
早晚版次增量判断
  ↓
LLM 增强
  ↓
Telegram / GitHub Pages / JSON
```

二次去重发生在确定性评分之后、最终多样性选择之前。这样被合并事件可以继承各来源的可信度与热度信息，同时不会浪费最终版次名额。

## 4. 去重判定

### 4.1 精确 URL 去重

先对 URL 做规范化：

- 域名转小写。
- 删除 URL fragment。
- 删除常见追踪参数，如 `utm_*`、`ref`、`source`、`campaign`。
- 删除末尾多余 `/`。
- 统一已知镜像链接与原始链接的可识别形式。
- 同一规范化 URL 必须合并。

### 4.2 近重复事件判定

除精确 URL 外，两个候选只有同时满足以下条件才能合并：

1. **核心实体相同**：例如都属于 `claude-code`、`codex`、`cursor` 或 `gemini-cli`。
2. **事件动作相同**：发布、更新、集成、安全、定价、评测、开源、收购、政策等动作必须一致。
3. **时间接近**：两条信息的 `latest_at` 相差不超过 48 小时。
4. **标题核心内容足够相似**：满足以下任一条件：
   - 关键词 Jaccard 相似度 ≥ 0.55；
   - 字符串相似度 ≥ 0.72，且至少共享两个非通用关键词；
   - 中英文别名映射后，实体、动作和功能对象一致。

动作分组：

- `release`：发布、上线、推出
- `update`：更新、升级、改进
- `integration`：集成、接入、支持
- `security`：安全漏洞、攻击、修复
- `pricing`：价格、套餐、降价、涨价
- `benchmark`：评测、榜单、基准成绩
- `open_source`：开源、权重发布
- `acquisition`：收购、合并
- `policy`：规则、许可、条款变更

### 4.3 不得合并

即使产品相同，以下情况也必须保留为不同新闻：

- 同一天发布两个不同功能。
- “发布新模型”和“调整 API 价格”。
- “安全漏洞披露”和“后续漏洞修复”。
- “官方发布”和几天后的独立实测结果。
- 时间相差超过 48 小时，且没有相同规范化 URL。
- 标题只有产品名相同，没有共同功能对象或事件动作。

## 5. 合并规则

### 5.1 主来源选择

来源优先级：

1. 官方来源。
2. `source_tiers` 可信分更高的来源。
3. 原始报道优先于聚合转载。
4. 信息更完整的来源。
5. 时间更新的来源。

### 5.2 合并后字段

```json
{
  "creator_event_id": "稳定事件标识",
  "story_id": "主记录 story_id",
  "merged_story_ids": ["story-a", "story-b"],
  "title": "主来源标题",
  "url": "主来源 URL",
  "source": "主来源名称",
  "source_count": 2,
  "source_names": ["Anthropic", "TechCrunch"],
  "sources": [
    {
      "title": "官方标题",
      "url": "https://...",
      "source": "Anthropic",
      "site_id": "official_ai",
      "official": true
    },
    {
      "title": "媒体标题",
      "url": "https://...",
      "source": "TechCrunch",
      "site_id": "curated_media",
      "official": false
    }
  ]
}
```

### 5.3 稳定事件标识

新增 `creator_event_id`，由以下信息生成稳定哈希：

```text
primary_entity + action_bucket + normalized_event_keywords
```

早晚版次状态优先使用 `creator_event_id`，而不是单个来源的 `story_id`。这样主来源变化或新增官方来源时，不会被误判成一条全新事件。

新增官方来源时：

- 事件仍是同一条。
- `change_type` 标记为 `confirmed` 或 `updated`。
- 主链接可以升级为官方来源。
- 晚报可作为“早期信号转为确认”重新出现一次。

## 6. 输出变化

### 6.1 Telegram

每条新闻增加：

```text
✅ 多源 2
```

或：

```text
👀 早期信号 · 多源 3
```

Telegram 主消息仍只放一个主链接，避免消息过长。其他来源在 GitHub Pages 归档页中展开查看。

### 6.2 GitHub Pages

`/creator/` 新闻卡片增加“多源 N”按钮：

- `source_count = 1` 时不显示。
- 点击后展开全部来源标题、名称和链接。
- 主来源标记“官方”或“主来源”。
- 所有远程内容继续转义，链接只允许 HTTP/HTTPS。

### 6.3 JSON 与审计

- `creator-candidates.json` 保存去重后的候选。
- `creator-brief.json` 保存当前去重版次。
- `creator-editions.json` 保存合并来源历史。
- 审计报告增加：
  - `secondary_dedup_merge_count`
  - `secondary_dedup_source_count`
  - `suspected_duplicate_rate`

## 7. 配置调整

`config/martin-ai-coding.json`：

```json
{
  "edition": {
    "min_items": 8,
    "max_items": 20,
    "candidate_limit": 50,
    "ai_coding_ratio": 0.7,
    "product_cap_ratio": 0.3
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

Workflow 默认变量：

```text
LLM_MAX_CALLS_PER_RUN=20
```

如果仓库 Variables 中已经手动设置为 12，需要同步改为 20；否则 Workflow 中的默认值生效。

## 8. 代码边界

建议新增独立模块：

```text
scripts/creator_dedup.py
```

职责：

- URL 规范化。
- 标题规范化。
- 动作识别。
- 近重复判定。
- 来源合并。
- `creator_event_id` 生成。

现有模块调整：

- `creator_profile.py`：校验 `dedup` 配置。
- `creator_rules.py`：评分后调用去重，再做多样性选择。
- `edition.py`：优先使用 `creator_event_id` 做状态判断。
- `creator_pipeline.py`：写入合并字段和去重指标。
- `telegram_publish.py`：显示“多源 N”。
- `creator/assets/app.js`：展开全部来源。
- `audit_creator_editions.py`：输出二次去重指标。

不修改上游 `update_news.py` 的核心事件合并算法，降低与上游同步时的冲突风险。

## 9. 测试设计

必须覆盖：

1. 相同 URL、不同追踪参数必须合并。
2. 同一 Claude Code 更新的中英文标题必须合并。
3. 官方来源和媒体来源合并后，官方来源成为主链接。
4. 相同产品、不同功能不得合并。
5. 相同产品、不同动作不得合并。
6. 相同标题但相差超过 48 小时不得模糊合并。
7. 新增官方来源时，早期信号状态升级为已确认。
8. 去重后每期最多 20 条。
9. 候选不足时不得降低评分门槛硬凑 20 条。
10. 20 条均可调用 LLM，调用预算不足时剩余条目规则降级。
11. Telegram 正确显示“多源 N”。
12. 页面展开来源时不产生未转义 HTML 或危险 URL。
13. 现有上游测试和创作者版测试全部通过。

## 10. 验收标准

- 每期不超过 20 条。
- 高质量候选不足时允许少于 20 条。
- 同一期人工可识别的重复事件率低于 5%。
- 用户指出的“同一事件不同出处”样例合并为一条。
- 合并后保留全部可追溯来源。
- 官方来源存在时，主链接为官方来源。
- 同一产品的不同功能没有被误合并。
- 早报中的早期信号新增官方出处后，晚报正确标记为确认更新。
- LLM 最大处理量与 20 条版次一致。
- 全仓测试、Python 编译和端到端 Dry Run 通过。

## 11. 非目标

本次不包含：

- 自动生成完整 X 帖子。
- 自动发布到 X、小红书或公众号。
- 向量数据库。
- 使用 LLM 做每一对候选的去重判断。
- 修改上游主抓取器的核心事件合并逻辑。
- 为达到 20 条降低评分门槛。
