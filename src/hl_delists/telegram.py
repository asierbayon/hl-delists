"""Read the public Telegram preview of @hyperliquid_announcements."""

from __future__ import annotations

import html
import re
from typing import Any

MESSAGE_SPLIT_RE = re.compile(r'<div class="tgme_widget_message_wrap')
POST_RE = re.compile(r'data-post="hyperliquid_announcements/(\d+)"')
TIME_RE = re.compile(r'datetime="([^"]+)"')
TEXT_RE = re.compile(
    r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL,
)
BEFORE_RE = re.compile(
    r'class="tme_messages_more js-messages_more" data-before="(\d+)"'
)
TAG_RE = re.compile(r"<[^>]+>")
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def parse_telegram_html(page: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    seen: set[int] = set()
    parts = MESSAGE_SPLIT_RE.split(page)
    for part in parts[1:]:
        post = POST_RE.search(part)
        if post is None:
            continue
        message_id = int(post.group(1))
        if message_id in seen:
            continue
        seen.add(message_id)
        stamp = TIME_RE.search(part)
        text_match = TEXT_RE.search(part)
        text = ""
        if text_match is not None:
            raw = BR_RE.sub("\n", text_match.group(1))
            raw = TAG_RE.sub("", raw)
            text = html.unescape(raw).strip()
        messages.append(
            {
                "id": message_id,
                "datetime": stamp.group(1) if stamp else None,
                "text": text,
                "url": f"https://t.me/hyperliquid_announcements/{message_id}",
            }
        )
    messages.sort(key=lambda item: int(item["id"]))
    return messages


def next_before(page: str) -> int | None:
    match = BEFORE_RE.search(page)
    if match is None:
        return None
    return int(match.group(1))
