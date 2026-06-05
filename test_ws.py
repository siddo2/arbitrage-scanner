#!/usr/bin/env python3
"""
Test WebSocket connectivity for blocked exchanges.
Run: python test_ws.py
"""
import json
import threading
import time
import websocket

RESULTS = {}

def test_binance():
    try:
        received = []
        ws = websocket.create_connection(
            "wss://stream.binance.com:9443/ws/!bookTicker",
            timeout=10
        )
        for _ in range(3):
            msg = ws.recv()
            received.append(json.loads(msg))
        ws.close()
        RESULTS["Binance"] = f"OK — {len(received)} messages, sample: {received[0].get('s')} bid={received[0].get('b')}"
    except Exception as e:
        RESULTS["Binance"] = f"FAIL — {type(e).__name__}: {e}"

def test_okx():
    try:
        ws = websocket.create_connection("wss://ws.okx.com:8443/ws/v5/public", timeout=10)
        sub = json.dumps({"op": "subscribe", "args": [{"channel": "tickers", "instId": "BTC-USDT"}]})
        ws.send(sub)
        msg = json.loads(ws.recv())
        msg2 = json.loads(ws.recv())
        ws.close()
        data = msg2.get("data", [{}])
        RESULTS["OKX"] = f"OK — last={data[0].get('last') if data else 'n/a'}"
    except Exception as e:
        RESULTS["OKX"] = f"FAIL — {type(e).__name__}: {e}"

def test_bitmart():
    try:
        ws = websocket.create_connection("wss://ws-manager-compress.bitmart.com/api?protocol=1.1", timeout=10)
        sub = json.dumps({"op": "subscribe", "args": ["spot/ticker:BTC_USDT"]})
        ws.send(sub)
        msg = ws.recv()
        ws.close()
        RESULTS["BitMart"] = f"OK — {str(msg)[:100]}"
    except Exception as e:
        RESULTS["BitMart"] = f"FAIL — {type(e).__name__}: {e}"

def test_coinex():
    try:
        ws = websocket.create_connection("wss://socket.coinex.com/v2/spot/", timeout=10)
        sub = json.dumps({"method": "state.subscribe", "params": {"market_list": ["BTCUSDT"]}, "id": 1})
        ws.send(sub)
        msg = ws.recv()
        ws.close()
        RESULTS["CoinEx"] = f"OK — {str(msg)[:100]}"
    except Exception as e:
        RESULTS["CoinEx"] = f"FAIL — {type(e).__name__}: {e}"

tests = [test_binance, test_okx, test_bitmart, test_coinex]
threads = [threading.Thread(target=t) for t in tests]
for t in threads: t.start()
for t in threads: t.join(timeout=15)

print("\n=== WebSocket Test Results ===")
for exchange, result in RESULTS.items():
    status = "✓" if result.startswith("OK") else "✗"
    print(f"  {status} {exchange}: {result}")
