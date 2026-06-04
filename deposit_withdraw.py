#!/usr/bin/env python3
"""
Fetch deposit/withdrawal status per coin per exchange.
- Public APIs for Gate.io, KuCoin, HTX, MEXC (no keys needed)
- CCXT with API keys from env vars for all others
"""

import os
import requests
import ccxt
from concurrent.futures import ThreadPoolExecutor, as_completed

TIMEOUT = 12


# ─── Public API fetchers (no auth needed) ────────────────────────────────────

def _public_gateio():
    resp = requests.get("https://api.gateio.ws/api/v4/spot/currencies", timeout=TIMEOUT)
    resp.raise_for_status()
    result = {}
    for item in resp.json():
        coin = item.get("currency", "").upper()
        if coin:
            result[coin] = {
                "deposit": not item.get("deposit_disabled", False),
                "withdraw": not item.get("withdraw_disabled", False),
            }
    return result


def _public_kucoin():
    resp = requests.get("https://api.kucoin.com/api/v2/currencies", timeout=TIMEOUT)
    resp.raise_for_status()
    result = {}
    for item in resp.json().get("data", []):
        coin = item.get("currency", "").upper()
        if coin:
            result[coin] = {
                "deposit": bool(item.get("isDepositEnabled", False)),
                "withdraw": bool(item.get("isWithdrawEnabled", False)),
            }
    return result


def _public_htx():
    resp = requests.get("https://api.huobi.pro/v2/reference/currencies", timeout=TIMEOUT)
    resp.raise_for_status()
    result = {}
    for item in resp.json().get("data", []):
        coin = item.get("currency", "").upper()
        chains = item.get("chains", [])
        if coin and chains:
            result[coin] = {
                "deposit": any(c.get("depositStatus") == "allowed" for c in chains),
                "withdraw": any(c.get("withdrawStatus") == "allowed" for c in chains),
            }
    return result


def _public_mexc():
    resp = requests.get("https://api.mexc.com/api/v3/capital/config/getall", timeout=TIMEOUT)
    resp.raise_for_status()
    result = {}
    for item in resp.json():
        coin = item.get("coin", "").upper()
        networks = item.get("networkList", [])
        if coin and networks:
            result[coin] = {
                "deposit": any(n.get("depositEnable", False) for n in networks),
                "withdraw": any(n.get("withdrawEnable", False) for n in networks),
            }
    return result


# ─── CCXT fetchers (require API keys from env) ────────────────────────────────

CCXT_CONFIG = {
    "Binance":  {"class": ccxt.binance,  "key": "BINANCE_API_KEY",  "secret": "BINANCE_SECRET"},
    "OKX":      {"class": ccxt.okx,      "key": "OKX_API_KEY",      "secret": "OKX_SECRET",      "passphrase": "OKX_PASSPHRASE"},
    "CoinEx":   {"class": ccxt.coinex,   "key": "COINEX_API_KEY",   "secret": "COINEX_SECRET"},
    "BitMart":  {"class": ccxt.bitmart,  "key": "BITMART_API_KEY",  "secret": "BITMART_SECRET",   "passphrase": "BITMART_MEMO"},
    "LBank":    {"class": ccxt.lbank,    "key": "LBANK_API_KEY",    "secret": "LBANK_SECRET"},
    "AscendEX": {"class": ccxt.ascendex, "key": "ASCENDEX_API_KEY", "secret": "ASCENDEX_SECRET"},
    "XT":       {"class": ccxt.xt,       "key": "XT_API_KEY",       "secret": "XT_SECRET"},
}


def _ccxt_fetch(name, cfg):
    api_key = os.environ.get(cfg["key"], "")
    secret = os.environ.get(cfg["secret"], "")
    if not api_key or not secret:
        return {}
    params = {"apiKey": api_key, "secret": secret, "timeout": 15000, "enableRateLimit": True}
    pp = os.environ.get(cfg.get("passphrase", ""), "")
    if pp:
        params["password"] = pp
    exchange = cfg["class"](params)
    currencies = exchange.fetch_currencies()
    result = {}
    for coin, data in currencies.items():
        result[coin.upper()] = {
            "deposit": bool(data.get("deposit", data.get("active", False))),
            "withdraw": bool(data.get("withdraw", data.get("active", False))),
        }
    return result


# ─── Dispatcher ───────────────────────────────────────────────────────────────

_PUBLIC_FETCHERS = {
    "Gate.io": _public_gateio,
    "KuCoin":  _public_kucoin,
    "HTX":     _public_htx,
    "MEXC":    _public_mexc,
}


def _fetch_one(name):
    try:
        if name in _PUBLIC_FETCHERS:
            return name, _PUBLIC_FETCHERS[name]()
        cfg = CCXT_CONFIG.get(name)
        if cfg:
            return name, _ccxt_fetch(name, cfg)
        return name, {}
    except Exception:
        return name, {}


def fetch_deposit_withdraw_status() -> dict:
    """
    Returns: {exchange_name: {coin: {"deposit": bool, "withdraw": bool}}}
    Empty dict = unknown (no API key or fetch failed).
    """
    all_exchanges = list(_PUBLIC_FETCHERS.keys()) + list(CCXT_CONFIG.keys())
    results = {}
    with ThreadPoolExecutor(max_workers=11) as executor:
        futures = {executor.submit(_fetch_one, name): name for name in all_exchanges}
        for future in as_completed(futures):
            name, data = future.result()
            results[name] = data
    return results
