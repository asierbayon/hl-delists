"""Fetch public sources and write the delist calendar.

Offline mode rebuilds outputs from files already stored under sources/.
A live run refreshes those files, then writes data/ and docs/ only when the
calendar or the meta diff actually changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hl_delists.build import assemble, public_entry
from hl_delists.calendar import blacklist_coins, freqtrade_pair_blacklist
from hl_delists.feeds import render_html, render_ics, render_rss
from hl_delists.http_client import PoliteHttp
from hl_delists.meta import diff_snapshots, snapshot_from_responses
from hl_delists.parse import parse_app_entry, parse_message
from hl_delists.telegram import next_before, parse_telegram_html
from hl_delists.timeutil import format_instant

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "sources"
DATA = ROOT / "data"
DOCS = ROOT / "docs"

ENTRIES_URL = "https://dzjnlsk4rxci0.cloudfront.net/mainnet/entries.json"
ENTRY_URL = "https://dzjnlsk4rxci0.cloudfront.net/mainnet/entry-{uuid}.json"
TELEGRAM_URL = "https://t.me/s/hyperliquid_announcements"
HLMEDIA_URL = "https://data.hlmedia.io/feeds/announcements.json"
INFO_URL = "https://api.hyperliquid.xyz/info"
SCHEMA_VERSION = "1"
KEEP_KEYWORDS = ("delist", "wound down", "sunset", "postpon")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update the Hyperliquid delist calendar.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 when committed outputs do not match a rebuild from sources/.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Rebuild from sources/ without fetching.",
    )
    parser.add_argument("--now", help="Override the clock used for status, as an ISO timestamp.")
    args = parser.parse_args(argv)
    if args.check:
        return _check()
    now = _parse_now(args.now)
    if not args.offline:
        refresh_sources(PoliteHttp())
    document = build_document(now)
    wrote = write_outputs(document)
    if wrote:
        print(f"wrote {len(document['entries'])} entries")
    else:
        print("calendar unchanged")
    return 0


def build_document(now: datetime) -> dict[str, Any]:
    facts = collect_facts()
    snapshot = _read_json(SOURCES / "meta" / "snapshot.json")
    entries = [public_entry(entry) for entry in assemble(facts, meta=snapshot, now=now)]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": format_instant(now),
        "entries": entries,
    }


def collect_facts() -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    bodies = sorted((SOURCES / "announcements" / "bodies").glob("*.json"))
    for path in bodies:
        facts.extend(parse_app_entry(_read_json(path)))
    messages = _read_json(SOURCES / "telegram" / "delist-messages.json")
    for message in sorted(messages, key=lambda item: int(item["id"])):
        if not message.get("datetime"):
            continue
        facts.extend(
            parse_message(
                message.get("text") or "",
                source_url=message["url"],
                announced_at=message["datetime"],
                source_id=f"tg:{message['id']}",
            )
        )
    matched_path = SOURCES / "hlmedia" / "matched-messages.json"
    if matched_path.exists():
        for message in _read_json(matched_path):
            facts.extend(
                parse_message(
                    message.get("text") or "",
                    source_url=message["url"],
                    announced_at=message["datetime"],
                    source_id=f"hlmedia:{message['id']}",
                )
            )
    return facts


def refresh_sources(client: PoliteHttp) -> None:
    _refresh_announcements(client)
    _refresh_telegram(client)
    _refresh_hlmedia(client)
    _refresh_meta(client)


def write_outputs(document: dict[str, Any]) -> bool:
    previous = _read_json(DATA / "delistings.json") if (DATA / "delistings.json").exists() else None
    if previous and previous.get("entries") == document["entries"]:
        return False
    DATA.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    _write_json(DATA / "delistings.json", document)
    rss = render_rss(document)
    ics = render_ics(document)
    html_page = render_html(document)
    blacklist = _blacklist_document(document)
    (DATA / "delistings.rss").write_text(rss, encoding="utf-8")
    (DATA / "delistings.ics").write_text(ics, encoding="utf-8")
    (DOCS / "index.html").write_text(html_page, encoding="utf-8")
    (DOCS / "delistings.rss").write_text(rss, encoding="utf-8")
    (DOCS / "delistings.ics").write_text(ics, encoding="utf-8")
    _write_json(DOCS / "delistings.json", document)
    _write_json(DATA / "freqtrade-blacklist.json", blacklist)
    _write_json(DOCS / "freqtrade-blacklist.json", blacklist)
    schema_path = DATA / "schema.json"
    if schema_path.exists():
        schema_text = schema_path.read_text(encoding="utf-8")
        (DOCS / "schema.json").write_text(schema_text, encoding="utf-8")
    changes_path = DATA / "market-changes.json"
    if changes_path.exists():
        (DOCS / "market-changes.json").write_text(
            changes_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return True


def _blacklist_document(document: dict[str, Any]) -> dict[str, Any]:
    calendar = {"entries": document["entries"]}
    at = document["generated_at"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": document["generated_at"],
        "description": (
            "Main-dex Hyperliquid perp pairs whose status is delisted or scheduled. "
            "The pair form is BASE/USDC:USDC. HIP-3 markets are listed as dex:asset "
            "and are not converted into Freqtrade pairs."
        ),
        "exchange": {
            "name": "hyperliquid",
            "pair_blacklist": freqtrade_pair_blacklist(quote="USDC", at=at, calendar=calendar),
        },
        "coins": [
            coin
            for coin in blacklist_coins(at=at, calendar=calendar)
            if ":" not in coin
        ],
        "hip3_coins": [
            coin for coin in blacklist_coins(at=at, calendar=calendar) if ":" in coin
        ],
    }


def _refresh_announcements(client: PoliteHttp) -> None:
    payload = client.get_json(ENTRIES_URL)
    if not isinstance(payload, dict):
        raise RuntimeError("Announcement index was not a JSON object.")
    index_path = SOURCES / "announcements" / "entries.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(index_path, payload)
    bodies = SOURCES / "announcements" / "bodies"
    bodies.mkdir(parents=True, exist_ok=True)
    known_hashes = {}
    for path in bodies.glob("*.json"):
        entry = _read_json(path)
        if entry.get("uuid") and entry.get("hash"):
            known_hashes[entry["uuid"]] = entry["hash"]
    for entry in payload.get("entries") or []:
        if entry.get("category") != "Delistings":
            continue
        uuid = entry.get("uuid")
        if not uuid:
            continue
        if known_hashes.get(uuid) == entry.get("hash") and (bodies / f"{uuid}.json").exists():
            continue
        body = client.get_json(ENTRY_URL.format(uuid=uuid))
        if isinstance(body, dict):
            _write_json(bodies / f"{uuid}.json", body)


def _refresh_telegram(client: PoliteHttp) -> None:
    state_path = SOURCES / "telegram" / "state.json"
    messages_path = SOURCES / "telegram" / "delist-messages.json"
    state = _read_json(state_path) if state_path.exists() else {"latest_id": 0}
    latest_id = int(state.get("latest_id") or 0)
    stored = _read_json(messages_path) if messages_path.exists() else []
    by_id = {int(message["id"]): message for message in stored}
    url = TELEGRAM_URL
    pages = 0
    highest = latest_id
    while pages < 80:
        page = client.get_text(url, accept="text/html")
        messages = parse_telegram_html(page)
        if not messages:
            break
        for message in messages:
            highest = max(highest, int(message["id"]))
            if int(message["id"]) <= latest_id:
                continue
            if _worth_storing(message.get("text") or ""):
                by_id[int(message["id"])] = message
        oldest = min(int(message["id"]) for message in messages)
        if latest_id and oldest <= latest_id:
            break
        before = next_before(page)
        if before is None:
            break
        url = f"{TELEGRAM_URL}?before={before}"
        pages += 1
    messages_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = [by_id[key] for key in sorted(by_id)]
    _write_json(messages_path, ordered)
    _write_json(state_path, {"latest_id": highest})


def _refresh_hlmedia(client: PoliteHttp) -> None:
    payload = client.get_json(HLMEDIA_URL)
    if not isinstance(payload, dict):
        return
    directory = SOURCES / "hlmedia"
    directory.mkdir(parents=True, exist_ok=True)
    _write_json(directory / "announcements.json", payload)
    matched_path = directory / "matched-messages.json"
    matched = _read_json(matched_path) if matched_path.exists() else []
    known = {item["url"] for item in matched}
    for item in payload.get("items") or []:
        text = item.get("content_text") or ""
        url = item.get("url")
        published = item.get("date_published")
        if not url or not published or url in known:
            continue
        if not _worth_storing(text):
            continue
        matched.append(
            {
                "id": url,
                "url": url,
                "datetime": published,
                "text": text,
            }
        )
        known.add(url)
    _write_json(matched_path, matched)


def _refresh_meta(client: PoliteHttp) -> None:
    main_meta = client.post_json(INFO_URL, {"type": "meta"})
    spot_meta = client.post_json(INFO_URL, {"type": "spotMeta"})
    if not isinstance(main_meta, dict) or not isinstance(spot_meta, dict):
        raise RuntimeError("Info meta response was not a JSON object.")
    dexes = _dexes_to_fetch()
    dex_metas = {}
    for dex in dexes:
        payload = client.post_json(INFO_URL, {"type": "meta", "dex": dex})
        if isinstance(payload, dict):
            dex_metas[dex] = payload
    fetched_at = format_instant(datetime.now(timezone.utc))
    current = snapshot_from_responses(
        main_meta=main_meta,
        spot_meta=spot_meta,
        dex_metas=dex_metas,
        fetched_at=fetched_at,
    )
    snapshot_path = SOURCES / "meta" / "snapshot.json"
    previous = _read_json(snapshot_path) if snapshot_path.exists() else None
    if previous and _snapshot_maps(previous) == _snapshot_maps(current):
        return
    changes = diff_snapshots(previous, current, observed_at=fetched_at)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(snapshot_path, current)
    changes_path = DATA / "market-changes.json"
    document = (
        _read_json(changes_path)
        if changes_path.exists()
        else {
            "schema_version": SCHEMA_VERSION,
            "note": (
                "Meta diffs start at the first committed snapshot. "
                "The baseline itself is not rewritten as historical listings or delistings."
            ),
            "changes": [],
        }
    )
    document["changes"] = list(document.get("changes") or []) + changes
    DATA.mkdir(parents=True, exist_ok=True)
    _write_json(changes_path, document)


def _dexes_to_fetch() -> list[str]:
    names = {"hyna", "cash"}
    snapshot_path = SOURCES / "meta" / "snapshot.json"
    if snapshot_path.exists():
        snapshot = _read_json(snapshot_path)
        names.update((snapshot.get("dexes") or {}).keys())
    bodies = SOURCES / "announcements" / "bodies"
    if bodies.exists():
        for path in bodies.glob("*.json"):
            for fact in parse_app_entry(_read_json(path)):
                if fact.get("dex"):
                    names.add(str(fact["dex"]))
    return sorted(names)


def _worth_storing(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in KEEP_KEYWORDS)


def _snapshot_maps(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "perps": snapshot.get("perps"),
        "spot_markets": snapshot.get("spot_markets"),
        "spot_tokens": snapshot.get("spot_tokens"),
        "dexes": snapshot.get("dexes"),
    }


def _check() -> int:
    committed_path = DATA / "delistings.json"
    if not committed_path.exists():
        print("missing data/delistings.json", file=sys.stderr)
        return 1
    committed = _read_json(committed_path)
    # Status was decided at generated_at. Rebuilding with that clock keeps the file stable.
    document = build_document(_parse_now(str(committed["generated_at"])))
    if committed.get("entries") != document["entries"]:
        print("data/delistings.json entries do not match sources/", file=sys.stderr)
        return 1
    problems = []
    if (DATA / "delistings.rss").read_text(encoding="utf-8") != render_rss(committed):
        problems.append("data/delistings.rss")
    # iCalendar is stored with CRLF. Text mode would hide those carriage returns.
    ics_disk = (DATA / "delistings.ics").read_bytes()
    if ics_disk != render_ics(committed).encode("utf-8"):
        problems.append("data/delistings.ics")
    if (DOCS / "delistings.ics").read_bytes() != ics_disk:
        problems.append("docs/delistings.ics")
    if (DOCS / "index.html").read_text(encoding="utf-8") != render_html(committed):
        problems.append("docs/index.html")
    if (DOCS / "delistings.json").read_text(encoding="utf-8") != committed_path.read_text(encoding="utf-8"):
        problems.append("docs/delistings.json")
    blacklist = _blacklist_document(committed)
    if _read_json(DATA / "freqtrade-blacklist.json") != blacklist:
        problems.append("data/freqtrade-blacklist.json")
    if problems:
        print("out of date: " + ", ".join(problems), file=sys.stderr)
        return 1
    print(f"ok {len(document['entries'])} entries")
    return 0


def _parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
