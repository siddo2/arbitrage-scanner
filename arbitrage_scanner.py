#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║         ARBITRAGE SCANNER — USDT PAIRS                  ║
║  Exchanges: Binance, OKX, KuCoin, Gate.io, MEXC,        ║
║             HTX, CoinEx, BitMart, LBank, AscendEX, XT   ║
╚══════════════════════════════════════════════════════════╝

Prérequis:
    pip install requests colorama tabulate

Usage:
    python3 arbitrage_scanner.py
    python3 arbitrage_scanner.py --min-spread 0.5 --min-volume 100000
    python3 arbitrage_scanner.py --refresh 10 --top 20
    python3 arbitrage_scanner.py --pairs BTC ETH SOL   (paires spécifiques)
    python3 arbitrage_scanner.py --export              (sauvegarde CSV)
"""

import requests
import time
import os
import sys
import argparse
import csv
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from tabulate import tabulate
from colorama import init, Fore, Back, Style

init(autoreset=True)

# Mode serveur : désactive clear écran et couleurs si pas de terminal interactif
IS_TTY = sys.stdout.isatty()

# ─────────────────────────────────────────────
#  CONFIGURATION DES EXCHANGES
# ─────────────────────────────────────────────

EXCHANGES = {
    "Binance": {
        "url": "https://api.binance.com/api/v3/ticker/bookTicker",
        "url_vol": "https://api.binance.com/api/v3/ticker/24hr",
        "parser": "binance",
        "fee": 0.001,  # 0.1% taker
    },
    "OKX": {
        "url": "https://www.okx.com/api/v5/market/tickers?instType=SPOT",
        "parser": "okx",
        "fee": 0.001,
    },
    "KuCoin": {
        "url": "https://api.kucoin.com/api/v1/market/allTickers",
        "parser": "kucoin",
        "fee": 0.001,
    },
    "Gate.io": {
        "url": "https://api.gateio.ws/api/v4/spot/tickers",
        "parser": "gate",
        "fee": 0.002,
    },
    "MEXC": {
        "url": "https://api.mexc.com/api/v3/ticker/bookTicker",
        "parser": "mexc",
        "fee": 0.002,
    },
    "HTX": {
        "url": "https://api.huobi.pro/market/tickers",
        "parser": "htx",
        "fee": 0.002,
    },
    "CoinEx": {
        "url": "https://api.coinex.com/v2/spot/ticker",
        "parser": "coinex",
        "fee": 0.002,
    },
    "BitMart": {
        "url": "https://api-cloud.bitmart.com/spot/quotation/v3/tickers",
        "parser": "bitmart",
        "fee": 0.0025,
    },
    "LBank": {
        "url": "https://api.lbank.info/v2/ticker/24hr.do?symbol=all",
        "parser": "lbank",
        "fee": 0.002,
    },
    "AscendEX": {
        "url": "https://ascendex.com/api/pro/v1/ticker",
        "parser": "ascendex",
        "fee": 0.002,
    },
    "XT": {
        "url": "https://sapi.xt.com/v4/public/ticker",
        "parser": "xt",
        "fee": 0.002,
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ArbitrageScanner/1.0)",
    "Accept": "application/json",
}

TIMEOUT = 8  # secondes

# ─────────────────────────────────────────────
#  PARSEURS PAR EXCHANGE
#  Retourne dict: { "BTCUSDT": {"bid": float, "ask": float, "volume": float} }
# ─────────────────────────────────────────────

def parse_binance(data):
    result = {}
    for item in data:
        sym = item.get("symbol", "")
        if sym.endswith("USDT"):
            try:
                result[sym] = {
                    "bid": float(item["bidPrice"]),
                    "ask": float(item["askPrice"]),
                    "volume": 0,  # sera complété par parse_binance_vol
                }
            except (KeyError, ValueError):
                pass
    return result

def parse_binance_vol(data):
    """Volumes 24h depuis /api/v3/ticker/24hr"""
    result = {}
    for item in data:
        sym = item.get("symbol", "")
        if sym.endswith("USDT"):
            try:
                result[sym] = float(item.get("quoteVolume", 0))
            except (ValueError, TypeError):
                pass
    return result

def parse_okx(data):
    result = {}
    items = data.get("data", [])
    for item in items:
        inst = item.get("instId", "")
        if inst.endswith("-USDT"):
            sym = inst.replace("-", "")
            try:
                bid = float(item.get("bidPx") or item.get("last", 0))
                ask = float(item.get("askPx") or item.get("last", 0))
                vol = float(item.get("volCcy24h", 0))
                if bid > 0 and ask > 0:
                    result[sym] = {"bid": bid, "ask": ask, "volume": vol}
            except (ValueError, TypeError):
                pass
    return result

def parse_kucoin(data):
    result = {}
    ticker = data.get("data", {}).get("ticker", [])
    for item in ticker:
        sym = item.get("symbol", "")
        if sym.endswith("-USDT"):
            norm = sym.replace("-", "")
            try:
                buy = float(item.get("buy") or 0)
                sell = float(item.get("sell") or 0)
                vol = float(item.get("volValue") or 0)
                if buy > 0 and sell > 0:
                    result[norm] = {"bid": buy, "ask": sell, "volume": vol}
            except (ValueError, TypeError):
                pass
    return result

def parse_gate(data):
    result = {}
    for item in data:
        pair = item.get("currency_pair", "")
        if pair.endswith("_USDT"):
            norm = pair.replace("_", "")
            try:
                bid = float(item.get("highest_bid") or item.get("last", 0))
                ask = float(item.get("lowest_ask") or item.get("last", 0))
                vol = float(item.get("quote_volume") or 0)
                if bid > 0 and ask > 0:
                    result[norm] = {"bid": bid, "ask": ask, "volume": vol}
            except (ValueError, TypeError):
                pass
    return result

def parse_mexc(data):
    result = {}
    for item in data:
        sym = item.get("symbol", "")
        if sym.endswith("USDT"):
            try:
                bid = float(item.get("bidPrice") or 0)
                ask = float(item.get("askPrice") or 0)
                if bid > 0 and ask > 0:
                    result[sym] = {"bid": bid, "ask": ask, "volume": 0}
            except (ValueError, TypeError):
                pass
    return result

def parse_htx(data):
    result = {}
    items = data.get("data", [])
    for item in items:
        sym = item.get("symbol", "")
        if sym.endswith("usdt"):
            norm = sym.upper()
            try:
                bid = float(item.get("bid") or 0)
                ask = float(item.get("ask") or 0)
                vol = float(item.get("vol") or 0)
                if bid > 0 and ask > 0:
                    result[norm] = {"bid": bid, "ask": ask, "volume": vol}
            except (ValueError, TypeError):
                pass
    return result

def parse_coinex(data):
    result = {}
    items = data.get("data", {})
    if isinstance(items, list):
        for item in items:
            market = item.get("market", "")
            if market.endswith("USDT"):
                try:
                    ticker = item.get("ticker", {})
                    bid = float(ticker.get("best_bid_price") or ticker.get("last", 0))
                    ask = float(ticker.get("best_ask_price") or ticker.get("last", 0))
                    vol = float(ticker.get("quote_volume") or 0)
                    if bid > 0 and ask > 0:
                        result[market] = {"bid": bid, "ask": ask, "volume": vol}
                except (ValueError, TypeError):
                    pass
    return result

def parse_bitmart(data):
    result = {}
    items = data.get("data", [])
    for item in items:
        sym = item.get("symbol", "")
        if sym.endswith("_USDT"):
            norm = sym.replace("_", "")
            try:
                bid = float(item.get("best_bid") or item.get("last_price", 0))
                ask = float(item.get("best_ask") or item.get("last_price", 0))
                vol = float(item.get("quote_volume_24h") or 0)
                if bid > 0 and ask > 0:
                    result[norm] = {"bid": bid, "ask": ask, "volume": vol}
            except (ValueError, TypeError):
                pass
    return result

def parse_lbank(data):
    result = {}
    items = data.get("data", [])
    for item in items:
        sym = item.get("symbol", "")
        if sym.endswith("_usdt"):
            norm = sym.upper().replace("_", "")
            try:
                ticker = item.get("ticker", {})
                last = float(ticker.get("latest") or ticker.get("close", 0))
                vol = float(ticker.get("turnover") or 0)
                if last > 0:
                    spread = last * 0.0003
                    result[norm] = {"bid": last - spread, "ask": last + spread, "volume": vol}
            except (ValueError, TypeError):
                pass
    return result

def parse_ascendex(data):
    result = {}
    items = data.get("data", [])
    for item in items:
        sym = item.get("symbol", "")
        if sym.endswith("/USDT"):
            norm = sym.replace("/", "")
            try:
                bid = float(item.get("bid", [0])[0] if isinstance(item.get("bid"), list) else item.get("bid", 0))
                ask = float(item.get("ask", [0])[0] if isinstance(item.get("ask"), list) else item.get("ask", 0))
                vol = float(item.get("volume", 0))
                if bid > 0 and ask > 0:
                    result[norm] = {"bid": bid, "ask": ask, "volume": vol}
            except (ValueError, TypeError):
                pass
    return result

def parse_xt(data):
    result = {}
    items = data.get("result", {}).get("tickers", []) if isinstance(data.get("result"), dict) else data.get("result", [])
    if not items and isinstance(data, list):
        items = data
    for item in items:
        sym = item.get("s", item.get("symbol", ""))
        if sym.endswith("_usdt") or sym.endswith("_USDT"):
            norm = sym.upper().replace("_", "")
            try:
                bid = float(item.get("bp") or item.get("bid") or item.get("c", 0))
                ask = float(item.get("ap") or item.get("ask") or item.get("c", 0))
                vol = float(item.get("qv") or item.get("quoteVolume") or 0)
                if bid > 0 and ask > 0:
                    result[norm] = {"bid": bid, "ask": ask, "volume": vol}
            except (ValueError, TypeError):
                pass
    return result

PARSERS = {
    "binance": parse_binance,
    "okx": parse_okx,
    "kucoin": parse_kucoin,
    "gate": parse_gate,
    "mexc": parse_mexc,
    "htx": parse_htx,
    "coinex": parse_coinex,
    "bitmart": parse_bitmart,
    "lbank": parse_lbank,
    "ascendex": parse_ascendex,
    "xt": parse_xt,
}

# ─────────────────────────────────────────────
#  FETCH DONNÉES
# ─────────────────────────────────────────────

def fetch_exchange(name, config):
    """Récupère les données d'un exchange. Retourne (name, data_dict) ou (name, None)."""
    try:
        r = requests.get(config["url"], headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        raw = r.json()
        parser = PARSERS[config["parser"]]
        parsed = parser(raw)

        # Binance: second appel pour récupérer les volumes 24h
        if name == "Binance" and "url_vol" in config:
            try:
                r_vol = requests.get(config["url_vol"], headers=HEADERS, timeout=TIMEOUT)
                r_vol.raise_for_status()
                volumes = parse_binance_vol(r_vol.json())
                for sym in parsed:
                    if sym in volumes:
                        parsed[sym]["volume"] = volumes[sym]
            except Exception:
                pass  # volumes restent à 0 si l'appel échoue

        return name, parsed
    except Exception as e:
        return name, None

def fetch_all_exchanges(verbose=False):
    """Fetch tous les exchanges en parallèle."""
    results = {}
    errors = []

    with ThreadPoolExecutor(max_workers=11) as executor:
        futures = {
            executor.submit(fetch_exchange, name, cfg): name
            for name, cfg in EXCHANGES.items()
        }
        for future in as_completed(futures):
            name, data = future.result()
            if data is not None:
                results[name] = data
                if verbose:
                    print(f"  {Fore.GREEN}✓{Style.RESET_ALL} {name}: {len(data)} paires")
            else:
                errors.append(name)
                if verbose:
                    print(f"  {Fore.RED}✗{Style.RESET_ALL} {name}: erreur")

    return results, errors

# ─────────────────────────────────────────────
#  CALCUL OPPORTUNITÉS
# ─────────────────────────────────────────────

def find_opportunities(market_data, min_spread_pct=0.3, min_volume=50000, filter_pairs=None):
    """
    Pour chaque paire commune, trouve le meilleur bid et le meilleur ask
    sur tous les exchanges, puis calcule le spread net.
    """
    # Index: symbol -> {exchange_name: {bid, ask, volume}}
    index = {}
    for exchange_name, pairs in market_data.items():
        fee = EXCHANGES[exchange_name]["fee"]
        for symbol, data in pairs.items():
            if filter_pairs:
                base = symbol.replace("USDT", "")
                if base not in [p.upper() for p in filter_pairs]:
                    continue
            if symbol not in index:
                index[symbol] = {}
            index[symbol][exchange_name] = {**data, "fee": fee}

    opportunities = []

    for symbol, exchanges in index.items():
        if len(exchanges) < 2:
            continue

        # Trouver meilleur ask (acheter le moins cher) et meilleur bid (vendre le plus cher)
        best_ask = None
        best_bid = None

        for exname, d in exchanges.items():
            ask = d["ask"]
            bid = d["bid"]
            if ask > 0:
                if best_ask is None or ask < best_ask["price"]:
                    best_ask = {"exchange": exname, "price": ask, "volume": d["volume"], "fee": d["fee"]}
            if bid > 0:
                if best_bid is None or bid > best_bid["price"]:
                    best_bid = {"exchange": exname, "price": bid, "volume": d["volume"], "fee": d["fee"]}

        if not best_ask or not best_bid:
            continue
        if best_ask["exchange"] == best_bid["exchange"]:
            continue

        spread_brut = ((best_bid["price"] - best_ask["price"]) / best_ask["price"]) * 100
        total_fees = (best_ask["fee"] + best_bid["fee"]) * 100
        spread_net = spread_brut - total_fees

        min_vol = min(best_ask["volume"], best_bid["volume"])
        if min_vol == 0:
            # Volume non dispo: on garde quand même mais avec indicateur
            min_vol_display = "N/A"
        else:
            min_vol_display = min_vol

        if spread_brut < min_spread_pct:
            continue
        if isinstance(min_vol_display, float) and min_vol_display < min_volume:
            continue

        score = spread_net * (1 + (min_vol / 1_000_000 if isinstance(min_vol, (int, float)) else 0))

        base = symbol.replace("USDT", "")
        opportunities.append({
            "pair": f"{base}/USDT",
            "buy_exchange": best_ask["exchange"],
            "buy_price": best_ask["price"],
            "sell_exchange": best_bid["exchange"],
            "sell_price": best_bid["price"],
            "spread_brut": spread_brut,
            "spread_net": spread_net,
            "fees": total_fees,
            "volume": min_vol_display,
            "score": score,
            "nb_exchanges": len(exchanges),
        })

    return sorted(opportunities, key=lambda x: x["score"], reverse=True)

# ─────────────────────────────────────────────
#  AFFICHAGE
# ─────────────────────────────────────────────

def clear():
    if IS_TTY:
        os.system("cls" if os.name == "nt" else "clear")

def color_spread(val):
    if not IS_TTY:
        prefix = "+" if val >= 0 else ""
        return f"{prefix}{val:.3f}%"
    if val >= 1.5:
        return f"{Fore.YELLOW}{Style.BRIGHT}+{val:.3f}%{Style.RESET_ALL}"
    elif val >= 0.7:
        return f"{Fore.GREEN}+{val:.3f}%{Style.RESET_ALL}"
    elif val >= 0:
        return f"{Fore.CYAN}+{val:.3f}%{Style.RESET_ALL}"
    else:
        return f"{Fore.RED}{val:.3f}%{Style.RESET_ALL}"

def format_price(price):
    if price >= 10000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.4f}"
    elif price >= 0.001:
        return f"{price:.6f}"
    else:
        return f"{price:.8f}"

def format_volume(vol):
    if vol == "N/A" or vol == 0:
        return "N/A" if not IS_TTY else f"{Fore.LIGHTBLACK_EX}N/A{Style.RESET_ALL}"
    if vol >= 1_000_000_000:
        return f"${vol/1_000_000_000:.2f}B"
    elif vol >= 1_000_000:
        return f"${vol/1_000_000:.2f}M"
    elif vol >= 1_000:
        return f"${vol/1_000:.1f}K"
    return f"${vol:.0f}"

def print_dashboard(opportunities, market_data, errors, args, elapsed):
    clear()

    now = datetime.now().strftime("%H:%M:%S")
    ok_count = len(market_data)
    total_pairs = sum(len(v) for v in market_data.values())

    if IS_TTY:
        print(f"{Fore.GREEN}{Style.BRIGHT}")
        print("╔══════════════════════════════════════════════════════════════════════════════════╗")
        print("║              ⚡  ARBITRAGE SCANNER — USDT PAIRS — PRIX RÉELS                   ║")
        print("╚══════════════════════════════════════════════════════════════════════════════════╝")
        print(Style.RESET_ALL)
        status = f"{Fore.GREEN}●{Style.RESET_ALL}" if ok_count == len(EXCHANGES) else f"{Fore.YELLOW}●{Style.RESET_ALL}"
        print(f"  {status} {now}  │  "
              f"{Fore.GREEN}{ok_count}/{len(EXCHANGES)} exchanges{Style.RESET_ALL}  │  "
              f"{Fore.CYAN}{total_pairs:,} paires{Style.RESET_ALL}  │  "
              f"{Fore.YELLOW}{len(opportunities)} opportunités{Style.RESET_ALL}  │  "
              f"Fetch: {elapsed:.1f}s")
    else:
        print(f"\n[{now}] {ok_count}/{len(EXCHANGES)} exchanges | {total_pairs:,} paires | {len(opportunities)} opportunités | Fetch: {elapsed:.1f}s")

    if errors:
        print(f"  Erreurs: {', '.join(errors)}")

    if not IS_TTY:
        print(f"  Filtres: spread >= {args.min_spread}% | volume >= ${args.min_volume:,.0f} | top {args.top}\n")
    else:
        print(f"\n  Filtres: spread ≥ {Fore.CYAN}{args.min_spread}%{Style.RESET_ALL}  │  "
              f"volume ≥ {Fore.CYAN}{format_volume(args.min_volume)}{Style.RESET_ALL}  │  "
              f"top {Fore.CYAN}{args.top}{Style.RESET_ALL}\n")

    if not opportunities:
        print("  Aucune opportunité trouvée. Réduis les filtres (--min-spread 0.1)\n")
        return

    top = opportunities[:args.top]
    rows = []
    for i, op in enumerate(top, 1):
        spread_net_str = color_spread(op["spread_net"])
        spread_brut_str = f"+{op['spread_brut']:.3f}%"
        if IS_TTY:
            indicator = "🔥" if op["spread_brut"] >= 1.5 else ("✅" if op["spread_brut"] >= 0.8 else "  ")
            rows.append([
                f"{i}",
                f"{indicator} {op['pair']}",
                f"{Fore.YELLOW}{op['buy_exchange']}{Style.RESET_ALL}",
                format_price(op["buy_price"]),
                f"{Fore.GREEN}{op['sell_exchange']}{Style.RESET_ALL}",
                format_price(op["sell_price"]),
                f"{Fore.WHITE}{spread_brut_str}{Style.RESET_ALL}",
                spread_net_str,
                f"{Fore.RED}-{op['fees']:.3f}%{Style.RESET_ALL}",
                format_volume(op["volume"]),
                f"{op['nb_exchanges']}",
            ])
        else:
            rows.append([
                i, op["pair"],
                op["buy_exchange"], format_price(op["buy_price"]),
                op["sell_exchange"], format_price(op["sell_price"]),
                spread_brut_str, spread_net_str,
                f"-{op['fees']:.3f}%",
                format_volume(op["volume"]),
                op["nb_exchanges"],
            ])

    headers = ["#", "PAIRE", "ACHETER SUR", "PRIX ACHAT", "VENDRE SUR", "PRIX VENTE",
               "SPREAD BRUT", "SPREAD NET", "FRAIS", "VOLUME MIN", "EX"]
    print(tabulate(rows, headers=headers, tablefmt="rounded_outline" if IS_TTY else "simple"))

    if IS_TTY:
        print(f"\n  {Fore.LIGHTBLACK_EX}Spread net = spread brut − frais d'échange des deux côtés{Style.RESET_ALL}")
        print(f"  {Fore.LIGHTBLACK_EX}Volume Min = plus petit des deux volumes (le vrai limitant){Style.RESET_ALL}")

# ─────────────────────────────────────────────
#  EXPORT CSV
# ─────────────────────────────────────────────

def export_csv(opportunities):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"arbitrage_{ts}.csv"
    fieldnames = ["pair", "buy_exchange", "buy_price", "sell_exchange", "sell_price",
                  "spread_brut", "spread_net", "fees", "volume", "score", "nb_exchanges"]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for op in opportunities:
            writer.writerow(op)
    print(f"\n  {Fore.GREEN}✓ Export: {filename}{Style.RESET_ALL}")
    return filename

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Arbitrage Scanner Crypto — USDT Pairs")
    parser.add_argument("--min-spread", type=float, default=0.3,
                        help="Spread minimum brut en %% (défaut: 0.3)")
    parser.add_argument("--min-volume", type=float, default=50000,
                        help="Volume minimum 24h en USD (défaut: 50000)")
    parser.add_argument("--top", type=int, default=25,
                        help="Nombre d'opportunités à afficher (défaut: 25)")
    parser.add_argument("--refresh", type=int, default=15,
                        help="Intervalle de rafraîchissement en secondes (défaut: 15)")
    parser.add_argument("--once", action="store_true",
                        help="Scan unique sans boucle")
    parser.add_argument("--pairs", nargs="+",
                        help="Filtrer sur des paires spécifiques, ex: BTC ETH SOL")
    parser.add_argument("--export", action="store_true",
                        help="Exporter les résultats en CSV")
    parser.add_argument("--verbose", action="store_true",
                        help="Afficher les détails du fetch")
    return parser.parse_args()

def main():
    args = parse_args()

    print(f"\n{Fore.GREEN}{Style.BRIGHT}  ⚡ ARBITRAGE SCANNER — démarrage...{Style.RESET_ALL}")
    print(f"  Exchanges: {', '.join(EXCHANGES.keys())}")
    print(f"  Paramètres: spread ≥ {args.min_spread}% | volume ≥ ${args.min_volume:,.0f} | top {args.top}")
    if args.pairs:
        print(f"  Paires filtrées: {', '.join(p.upper() for p in args.pairs)}")
    print()

    iteration = 0

    while True:
        iteration += 1

        if args.verbose:
            print(f"\n  Fetch #{iteration}...")

        t0 = time.time()
        market_data, errors = fetch_all_exchanges(verbose=args.verbose)
        elapsed = time.time() - t0

        opportunities = find_opportunities(
            market_data,
            min_spread_pct=args.min_spread,
            min_volume=args.min_volume,
            filter_pairs=args.pairs,
        )

        print_dashboard(opportunities, market_data, errors, args, elapsed)

        if args.export and opportunities:
            export_csv(opportunities)

        if args.once:
            break

        print(f"\n  {Fore.LIGHTBLACK_EX}Prochain scan dans {args.refresh}s... (Ctrl+C pour arrêter){Style.RESET_ALL}")

        try:
            time.sleep(args.refresh)
        except KeyboardInterrupt:
            print(f"\n\n  {Fore.YELLOW}Arrêt du scanner.{Style.RESET_ALL}\n")
            sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {Fore.YELLOW}Arrêt du scanner.{Style.RESET_ALL}\n")
        sys.exit(0)
