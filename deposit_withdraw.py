#!/usr/bin/env python3
"""
Fetch deposit/withdrawal status per coin per exchange.
- Direct HTTP + HMAC signing for exchanges requiring auth
- Public APIs for Gate.io and HTX (no keys needed from Railway)
"""

import os
import time
import hmac
import hashlib
import base64
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

TIMEOUT = 12
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


# ─── Public API fetchers ──────────────────────────────────────────────────────

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


# ─── Authenticated fetchers ───────────────────────────────────────────────────

def _auth_mexc():
    api_key = os.environ.get("MEXC_API_KEY", "")
    secret = os.environ.get("MEXC_SECRET", "")
    if not api_key or not secret:
        return {}
    ts = str(int(time.time() * 1000))
    query = f"timestamp={ts}&recvWindow=10000"
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"https://api.mexc.com/api/v3/capital/config/getall?{query}&signature={sig}"
    resp = requests.get(url, headers={**HEADERS, "X-MEXC-APIKEY": api_key}, timeout=TIMEOUT)
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


def _auth_kucoin():
    api_key = os.environ.get("KUCOIN_API_KEY", "")
    secret = os.environ.get("KUCOIN_SECRET", "")
    passphrase = os.environ.get("KUCOIN_PASSPHRASE", "")
    if not api_key or not secret or not passphrase:
        return {}
    ts = str(int(time.time() * 1000))
    endpoint = "/api/v3/currencies"
    str_to_sign = ts + "GET" + endpoint
    sig = base64.b64encode(
        hmac.new(secret.encode(), str_to_sign.encode(), hashlib.sha256).digest()
    ).decode()
    pp_sig = base64.b64encode(
        hmac.new(secret.encode(), passphrase.encode(), hashlib.sha256).digest()
    ).decode()
    headers = {
        "KC-API-KEY": api_key,
        "KC-API-SIGN": sig,
        "KC-API-TIMESTAMP": ts,
        "KC-API-PASSPHRASE": pp_sig,
        "KC-API-KEY-VERSION": "2",
        "Content-Type": "application/json",
    }
    resp = requests.get(f"https://api.kucoin.com{endpoint}", headers=headers, timeout=TIMEOUT)
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


def _auth_xt():
    api_key = os.environ.get("XT_API_KEY", "")
    secret = os.environ.get("XT_SECRET", "")
    if not api_key or not secret:
        return {}
    ts = str(int(time.time() * 1000))
    # XT signing: HMAC-SHA256(secret, "appid="+apikey+"&timestamp="+ts)
    payload = f"appid={api_key}&timestamp={ts}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    headers = {
        "validate-appkey": api_key,
        "validate-timestamp": ts,
        "validate-signature": sig,
        "validate-algorithms": "HmacSHA256",
        "Content-Type": "application/json",
    }
    resp = requests.get(
        "https://sapi.xt.com/v4/public/wallet/support/currency",
        headers=headers, timeout=TIMEOUT
    )
    resp.raise_for_status()
    result = {}
    for item in resp.json().get("result", []):
        coin = item.get("currency", "").upper()
        if coin:
            result[coin] = {
                "deposit": bool(item.get("supportDeposit", False)),
                "withdraw": bool(item.get("supportWithdraw", False)),
            }
    return result


def _auth_lbank():
    api_key = os.environ.get("LBANK_API_KEY", "")
    secret = os.environ.get("LBANK_SECRET", "")
    if not api_key or not secret:
        return {}
    ts = str(int(time.time() * 1000))
    params = {"api_key": api_key, "timestamp": ts}
    query = "&".join(f"{k}={params[k]}" for k in sorted(params))
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest().upper()
    data = {**params, "sign": sig, "sign_type": "1"}
    resp = requests.post(
        "https://api.lbank.info/v2/supplement/user_info.do",
        data=data, timeout=TIMEOUT
    )
    resp.raise_for_status()
    result = {}
    for item in resp.json().get("data", {}).get("list", []):
        coin = item.get("coinType", "").upper()
        if coin:
            result[coin] = {
                "deposit": bool(item.get("isCanRecharge", False)),
                "withdraw": bool(item.get("isCanWithdraw", False)),
            }
    return result


def _auth_gateio():
    """Gate.io authenticated (more complete data than public endpoint)."""
    api_key = os.environ.get("GATEIO_API_KEY", "")
    secret = os.environ.get("GATEIO_SECRET", "")
    if not api_key or not secret:
        return _public_gateio()  # fallback to public
    ts = str(int(time.time()))
    endpoint = "/api/v4/spot/currencies"
    body_hash = hashlib.sha512(b"").hexdigest()
    str_to_sign = f"GET\n{endpoint}\n\n{body_hash}\n{ts}"
    sig = hmac.new(secret.encode(), str_to_sign.encode(), hashlib.sha512).hexdigest()
    headers = {
        "KEY": api_key,
        "Timestamp": ts,
        "SIGN": sig,
        "Content-Type": "application/json",
    }
    resp = requests.get(f"https://api.gateio.ws{endpoint}", headers=headers, timeout=TIMEOUT)
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


def _ascendex_headers(api_key, secret, sign_path):
    ts = str(int(time.time() * 1000))
    # AscendEX signs with only the last part: e.g. "v1/info" not "api/pro/v1/info"
    msg = f"{ts}+{sign_path}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return ts, {
        "x-auth-key": api_key,
        "x-auth-signature": sig,
        "x-auth-timestamp": ts,
        "Content-Type": "application/json",
    }


def _auth_ascendex():
    api_key = os.environ.get("ASCENDEX_API_KEY", "")
    secret = os.environ.get("ASCENDEX_SECRET", "")
    if not api_key or not secret:
        return {}
    # Step 1: get account group — sign with "v1/info"
    _, headers = _ascendex_headers(api_key, secret, "v1/info")
    info_resp = requests.get(
        "https://ascendex.com/api/pro/v1/info",
        headers=headers, timeout=TIMEOUT
    )
    info_resp.raise_for_status()
    group = info_resp.json().get("data", {}).get("accountGroup", 0)
    # Step 2: fetch wallet assets — sign with "v1/wallet/asset"
    _, headers2 = _ascendex_headers(api_key, secret, "v1/wallet/asset")
    resp = requests.get(
        f"https://ascendex.com/{group}/api/pro/v1/wallet/asset",
        headers=headers2, timeout=TIMEOUT
    )
    resp.raise_for_status()
    result = {}
    for item in resp.json().get("data", []):
        coin = item.get("assetCode", "").upper()
        if coin:
            result[coin] = {
                "deposit": bool(item.get("depositEnabled", False)),
                "withdraw": bool(item.get("withdrawalEnabled", False)),
            }
    return result


# ─── Dispatcher ───────────────────────────────────────────────────────────────

_FETCHERS = {
    "Gate.io":  _auth_gateio,
    "HTX":      _public_htx,
    "MEXC":     _auth_mexc,
    "KuCoin":   _auth_kucoin,
    "XT":       _auth_xt,
    # exchanges below return {} until keys added
    "LBank":    _auth_lbank,
    "AscendEX": _auth_ascendex,
    "Binance":  lambda: {},
    "OKX":      lambda: {},
    "CoinEx":   lambda: {},
    "BitMart":  lambda: {},
}


def _fetch_one(name):
    try:
        return name, _FETCHERS[name]()
    except Exception as e:
        print(f"[dw] {name} error: {type(e).__name__}: {e}")
        return name, {}


def fetch_deposit_withdraw_status() -> dict:
    """
    Returns: {exchange_name: {coin: {"deposit": bool, "withdraw": bool}}}
    Empty dict = unknown (no API key or fetch failed).
    """
    results = {}
    with ThreadPoolExecutor(max_workers=11) as executor:
        futures = {executor.submit(_fetch_one, name): name for name in _FETCHERS}
        for future in as_completed(futures):
            name, data = future.result()
            results[name] = data
    return results
