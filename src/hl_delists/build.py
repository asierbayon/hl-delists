"""Merge parsed facts into the published delist calendar."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from hl_delists.timeutil import format_instant, parse_instant

INFO_URL = "https://api.hyperliquid.xyz/info"
CLOSE = timedelta(hours=2)


def assemble(
    facts: list[dict[str, Any]],
    *,
    meta: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    schedules = [dict(fact) for fact in facts if fact["fact"] == "schedule"]
    corrections = [fact for fact in facts if fact["fact"] == "correction"]
    postponements = [fact for fact in facts if fact["fact"] == "postponement"]
    confirmations = [fact for fact in facts if fact["fact"] == "confirmation"]
    quorums = [fact for fact in facts if fact["fact"] == "quorum"]
    notices = [dict(fact) for fact in facts if fact["fact"] == "notice"]
    sunsets = [dict(fact) for fact in facts if fact["fact"] == "sunset"]

    for schedule in schedules:
        _ensure_lists(schedule)
    schedules = _dedupe_schedules(schedules)
    _apply_corrections(schedules, corrections)
    _apply_postponements(schedules, postponements)
    _apply_quorums(schedules, quorums)
    attached = _apply_confirmations(schedules, notices, confirmations)

    entries = [_schedule_entry(item) for item in schedules]
    entries.extend(_notice_entries(notices))
    entries.extend(_sunset_entries(sunsets))
    entries.extend(_orphan_confirmations(confirmations, attached, entries))
    _mark_later_schedules(entries)
    _annotate_meta(entries, meta)
    for entry in entries:
        entry["status"] = _status(entry, now)
    entries.extend(_observed(entries, meta))
    entries.sort(key=lambda item: (item.get("announced_at") or "", item["asset"].upper(), item["id"]))
    return entries


def _ensure_lists(schedule: dict[str, Any]) -> None:
    if "source_urls" not in schedule:
        schedule["source_urls"] = [schedule["source_url"]]
    if "source_ids" not in schedule:
        schedule["source_ids"] = [schedule["source_id"]]
    if "reference_urls" not in schedule:
        schedule["reference_urls"] = []
    if "confirmation_urls" not in schedule:
        schedule["confirmation_urls"] = []
    if "postponed" not in schedule:
        schedule["postponed"] = False
    if "quorum_time" not in schedule:
        schedule["quorum_time"] = None


def _dedupe_schedules(schedules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for schedule in sorted(schedules, key=lambda item: item["announced_at"]):
        match = None
        for existing in merged:
            if _same_market(existing, schedule) and existing["kind"] == schedule["kind"]:
                if _times_close(existing.get("when"), schedule.get("when")):
                    match = existing
                    break
        if match is None:
            merged.append(schedule)
            continue
        _merge_sources(match, schedule)
        if not match.get("settlement") and schedule.get("settlement"):
            match["settlement"] = schedule["settlement"]
        if schedule["announced_at"] < match["announced_at"]:
            match["announced_at"] = schedule["announced_at"]
            match["excerpt"] = schedule["excerpt"]
    return merged


def _apply_corrections(
    schedules: list[dict[str, Any]], corrections: list[dict[str, Any]]
) -> None:
    for correction in sorted(corrections, key=lambda item: item["announced_at"]):
        candidates = [
            schedule
            for schedule in schedules
            if _same_market(schedule, correction)
            and schedule["announced_at"] <= correction["announced_at"]
        ]
        if not candidates:
            continue
        target = max(candidates, key=lambda item: item["announced_at"])
        if correction.get("when"):
            target["when"] = correction["when"]
            target["approximate"] = bool(correction.get("approximate"))
        elif correction.get("clock") and target.get("when"):
            hour, minute = correction["clock"]
            moment = parse_instant(target["when"]).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            target["when"] = format_instant(moment)
            target["approximate"] = bool(correction.get("approximate"))
        _add_url(target, correction["source_url"], correction["source_id"])


def _apply_postponements(
    schedules: list[dict[str, Any]], postponements: list[dict[str, Any]]
) -> None:
    for postponement in postponements:
        candidates = [
            schedule
            for schedule in schedules
            if _same_market(schedule, postponement)
            and schedule["announced_at"] <= postponement["announced_at"]
        ]
        if not candidates:
            continue
        target = max(candidates, key=lambda item: item["announced_at"])
        target["postponed"] = True
        _add_url(target, postponement["source_url"], postponement["source_id"])


def _apply_quorums(schedules: list[dict[str, Any]], quorums: list[dict[str, Any]]) -> None:
    for quorum in quorums:
        candidates = [
            schedule
            for schedule in schedules
            if _same_market(schedule, quorum) and schedule.get("when")
        ]
        if not candidates:
            continue
        quorum_at = parse_instant(quorum["when"])
        close = [
            schedule
            for schedule in candidates
            if abs((parse_instant(schedule["when"]) - quorum_at).total_seconds()) <= 3 * 24 * 3600
        ]
        if not close:
            continue
        target = min(close, key=lambda item: abs((parse_instant(item["when"]) - quorum_at).total_seconds()))
        target["quorum_time"] = quorum["when"]
        target["reference_urls"] = _unique(target["reference_urls"] + list(quorum.get("reference_urls") or []))
        _add_url(target, quorum["source_url"], quorum["source_id"])


def _apply_confirmations(
    schedules: list[dict[str, Any]],
    notices: list[dict[str, Any]],
    confirmations: list[dict[str, Any]],
) -> set[tuple[str, str]]:
    attached: set[tuple[str, str]] = set()
    for notice in notices:
        _ensure_lists(notice)
    for confirmation in confirmations:
        key = (_asset_key(confirmation), confirmation["source_url"])
        schedule_hits = [
            schedule
            for schedule in schedules
            if _same_market(schedule, confirmation)
            and schedule.get("when")
            and parse_instant(schedule["when"]) <= parse_instant(confirmation["announced_at"]) + timedelta(days=2)
        ]
        if schedule_hits:
            target = max(schedule_hits, key=lambda item: item["when"])
            target["confirmation_urls"] = _unique(target["confirmation_urls"] + [confirmation["source_url"]])
            _add_url(target, confirmation["source_url"], confirmation["source_id"])
            attached.add(key)
            continue
        notice_hits = [notice for notice in notices if _same_market(notice, confirmation)]
        if notice_hits:
            target = notice_hits[0]
            target["confirmation_urls"] = _unique(target["confirmation_urls"] + [confirmation["source_url"]])
            _add_url(target, confirmation["source_url"], confirmation["source_id"])
            attached.add(key)
    return attached


def _schedule_entry(schedule: dict[str, Any]) -> dict[str, Any]:
    kind = schedule["kind"]
    approximate = bool(schedule.get("approximate"))
    vote_time = schedule["when"] if kind == "delist_vote" else None
    effective_time = schedule.get("quorum_time")
    effective_approximate = False
    if kind == "scheduled_delist":
        effective_time = schedule["when"]
        effective_approximate = approximate
    entry = _blank_entry(
        asset=schedule["asset"],
        market=schedule["market"],
        dex=schedule.get("dex"),
        kind=kind,
        announced_at=schedule["announced_at"],
        source_url=_preferred_url(schedule),
        source_urls=_unique(schedule["source_urls"]),
        excerpt=schedule["excerpt"],
    )
    entry["vote_time"] = vote_time
    entry["vote_time_approximate"] = approximate if vote_time else False
    entry["effective_time"] = effective_time
    entry["effective_time_approximate"] = effective_approximate
    entry["settlement"] = schedule.get("settlement")
    entry["reference_urls"] = _unique(schedule.get("reference_urls") or [])
    entry["_postponed"] = bool(schedule.get("postponed"))
    entry["_confirmed"] = bool(schedule.get("confirmation_urls") or schedule.get("quorum_time"))
    entry["_when"] = schedule.get("when")
    entry["id"] = _entry_id(schedule)
    return entry


def _notice_entries(notices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for notice in notices:
        _ensure_lists(notice)
        entry = _blank_entry(
            asset=notice["asset"],
            market=notice.get("market") or "perp",
            dex=notice.get("dex"),
            kind="delist_notice",
            announced_at=notice["announced_at"],
            source_url=notice["source_url"],
            source_urls=_unique(notice["source_urls"]),
            excerpt=notice["excerpt"],
        )
        entry["settlement"] = notice.get("settlement")
        entry["reference_urls"] = _unique(notice.get("reference_urls") or [])
        entry["_postponed"] = False
        entry["_confirmed"] = bool(notice.get("confirmation_urls"))
        entry["_when"] = None
        entry["id"] = _entry_id(notice)
        entries.append(entry)
    return entries


def _sunset_entries(sunsets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for sunset in sorted(sunsets, key=lambda item: item["announced_at"]):
        sunset = dict(sunset)
        _ensure_lists(sunset)
        match = None
        for existing in merged:
            if (
                _same_market(existing, sunset)
                and existing.get("market_name") == sunset.get("market_name")
                and _times_close(existing.get("when"), sunset.get("when"))
            ):
                match = existing
                break
        if match is None:
            merged.append(sunset)
            continue
        _merge_sources(match, sunset)
    entries = []
    for sunset in merged:
        entry = _blank_entry(
            asset=sunset["asset"],
            market="hip3",
            dex=sunset.get("dex"),
            kind="hip3_sunset",
            announced_at=sunset["announced_at"],
            source_url=_preferred_url(sunset),
            source_urls=_unique(sunset["source_urls"]),
            excerpt=sunset["excerpt"],
        )
        entry["market_name"] = sunset.get("market_name")
        entry["effective_time"] = sunset.get("when")
        entry["effective_time_end"] = sunset.get("when_end")
        entry["effective_time_approximate"] = bool(sunset.get("approximate"))
        entry["settlement"] = sunset.get("settlement")
        entry["reference_urls"] = _unique(sunset.get("reference_urls") or [])
        entry["_postponed"] = False
        entry["_confirmed"] = False
        entry["_when"] = sunset.get("when")
        entry["id"] = _entry_id(sunset)
        entries.append(entry)
    return entries


def _orphan_confirmations(
    confirmations: list[dict[str, Any]],
    attached: set[tuple[str, str]],
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    known = {_asset_key(entry) for entry in entries}
    grouped: dict[str, dict[str, Any]] = {}
    for confirmation in confirmations:
        key = (_asset_key(confirmation), confirmation["source_url"])
        if key in attached or _asset_key(confirmation) in known:
            continue
        asset_key = _asset_key(confirmation)
        current = grouped.get(asset_key)
        if current is None:
            grouped[asset_key] = dict(confirmation)
            grouped[asset_key]["source_urls"] = [confirmation["source_url"]]
            continue
        current["source_urls"].append(confirmation["source_url"])
    orphans = []
    for confirmation in grouped.values():
        entry = _blank_entry(
            asset=confirmation["asset"],
            market=confirmation.get("market") or "perp",
            dex=confirmation.get("dex"),
            kind="delist_notice",
            announced_at=confirmation["announced_at"],
            source_url=confirmation["source_url"],
            source_urls=_unique(confirmation["source_urls"]),
            excerpt=confirmation["excerpt"],
        )
        entry["_postponed"] = False
        entry["_confirmed"] = True
        entry["_when"] = None
        entry["id"] = _entry_id(confirmation)
        orphans.append(entry)
    return orphans


def _mark_later_schedules(entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        entry["_later"] = False
        if entry["kind"] not in {"delist_vote", "scheduled_delist"} or not entry.get("_when"):
            continue
        for other in entries:
            if other is entry or other["kind"] != entry["kind"]:
                continue
            if not _same_market(entry, other) or not other.get("_when"):
                continue
            if other["_when"] > entry["_when"]:
                entry["_later"] = True
                break


def _annotate_meta(entries: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    perps = meta.get("perps") or {}
    dexes = meta.get("dexes") or {}
    for entry in entries:
        entry["api_coin"] = None
        entry["api_is_delisted"] = None
        if entry["market"] == "perp":
            asset = entry["asset"]
            if asset in perps:
                entry["api_coin"] = asset
                entry["api_is_delisted"] = bool(perps[asset])
            continue
        if entry["market"] != "hip3" or not entry.get("dex"):
            continue
        coin = f"{entry['dex']}:{entry['asset']}"
        dex_map = dexes.get(entry["dex"]) or {}
        if coin in dex_map:
            entry["api_coin"] = coin
            entry["api_is_delisted"] = bool(dex_map[coin])


def _status(entry: dict[str, Any], now: datetime) -> str:
    if entry.get("_postponed") and entry.get("api_is_delisted") is not True:
        return "postponed"
    if entry.get("_confirmed"):
        if entry.get("api_is_delisted") is False:
            return "relisted"
        return "delisted"
    if entry.get("api_is_delisted") is True and not entry.get("_later"):
        return "delisted"
    if entry.get("_later"):
        return "superseded"
    event_time = entry.get("vote_time") or entry.get("effective_time")
    if event_time and parse_instant(str(event_time)) > now:
        return "scheduled"
    if entry.get("api_is_delisted") is False:
        return "unconfirmed"
    if entry["market"] == "hip3":
        return "elapsed"
    return "unconfirmed"


def _observed(entries: list[dict[str, Any]], meta: dict[str, Any]) -> list[dict[str, Any]]:
    covered_perps = {
        entry["asset"]
        for entry in entries
        if entry["market"] == "perp" and not entry.get("dex")
    }
    covered_hip3 = {
        (entry.get("dex"), entry["asset"])
        for entry in entries
        if entry["market"] == "hip3"
    }
    observed = []
    for asset, is_delisted in sorted((meta.get("perps") or {}).items()):
        if not is_delisted or asset in covered_perps:
            continue
        observed.append(_observed_entry(asset=asset, market="perp", dex=None, api_coin=asset))
    for dex, coins in sorted((meta.get("dexes") or {}).items()):
        for coin, is_delisted in sorted(coins.items()):
            if not is_delisted or ":" not in coin:
                continue
            _dex_name, asset = coin.split(":", 1)
            if (dex, asset) in covered_hip3:
                continue
            observed.append(
                _observed_entry(asset=asset, market="hip3", dex=dex, api_coin=coin)
            )
    return observed


def _observed_entry(
    *, asset: str, market: str, dex: str | None, api_coin: str
) -> dict[str, Any]:
    entry = _blank_entry(
        asset=asset,
        market=market,
        dex=dex,
        kind="observed_delisted",
        announced_at=None,
        source_url=INFO_URL,
        source_urls=[INFO_URL],
        excerpt=(
            "isDelisted is true in the Hyperliquid info meta response. "
            "No matching delist announcement was found in the sources checked."
        ),
    )
    entry["api_coin"] = api_coin
    entry["api_is_delisted"] = True
    entry["status"] = "delisted"
    suffix = api_coin if dex else asset
    entry["id"] = f"meta:{market}:{suffix}"
    return entry


def _blank_entry(
    *,
    asset: str,
    market: str,
    dex: str | None,
    kind: str,
    announced_at: str | None,
    source_url: str,
    source_urls: list[str],
    excerpt: str,
) -> dict[str, Any]:
    return {
        "id": "",
        "asset": asset,
        "market": market,
        "dex": dex,
        "market_name": None,
        "kind": kind,
        "status": "",
        "announced_at": announced_at,
        "vote_time": None,
        "vote_time_approximate": False,
        "effective_time": None,
        "effective_time_approximate": False,
        "effective_time_end": None,
        "settlement": None,
        "source_url": source_url,
        "source_urls": source_urls,
        "excerpt": excerpt,
        "reference_urls": [],
        "api_coin": None,
        "api_is_delisted": None,
    }


def _entry_id(fact: dict[str, Any]) -> str:
    app_ids = [source for source in fact.get("source_ids") or [fact.get("source_id")] if str(source).startswith("app:")]
    asset = fact["asset"]
    if app_ids:
        uuid = str(app_ids[0]).split(":", 1)[1]
        return f"app:{uuid}:{asset}"
    tg_ids = []
    for source in fact.get("source_ids") or [fact.get("source_id")]:
        text = str(source)
        if text.startswith("tg:"):
            tg_ids.append(int(text.split(":", 1)[1]))
    if tg_ids:
        return f"tg:{min(tg_ids)}:{asset}"
    return f"{fact.get('source_id')}:{asset}"


def _preferred_url(fact: dict[str, Any]) -> str:
    for url in fact.get("source_urls") or []:
        if "app.hyperliquid.xyz/announcement/" in url:
            return url
    return fact["source_url"]


def _same_market(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        str(left.get("asset", "")).casefold() == str(right.get("asset", "")).casefold()
        and (left.get("market") or "perp") == (right.get("market") or "perp")
        and (left.get("dex") or None) == (right.get("dex") or None)
    )


def _asset_key(fact: dict[str, Any]) -> str:
    return "|".join(
        [
            str(fact.get("market") or "perp"),
            str(fact.get("dex") or ""),
            str(fact.get("asset") or "").casefold(),
        ]
    )


def _times_close(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return abs((parse_instant(left) - parse_instant(right)).total_seconds()) <= CLOSE.total_seconds()


def _merge_sources(target: dict[str, Any], extra: dict[str, Any]) -> None:
    _add_url(target, extra["source_url"], extra["source_id"])
    for url in extra.get("source_urls") or []:
        _add_url(target, url, extra.get("source_id") or "")
    target["reference_urls"] = _unique(
        list(target.get("reference_urls") or []) + list(extra.get("reference_urls") or [])
    )


def _add_url(target: dict[str, Any], url: str, source_id: str) -> None:
    if url and url not in target["source_urls"]:
        target["source_urls"].append(url)
    if source_id and source_id not in target["source_ids"]:
        target["source_ids"].append(source_id)


def _unique(values: list[str]) -> list[str]:
    found: list[str] = []
    for value in values:
        if value and value not in found:
            found.append(value)
    return found


def public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Drop assembly bookkeeping before writing JSON."""
    published = {
        key: value
        for key, value in entry.items()
        if not key.startswith("_")
    }
    return published
