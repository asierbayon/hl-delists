"""Parser tests against real Hyperliquid announcement fixtures."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from hl_delists.parse import parse_app_entry, parse_message

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "tests" / "fixtures" / "app"
TELEGRAM = ROOT / "tests" / "fixtures" / "telegram_delist_messages.json"

# Messages that mention "delist" only in passing and must not become schedules.
NON_EVENTS = {334, 427, 463, 471, 478, 480, 533}


def _load_app(uuid: str) -> dict:
    return json.loads((APP / f"{uuid}.json").read_text(encoding="utf-8"))


def _telegram() -> list[dict]:
    return json.loads(TELEGRAM.read_text(encoding="utf-8"))


def _telegram_by_id() -> dict[int, dict]:
    return {int(message["id"]): message for message in _telegram()}


def _facts(message: dict) -> list[dict]:
    return parse_message(
        message["text"],
        source_url=message["url"],
        announced_at=message["datetime"],
        source_id=f"tg:{message['id']}",
    )


class AppAnnouncementTests(unittest.TestCase):
    def test_vine_vote_matches_the_published_notice(self) -> None:
        facts = parse_app_entry(_load_app("rl469tntie"))
        schedules = [fact for fact in facts if fact["fact"] == "schedule"]
        self.assertEqual(len(schedules), 1)
        vine = schedules[0]
        self.assertEqual(vine["asset"], "VINE")
        self.assertEqual(vine["kind"], "delist_vote")
        self.assertEqual(vine["market"], "perp")
        self.assertEqual(vine["when"], "2026-08-26T09:30:00Z")
        self.assertTrue(vine["approximate"])
        self.assertEqual(vine["settlement"], "1h_oracle_twap")
        self.assertEqual(
            vine["source_url"],
            "https://app.hyperliquid.xyz/announcement/rl469tntie",
        )
        self.assertIn("delist VINE", vine["excerpt"])

    def test_multi_asset_may_vote(self) -> None:
        facts = parse_app_entry(_load_app("15voh4lxgo2"))
        assets = [fact["asset"] for fact in facts if fact["fact"] == "schedule"]
        self.assertEqual(
            assets,
            ["MAV", "MAVIA", "MEW", "PROMPT", "SCR", "TST", "USTC", "YZY", "ZEREBRO"],
        )
        self.assertTrue(all(fact["when"] == "2026-05-05T09:00:00Z" for fact in facts))
        self.assertTrue(all(fact["approximate"] for fact in facts))

    def test_mkr_as_part_of_clause_does_not_swallow_the_time(self) -> None:
        facts = parse_app_entry(_load_app("8pcq8szcgpm"))
        schedules = [fact for fact in facts if fact["fact"] == "schedule"]
        self.assertEqual([fact["asset"] for fact in schedules], ["MKR"])
        self.assertEqual(schedules[0]["when"], "2025-09-05T10:00:00Z")
        self.assertIsNone(schedules[0]["settlement"])

    def test_kdogs_ticker_is_preserved(self) -> None:
        facts = parse_app_entry(_load_app("igatpkcw9m"))
        assets = [fact["asset"] for fact in facts if fact["fact"] == "schedule"]
        self.assertEqual(assets, ["kDOGS", "OGN", "REQ", "STG"])
        self.assertEqual(facts[0]["when"], "2025-08-04T10:00:00Z")

    def test_launchcoin_settles_at_mark_price(self) -> None:
        facts = parse_app_entry(_load_app("w50kcqiztvk"))
        schedule = facts[0]
        self.assertEqual(schedule["asset"], "LAUNCHCOIN")
        self.assertEqual(schedule["when"], "2025-10-25T07:00:00Z")
        self.assertEqual(schedule["settlement"], "mark_price")

    def test_hyena_sunset_lists_named_markets_and_window(self) -> None:
        facts = parse_app_entry(_load_app("nkbbby8yrh"))
        self.assertEqual(len(facts), 18)
        self.assertTrue(all(fact["dex"] == "hyna" for fact in facts))
        self.assertTrue(all(fact["when"] == "2026-08-31T10:00:00Z" for fact in facts))
        self.assertTrue(all(fact["when_end"] == "2026-09-02T15:00:00Z" for fact in facts))
        self.assertTrue(all(fact["settlement"] == "final_mark_price" for fact in facts))
        self.assertFalse(any(fact["approximate"] for fact in facts))
        assets = [fact["asset"] for fact in facts]
        self.assertIn("1000PEPE", assets)
        self.assertIn("BASED", assets)
        self.assertIn("https://docs.hyena.trade/", facts[0]["reference_urls"])

    def test_dreamcash_keeps_google_as_written(self) -> None:
        facts = parse_app_entry(_load_app("ydvor1grh4"))
        assets = [fact["asset"] for fact in facts]
        self.assertIn("GOOGLE", assets)
        self.assertNotIn("GOOGL", assets)
        self.assertEqual(len(assets), 15)
        self.assertEqual(facts[0]["when"], "2026-06-30T13:45:00Z")
        self.assertIsNone(facts[0]["when_end"])
        self.assertEqual(facts[0]["dex"], "cash")

    def test_every_app_schedule_has_a_source_link(self) -> None:
        for path in APP.glob("*.json"):
            entry = json.loads(path.read_text(encoding="utf-8"))
            facts = parse_app_entry(entry)
            self.assertGreater(len(facts), 0, path.name)
            for fact in facts:
                self.assertTrue(fact["source_url"].startswith("https://"))
                self.assertIn(entry["uuid"], fact["source_url"])


class TelegramAnnouncementTests(unittest.TestCase):
    def test_date_word_orders_from_real_posts(self) -> None:
        messages = _telegram_by_id()
        expectations = {
            565: ("IP", "2026-06-29T09:30:00Z"),
            551: ("BLAST", "2026-05-25T09:00:00Z"),
            582: ("VINE", "2026-08-26T09:30:00Z"),
            540: ("ZEREBRO", "2026-05-05T09:00:00Z"),
            558: ("TON", "2026-06-15T09:00:00Z"),
        }
        for message_id, (asset, when) in expectations.items():
            schedules = [
                fact
                for fact in _facts(messages[message_id])
                if fact["fact"] == "schedule" and fact["asset"] == asset
            ]
            self.assertEqual(len(schedules), 1, message_id)
            self.assertEqual(schedules[0]["when"], when)
            self.assertTrue(schedules[0]["approximate"])

    def test_ftm_correction_and_rndr_clock_change(self) -> None:
        messages = _telegram_by_id()
        ftm = _facts(messages[286])
        self.assertEqual(ftm[0]["fact"], "correction")
        self.assertEqual(ftm[0]["asset"], "FTM")
        self.assertEqual(ftm[0]["when"], "2025-01-12T03:30:00Z")
        self.assertFalse(ftm[0]["approximate"])

        rndr = _facts(messages[212])
        self.assertEqual(rndr[0]["fact"], "correction")
        self.assertEqual(rndr[0]["asset"], "RNDR")
        self.assertEqual(rndr[0]["clock"], (11, 0))
        self.assertTrue(rndr[0]["approximate"])

    def test_fet_was_postponed_and_banana_was_not_in_the_confirmation(self) -> None:
        messages = _telegram_by_id()
        postponed = [fact["asset"] for fact in _facts(messages[194]) if fact["fact"] == "postponement"]
        self.assertEqual(postponed, ["FET"])
        confirmed = [
            fact["asset"] for fact in _facts(messages[205]) if fact["fact"] == "confirmation"
        ]
        self.assertEqual(confirmed, ["NFTI", "OX", "PANDORA", "SHIA", "UNIBOT"])
        self.assertNotIn("BANANA", confirmed)
        banana = [
            fact["asset"]
            for fact in _facts(messages[200])
            if fact["fact"] == "schedule"
        ]
        self.assertIn("BANANA", banana)

    def test_quorum_times_and_jelly_notice(self) -> None:
        messages = _telegram_by_id()
        myro = [fact for fact in _facts(messages[336]) if fact["fact"] == "quorum"]
        self.assertEqual([fact["asset"] for fact in myro], ["MYRO"])
        self.assertEqual(myro[0]["when"], "2025-03-29T13:16:00Z")
        self.assertTrue(any("/explorer/tx/" in url for url in myro[0]["reference_urls"]))

        jelly = [fact for fact in _facts(messages[332]) if fact["fact"] == "notice"]
        self.assertEqual(len(jelly), 1)
        self.assertEqual(jelly[0]["asset"], "JELLY")

        listed_and_delisted = [
            fact["asset"] for fact in _facts(messages[473]) if fact["fact"] == "confirmation"
        ]
        self.assertEqual(listed_and_delisted, ["AI16Z"])

    def test_passing_mentions_do_not_become_events(self) -> None:
        messages = _telegram_by_id()
        for message_id in NON_EVENTS:
            facts = [
                fact
                for fact in _facts(messages[message_id])
                if fact["fact"] in {"schedule", "notice", "sunset", "confirmation", "quorum"}
            ]
            self.assertEqual(facts, [], message_id)

    def test_every_parsed_asset_comes_from_the_message(self) -> None:
        for message in _telegram():
            facts = _facts(message)
            for fact in facts:
                self.assertTrue(fact["source_url"].startswith("https://t.me/"))
                asset = fact.get("asset")
                if asset:
                    self.assertIn(asset, message["text"])


if __name__ == "__main__":
    unittest.main()
