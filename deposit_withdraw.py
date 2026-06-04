#!/usr/bin/env python3
"""
Fetch deposit/withdrawal status per coin for each exchange using public APIs only.
"""

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

TIMEOUT = 10


def _fetch_gateio():
    """Gate.io public endpoint — no auth required."""
    try:
        resp = requests.get(
            "https://api.gateio.ws/api/v4/spot/currencies",
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        result = {}
        for item in resp.json():
            coin = item.get("currency", "").upper()
            if not coin:
                continue
            result[coin] = {
                "deposit": not item.get("deposit_disabled", False),
                "withdraw": not item.get("withdraw_disabled", False),
            }
        return result
    except Exception:
        return {}


def _fetch_kucoin():
    """KuCoin public endpoint — no auth required."""
    try:
        resp = requests.get(
            "https://api.kucoin.com/api/v2/currencies",
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        result = {}
        for item in data:
            coin = item.get("currency", "").upper()
            if not coin:
                continue
            result[coin] = {
                "deposit": bool(item.get("isDepositEnabled", False)),
                "withdraw": bool(item.get("isWithdrawEnabled", False)),
            }
        return result
    except Exception:
        return {}


def _fetch_htx():
    """HTX/Huobi public endpoint — no auth required."""
    try:
        resp = requests.get(
            "https://api.huobi.pro/v2/reference/currencies",
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        result = {}
        for item in data:
            coin = item.get("currency", "").upper()
            if not coin:
                continue
            chains = item.get("chains", [])
            if not chains:
                continue
            # Coin is enabled if ANY chain allows it
            deposit_ok = any(
                c.get("depositStatus", "prohibited") == "allowed"
                for c in chains
            )
            withdraw_ok = any(
                c.get("withdrawStatus", "prohibited") == "allowed"
                for c in chains
            )
            result[coin] = {"deposit": deposit_ok, "withdraw": withdraw_ok}
        return result
    except Exception:
        return {}


def _fetch_mexc():
    """MEXC public endpoint — may require auth, returns {} on failure."""
    try:
        resp = requests.get(
            "https://api.mexc.com/api/v3/capital/config/getall",
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        result = {}
        for item in resp.json():
            coin = item.get("coin", "").upper()
            if not coin:
                continue
            network_list = item.get("networkList", [])
            if not network_list:
                continue
            deposit_ok = any(n.get("depositEnable", False) for n in network_list)
            withdraw_ok = any(n.get("withdrawEnable", False) for n in network_list)
            result[coin] = {"deposit": deposit_ok, "withdraw": withdraw_ok}
        return result
    except Exception:
        return {}


def fetch_deposit_withdraw_status() -> dict:
    """
    Returns a dict keyed by exchange name, each value a dict of
    coin -> {"deposit": bool, "withdraw": bool}.
    Unknown exchanges or failed fetches return empty dicts.
    """
    fetchers = {
        "Gate.io": _fetch_gateio,
        "KuCoin": _fetch_kucoin,
        "HTX": _fetch_htx,
        "MEXC": _fetch_mexc,
        # Auth required or no known public endpoint — return empty (unknown)
        "Binance": lambda: {},
        "OKX": lambda: {},
        "CoinEx": lambda: {},
        "BitMart": lambda: {},
        "LBank": lambda: {},
        "AscendEX": lambda: {},
        "XT": lambda: {},
    }

    results = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_to_name = {
            executor.submit(fn): name for name, fn in fetchers.items()
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception:
                results[name] = {}

    return results
