from pathlib import Path

WORKFLOW = Path(".github/workflows/update-news.yml").read_text(encoding="utf-8")


def test_workflow_runs_at_beijing_morning_and_evening_only():
    assert 'cron: "17 0 * * *"' in WORKFLOW
    assert 'cron: "47 12 * * *"' in WORKFLOW
    assert 'cron: "17 * * * *"' not in WORKFLOW


def test_workflow_builds_creator_brief_before_telegram_and_commit():
    creator = WORKFLOW.index("python scripts/creator_pipeline.py")
    telegram = WORKFLOW.index("python scripts/telegram_publish.py")
    commit = WORKFLOW.index("Commit and push changes")
    assert creator < telegram < commit


def test_workflow_uses_secret_backed_llm_and_telegram_credentials():
    assert "LLM_API_KEY: ${{ secrets.LLM_API_KEY || secrets.DEEPSEEK_API_KEY }}" in WORKFLOW
    assert "TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}" in WORKFLOW
    assert "TELEGRAM_CHANNEL_ID: ${{ secrets.TELEGRAM_CHANNEL_ID }}" in WORKFLOW


def test_workflow_keeps_existing_paid_source_and_push_safety_controls():
    assert "force_tikhub:" in WORKFLOW
    assert "TIKHUB_API_KEY: ${{ secrets.TIKHUB_API_KEY }}" in WORKFLOW
    assert "Generated files under data/ were not staged" in WORKFLOW
    assert "git pull --rebase origin" in WORKFLOW


def test_workflow_prefers_creator_feed_template_before_public_demo():
    creator_pos = WORKFLOW.index("feeds/martin-ai-coding.example.opml")
    upstream_pos = WORKFLOW.index("feeds/follow.example.opml")
    assert creator_pos < upstream_pos


def test_workflow_supports_manual_edition_and_publish_controls():
    assert "edition:" in WORKFLOW
    assert "options: [auto, morning, evening]" in WORKFLOW
    assert "publish_telegram:" in WORKFLOW
    assert 'echo "EDITION_KIND=$edition" >> "$GITHUB_ENV"' in WORKFLOW


def test_workflow_defaults_to_20_llm_calls():
    assert "LLM_MAX_CALLS_PER_RUN: ${{ vars.LLM_MAX_CALLS_PER_RUN || 20 }}" in WORKFLOW
