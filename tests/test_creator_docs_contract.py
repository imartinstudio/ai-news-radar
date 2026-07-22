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
    assert history["editions"] == []
    assert brief["items"] == []
    assert brief["llm_meta"]["calls_used"] == 0
