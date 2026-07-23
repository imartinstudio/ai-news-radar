import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runbook_documents_required_secrets_and_recovery_commands():
    text = (ROOT / "docs/CREATOR_PIPELINE.md").read_text(encoding="utf-8")
    for value in ("DEEPSEEK_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID"):
        assert value in text
    assert "python scripts/creator_pipeline.py" in text
    assert "python scripts/telegram_publish.py" in text
    assert "python scripts/audit_creator_editions.py" in text
    assert "故障恢复" in text


def test_readme_documents_creator_page_and_twice_daily_schedule():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## AI Coding 创作者版" in text
    assert "[AI Coding 创作者版](creator/)" in text
    assert "17 0 * * *" in text
    assert "47 12 * * *" in text
    assert "默认每 30 分钟运行一次" not in text
    assert "feeds/martin-ai-coding.example.opml" in text


def test_gitignore_protects_local_secrets_without_hiding_public_creator_data():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env.*" in text
    assert "feeds/follow.opml" in text
    assert "config/*.local.json" in text
    assert "telegram-preview.*" in text
    for filename in (
        "creator-brief.json",
        "creator-editions.json",
        "edition-state.json",
        "creator-cache.json",
        "telegram-state.json",
    ):
        assert filename not in text


def test_initial_creator_page_data_is_valid_and_empty():
    history = json.loads((ROOT / "data/creator-editions.json").read_text(encoding="utf-8"))
    brief = json.loads((ROOT / "data/creator-brief.json").read_text(encoding="utf-8"))
    assert history["version"] == 1
    assert isinstance(history.get("editions"), list)
    assert isinstance(brief.get("items"), list)
    assert isinstance(brief.get("llm_meta"), dict)
    assert int(brief["llm_meta"].get("calls_used") or 0) >= 0
    assert int(brief.get("total_items") or len(brief["items"])) <= 20
    for edition in history["editions"]:
        assert isinstance(edition, dict)
        assert edition.get("edition_id")
        assert isinstance(edition.get("items"), list)
        assert len(edition["items"]) <= 20


def test_docs_describe_20_item_non_filling_policy():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs/CREATOR_PIPELINE.md").read_text(encoding="utf-8")
    assert "最多 20 条" in readme
    assert "不硬凑" in readme
    assert "LLM_MAX_CALLS_PER_RUN=20" in runbook
