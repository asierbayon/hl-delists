"""Feed rendering."""

from __future__ import annotations

import unittest

from hl_delists.feeds import render_ics, render_rss

DOCUMENT = {
    "generated_at": "2026-11-24T00:00:00Z",
    "entries": [
        {
            "id": "app:rl469tntie:VINE",
            "asset": "VINE",
            "market": "perp",
            "dex": None,
            "kind": "delist_vote",
            "status": "delisted",
            "announced_at": "2026-08-24T10:06:23Z",
            "vote_time": "2026-08-26T09:30:00Z",
            "vote_time_approximate": True,
            "effective_time": None,
            "effective_time_approximate": False,
            "effective_time_end": None,
            "settlement": "1h_oracle_twap",
            "source_url": "https://app.hyperliquid.xyz/announcement/rl469tntie",
            "excerpt": "Validators will vote on whether to delist VINE & settle.",
        }
    ],
}


class FeedTests(unittest.TestCase):
    def test_rss_links_the_source_and_escapes_text(self) -> None:
        rss = render_rss(DOCUMENT)
        self.assertIn("<rss version=\"2.0\">", rss)
        self.assertIn("https://app.hyperliquid.xyz/announcement/rl469tntie", rss)
        self.assertIn("VINE &amp; settle", rss)
        self.assertNotIn("VINE & settle", rss)

    def test_ics_uses_the_stated_vote_time(self) -> None:
        ics = render_ics(DOCUMENT)
        self.assertIn("BEGIN:VCALENDAR", ics)
        self.assertIn("DTSTART:20260826T093000Z", ics)
        self.assertIn("URL:https://app.hyperliquid.xyz/announcement/rl469tntie", ics)
        self.assertIn("approximate", ics)


if __name__ == "__main__":
    unittest.main()
