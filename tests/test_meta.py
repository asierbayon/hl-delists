"""Meta snapshot diffs."""

from __future__ import annotations

import unittest

from hl_delists.meta import diff_snapshots, snapshot_from_responses


class MetaDiffTests(unittest.TestCase):
    def test_first_snapshot_is_a_baseline(self) -> None:
        current = _snapshot()
        self.assertEqual(diff_snapshots(None, current, observed_at="2026-11-24T00:00:00Z"), [])

    def test_flag_flip_listing_and_spot_removal(self) -> None:
        previous = _snapshot()
        current = _snapshot()
        current["perps"]["NEW"] = False
        current["perps"]["VINE"] = True
        current["dexes"]["hyna"]["hyna:BTC"] = True
        current["spot_markets"] = ["@1"]
        changes = diff_snapshots(previous, current, observed_at="2026-11-24T01:00:00Z")
        kinds = {(change["asset"], change["kind"], change["market"]) for change in changes}
        self.assertIn(("NEW", "listed", "perp"), kinds)
        self.assertIn(("VINE", "delisted", "perp"), kinds)
        self.assertIn(("hyna:BTC", "delisted", "hip3"), kinds)
        self.assertIn(("PURR/USDC", "spot_removed", "spot"), kinds)
        for change in changes:
            self.assertEqual(change["source_url"], "https://api.hyperliquid.xyz/info")


def _snapshot() -> dict:
    return snapshot_from_responses(
        main_meta={
            "universe": [
                {"name": "BTC", "isDelisted": False},
                {"name": "VINE", "isDelisted": False},
            ]
        },
        spot_meta={
            "universe": [{"name": "PURR/USDC"}, {"name": "@1"}],
            "tokens": [{"name": "PURR"}, {"name": "USDC"}],
        },
        dex_metas={
            "hyna": {"universe": [{"name": "hyna:BTC", "isDelisted": False}]},
        },
        fetched_at="2026-11-24T00:00:00Z",
    )


if __name__ == "__main__":
    unittest.main()
