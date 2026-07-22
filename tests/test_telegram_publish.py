import json
from pathlib import Path
from unittest.mock import patch

from scripts.telegram_publish import publish, render_messages, should_send


def sample_edition(count: int = 1) -> dict:
    return {
        "edition_id": "2026-07-22-morning",
        "edition_kind": "morning",
        "generated_at": "2026-07-22T00:17:00Z",
        "items": [
            {
                "story_id": f"story-{index}",
                "title": "Claude <Code> & Codex" + (" 很长" * 20),
                "url": "https://example.com/a?x=1&y=2",
                "verification_status": "confirmed",
                "change_type": "new",
                "summary_zh": "摘要" * 30,
                "why_it_matters": "影响工作流" * 20,
                "creator_score": 90,
                "angles": [
                    {
                        "platform": "x",
                        "title": "我会怎么测试 <Codex>",
                        "angle": "从真实项目出发 & 对比旧流程",
                    }
                ],
            }
            for index in range(count)
        ],
    }


def test_render_escapes_html_and_stays_under_limit():
    messages = render_messages(sample_edition(count=12), max_chars=1200)

    assert "&lt;Code&gt;" in messages[0]
    assert "&amp; Codex" in messages[0]
    assert all(len(message) <= 1200 for message in messages)
    assert len(messages) > 1


def test_same_edition_is_not_sent_twice():
    assert should_send("edition-1", {"last_sent_edition_id": "edition-1"}) is False
    assert should_send("edition-2", {"last_sent_edition_id": "edition-1"}) is True


def test_dry_run_does_not_write_state(tmp_path: Path, capsys):
    edition_path = tmp_path / "brief.json"
    state_path = tmp_path / "state.json"
    edition_path.write_text(json.dumps(sample_edition()), encoding="utf-8")

    result = publish(edition_path, state_path, dry_run=True)

    assert result == 0
    assert not state_path.exists()
    assert "AI Coding 早报" in capsys.readouterr().out


def test_state_is_written_only_after_all_fragments_succeed(tmp_path: Path):
    edition_path = tmp_path / "brief.json"
    state_path = tmp_path / "state.json"
    edition_path.write_text(json.dumps(sample_edition(count=12)), encoding="utf-8")

    with patch.dict(
        "os.environ",
        {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHANNEL_ID": "@channel"},
        clear=True,
    ), patch("scripts.telegram_publish.send_message", return_value={"ok": True}) as send:
        result = publish(edition_path, state_path, dry_run=False, max_chars=1200)

    assert result == 0
    assert send.call_count > 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["last_sent_edition_id"] == "2026-07-22-morning"
