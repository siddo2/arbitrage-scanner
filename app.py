#!/usr/bin/env python3
"""
Flask API server for the Arbitrage Scanner dashboard.
Imports fetch/parse logic directly from arbitrage_scanner.py.
"""

import threading
import time
from datetime import datetime

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

from arbitrage_scanner import fetch_all_exchanges, find_opportunities, EXCHANGES

app = Flask(__name__)
CORS(app)

# ─────────────────────────────────────────────
#  GLOBAL STATE
# ─────────────────────────────────────────────

_lock = threading.Lock()
_state = {
    "opportunities": [],
    "metadata": {
        "exchanges_ok": [],
        "exchanges_error": [],
        "total_pairs": 0,
        "elapsed": 0.0,
        "last_update": None,
        "fetching": False,
    },
}

REFRESH_INTERVAL = 15  # seconds
DEFAULT_MIN_SPREAD = 0.3
DEFAULT_MIN_VOLUME = 50000


def _format_volume(vol):
    """Return human-readable volume string."""
    if vol is None:
        return "N/A"
    if vol >= 1_000_000_000:
        return f"${vol / 1_000_000_000:.2f}B"
    elif vol >= 1_000_000:
        return f"${vol / 1_000_000:.2f}M"
    elif vol >= 1_000:
        return f"${vol / 1_000:.1f}K"
    return f"${vol:.0f}"


def _do_refresh():
    """Fetch data from all exchanges and update global state."""
    with _lock:
        _state["metadata"]["fetching"] = True

    try:
        t0 = time.time()
        market_data, errors = fetch_all_exchanges(verbose=False)
        elapsed = time.time() - t0

        # Fetch raw opportunities with loose filters; per-request filtering applied later
        opportunities = find_opportunities(
            market_data,
            min_spread_pct=DEFAULT_MIN_SPREAD,
            min_volume=0,
        )

        serialized = []
        for op in opportunities:
            item = dict(op)
            raw_vol = item["volume"]
            if raw_vol == "N/A":
                item["volume"] = None
                item["volume_display"] = "N/A"
            else:
                item["volume"] = raw_vol
                item["volume_display"] = _format_volume(raw_vol)
            serialized.append(item)

        with _lock:
            _state["opportunities"] = serialized
            _state["metadata"] = {
                "exchanges_ok": list(market_data.keys()),
                "exchanges_error": errors,
                "total_pairs": sum(len(v) for v in market_data.values()),
                "elapsed": round(elapsed, 2),
                "last_update": datetime.utcnow().isoformat(),
                "fetching": False,
            }
    except Exception as e:
        print(f"[refresh] error: {e}")
        with _lock:
            _state["metadata"]["fetching"] = False
            _state["metadata"]["last_update"] = datetime.utcnow().isoformat()


def _background_loop():
    """Background thread: refreshes data every REFRESH_INTERVAL seconds."""
    while True:
        _do_refresh()
        time.sleep(REFRESH_INTERVAL)


# Start background refresh thread immediately
_thread = threading.Thread(target=_background_loop, daemon=True)
_thread.start()


# ─────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/opportunities")
def api_opportunities():
    try:
        min_spread = float(request.args.get("min_spread", DEFAULT_MIN_SPREAD))
    except (ValueError, TypeError):
        min_spread = DEFAULT_MIN_SPREAD

    try:
        min_volume = float(request.args.get("min_volume", DEFAULT_MIN_VOLUME))
    except (ValueError, TypeError):
        min_volume = DEFAULT_MIN_VOLUME

    exchanges_filter_raw = request.args.get("exchanges", "")
    allowed_exchanges = (
        {e.strip() for e in exchanges_filter_raw.split(",") if e.strip()}
        if exchanges_filter_raw else set()
    )

    pair_search = request.args.get("pairs", "").upper().strip()

    with _lock:
        ops = list(_state["opportunities"])
        meta = dict(_state["metadata"])

    filtered = []
    for op in ops:
        if op["spread_brut"] < min_spread:
            continue
        vol = op.get("volume")
        if vol is not None and vol < min_volume:
            continue
        if allowed_exchanges:
            if (op["buy_exchange"] not in allowed_exchanges
                    and op["sell_exchange"] not in allowed_exchanges):
                continue
        if pair_search and pair_search not in op["pair"].upper():
            continue
        filtered.append(op)

    return jsonify({
        "opportunities": filtered,
        "metadata": meta,
    })


@app.route("/api/status")
def api_status():
    with _lock:
        meta = dict(_state["metadata"])

    exchange_status = {}
    for name in EXCHANGES:
        exchange_status[name] = {
            "ok": name in meta.get("exchanges_ok", []),
            "fee": EXCHANGES[name]["fee"],
        }

    return jsonify({
        "exchanges": exchange_status,
        "metadata": meta,
    })


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
