#!/usr/bin/env python3
"""
Fetch deposit/withdrawal status per coin using CCXT.
Uses API keys from environment variables when available, falls back to public access.
"""

import os
import ccxt
from concurrent.futures import ThreadPoolExecutor, as_completed

# Exchange CCXT class mapping + env var names for API keys
EXCHANGE_CONFIG = {
    "Binance": {
        "class": ccxt.binance,
        "key_env": "BINANCE_API_KEY",
        "secret_env": "BINANCE_SECRET",
    },
    "OKX": {
        "class": ccxt.okx,
        "key_env": "OKX_API_KEY",
        "secret_env": "OKX_SECRET",
        "passphrase_env": "OKX_PASSPHRASE",
    },
    "KuCoin": {
        "class": ccxt.kucoin,
        "key_env": "KUCOIN_API_KEY",
        "secret_env": "KUCOIN_SECRET",
        "passphrase_env": "KUCOIN_PASSPHRASE",
    },
    "Gate.io": {
        "class": ccxt.gateio,
        "key_env": "GATEIO_API_KEY",
        "secret_env": "GATEIO_SECRET",
    },
    "MEXC": {
        "class": ccxt.mexc,
        "key_env": "MEXC_API_KEY",
        "secret_env": "MEXC_SECRET",
    },
    "HTX": {
        "class": ccxt.htx,
        "key_env": "HTX_API_KEY",
        "secret_env": "HTX_SECRET",
    },
    "CoinEx": {
        "class": ccxt.coinex,
        "key_env": "COINEX_API_KEY",
        "secret_env": "COINEX_SECRET",
    },
    "BitMart": {
        "class": ccxt.bitmart,
        "key_env": "BITMART_API_KEY",
        "secret_env": "BITMART_SECRET",
        "passphrase_env": "BITMART_MEMO",
    },
    "LBank": {
        "class": ccxt.lbank,
        "key_env": "LBANK_API_KEY",
        "secret_env": "LBANK_SECRET",
    },
    "AscendEX": {
        "class": ccxt.ascendex,
        "key_env": "ASCENDEX_API_KEY",
        "secret_env": "ASCENDEX_SECRET",
    },
    "XT": {
        "class": ccxt.xt,
        "key_env": "XT_API_KEY",
        "secret_env": "XT_SECRET",
    },
}


def _build_exchange(name, cfg):
    params = {"timeout": 15000, "enableRateLimit": True}
    key = os.environ.get(cfg.get("key_env", ""))
    secret = os.environ.get(cfg.get("secret_env", ""))
    if key and secret:
        params["apiKey"] = key
        params["secret"] = secret
    pp = os.environ.get(cfg.get("passphrase_env", ""), "")
    if pp:
        params["password"] = pp
    return cfg["class"](params)


def _fetch_one(name, cfg):
    try:
        exchange = _build_exchange(name, cfg)
        # fetch_currencies requires auth on most exchanges
        if not exchange.apiKey:
            return name, {}
        currencies = exchange.fetch_currencies()
        result = {}
        for coin, data in currencies.items():
            coin_upper = coin.upper()
            result[coin_upper] = {
                "deposit": bool(data.get("deposit", data.get("active", False))),
                "withdraw": bool(data.get("withdraw", data.get("active", False))),
            }
        return name, result
    except Exception:
        return name, {}


def fetch_deposit_withdraw_status() -> dict:
    """
    Returns dict: {exchange_name: {coin: {"deposit": bool, "withdraw": bool}}}
    Empty dict for an exchange means status unknown (no API key or fetch failed).
    """
    results = {}
    with ThreadPoolExecutor(max_workers=11) as executor:
        futures = {
            executor.submit(_fetch_one, name, cfg): name
            for name, cfg in EXCHANGE_CONFIG.items()
        }
        for future in as_completed(futures):
            name, data = future.result()
            results[name] = data
    return results
