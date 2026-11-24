"""The files committed for publication match a rebuild of the stored sources."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from hl_delists.update import main

ROOT = Path(__file__).resolve().parents[1]


class PublishedCalendarTests(unittest.TestCase):
    def test_outputs_match_sources(self) -> None:
        self.assertEqual(main(["--check"]), 0)

    def test_backfill_links_every_entry(self) -> None:
        document = json.loads((ROOT / "data" / "delistings.json").read_text(encoding="utf-8"))
        entries = document["entries"]
        self.assertGreaterEqual(len(entries), 100)
        self.assertEqual(document["schema_version"], "1")
        vine = next(entry for entry in entries if entry["id"] == "app:rl469tntie:VINE")
        self.assertEqual(vine["vote_time"], "2026-08-26T09:30:00Z")
        self.assertTrue(vine["vote_time_approximate"])
        self.assertEqual(vine["source_url"], "https://app.hyperliquid.xyz/announcement/rl469tntie")
        announced = [entry["announced_at"] for entry in entries if entry["announced_at"]]
        self.assertEqual(min(announced), "2024-03-09T02:28:02Z")
        for entry in entries:
            self.assertTrue(entry["source_url"].startswith("https://"), entry["id"])
            self.assertTrue(entry["source_urls"])


if __name__ == "__main__":
    unittest.main()
