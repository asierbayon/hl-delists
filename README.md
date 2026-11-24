# hl-delists

A machine-readable calendar of [Hyperliquid](https://hyperliquid.xyz) delistings.

Hyperliquid delistings are decided by validator vote and announced in advance, but the posts are human-readable text. The info API only sets `isDelisted` once a delisting has already happened, so a bot can keep opening positions until settlement. When a delist goes through, open positions are settled at the oracle price described in the announcement (often the one-hour TWAP) and open orders are cancelled.

This repository turns the public announcements into `delistings.json`, an RSS feed, and an iCalendar feed, and it diffs the info API so later runs can see listings and delistings that actually flipped.

It is an unofficial public-good archive. It is not a Hyperliquid product.

## Feeds

| File | What it is |
| --- | --- |
| [data/delistings.json](data/delistings.json) | Calendar. Schema: [data/schema.json](data/schema.json) |
| [data/delistings.rss](data/delistings.rss) | RSS 2.0 |
| [data/delistings.ics](data/delistings.ics) | iCalendar. `DTSTART` is the time stated in the source |
| [data/freqtrade-blacklist.json](data/freqtrade-blacklist.json) | Main-dex perp pairs to avoid, as `BASE/USDC:USDC` |
| [data/market-changes.json](data/market-changes.json) | Info-API diffs after the first snapshot |

Raw files:

- https://raw.githubusercontent.com/asierbayon/hl-delists/main/data/delistings.json
- https://raw.githubusercontent.com/asierbayon/hl-delists/main/data/delistings.rss
- https://raw.githubusercontent.com/asierbayon/hl-delists/main/data/delistings.ics
- https://raw.githubusercontent.com/asierbayon/hl-delists/main/data/freqtrade-blacklist.json

The same files are copied under `docs/` for GitHub Pages. `docs/index.html` is the calendar page. When Pages is enabled for this repository:

- https://asierbayon.github.io/hl-delists/
- https://asierbayon.github.io/hl-delists/delistings.json
- https://asierbayon.github.io/hl-delists/delistings.rss
- https://asierbayon.github.io/hl-delists/delistings.ics

## Page

`docs/index.html` reads `delistings.json` from the same directory. It does not call a live API. Each row shows the asset, market, status, vote time, effective time, and a link to the source. The status and market filters use the values from the schema, and the search box matches the asset. A time the announcement called approximate is labeled approximate. A time the source did not state is shown as none.

GitHub Pages, once enabled on the `docs/` folder, serves the page at https://asierbayon.github.io/hl-delists/.

Serve that folder so the page and the JSON share an origin:

```bash
python -m http.server -d docs 8000
```

Open http://127.0.0.1:8000/. Opening the HTML file directly does not work: the browser will not let the page read `delistings.json`.

## Schema

`data/delistings.json` is schema version `1`. Each entry has:

- `asset`, `market` (`perp`, `spot`, or `hip3`), and `dex` for a HIP-3 market
- `kind`: `delist_vote`, `scheduled_delist`, `delist_notice`, `hip3_sunset`, or `observed_delisted`
- `status`: `scheduled`, `delisted`, `postponed`, `unconfirmed`, `superseded`, `elapsed`, or `relisted`
- `announced_at`, `vote_time`, `effective_time`
- `vote_time_approximate` / `effective_time_approximate` when the source said "around" or "approximately"
- `settlement`: `1h_oracle_twap`, `mark_price`, or `final_mark_price` when the post states it, otherwise `null`
- `source_url` and `source_urls`
- `api_coin` and `api_is_delisted` when the coin matched an info `meta` response

`effective_time` is set only when a source states one: a direct "will be delisted at" clock time, a later correction, a reported onchain quorum time, or the start of a HIP-3 wind-down. A validator vote leaves `effective_time` null. Those posts describe settlement as the one-hour oracle TWAP before the vote, which is not itself a single timestamp.

`vote_time` is the clock time written in the post, in UTC, even when the wording is approximate.

## Backfill

Built from public posts, not from guessed dates.

- Telegram announcements, https://t.me/s/hyperliquid_announcements, from the first delist wording found on 2024-03-09 (STRAX) through the latest post checked. The channel's oldest post is 2023-08-04.
- In-app announcements, the index behind https://app.hyperliquid.xyz/announcements and the VINE notice https://app.hyperliquid.xyz/announcement/rl469tntie. The index begins 2025-02-12. Delist posts there begin with MYRO on 2025-03-28.
- The HL/MEDIA mirror of the newest Telegram posts, https://data.hlmedia.io/feeds/announcements.json
- Info meta for main perps, spot, and the `hyna` and `cash` HIP-3 dexes: https://api.hyperliquid.xyz/info

As of the committed snapshot (2026-11-24): 102 entries, of which 56 are distinct main-perp assets with `isDelisted: true`. That snapshot has 235 perp assets (56 delisted) and 356 spot markets. No spot delist announcement was found, and `spotMeta` does not carry `isDelisted`.

Two announced names did not become delistings. FET was postponed on 2024-06-12 and is still listed. BANANA was named in the 2024-06-27 schedule, omitted from the later confirmation, and `isDelisted` is false. TST was in a vote on 2026-05-05 and again on 2026-05-25; the earlier vote is `superseded`.

## Use the helper

```bash
pip install -e .
```

```python
from hl_delists import (
    blacklist_coins,
    freqtrade_pair_blacklist,
    is_scheduled_for_delist,
    upcoming_delists,
)

is_scheduled_for_delist("VINE")
upcoming_delists()
freqtrade_pair_blacklist()
```

`is_scheduled_for_delist("VINE")` is true only while a delist is still scheduled. A coin that has already been delisted returns false. Pass `hyna:BTC` for a HIP-3 market. A main-dex query does not match a HIP-3 market with the same base.

`blacklist_coins()` returns main-dex tickers and dex-qualified HIP-3 names whose status is `delisted` or `scheduled`. Postponed and unconfirmed names are left out.

`freqtrade_pair_blacklist()` returns main-dex perps as `BASE/USDC:USDC`. That assumes the USDC-settled perp used by Freqtrade's Hyperliquid pair format. HIP-3 names are in `hip3_coins` inside `data/freqtrade-blacklist.json` and are not rewritten into pairs.

From a checkout, the helper reads `data/delistings.json`. Point `HL_DELISTS_FILE` at another copy if you need to.

```python
import json
import urllib.request

url = "https://raw.githubusercontent.com/asierbayon/hl-delists/main/data/delistings.json"
with urllib.request.urlopen(url, timeout=30) as response:
    calendar = json.load(response)
```

There are no third-party dependencies. Tests run with the standard library:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Updates

`.github/workflows/update.yml` runs every 15 minutes and on demand. It:

1. Pulls the in-app announcement index, the Telegram preview, and the HL/MEDIA feed.
2. Parses delist votes, direct delist schedules, postponements, corrections, and HIP-3 sunsets.
3. Diffs info `meta` and `spotMeta` against `sources/meta/snapshot.json`. A new perp, an `isDelisted` flip, a new spot market, or a spot market that disappeared is appended to `data/market-changes.json`. The first snapshot is a baseline, so it does not invent a history of listings.

Requests use `User-Agent: hl-delists/0.1 (+https://github.com/asierbayon/hl-delists; public-good delist calendar)` and wait at least one second between calls to the same host. A run with no new posts fetches the index, one Telegram page, the HL/MEDIA feed, and the meta endpoints. It does not walk the whole Telegram history again.

Rebuild what is already stored, without the network:

```bash
PYTHONPATH=src python -m hl_delists.update --offline
PYTHONPATH=src python -m hl_delists.update --check
```

## Limitations

- The parser only accepts wording it has seen: validator votes, "will be delisted on … at … UTC", postponements, clock corrections, "were/was delisted", reported quorum times, and HIP-3 "wound down" posts. A different sentence, or a delist that was only in an image, is missed.
- Vote times are often approximate. `vote_time_approximate` is true in that case. Do not treat them as the block time of settlement.
- `effective_time` is empty for ordinary validator votes. Settlement is described as the one-hour oracle TWAP before the vote, or as mark price, depending on the post. Older votes do not say which.
- Quorum clock times are recorded only for the March and April 2025 posts that printed them (MYRO at 13:16 UTC, and the two April batches). Later confirmations usually say only that the asset was delisted.
- The info API does not expose a scheduled time or a vote result. `isDelisted` is observed at poll time. `data/market-changes.json` dates that observation, not the chain time, and it starts at the first committed snapshot.
- Telegram posts already fetched are not downloaded again, so an edit to an old post can be missed until the parser's stored copy is refreshed.
- HIP-3 sunsets name a window. They do not say which market is delisted at which hour inside that window. `effective_time` is the start of the window, and `effective_time_end` is the concluding time when the post gives one.
- The Dreamcash post says `GOOGLE-USDT`. Info meta has `cash:GOOGL`. Those are not treated as the same coin.
- Some HIP-3 markets are `isDelisted` in meta but were not named in the sunset post. Those rows are `observed_delisted`, sourced to the info API, with no announcement time.
- Spot markets have no `isDelisted` flag. A name that disappears from `spotMeta` is recorded as `spot_removed`, which can also be a rename or a bad response. It is not marked as a confirmed delisting.
- GitHub's scheduler can start the 15-minute job late. A new post can sit unseen for longer than 15 minutes.
- Pair blacklist strings assume `BASE/USDC:USDC`. Other quotes need a different pattern.

## Disclaimer

This project is not affiliated with Hyperliquid or with the authors of the source posts. The data can be wrong, late, or incomplete. Nothing here is trading, investment, or risk-management advice. Read the linked source before relying on an entry, and do not use this feed as the only control that stops a live strategy from trading a market.
