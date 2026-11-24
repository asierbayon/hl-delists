"""Snapshots and diffs of the Hyperliquid info meta endpoints."""

from __future__ import annotations

from typing import Any

INFO_URL = "https://api.hyperliquid.xyz/info"


def snapshot_from_responses(
    *,
    main_meta: dict[str, Any],
    spot_meta: dict[str, Any],
    dex_metas: dict[str, dict[str, Any]],
    fetched_at: str,
) -> dict[str, Any]:
    perps = {
        str(asset["name"]): bool(asset.get("isDelisted"))
        for asset in main_meta.get("universe") or []
        if asset.get("name")
    }
    spot_markets = sorted(
        {
            str(market["name"])
            for market in spot_meta.get("universe") or []
            if market.get("name")
        }
    )
    spot_tokens = sorted(
        {
            str(token["name"])
            for token in spot_meta.get("tokens") or []
            if token.get("name")
        }
    )
    dexes: dict[str, dict[str, bool]] = {}
    for dex, payload in sorted(dex_metas.items()):
        dexes[dex] = {
            str(asset["name"]): bool(asset.get("isDelisted"))
            for asset in payload.get("universe") or []
            if asset.get("name")
        }
    return {
        "fetched_at": fetched_at,
        "perps": dict(sorted(perps.items())),
        "spot_markets": spot_markets,
        "spot_tokens": spot_tokens,
        "dexes": dexes,
    }


def diff_snapshots(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    observed_at: str,
) -> list[dict[str, Any]]:
    """Changes since the previous snapshot. The first snapshot is a baseline, not history."""
    if not previous:
        return []
    changes: list[dict[str, Any]] = []
    changes.extend(
        _diff_flag_map(
            previous.get("perps") or {},
            current.get("perps") or {},
            market="perp",
            dex=None,
            observed_at=observed_at,
        )
    )
    for dex in sorted(set(previous.get("dexes") or {}) | set(current.get("dexes") or {})):
        changes.extend(
            _diff_flag_map(
                (previous.get("dexes") or {}).get(dex) or {},
                (current.get("dexes") or {}).get(dex) or {},
                market="hip3",
                dex=dex,
                observed_at=observed_at,
            )
        )
    changes.extend(
        _diff_names(
            previous.get("spot_markets") or [],
            current.get("spot_markets") or [],
            kind_added="spot_listed",
            kind_removed="spot_removed",
            market="spot",
            observed_at=observed_at,
        )
    )
    return changes


def _diff_flag_map(
    previous: dict[str, bool],
    current: dict[str, bool],
    *,
    market: str,
    dex: str | None,
    observed_at: str,
) -> list[dict[str, Any]]:
    changes = []
    for name in sorted(set(current) - set(previous)):
        kind = "delisted" if current[name] else "listed"
        changes.append(_change(kind, name, market, dex, observed_at))
    for name in sorted(set(previous) - set(current)):
        changes.append(_change("removed_from_meta", name, market, dex, observed_at))
    for name in sorted(set(previous) & set(current)):
        if previous[name] is False and current[name] is True:
            changes.append(_change("delisted", name, market, dex, observed_at))
        elif previous[name] is True and current[name] is False:
            changes.append(_change("relisted", name, market, dex, observed_at))
    return changes


def _diff_names(
    previous: list[str],
    current: list[str],
    *,
    kind_added: str,
    kind_removed: str,
    market: str,
    observed_at: str,
) -> list[dict[str, Any]]:
    before = set(previous)
    after = set(current)
    changes = []
    for name in sorted(after - before):
        changes.append(_change(kind_added, name, market, None, observed_at))
    for name in sorted(before - after):
        changes.append(_change(kind_removed, name, market, None, observed_at))
    return changes


def _change(
    kind: str,
    asset: str,
    market: str,
    dex: str | None,
    observed_at: str,
) -> dict[str, Any]:
    if dex and not asset.startswith(f"{dex}:"):
        label = f"{dex}:{asset}"
    else:
        label = asset
    return {
        "id": f"meta:{observed_at}:{market}:{label}:{kind}",
        "observed_at": observed_at,
        "kind": kind,
        "market": market,
        "asset": asset,
        "dex": dex,
        "source_url": INFO_URL,
    }
