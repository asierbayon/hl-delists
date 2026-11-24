"""The public t.me preview page is the live Telegram source."""

from __future__ import annotations

import unittest
from pathlib import Path

from hl_delists.telegram import next_before, parse_telegram_html

PAGE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "telegram_page_sample.html"


class TelegramHtmlTests(unittest.TestCase):
    def test_sample_page_contains_the_vine_delist_line(self) -> None:
        messages = parse_telegram_html(PAGE.read_text(encoding="utf-8"))
        by_id = {message["id"]: message for message in messages}
        self.assertIn(585, by_id)
        self.assertIn("VINE perps were delisted", by_id[585]["text"])
        self.assertEqual(
            by_id[585]["url"],
            "https://t.me/hyperliquid_announcements/585",
        )
        self.assertTrue(by_id[585]["datetime"].startswith("2026-08-31"))
        self.assertEqual(next_before(PAGE.read_text(encoding="utf-8")), 584)


if __name__ == "__main__":
    unittest.main()
