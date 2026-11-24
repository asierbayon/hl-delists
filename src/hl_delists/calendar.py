"""Load the published calendar and answer bot-facing questions."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hl_delists.timeutil import parse_instant

ACTIVE_STATUSES = {"scheduled", "delisted"}


def load_calendar(path: str | Path | None = None) -> dict[str, Any]:
    calendar_path = Path(path) if path is not None else _default_calendar_path()
    return json.loads(calendar_path.read_text(encoding="utf-8"))


def is_scheduled_for_delist(
    coin: str,
    *,
    at: datetime | str | None = None,
    calendar: dict[str, Any] | None = None,
) -> bool:
    moment = _as_datetime(at)
    for entry in _entries(calendar):
        if entry.get("status") != "scheduled":
            continue
        if not _coin_matches(coin, entry):
            continue
        if _still_scheduled(entry, moment):
            return True
    return False


def upcoming_delists(
    *,
    at: datetime | str | None = None,
    calendar: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    moment = _as_datetime(at)
    found = []
    for entry in _entries(calendar):
        if entry.get("status") != "scheduled":
            continue
        if _still_scheduled(entry, moment):
            found.append(entry)
    found.sort(key=_sort_key)
    return found


def blacklist_coins(
    *,
    at: datetime | str | None = None,
    calendar: dict[str, Any] | None = None,
) -> list[str]:
    """Main-perp tickers and dex-qualified HIP-3 names to avoid."""
    moment = _as_datetime(at)
    names: set[str] = set()
    for entry in _entries(calendar):
        if entry.get("status") not in ACTIVE_STATUSES:
            continue
        if entry.get("status") == "scheduled" and not _still_scheduled(entry, moment):
            continue
        names.add(_blacklist_name(entry))
    return sorted(names, key=str.upper)


def freqtrade_pair_blacklist(
    *,
    quote: str = "USDC",
    at: datetime | str | None = None,
    calendar: dict[str, Any] | None = None,
) -> list[str]:
    """Freqtrade pairs for main-dex perps. HIP-3 names are not rewritten."""
    moment = _as_datetime(at)
    pairs: set[str] = set()
    for entry in _entries(calendar):
        if entry.get("market") != "perp":
            continue
        if entry.get("dex"):
            continue
        if entry.get("status") not in ACTIVE_STATUSES:
            continue
        if entry.get("status") == "scheduled" and not _still_scheduled(entry, moment):
            continue
        asset = str(entry.get("asset") or "")
        if not asset:
            continue
        pairs.add(f"{asset}/{quote}:{quote}")
    return sorted(pairs)


def _entries(calendar: dict[str, Any] | None) -> list[dict[str, Any]]:
    data = calendar if calendar is not None else load_calendar()
    entries = data.get("entries") or []
    return [entry for entry in entries if isinstance(entry, dict)]


def _default_calendar_path() -> Path:
    override = os.environ.get("HL_DELISTS_FILE")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    bundled = here.parents[2] / "data" / "delistings.json"
    if bundled.exists():
        return bundled
    packaged = here.parent / "delistings.json"
    return packaged


def _as_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return parse_instant(value)


def _coin_matches(coin: str, entry: dict[str, Any]) -> bool:
    query = coin.strip()
    dex = entry.get("dex")
    asset = str(entry.get("asset") or "")
    if ":" in query:
        want_dex, want_asset = query.split(":", 1)
        if not dex:
            return False
        return want_dex.casefold() == str(dex).casefold() and want_asset.casefold() == asset.casefold()
    if dex:
        return False
    return query.casefold() == asset.casefold()


def _blacklist_name(entry: dict[str, Any]) -> str:
    asset = str(entry.get("asset") or "")
    dex = entry.get("dex")
    if dex:
        return f"{dex}:{asset}"
    return asset


def _still_scheduled(entry: dict[str, Any], moment: datetime) -> bool:
    for key in ("vote_time", "effective_time"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            return parse_instant(str(raw)) >= moment
        except ValueError:
            continue
    return True


def _sort_key(entry: dict[str, Any]) -> str:
    return str(entry.get("vote_time") or entry.get("effective_time") or entry.get("announced_at") or "")
