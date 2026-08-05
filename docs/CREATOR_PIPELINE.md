# AI Coding 创作者情报管线

这套扩展在现有 AI News Radar 的采集、相关性过滤和事件合并之后运行，不替换上游 `scripts/update_news.py`。它每天北京时间早晚各生成一个增量版次，写入 GitHub Pages 数据，并可推送到一个 Telegram 频道。

## 输出

- `data/creator-candidates.json`：本轮规则评分与二次去重后的候选，最多 20 条。
- `data/creator-brief.json`：当前早报或晚报，供 Telegram 与 Agent 使用。
- `data/creator-editions.json`：最近 60 个版次的轻量历史，`/creator/` 页面读取它。
- `data/edition-state.json`：故事最近推送状态，用于晚报去重和状态迁移。
- `data/creator-cache.json`：LLM 增强缓存，保留 21 天。
- `data/telegram-state.json`：最近成功发送的 Telegram 版次。

## GitHub Secrets

至少配置：

```text
DEEPSEEK_API_KEY 或 LLM_API_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHANNEL_ID
```

Secret 只能存放在 GitHub Settings → Secrets and variables → Actions。不要把 API Key、Bot Token、Cookie、私有 OPML 或 `.env` 提交到仓库。

## 可选 Variables

```text
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
LLM_BASE_URL=https://api.deepseek.com
LLM_MAX_CALLS_PER_RUN=20
TELEGRAM_ENABLED=1
```

现有 `DEEPSEEK_API_BASE_URL`、`DEEPSEEK_MODEL` 仍可作为兼容回退。没有 LLM Key 或达到调用上限时，系统使用规则摘要，不阻断整个 Workflow。

## 二次事件去重

创作者管线在 `stories-merged.json` 之后再次执行确定性去重：同一核心实体、同一事件动作、48 小时内且标题核心内容相似的记录会合并。官方来源优先成为主链接，其他出处保存在 `sources[]`。同一产品的不同功能或不同动作不会合并。

## 调度

Workflow 使用 UTC cron，对应北京时间：

```text
22:00 UTC → 次日 06:00 早报
10:00 UTC → 18:00 晚报
```

手动运行时可选择 `auto`、`morning`、`evening`，并决定是否发送 Telegram。

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

python scripts/update_news.py \
  --output-dir data \
  --window-hours 24 \
  --archive-days 21 \
  --rss-opml feeds/martin-ai-coding.example.opml

python scripts/persona_score.py --data-dir data

python scripts/creator_pipeline.py \
  --data-dir data \
  --profile config/martin-ai-coding.json \
  --persona personas/martin-creator.md \
  --edition morning

python scripts/telegram_publish.py \
  --edition-file data/creator-brief.json \
  --state-file data/telegram-state.json \
  --dry-run

python scripts/audit_creator_editions.py \
  --data-dir data \
  --feedback config/creator-feedback.json

python -m http.server 8080
```

打开 `http://localhost:8080/creator/` 查看创作者情报归档。

## 人工反馈

在 `config/creator-feedback.json` 的 `items` 中按 `story_id` 记录：

```json
{
  "version": 1,
  "items": {
    "story_xxx": {
      "useful": true,
      "noise": false,
      "published": true,
      "platform": "x",
      "notes": "只供人工复盘，不进入公开审计报告"
    }
  }
}
```

支持的平台建议使用 `x`、`xiaohongshu`、`wechat`。

## 故障恢复

### Telegram 失败

`creator-brief.json` 已生成时，可只重跑：

```bash
python scripts/telegram_publish.py \
  --edition-file data/creator-brief.json \
  --state-file data/telegram-state.json
```

只有全部消息片段发送成功后才会更新 `telegram-state.json`。

### LLM 失败或超额

系统自动写入 `enrichment_mode=rules_fallback`，Workflow 应继续成功。检查 `creator-brief.json` 中的 `llm_meta`，它只包含 provider、model、调用数、缓存命中数和降级数，不包含密钥。

### 抓取源失败

查看 `data/source-status.json`。不要删除旧历史；优先修复或暂时禁用单个源。

### 错误信息已推送

修正来源或可信状态后重新生成。状态指纹变化会以 `change_type=updated` 或 `change_type=confirmed` 进入下一版，而不是静默覆盖历史。

## 7 天验收

运行：

```bash
python scripts/audit_creator_editions.py \
  --data-dir data \
  --feedback config/creator-feedback.json \
  --output reports/creator-quality/latest.json
```

目标：

- Actions 成功率不低于 95%。
- 平均每期 8–12 条；安静时段允许更少，不以噪音补足。
- 未发生实质变化的跨版重复率低于 10%。
- 人工标记噪音率低于 20%。
- 每期至少 2 个可用内容角度。
- 每条信息均能追溯到原始 URL。
- LLM 与付费源预测月成本低于 10 美元。
