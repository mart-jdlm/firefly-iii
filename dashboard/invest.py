"""The PEA: positions, Yahoo Finance prices (with a fallback), deposits, dividends, fees and the index benchmark."""

import concurrent.futures
import datetime as dt
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import firefly


PEA_POSITIONS = os.environ.get("PEA_POSITIONS", "/patrimoine/pea.txt")

PEA_BREAKDOWN = os.environ.get("PEA_BREAKDOWN", "/patrimoine/repartition.json")

YAHOO_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")

_last_good: dict[str, tuple[str, object]] = {}  # what Yahoo last answered, per request: (date, value)

_last_good_lock = threading.Lock()


def yahoo_chart(symbol: str, params: str) -> dict | None:
    """The `result` of Yahoo Finance's chart API for a symbol, trying both of its hosts; None when
    neither answers properly. Yahoo has no official API and fails now and then."""
    for host in YAHOO_HOSTS:
        url = f"https://{host}/v8/finance/chart/{urllib.parse.quote(symbol)}?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)["chart"]["result"][0]
        except (urllib.error.URLError, KeyError, TypeError, IndexError, ValueError):
            continue
    return None


def remember(key: str, value) -> None:
    with _last_good_lock:
        _last_good[key] = (dt.date.today().isoformat(), value)


def last_good(key: str) -> tuple[object, str] | None:
    with _last_good_lock:
        old = _last_good.get(key)
    return (old[1], old[0]) if old else None


def yahoo_quote(symbol: str) -> dict | None:
    """Last price and previous close of a Yahoo Finance symbol, only when quoted in euros. When
    Yahoo cannot be reached the last price seen is returned, marked with the day it is from
    ("as_of"), so the PEA is not undervalued by a missing line."""
    result = yahoo_chart(symbol, "range=1d&interval=1d")
    if result is None:
        old = last_good("quote" + symbol)
        return {**old[0], "as_of": old[1]} if old else None
    try:
        meta = result["meta"]
        if meta["currency"] != "EUR":
            return None
        quote = {"price": meta["regularMarketPrice"],
                 "previous": meta.get("chartPreviousClose") or meta.get("previousClose")}
    except (KeyError, TypeError):
        return None
    remember("quote" + symbol, quote)
    return quote


def yahoo_history(symbol: str, since: str) -> list[list] | None:
    """Daily closes [[date, price], ...] of a euro Yahoo Finance symbol from `since` (YYYY-MM-DD)
    to now; the last good history when Yahoo cannot be reached, None when there is none."""
    start = int(dt.datetime.combine(dt.date.fromisoformat(since) - dt.timedelta(days=7), dt.time(), dt.timezone.utc).timestamp())
    key = f"history{symbol}{since}"
    result = yahoo_chart(symbol, f"period1={start}&period2={int(time.time()) + 86400}&interval=1d")
    if result is None:
        old = last_good(key)
        return old[0] if old else None
    try:
        if result["meta"]["currency"] != "EUR":
            return None
        closes = result["indicators"]["quote"][0]["close"]
        days = [[dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat(), round(close, 4)]
                for ts, close in zip(result["timestamp"], closes) if close]
    except (KeyError, TypeError, IndexError, ValueError):
        return None
    if days:
        remember(key, days)
    return days or None


BENCHMARK = os.environ.get("PEA_BENCHMARK", "CW8.PA")

BENCHMARK_LABEL = os.environ.get("PEA_BENCHMARK_LABEL", "MSCI World")


PRU_WORD = re.compile(r"(?:^|\s)pru=(\d+(?:[.,]\d+)?)(?=\s|$)")


def split_label(label: str) -> tuple[str, float | None]:
    """A line's comment without its `pru=` word, and that average purchase price per share (None
    when absent). The word lives in the comment so valuation.sh and older readers ignore it."""
    found = PRU_WORD.search(label)
    if not found:
        return label, None
    return " ".join(PRU_WORD.sub(" ", label).split()), float(found.group(1).replace(",", "."))


def read_positions() -> list[dict] | None:
    """Lines of the PEA positions file (symbol, quantity, label, pru), None without the file."""
    try:
        f = open(PEA_POSITIONS, encoding="utf-8")
    except FileNotFoundError:
        return None
    lines = []
    with f:
        for raw in f:
            parts = raw.split(None, 2)
            if not parts or parts[0].startswith("#"):
                continue
            try:
                label, pru = split_label(parts[2].strip() if len(parts) > 2 else "")
                lines.append({"symbol": parts[0], "quantity": float(parts[1]), "label": label, "pru": pru})
            except (IndexError, ValueError):
                continue
    return lines


def read_breakdown() -> dict | None:
    """What each holding is made of, from patrimoine/repartition.json (None without a usable file):
    {symbol: {"classe": "Actions", "zones": {"Europe": 60, ...}, "secteurs": {...}}}. Weights are
    percentages; anything malformed is dropped rather than shown wrong."""
    try:
        with open(PEA_BREAKDOWN, encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return None
    if not isinstance(raw, dict):
        return None

    def weights(value) -> dict:
        if not isinstance(value, dict):
            return {}
        return {str(k): float(w) for k, w in value.items()
                if isinstance(w, (int, float)) and not isinstance(w, bool) and w > 0}

    out = {}
    for symbol, info in raw.items():
        if not isinstance(info, dict) or symbol.startswith("_"):
            continue
        out[symbol] = {"classe": str(info["classe"]) if isinstance(info.get("classe"), str) else None,
                       "zones": weights(info.get("zones")), "secteurs": weights(info.get("secteurs"))}
    return out or None


DIVIDEND_WORDS = re.compile(r"dividende", re.I)

FEE_WORDS = re.compile(r"frais|courtage|commission", re.I)


def pea_kind(category: str | None) -> str:
    """How a PEA transaction counts: its category says dividend or fee, anything else is a deposit
    or withdrawal of the owner's own money."""
    if category and DIVIDEND_WORDS.search(category):
        return "dividend"
    if category and FEE_WORDS.search(category):
        return "fee"
    return "flow"


def benchmark_data(flows: list[dict]) -> dict | None:
    prices = yahoo_history(BENCHMARK, flows[0]["date"]) if flows else None
    return {"symbol": BENCHMARK, "label": BENCHMARK_LABEL, "prices": prices} if prices else None


def pea_data() -> dict:
    accounts = [a for a in firefly.api_all("/accounts", {"type": "asset"})
                if a["attributes"]["name"].startswith(firefly.INVESTMENT_PREFIX)]
    balance = firefly.money(sum(float(a["attributes"]["current_balance"]) for a in accounts))
    monthly: dict[str, float] = {}
    flows: list[dict] = []
    extras = {"dividend": [], "fee": []}  # what the PEA earned or paid itself, by date
    for account in accounts:
        for group in firefly.api_all(f"/accounts/{account['id']}/transactions", {"type": "all"}):
            for t in group["attributes"]["transactions"]:
                if t["category_name"] == "Valorisation":
                    continue
                amount = float(t["amount"])
                if t["destination_id"] == account["id"]:
                    pass
                elif t["source_id"] == account["id"]:
                    amount = -amount
                else:
                    continue
                kind = pea_kind(t["category_name"])
                if kind != "flow":
                    extras[kind].append({"date": t["date"][:10], "amount": abs(firefly.money(amount))})
                    continue
                month = t["date"][:7]
                monthly[month] = round(monthly.get(month, 0) + amount, 2)
                flows.append({"date": t["date"][:10], "amount": firefly.money(amount)})
    flows.sort(key=lambda f: f["date"])
    invested = firefly.money(sum(monthly.values()))

    positions, cash = [], 0.0
    lines = read_positions()
    if lines:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            quotes = list(pool.map(lambda l: None if l["symbol"] == "especes" else yahoo_quote(l["symbol"]), lines))
        for line, quote in zip(lines, quotes):
            if line["symbol"] == "especes":
                cash += line["quantity"]
                continue
            price = quote["price"] if quote else None
            previous = quote["previous"] if quote else None
            pru = line.get("pru")
            positions.append({
                "symbol": line["symbol"], "label": line["label"], "quantity": line["quantity"],
                "pru": pru, "cost": firefly.money(line["quantity"] * pru) if pru else None,
                "price": price, "value": firefly.money(line["quantity"] * price) if price else None,
                "as_of": quote.get("as_of") if quote else None,
                "day": round((price / previous - 1) * 100, 2) if price and previous else None,
            })
    else:
        cash = balance
    return {"has_file": lines is not None, "balance": balance, "invested": invested,
            "contributions": monthly, "flows": flows,
            "dividends": sorted(extras["dividend"], key=lambda e: e["date"]),
            "fees": sorted(extras["fee"], key=lambda e: e["date"]), "positions": positions, "cash": firefly.money(cash),
            "benchmark": benchmark_data(flows), "breakdown": read_breakdown()}
