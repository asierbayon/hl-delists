"""Calendar assembly, using the real announcement fixtures."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from hl_delists.build import assemble, public_entry
from hl_delists.calendar import (
    blacklist_coins,
    freqtrade_pair_blacklist,
    is_scheduled_for_delist,
    upcoming_delists,
)
from hl_delists.parse import parse_app_entry, parse_message

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)


def _facts() -> list[dict]:
    facts = []
    for path in sorted((ROOT / "tests" / "fixtures" / "app").glob("*.json")):
        facts.extend(parse_app_entry(json.loads(path.read_text(encoding="utf-8"))))
    messages = json.loads(
        (ROOT / "tests" / "fixtures" / "telegram_delist_messages.json").read_text(encoding="utf-8")
    )
    for message in messages:
        facts.extend(
            parse_message(
                message["text"],
                source_url=message["url"],
                announced_at=message["datetime"],
                source_id=f"tg:{message['id']}",
            )
        )
    return facts


def _calendar(extra_facts: list[dict] | None = None, meta: dict | None = None, now: datetime = NOW):
    facts = _facts()
    if extra_facts:
        facts.extend(extra_facts)
    if meta is None:
        meta = {
            "perps": {
                "VINE": True,
                "FET": False,
                "BANANA": False,
                "FTM": True,
                "RNDR": True,
                "JELLY": True,
                "MYRO": True,
                "TST": True,
                "BTC": False,
            },
            "dexes": {"hyna": {"hyna:BTC": True}, "cash": {}},
        }
    entries = [public_entry(entry) for entry in assemble(facts, meta=meta, now=now)]
    return {"entries": entries}


class AssembleTests(unittest.TestCase):
    def test_real_events_keep_source_times_and_status(self) -> None:
        entries = {entry["id"]: entry for entry in _calendar()["entries"]}
        vine = entries["app:rl469tntie:VINE"]
        self.assertEqual(vine["vote_time"], "2026-08-26T09:30:00Z")
        self.assertTrue(vine["vote_time_approximate"])
        self.assertIsNone(vine["effective_time"])
        self.assertEqual(vine["status"], "delisted")
        self.assertTrue(vine["source_url"].startswith("https://app.hyperliquid.xyz/announcement/"))
        self.assertTrue(any("t.me/hyperliquid_announcements/582" in url for url in vine["source_urls"]))

        ftm = entries["tg:282:FTM"]
        self.assertEqual(ftm["effective_time"], "2025-01-12T03:30:00Z")
        self.assertFalse(ftm["effective_time_approximate"])
        self.assertEqual(ftm["status"], "delisted")

        rndr = entries["tg:209:RNDR"]
        self.assertEqual(rndr["effective_time"], "2024-07-21T11:00:00Z")
        self.assertTrue(rndr["effective_time_approximate"])

        self.assertEqual(entries["tg:190:FET"]["status"], "postponed")
        self.assertEqual(entries["tg:200:BANANA"]["status"], "unconfirmed")
        self.assertEqual(entries["app:i9excsb5cdc:MYRO"]["effective_time"], "2025-03-29T13:16:00Z")
        self.assertEqual(entries["app:15voh4lxgo2:TST"]["status"], "superseded")
        self.assertEqual(entries["app:5w9usyzab1b:TST"]["status"], "delisted")
        self.assertEqual(entries["app:ydvor1grh4:GOOGLE"]["asset"], "GOOGLE")
        self.assertIsNone(entries["app:ydvor1grh4:GOOGLE"]["api_coin"])

        ids = [entry["id"] for entry in entries.values()]
        self.assertEqual(len(ids), len(set(ids)))
        for entry in entries.values():
            self.assertTrue(str(entry["source_url"]).startswith("https://"), entry["id"])

    def test_blacklist_does_not_treat_hip3_btc_as_main_btc(self) -> None:
        calendar = _calendar()
        self.assertFalse(is_scheduled_for_delist("VINE", at=NOW, calendar=calendar))
        self.assertEqual(upcoming_delists(at=NOW, calendar=calendar), [])
        coins = blacklist_coins(at=NOW, calendar=calendar)
        pairs = freqtrade_pair_blacklist(at=NOW, calendar=calendar)
        self.assertIn("VINE", coins)
        self.assertIn("hyna:BTC", coins)
        self.assertNotIn("BTC", coins)
        self.assertNotIn("FET", coins)
        self.assertNotIn("BANANA", coins)
        self.assertIn("VINE/USDC:USDC", pairs)
        self.assertNotIn("BTC/USDC:USDC", pairs)
        self.assertNotIn("FET/USDC:USDC", pairs)

    def test_future_vote_is_scheduled(self) -> None:
        fact = {
            "fact": "schedule",
            "kind": "delist_vote",
            "asset": "TESTCOIN",
            "market": "perp",
            "dex": None,
            "when": "2027-01-02T09:00:00Z",
            "approximate": True,
            "settlement": "1h_oracle_twap",
            "source_url": "https://t.me/hyperliquid_announcements/999999",
            "source_id": "tg:999999",
            "announced_at": "2026-12-20T00:00:00Z",
            "excerpt": "synthetic future vote for the helper test",
        }
        calendar = _calendar(extra_facts=[fact])
        self.assertTrue(is_scheduled_for_delist("TESTCOIN", at=NOW, calendar=calendar))
        upcoming = upcoming_delists(at=NOW, calendar=calendar)
        self.assertEqual([entry["asset"] for entry in upcoming], ["TESTCOIN"])
        self.assertIn("TESTCOIN/USDC:USDC", freqtrade_pair_blacklist(at=NOW, calendar=calendar))
        self.assertFalse(
            is_scheduled_for_delist("TESTCOIN", at="2027-02-01T00:00:00Z", calendar=calendar)
        )


if __name__ == "__main__":
    unittest.main()
