"""RSS, iCalendar, and a small HTML page for the delist calendar."""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any

from hl_delists.timeutil import parse_instant

PAGE_URL = "https://asierbayon.github.io/hl-delists/"
REPO_URL = "https://github.com/asierbayon/hl-delists"


def render_rss(document: dict[str, Any]) -> str:
    generated = parse_instant(str(document["generated_at"]))
    items = []
    for entry in document.get("entries") or []:
        title = _item_title(entry)
        description = _item_description(entry)
        items.append(
            "\n".join(
                [
                    "    <item>",
                    f"      <title>{_xml(title)}</title>",
                    f"      <link>{_xml(entry['source_url'])}</link>",
                    f"      <guid isPermaLink=\"false\">{_xml(entry['id'])}</guid>",
                    f"      <pubDate>{_xml(_rfc822(entry.get('announced_at'), generated))}</pubDate>",
                    f"      <description>{_xml(description)}</description>",
                    "    </item>",
                ]
            )
        )
    body = "\n".join(items)
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<rss version=\"2.0\">\n"
        "  <channel>\n"
        "    <title>Hyperliquid delistings</title>\n"
        f"    <link>{_xml(PAGE_URL)}</link>\n"
        "    <description>Scheduled and completed Hyperliquid delistings, "
        "each linked to its public source. Times the source called approximate "
        "are marked as such.</description>\n"
        f"    <lastBuildDate>{_xml(format_datetime(generated))}</lastBuildDate>\n"
        f"{body}\n"
        "  </channel>\n"
        "</rss>\n"
    )


def render_ics(document: dict[str, Any]) -> str:
    generated = parse_instant(str(document["generated_at"]))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//hl-delists//Hyperliquid delistings//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Hyperliquid delistings",
        _fold(f"X-WR-CALDESC:Delist votes and scheduled delistings from public Hyperliquid announcements. See {REPO_URL}"),
    ]
    for entry in document.get("entries") or []:
        start = entry.get("vote_time") or entry.get("effective_time")
        if not start:
            continue
        start_at = parse_instant(str(start))
        if entry.get("effective_time_end"):
            end_at = parse_instant(str(entry["effective_time_end"]))
        else:
            # DTEND is exclusive. A one-minute block keeps the stated instant visible.
            end_at = start_at + timedelta(minutes=1)
        summary = _item_title(entry)
        description = _item_description(entry)
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{_ics_text(entry['id'])}@hl-delists",
                f"DTSTAMP:{_ics_stamp(generated)}",
                f"DTSTART:{_ics_stamp(start_at)}",
                f"DTEND:{_ics_stamp(end_at)}",
                _fold(f"SUMMARY:{_ics_text(summary)}"),
                _fold(f"DESCRIPTION:{_ics_text(description)}"),
                _fold(f"URL:{entry['source_url']}"),
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def render_html(document: dict[str, Any]) -> str:
    rows = []
    for entry in document.get("entries") or []:
        when = entry.get("vote_time") or entry.get("effective_time") or ""
        if entry.get("vote_time_approximate") or entry.get("effective_time_approximate"):
            when = f"{when} (approximate)" if when else "approximate"
        asset = entry["asset"]
        if entry.get("dex"):
            asset = f"{entry['dex']}:{asset}"
        rows.append(
            "<tr>"
            f"<td>{_html(entry.get('status'))}</td>"
            f"<td>{_html(asset)}</td>"
            f"<td>{_html(entry.get('market'))}</td>"
            f"<td>{_html(entry.get('kind'))}</td>"
            f"<td>{_html(when)}</td>"
            f"<td><a href=\"{_html(entry['source_url'])}\">source</a></td>"
            "</tr>"
        )
    count = len(document.get("entries") or [])
    generated = _html(document.get("generated_at"))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hyperliquid delistings</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.45; color: #172026; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 0.92rem; }}
    th, td {{ border-bottom: 1px solid #d5dde2; text-align: left; padding: 0.35rem 0.5rem; vertical-align: top; }}
    a {{ color: #0b57d0; }}
  </style>
</head>
<body>
  <h1>Hyperliquid delistings</h1>
  <p>Machine-readable calendar of public Hyperliquid delist announcements. {count} entries. Generated {generated}.</p>
  <p>
    <a href="delistings.json">delistings.json</a> ·
    <a href="delistings.rss">RSS</a> ·
    <a href="delistings.ics">ICS</a> ·
    <a href="freqtrade-blacklist.json">Freqtrade blacklist</a> ·
    <a href="schema.json">schema</a> ·
    <a href="{REPO_URL}">source</a>
  </p>
  <p>This is an unofficial compilation of public posts and the exchange info API. It is not a product of Hyperliquid and it is not trading advice. Open the source link before acting on a row. Times marked approximate were described that way by the announcement.</p>
  <table>
    <thead>
      <tr><th>Status</th><th>Asset</th><th>Market</th><th>Kind</th><th>Time (UTC)</th><th>Source</th></tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>
"""


def _item_title(entry: dict[str, Any]) -> str:
    asset = entry["asset"]
    if entry.get("dex"):
        asset = f"{entry['dex']}:{asset}"
    kind = str(entry.get("kind") or "delist").replace("_", " ")
    return f"{asset} {kind} ({entry.get('status')})"


def _item_description(entry: dict[str, Any]) -> str:
    parts = [
        f"Status: {entry.get('status')}",
        f"Market: {entry.get('market')}",
    ]
    if entry.get("vote_time"):
        approx = " (approximate)" if entry.get("vote_time_approximate") else ""
        parts.append(f"Vote time: {entry['vote_time']}{approx}")
    if entry.get("effective_time"):
        approx = " (approximate)" if entry.get("effective_time_approximate") else ""
        parts.append(f"Effective time: {entry['effective_time']}{approx}")
    if entry.get("effective_time_end"):
        parts.append(f"Window end: {entry['effective_time_end']}")
    if entry.get("settlement"):
        parts.append(f"Settlement described as: {entry['settlement']}")
    parts.append(f"Source: {entry.get('source_url')}")
    if entry.get("excerpt"):
        parts.append(str(entry["excerpt"]))
    return "\n".join(parts)


def _rfc822(value: str | None, fallback: datetime) -> str:
    if not value:
        return format_datetime(fallback)
    return format_datetime(parse_instant(value))


def _ics_stamp(value: datetime) -> str:
    utc = value.astimezone(timezone.utc).replace(microsecond=0)
    return utc.strftime("%Y%m%dT%H%M%SZ")


def _ics_text(value: str) -> str:
    text = str(value).replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")
    return text


def _fold(line: str) -> str:
    raw = line.encode("utf-8")
    if len(raw) <= 73:
        return line
    chunks: list[str] = []
    current = ""
    current_len = 0
    limit = 73
    for char in line:
        encoded = len(char.encode("utf-8"))
        if current and current_len + encoded > limit:
            chunks.append(current)
            current = char
            current_len = encoded
            limit = 72
            continue
        current += char
        current_len += encoded
    if current:
        chunks.append(current)
    return "\r\n ".join(chunks)


def _xml(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _html(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)
