from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

STATUS_ICON = {
    "confirmed": "✅",
    "single_source": "◻️",
    "early_signal": "👀",
    "rumor": "⚠️",
}
STATUS_TEXT = {
    "confirmed": "已确认",
    "single_source": "单一来源",
    "early_signal": "早期信号",
    "rumor": "待确认",
}
CHANGE_ICON = {"new": "", "confirmed": "🔄", "updated": "🆕"}
PLATFORM_LABEL = {"x": "X", "xiaohongshu": "小红书", "wechat": "公众号"}


def status_text(status: str) -> str:
    return STATUS_TEXT.get(str(status or ""), str(status or "单一来源"))


def source_count_label(item: dict[str, Any]) -> str:
    try:
        count = int(item.get("source_count") or 1)
    except (TypeError, ValueError):
        count = 1
    return f" · 多源 {count}" if count > 1 else ""


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return default


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _plain(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _escaped(value: Any, limit: int) -> str:
    return html.escape(_plain(value, limit), quote=True)


def _safe_url(value: Any) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return html.escape(text, quote=True)


def _edition_title(edition: dict[str, Any]) -> str:
    kind = str(edition.get("edition_kind") or "morning")
    icon, label = ("🌅", "早报") if kind == "morning" else ("🌙", "晚报")
    date_text = str(edition.get("edition_id") or "").split("-")
    date_label = "-".join(date_text[:3]) if len(date_text) >= 3 else str(edition.get("edition_id") or "")
    return f"{icon} <b>AI Coding {label}｜{html.escape(date_label)}</b>"


def _render_item(item: dict[str, Any], index: int, target: int) -> str:
    title_limit, summary_limit, why_limit = 180, 240, 200
    while True:
        status = str(item.get("verification_status") or "single_source")
        change = str(item.get("change_type") or "new")
        score = item.get("creator_score")
        score_text = f"｜评分 {score:g}" if isinstance(score, (int, float)) else ""
        source_url = _safe_url(item.get("url") or item.get("primary_url"))
        source_line = f'原始来源： <a href="{source_url}">{source_url}</a>' if source_url else ""
        lines = [
            f"<b>{index}. {_escaped(item.get('title'), title_limit)}</b>",
            (
                f"{STATUS_ICON.get(status, '◻️')} "
                f"{html.escape(status_text(status))}"
                f"{html.escape(source_count_label(item))}"
                f"{score_text} {CHANGE_ICON.get(change, '')}"
            ).strip(),
            f"发生了什么：{_escaped(item.get('summary_zh'), summary_limit)}",
            f"为什么重要：{_escaped(item.get('why_it_matters'), why_limit)}",
        ]
        if source_line:
            lines.append(source_line)
        block = "\n".join(lines)
        if len(block) <= target:
            return block
        if title_limit <= 24 and summary_limit <= 36 and why_limit <= 36:
            minimal = f"<b>{index}. {_escaped(item.get('title'), 24)}</b>\n{source_line}".strip()
            return minimal if len(minimal) <= target else f"<b>{index}. 资讯更新</b>"
        title_limit = max(24, int(title_limit * 0.7))
        summary_limit = max(36, int(summary_limit * 0.7))
        why_limit = max(36, int(why_limit * 0.7))


def _angle_blocks(edition: dict[str, Any], target: int) -> list[str]:
    blocks: list[str] = []
    count = 0
    for item in edition.get("items", []):
        angles = item.get("angles")
        if not isinstance(angles, list):
            continue
        for angle in angles:
            if count >= 3 or not isinstance(angle, dict):
                break
            platform = PLATFORM_LABEL.get(str(angle.get("platform") or "").lower(), "选题")
            block = (
                f"• <b>[{html.escape(platform)}] {_escaped(angle.get('title'), 80)}</b>\n"
                f"  {_escaped(angle.get('angle'), 150)}"
            )
            if len(block) > target:
                block = f"• <b>[{html.escape(platform)}] {_escaped(angle.get('title'), 50)}</b>"
            blocks.append(block)
            count += 1
        if count >= 3:
            break
    if not blocks:
        return []
    return ["✍️ <b>今日选题</b>", *blocks]


def render_messages(edition: dict[str, Any], max_chars: int = 3900) -> list[str]:
    if max_chars < 400:
        raise ValueError("max_chars_too_small")
    title = _edition_title(edition)
    continuation = "📎 <b>AI Coding 情报续</b>"
    item_target = max_chars - len(continuation) - 4
    blocks = [
        _render_item(item, index, item_target)
        for index, item in enumerate(edition.get("items", []), start=1)
        if isinstance(item, dict)
    ]
    blocks.extend(_angle_blocks(edition, item_target))
    if not blocks:
        blocks = ["本期暂无达到推送门槛的新信息。"]

    messages: list[str] = []
    current = title
    for block in blocks:
        separator = "\n\n"
        if len(current) + len(separator) + len(block) <= max_chars:
            current += separator + block
            continue
        messages.append(current)
        current = continuation + separator + block
    if current:
        messages.append(current)
    return messages


def should_send(edition_id: str, state: dict[str, Any]) -> bool:
    return bool(edition_id) and str(state.get("last_sent_edition_id") or "") != str(edition_id)


def send_message(token: str, chat_id: str, text: str) -> dict[str, Any]:
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise RuntimeError("telegram_not_ok")
    return payload


def _enabled() -> bool:
    value = str(os.environ.get("TELEGRAM_ENABLED") or "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def publish(
    edition_path: Path,
    state_path: Path,
    *,
    dry_run: bool = False,
    max_chars: int = 3900,
) -> int:
    edition = _load_json(edition_path, {})
    if not isinstance(edition, dict):
        raise ValueError("edition_shape")
    edition_id = str(edition.get("edition_id") or "")
    state = _load_json(state_path, {})
    if not isinstance(state, dict):
        state = {}
    if not should_send(edition_id, state):
        print(f"telegram: skip already sent edition={edition_id}")
        return 0
    if not edition.get("items"):
        print(f"telegram: skip empty edition={edition_id}")
        return 0

    messages = render_messages(edition, max_chars=max_chars)
    if dry_run:
        for index, message in enumerate(messages, start=1):
            print(f"--- Telegram {index}/{len(messages)} ---")
            print(message)
        return 0

    if not _enabled():
        print("telegram: disabled")
        return 0
    token = str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(os.environ.get("TELEGRAM_CHANNEL_ID") or "").strip()
    if not token or not chat_id:
        print("telegram: skipped because token or channel id is missing")
        return 0

    message_ids: list[Any] = []
    for message in messages:
        result = send_message(token, chat_id, message)
        message_ids.append((result.get("result") or {}).get("message_id") if isinstance(result.get("result"), dict) else None)

    _write_json_atomic(
        state_path,
        {
            "version": 1,
            "last_sent_edition_id": edition_id,
            "last_sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "message_count": len(messages),
            "message_ids": message_ids,
        },
    )
    print(f"telegram: sent edition={edition_id} messages={len(messages)}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish creator brief to Telegram")
    parser.add_argument("--edition-file", default="data/creator-brief.json")
    parser.add_argument("--state-file", default="data/telegram-state.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-chars", type=int, default=3900)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return publish(
        Path(args.edition_file),
        Path(args.state_file),
        dry_run=args.dry_run,
        max_chars=args.max_chars,
    )


if __name__ == "__main__":
    raise SystemExit(main())
