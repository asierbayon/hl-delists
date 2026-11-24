"""Turn announcement text into structured delist facts.

Facts keep the source's wording. Times described as "around" or
"approximately" are flagged and are not treated as exact chain timestamps.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from hl_delists.timeutil import (
    format_instant,
    parse_instant,
    parse_stated_datetime,
    shift_if_before_announcement,
)

TICKER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,14}$")
HIP3_BASE_RE = re.compile(r"^[A-Za-z0-9]{2,20}$")

STOP_ASSETS = {
    "USD",
    "USDC",
    "USDT",
    "USDE",
    "UTC",
    "PERP",
    "PERPS",
    "AND",
    "THE",
    "ALL",
    "NOTE",
    "HIP",
    "SPOT",
    "MARK",
}

VOTE_CUE_RE = re.compile(
    r"\b(?:whether to delist|vote to delist|voting whether to delist|"
    r"voting on whether to delist)\b",
    re.IGNORECASE,
)

DIRECT_RE = re.compile(
    r"(?P<assets>.+?)\s+will be delisted\s+(?P<when>[^.]{0,120}?\bUTC\b)",
    re.IGNORECASE,
)

REMINDER_RE = re.compile(
    r"\bDelisting\s+\$?(?P<asset>[A-Za-z][A-Za-z0-9]{0,14})\s+on\s+"
    r"(?P<when>[^.]{0,80}?\bUTC\b)",
    re.IGNORECASE,
)

CORRECTION_DATED_RE = re.compile(
    r"\b(?P<asset>[A-Za-z][A-Za-z0-9]{0,14})\s+perps?\s+will be delisted at\s+"
    r"(?P<when>\d{1,2}:\d{2}\s*UTC\s+on\s+.+?)\s+rather than\b",
    re.IGNORECASE,
)

CORRECTION_CLOCK_RE = re.compile(
    r"\bthe\s+(?P<asset>[A-Za-z][A-Za-z0-9]{0,14})\s+perp delisting will take place at\s+"
    r"(?P<approx>approximately\s+|approx\.?\s+|around\s+)?(?P<time>\d{1,2}:\d{2})\s*UTC\b",
    re.IGNORECASE,
)

POSTPONE_RE = re.compile(
    r"(?:\$?(?P<asset>[A-Za-z][A-Za-z0-9]{0,14})(?:-USD[A-Z]*)?\s+delisting will be postponed)"
    r"|(?:Postponed delisting of\s+\$?(?P<asset2>[A-Za-z][A-Za-z0-9]{0,14}))",
    re.IGNORECASE,
)

QUORUM_RE = re.compile(
    r"onchain delisting of\s+(?P<assets>.+?)\s+perps took place\b"
    r".{0,400}?quorum was reached at\s+(?P<time>\d{1,2}:\d{2})\s*UTC\b",
    re.IGNORECASE | re.DOTALL,
)

NOTICE_RE = re.compile(
    r"\bvoted to delist\s+(?P<asset>[A-Za-z][A-Za-z0-9]{0,14})\s+perps\b",
    re.IGNORECASE,
)

CONFIRM_FOR_RE = re.compile(
    r"\bdelisted perps for\s+(?P<assets>[^.\n]+)",
    re.IGNORECASE,
)

CONFIRM_HAS_RE = re.compile(
    r"\b(?P<asset>[A-Za-z][A-Za-z0-9]{0,14})\s+has been delisted\b",
    re.IGNORECASE,
)

SUNSET_RE = re.compile(
    r"All\s+(?P<label>[^()\n]+?)\s+\((?P<dex>[A-Za-z0-9]+)\)\s+markets will be wound down"
    r".{0,500}?starting from\s+(?P<start>.+?\bUTC\b)",
    re.IGNORECASE | re.DOTALL,
)

SUNSET_END_RE = re.compile(
    r"concluding on\s+(?P<end>.+?\bUTC\b)",
    re.IGNORECASE | re.DOTALL,
)

MARKETS_RE = re.compile(
    r"markets include:\s*(?P<body>.+)",
    re.IGNORECASE | re.DOTALL,
)

URL_RE = re.compile(r"https?://\S+")


def parse_message(
    text: str,
    *,
    source_url: str,
    announced_at: str,
    source_id: str,
    links: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Parse one announcement body into zero or more facts."""
    announced = parse_instant(announced_at)
    raw_text = text or ""
    found_links = list(links or [])
    for url in URL_RE.findall(raw_text):
        cleaned_url = url.rstrip(").,")
        if cleaned_url not in found_links:
            found_links.append(cleaned_url)
    cleaned = URL_RE.sub("", raw_text)
    message_settlement = _settlement(cleaned)
    facts: list[dict[str, Any]] = []
    facts.extend(
        _sunset_facts(
            cleaned,
            source_url=source_url,
            announced=announced,
            source_id=source_id,
            links=found_links,
        )
    )
    for raw_line in cleaned.splitlines():
        line = raw_line.strip().lstrip("+").strip()
        if "delist" not in line.lower():
            continue
        facts.extend(
            _line_facts(
                line,
                source_url=source_url,
                announced=announced,
                source_id=source_id,
            )
        )
    facts.extend(
        _quorum_facts(
            cleaned,
            source_url=source_url,
            announced=announced,
            source_id=source_id,
            links=found_links,
        )
    )
    for fact in facts:
        if fact.get("settlement"):
            continue
        if fact.get("fact") in {"schedule", "notice", "sunset"}:
            fact["settlement"] = message_settlement
    return facts


def parse_app_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    text, links = draftjs_text_and_links(entry.get("content"))
    uuid = str(entry.get("uuid") or "")
    source_url = f"https://app.hyperliquid.xyz/announcement/{uuid}"
    return parse_message(
        text,
        source_url=source_url,
        announced_at=str(entry.get("createdAt") or ""),
        source_id=f"app:{uuid}",
        links=links,
    )


def draftjs_text_and_links(content: Any) -> tuple[str, list[str]]:
    if isinstance(content, str):
        content = json.loads(content)
    if not isinstance(content, dict):
        return "", []
    blocks = content.get("blocks") or []
    lines = []
    for block in blocks:
        if isinstance(block, dict):
            lines.append(str(block.get("text") or ""))
    links: list[str] = []
    entity_map = content.get("entityMap") or {}
    if isinstance(entity_map, dict):
        for entity in entity_map.values():
            if not isinstance(entity, dict):
                continue
            data = entity.get("data") or {}
            url = data.get("url") if isinstance(data, dict) else None
            if isinstance(url, str) and url.startswith("http"):
                links.append(url)
    return "\n".join(lines).strip(), links


def _line_facts(
    line: str,
    *,
    source_url: str,
    announced: datetime,
    source_id: str,
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    postponement = _postponement(line, source_url, announced, source_id)
    if postponement is not None:
        facts.append(postponement)
    correction = _correction(line, source_url, announced, source_id)
    if correction is not None:
        facts.append(correction)
    elif VOTE_CUE_RE.search(line):
        facts.extend(_vote_schedules(line, source_url, announced, source_id))
    else:
        facts.extend(_direct_schedules(line, source_url, announced, source_id))
    notice = _notice(line, source_url, announced, source_id)
    if notice is not None:
        facts.append(notice)
    facts.extend(_confirmations(line, source_url, announced, source_id))
    return facts


def _base_fact(
    fact: str,
    *,
    source_url: str,
    announced: datetime,
    source_id: str,
    excerpt: str,
) -> dict[str, Any]:
    return {
        "fact": fact,
        "source_url": source_url,
        "source_id": source_id,
        "announced_at": format_instant(announced),
        "excerpt": _excerpt(excerpt),
    }


def _postponement(
    line: str,
    source_url: str,
    announced: datetime,
    source_id: str,
) -> dict[str, Any] | None:
    match = POSTPONE_RE.search(line)
    if match is None:
        return None
    asset = match.group("asset") or match.group("asset2")
    if not _is_ticker(asset):
        return None
    fact = _base_fact(
        "postponement",
        source_url=source_url,
        announced=announced,
        source_id=source_id,
        excerpt=line,
    )
    fact["asset"] = asset
    fact["market"] = "perp"
    return fact


def _correction(
    line: str,
    source_url: str,
    announced: datetime,
    source_id: str,
) -> dict[str, Any] | None:
    if not re.search(r"\b(rather than|instead of)\b", line, re.IGNORECASE):
        return None
    dated = CORRECTION_DATED_RE.search(line)
    if dated is not None:
        stated = _resolve_when(dated.group("when"), announced)
        if stated is None or not _is_ticker(dated.group("asset")):
            return None
        moment, approximate, _year_explicit = stated
        fact = _base_fact(
            "correction",
            source_url=source_url,
            announced=announced,
            source_id=source_id,
            excerpt=line,
        )
        fact["asset"] = dated.group("asset")
        fact["market"] = "perp"
        fact["when"] = format_instant(moment)
        fact["approximate"] = approximate
        return fact
    clock = CORRECTION_CLOCK_RE.search(line)
    if clock is None or not _is_ticker(clock.group("asset")):
        return None
    fact = _base_fact(
        "correction",
        source_url=source_url,
        announced=announced,
        source_id=source_id,
        excerpt=line,
    )
    fact["asset"] = clock.group("asset")
    fact["market"] = "perp"
    fact["clock"] = _clock(clock.group("time"))
    fact["approximate"] = True if clock.group("approx") else _is_approximate(line)
    return fact


def _vote_schedules(
    line: str,
    source_url: str,
    announced: datetime,
    source_id: str,
) -> list[dict[str, Any]]:
    match = re.search(r"\bdelist\s+(?P<body>.+)$", line, re.IGNORECASE)
    if match is None:
        return []
    body = match.group("body")
    located = _split_assets_and_when(body)
    if located is None:
        return []
    assets_blob, when_phrase = located
    stated = _resolve_when(when_phrase, announced)
    if stated is None:
        return []
    moment, approximate, _year_explicit = stated
    assets = split_assets(assets_blob)
    if not assets:
        return []
    market = "spot" if _is_spot_schedule(assets_blob, when_phrase) else "perp"
    facts = []
    for asset in assets:
        fact = _base_fact(
            "schedule",
            source_url=source_url,
            announced=announced,
            source_id=source_id,
            excerpt=line,
        )
        fact.update(
            {
                "kind": "delist_vote",
                "asset": asset,
                "market": market,
                "dex": None,
                "when": format_instant(moment),
                "approximate": approximate,
                "settlement": _settlement(line),
            }
        )
        facts.append(fact)
    return facts


def _direct_schedules(
    line: str,
    source_url: str,
    announced: datetime,
    source_id: str,
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    direct = DIRECT_RE.search(line)
    if direct is not None:
        stated = _resolve_when(direct.group("when"), announced)
        assets = split_assets(direct.group("assets"))
        if stated is not None and assets:
            moment, approximate, _year_explicit = stated
            market = "spot" if _is_spot_schedule(direct.group("assets"), direct.group("when")) else "perp"
            for asset in assets:
                fact = _base_fact(
                    "schedule",
                    source_url=source_url,
                    announced=announced,
                    source_id=source_id,
                    excerpt=line,
                )
                fact.update(
                    {
                        "kind": "scheduled_delist",
                        "asset": asset,
                        "market": market,
                        "dex": None,
                        "when": format_instant(moment),
                        "approximate": approximate,
                        "settlement": _settlement(line),
                    }
                )
                facts.append(fact)
    reminder = REMINDER_RE.search(line)
    if reminder is not None and _is_ticker(reminder.group("asset")):
        stated = _resolve_when(reminder.group("when"), announced)
        if stated is not None:
            moment, approximate, _year_explicit = stated
            fact = _base_fact(
                "schedule",
                source_url=source_url,
                announced=announced,
                source_id=source_id,
                excerpt=line,
            )
            fact.update(
                {
                    "kind": "scheduled_delist",
                    "asset": reminder.group("asset"),
                    "market": "perp",
                    "dex": None,
                    "when": format_instant(moment),
                    "approximate": approximate,
                    "settlement": _settlement(line),
                }
            )
            facts.append(fact)
    return facts


def _notice(
    line: str,
    source_url: str,
    announced: datetime,
    source_id: str,
) -> dict[str, Any] | None:
    match = NOTICE_RE.search(line)
    if match is None or not _is_ticker(match.group("asset")):
        return None
    fact = _base_fact(
        "notice",
        source_url=source_url,
        announced=announced,
        source_id=source_id,
        excerpt=line,
    )
    fact.update(
        {
            "kind": "delist_notice",
            "asset": match.group("asset"),
            "market": "perp",
            "dex": None,
            "settlement": _settlement(line),
        }
    )
    return fact


def _confirmations(
    line: str,
    source_url: str,
    announced: datetime,
    source_id: str,
) -> list[dict[str, Any]]:
    assets: list[str] = []
    for match in CONFIRM_FOR_RE.finditer(line):
        assets.extend(split_assets(match.group("assets")))
    for segment in line.split(";"):
        was = re.search(
            r"(?P<assets>.+?)\s+(?:perps?\s+)?(?:were|was) delisted\b",
            segment,
            re.IGNORECASE,
        )
        if was is None:
            continue
        blob = was.group("assets")
        pieces = re.split(r"\blisted\s+and\s+", blob, flags=re.IGNORECASE)
        assets.extend(split_assets(pieces[-1]))
    has = CONFIRM_HAS_RE.search(line)
    if has is not None and _is_ticker(has.group("asset")):
        assets.append(has.group("asset"))
    facts = []
    seen: set[str] = set()
    for asset in assets:
        if asset in seen:
            continue
        seen.add(asset)
        fact = _base_fact(
            "confirmation",
            source_url=source_url,
            announced=announced,
            source_id=source_id,
            excerpt=line,
        )
        fact["asset"] = asset
        fact["market"] = "perp"
        facts.append(fact)
    return facts


def _quorum_facts(
    text: str,
    *,
    source_url: str,
    announced: datetime,
    source_id: str,
    links: list[str],
) -> list[dict[str, Any]]:
    match = QUORUM_RE.search(text)
    if match is None:
        return []
    clock = _clock(match.group("time"))
    if clock is None:
        return []
    hour, minute = clock
    moment = announced.astimezone(timezone.utc).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    excerpt = _excerpt(match.group(0).replace("\n", " "))
    facts = []
    for asset in split_assets(match.group("assets")):
        fact = _base_fact(
            "quorum",
            source_url=source_url,
            announced=announced,
            source_id=source_id,
            excerpt=excerpt,
        )
        fact["asset"] = asset
        fact["market"] = "perp"
        fact["when"] = format_instant(moment)
        fact["reference_urls"] = [url for url in links if "/explorer/tx/" in url]
        facts.append(fact)
    return facts


def _sunset_facts(
    text: str,
    *,
    source_url: str,
    announced: datetime,
    source_id: str,
    links: list[str],
) -> list[dict[str, Any]]:
    match = SUNSET_RE.search(text)
    if match is None:
        return []
    start = _resolve_when(match.group("start"), announced)
    if start is None:
        return []
    start_at, start_approx, _year_explicit = start
    end_at = None
    end_match = SUNSET_END_RE.search(text)
    if end_match is not None:
        resolved_end = _resolve_when(end_match.group("end"), announced)
        if resolved_end is not None:
            end_at = resolved_end[0]
    markets = _sunset_markets(text)
    if not markets:
        return []
    settlement = "final_mark_price" if re.search(r"final mark price", text, re.IGNORECASE) else _settlement(text)
    facts = []
    for market_name, asset in markets:
        fact = _base_fact(
            "sunset",
            source_url=source_url,
            announced=announced,
            source_id=source_id,
            excerpt=text,
        )
        fact.update(
            {
                "kind": "hip3_sunset",
                "asset": asset,
                "market_name": market_name,
                "market": "hip3",
                "dex": match.group("dex"),
                "dex_label": match.group("label").strip(),
                "when": format_instant(start_at),
                "when_end": format_instant(end_at) if end_at else None,
                "approximate": start_approx,
                "settlement": settlement,
                "reference_urls": list(links),
            }
        )
        facts.append(fact)
    return facts


def _sunset_markets(text: str) -> list[tuple[str, str]]:
    match = MARKETS_RE.search(text)
    if match is None:
        return []
    body = match.group("body").strip()
    body = body.split("\n\n", 1)[0]
    body = body.strip().rstrip(".")
    found: list[tuple[str, str]] = []
    for part in re.split(r",|\band\b", body):
        token = part.strip().strip(".").strip()
        if not token or "-" not in token:
            continue
        base, _quote = token.split("-", 1)
        if not HIP3_BASE_RE.fullmatch(base):
            continue
        if base.upper() in STOP_ASSETS:
            continue
        found.append((token, base))
    return found


def _split_assets_and_when(body: str) -> tuple[str, str] | None:
    from hl_delists.timeutil import DATE_RE, TIME_RE

    time_match = TIME_RE.search(body)
    date_match = DATE_RE.search(body)
    if time_match is None or date_match is None:
        return None
    cut = min(time_match.start(), date_match.start())
    prefix = body[:cut]
    preposition = re.search(r"\b(around|on|at)\s*$", prefix, re.IGNORECASE)
    if preposition is not None:
        assets_blob = prefix[: preposition.start()]
        when_phrase = body[preposition.start() :]
    else:
        assets_blob = prefix
        when_phrase = body[cut:]
    assets_blob = re.sub(r"\s+as part of\s+.*$", "", assets_blob, flags=re.IGNORECASE)
    assets_blob = re.sub(r"\s+perps?\s*$", "", assets_blob, flags=re.IGNORECASE)
    # The when-phrase should run through the UTC token, not the rest of the sentence.
    utc = re.search(r"\bUTC\b", when_phrase, re.IGNORECASE)
    if utc is not None:
        # Keep a trailing date that sits after "UTC on <date>".
        after = when_phrase[utc.end() :]
        trailing_date = DATE_RE.search(after)
        if trailing_date is not None and after[: trailing_date.start()].strip() in {"", "on"}:
            when_phrase = when_phrase[: utc.end() + trailing_date.end()]
        else:
            when_phrase = when_phrase[: utc.end()]
    return assets_blob, when_phrase


def split_assets(blob: str) -> list[str]:
    text = blob.replace(" & ", " and ")
    text = re.sub(r"\s+and\s+", ", ", text, flags=re.IGNORECASE)
    assets: list[str] = []
    for raw in text.split(","):
        token = raw.strip().strip(".").strip()
        token = re.sub(r"-USD[A-Z]*$", "", token, flags=re.IGNORECASE)
        token = token.lstrip("$")
        token = re.sub(r"\s+perps?$", "", token, flags=re.IGNORECASE)
        token = token.strip()
        if _is_ticker(token):
            assets.append(token)
    return assets


def _resolve_when(
    phrase: str, announced: datetime
) -> tuple[datetime, bool, bool] | None:
    parsed = parse_stated_datetime(phrase, announced.year)
    if parsed is None:
        return None
    moment, approximate, year_explicit = parsed
    if not year_explicit:
        moment = shift_if_before_announcement(moment, announced)
    return moment, approximate, year_explicit


def _settlement(text: str) -> str | None:
    lowered = text.lower()
    if "final mark price" in lowered:
        return "final_mark_price"
    if "1 hour time weighted" in lowered or "1h twap" in lowered:
        return "1h_oracle_twap"
    if "mark price" in lowered:
        return "mark_price"
    return None


def _is_spot_schedule(assets_blob: str, when_phrase: str) -> bool:
    window = f"{assets_blob} {when_phrase}".lower()
    if "spot oracle" in window:
        return False
    return re.search(r"\bspot\b", window) is not None


def _is_ticker(value: str | None) -> bool:
    if not value or not TICKER_RE.fullmatch(value):
        return False
    return value.upper() not in STOP_ASSETS


def _is_approximate(phrase: str) -> bool:
    return re.search(r"\b(around|approximately|approx\.?)\b", phrase, re.IGNORECASE) is not None


def _clock(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if match is None:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _excerpt(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= 500:
        return compact
    return compact[:497] + "..."
