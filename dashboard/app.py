"""Dashboard for Firefly III: income, spending, saving and net worth (see the README, "Dashboard").

Read-only web page in the spirit of Finary. It only issues GET requests to the Firefly III API,
needs FIREFLY_URL and FIREFLY_TOKEN, and has no dependency beyond the standard library.
Listens on port 8787; `tailscale serve` publishes it on the tailnet. DASHBOARD_ALLOWED_HOSTS
(comma separated, default localhost) lists the Host names accepted, against DNS rebinding.
"""

import calendar
import concurrent.futures
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIREFLY_URL = os.environ.get("FIREFLY_URL", "http://app:8080").rstrip("/")
FIREFLY_TOKEN = os.environ["FIREFLY_TOKEN"]
PEA_POSITIONS = os.environ.get("PEA_POSITIONS", "/patrimoine/pea.txt")
# Read-only here: goals of the assistant's goals file that follow an account's balance.
GOALS_FILE = os.environ.get("GOALS_FILE", "/patrimoine/objectifs.json")
# Read-only: the monthly reviews written by bilan/bilan.sh (YYYY-MM.facts.json, .comments.json, .html).
BILANS_DIR = os.environ.get("BILANS_DIR", "/bilans")
PORT = int(os.environ.get("DASHBOARD_PORT", "8787"))
ALLOWED = {h.strip() for h in os.environ.get("DASHBOARD_ALLOWED_HOSTS", "").split(",") if h.strip()}
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_SECONDS = 300
MAX_MONTHS = 36

# Same conventions as assistant/server.py: family debts and the PEA are asset accounts that are
# not money spent from, and the PEA is kept at market value by cron/valuation.sh.
DEBT_PREFIX = "Dette"
INVESTMENT_PREFIX = "PEA"
UNCATEGORISED = "(sans catégorie)"


def api(path: str, params: dict | list | None = None):
    url = f"{FIREFLY_URL}/api/v1{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {FIREFLY_TOKEN}", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def api_write(method: str, path: str, body: dict | None = None):
    """POST / PUT / DELETE to Firefly III; its validation message becomes a ValueError."""
    request = urllib.request.Request(
        f"{FIREFLY_URL}/api/v1{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {FIREFLY_TOKEN}", "Accept": "application/json",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
            return json.loads(content) if content else None
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read())
            errors = detail.get("errors") or {}
            message = " ".join(m for v in errors.values() for m in v) or detail.get("message", "")
        except ValueError:
            message = ""
        raise ValueError(message or f"Firefly III answered {e.code}") from e


def api_all(path: str, params: dict | None = None) -> list[dict]:
    items, page = [], 1
    while True:
        body = api(path, {**(params or {}), "limit": 200, "page": page})
        items += body["data"]
        if page >= body["meta"]["pagination"]["total_pages"]:
            return items
        page += 1


def money(value) -> float:
    return round(float(value or 0), 2)


def month_bounds(year: int, month: int) -> tuple[str, str]:
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1).isoformat(), dt.date(year, month, last).isoformat()


def months_back(count: int) -> list[tuple[int, int]]:
    today = dt.date.today()
    result = []
    for back in range(count - 1, -1, -1):
        year, month = divmod(today.year * 12 + today.month - 1 - back, 12)
        result.append((year, month + 1))
    return result


def insight(path: str, start: str, end: str, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    return api(f"/insight/{path}", [("start", start), ("end", end)] + [("accounts[]", i) for i in ids])


def by_category(kind: str, start: str, end: str, ids: list[str]) -> dict[str, float]:
    rows = {r["name"]: money(r["difference"]) for r in insight(f"{kind}/category", start, end, ids)}
    other = sum(float(r["difference"]) for r in insight(f"{kind}/no-category", start, end, ids))
    if other:
        rows[UNCATEGORISED] = money(other)
    # Expenses come back negative; the page works with positive amounts.
    return {name: abs(v) for name, v in rows.items() if v}


def net_worth_at(date: str) -> dict:
    groups = {"courant": 0.0, "epargne": 0.0, "investissements": 0.0, "dettes": 0.0}
    accounts = []
    for kind in ("asset", "liabilities"):
        for a in api_all("/accounts", {"type": kind, "date": date}):
            attr = a["attributes"]
            if not attr["active"] or not attr["include_net_worth"]:
                continue
            name, balance = attr["name"], money(attr["current_balance"])
            if attr["type"] == "liabilities" or name.startswith(DEBT_PREFIX):
                group = "dettes"
            elif name.startswith(INVESTMENT_PREFIX):
                group = "investissements"
            elif attr["account_role"] == "savingAsset":
                group = "epargne"
            else:
                group = "courant"
            groups[group] += balance
            accounts.append({"name": name, "group": group, "balance": balance})
    groups = {g: money(v) for g, v in groups.items()}
    return {**groups, "total": money(sum(groups.values())), "accounts": accounts}


def month_figures(year: int, month: int, everyday: list[str], investments: list[str]) -> dict:
    start, end = month_bounds(year, month)
    today = dt.date.today()
    end_date = min(today, dt.date.fromisoformat(end))
    expenses = by_category("expense", start, end, everyday)
    income = by_category("income", start, end, everyday)
    market = money(sum(float(r["difference"]) for kind in ("income", "expense")
                       for r in insight(f"{kind}/total", start, end, investments)))
    return {
        "month": start[:7],
        "expenses": expenses,
        "income": income,
        "earned": money(sum(income.values())),
        "spent": money(sum(expenses.values())),
        "market": market,
        "net_worth": net_worth_at(end_date.isoformat()),
    }


def build(months: int) -> dict:
    accounts = api_all("/accounts", {"type": "asset"})
    names = {a["id"]: a["attributes"]["name"] for a in accounts}
    investments = [i for i, n in names.items() if n.startswith(INVESTMENT_PREFIX)]
    everyday = [i for i, n in names.items() if not n.startswith((DEBT_PREFIX, INVESTMENT_PREFIX))]

    # One extra month before the first, to know how much net worth moved during it.
    periods = months_back(months + 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda p: month_figures(*p, everyday, investments), periods))

    result = []
    for previous, row in zip(rows, rows[1:]):
        change = money(row["net_worth"]["total"] - previous["net_worth"]["total"])
        row["change"] = change
        # What was really put aside: net worth growth without the PEA's market moves. Money
        # borrowed from family counts negatively.
        row["saved"] = money(change - row["market"])
        row["saved_simple"] = money(row["earned"] - row["spent"])
        result.append(row)
    return {
        "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "currency": "EUR",
        "months": result,
    }


def expense_tree(month: str) -> dict:
    """Spending of one month as {budget: {category: amount}}, from the withdrawals of everyday
    accounts. Budgets are the coarse groups (Vie courante, Loisirs...), categories the detail."""
    year, mon = map(int, month.split("-"))
    start, end = month_bounds(year, mon)
    names = {a["id"]: a["attributes"]["name"] for a in api_all("/accounts", {"type": "asset"})}
    everyday = {i for i, n in names.items() if not n.startswith((DEBT_PREFIX, INVESTMENT_PREFIX))}
    # Widened by a day and checked below, so the bounds are inclusive whatever the operators do.
    query = (f"type:withdrawal date_after:{dt.date.fromisoformat(start) - dt.timedelta(days=1)} "
             f"date_before:{dt.date.fromisoformat(end) + dt.timedelta(days=1)}")
    tree: dict[str, dict[str, float]] = {}
    page = 1
    while True:
        body = api("/search/transactions", {"query": query, "limit": 200, "page": page})
        for group in body["data"]:
            for t in group["attributes"]["transactions"]:
                if (t["source_id"] not in everyday or t["category_name"] == "Valorisation"
                        or not start <= t["date"][:10] <= end):
                    continue
                budget = t["budget_name"] or "Sans budget"
                category = t["category_name"] or UNCATEGORISED
                tree.setdefault(budget, {})
                tree[budget][category] = tree[budget].get(category, 0) + float(t["amount"])
        if page >= body["meta"]["pagination"]["total_pages"]:
            break
        page += 1
    return {b: {c: money(v) for c, v in cats.items()} for b, cats in tree.items()}


def everyday_ids() -> set[str]:
    return {a["id"] for a in api_all("/accounts", {"type": "asset"})
            if not a["attributes"]["name"].startswith((DEBT_PREFIX, INVESTMENT_PREFIX))}


def everyday_row(t: dict, group_id: str, everyday: set[str]) -> dict | None:
    """A search hit as the page shows it, or None when it does not touch an everyday account
    (the PEA, family debts) or is a PEA valuation."""
    if t["category_name"] == "Valorisation":
        return None
    kind = t["type"]
    mine = (t["source_id"] in everyday if kind == "withdrawal"
            else t["destination_id"] in everyday if kind == "deposit"
            else t["source_id"] in everyday or t["destination_id"] in everyday)
    if not mine:
        return None
    return {"id": t["transaction_journal_id"], "group": group_id, "date": t["date"][:10], "type": kind,
            "description": t["description"], "amount": money(t["amount"]),
            "category": t["category_name"], "budget": t["budget_name"],
            "source": t["source_name"], "destination": t["destination_name"],
            "notes": t["notes"], "bill": t["bill_name"]}


def search_transactions(text: str) -> list[dict]:
    """The 30 most recent transactions whose description matches `text`, on any date."""
    text = " ".join(text.split())[:80]
    if len(text) < 2:
        return []
    everyday = everyday_ids()
    found = []
    for group in api("/search/transactions", {"query": f'description_contains:"{text.replace(chr(34), "")}"', "limit": 100})["data"]:
        for t in group["attributes"]["transactions"]:
            row = everyday_row(t, group["id"], everyday)
            if row:
                found.append(row)
    return sorted(found, key=lambda t: (t["date"], t["id"]), reverse=True)[:30]


def month_transactions(month: str) -> list[dict]:
    """Every transaction of a month touching an everyday account, newest first."""
    year, mon = map(int, month.split("-"))
    return range_transactions(*month_bounds(year, mon))


MAX_RANGE_DAYS = 1100


def range_transactions(start: str, end: str) -> list[dict]:
    """Every transaction from `start` to `end` (inclusive, YYYY-MM-DD) touching an everyday
    account, newest first."""
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if last < first or (last - first).days > MAX_RANGE_DAYS:
        raise ValueError("Période invalide")
    everyday = everyday_ids()
    query = (f"date_after:{dt.date.fromisoformat(start) - dt.timedelta(days=1)} "
             f"date_before:{dt.date.fromisoformat(end) + dt.timedelta(days=1)}")
    found, page = [], 1
    while True:
        body = api("/search/transactions", {"query": query, "limit": 200, "page": page})
        for group in body["data"]:
            for t in group["attributes"]["transactions"]:
                row = everyday_row(t, group["id"], everyday)
                if row and start <= row["date"] <= end:
                    found.append(row)
        if page >= body["meta"]["pagination"]["total_pages"]:
            break
        page += 1
    return sorted(found, key=lambda t: (t["date"], t["id"]), reverse=True)


def month_budgets(month: str) -> list[dict]:
    year, mon = map(int, month.split("-"))
    start, end = month_bounds(year, mon)
    result = []
    for b in api_all("/budgets"):
        attr = b["attributes"]
        if not attr["active"]:
            continue
        limits = api(f"/budgets/{b['id']}/limits", {"start": start, "end": end})["data"]
        amount = sum(float(l["attributes"]["amount"]) for l in limits)
        spent = sum(float(x["sum"]) for x in
                    api(f"/budgets/{b['id']}", {"start": start, "end": end})["data"]["attributes"]["spent"])
        result.append({"name": attr["name"], "limit": money(amount) if limits else None,
                       "spent": money(-spent)})
    return result


def bills_data() -> dict:
    today = dt.date.today()
    end = today + dt.timedelta(days=90)
    bills, upcoming = [], []
    for b in api_all("/bills", {"start": today.isoformat(), "end": end.isoformat()}):
        attr = b["attributes"]
        if not attr["active"]:
            continue
        average = money((float(attr["amount_min"]) + float(attr["amount_max"])) / 2)
        bills.append({"name": attr["name"], "amount": average, "frequency": attr["repeat_freq"],
                      "min": money(attr["amount_min"]), "max": money(attr["amount_max"])})
        for date in attr["pay_dates"]:
            if today.isoformat() <= date[:10] <= end.isoformat():
                upcoming.append({"date": date[:10], "name": attr["name"], "amount": average})
    piggies = [{"name": p["attributes"]["name"], "current": money(p["attributes"]["current_amount"]),
                "target": money(p["attributes"]["target_amount"]),
                "date": (p["attributes"]["target_date"] or "")[:10] or None}
               for p in api_all("/piggy-banks") if p["attributes"]["active"]]
    return {"bills": bills, "upcoming": sorted(upcoming, key=lambda u: u["date"]), "piggies": piggies}


def yahoo_quote(symbol: str) -> dict | None:
    """Last price and previous close of a Yahoo Finance symbol, only when quoted in euros."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=1d&interval=1d"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            meta = json.load(response)["chart"]["result"][0]["meta"]
        if meta["currency"] != "EUR":
            return None
        return {"price": meta["regularMarketPrice"],
                "previous": meta.get("chartPreviousClose") or meta.get("previousClose")}
    except (urllib.error.URLError, KeyError, TypeError, IndexError, ValueError):
        return None


BENCHMARK = os.environ.get("PEA_BENCHMARK", "CW8.PA")
BENCHMARK_LABEL = os.environ.get("PEA_BENCHMARK_LABEL", "MSCI World")


def yahoo_history(symbol: str, since: str) -> list[list] | None:
    """Daily closes [[date, price], ...] of a euro Yahoo Finance symbol from `since` (YYYY-MM-DD)
    to now; None when the quotes cannot be had."""
    start = int(dt.datetime.combine(dt.date.fromisoformat(since) - dt.timedelta(days=7), dt.time(), dt.timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?period1={start}&period2={int(time.time()) + 86400}&interval=1d")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)["chart"]["result"][0]
        if result["meta"]["currency"] != "EUR":
            return None
        closes = result["indicators"]["quote"][0]["close"]
        days = [[dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat(), round(close, 4)]
                for ts, close in zip(result["timestamp"], closes) if close]
        return days or None
    except (urllib.error.URLError, KeyError, TypeError, IndexError, ValueError):
        return None


def read_positions() -> list[dict] | None:
    """Lines of the PEA positions file (symbol, quantity, label), None without the file."""
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
                lines.append({"symbol": parts[0], "quantity": float(parts[1]),
                              "label": parts[2].strip() if len(parts) > 2 else ""})
            except (IndexError, ValueError):
                continue
    return lines


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
    accounts = [a for a in api_all("/accounts", {"type": "asset"})
                if a["attributes"]["name"].startswith(INVESTMENT_PREFIX)]
    balance = money(sum(float(a["attributes"]["current_balance"]) for a in accounts))
    monthly: dict[str, float] = {}
    flows: list[dict] = []
    extras = {"dividend": [], "fee": []}  # what the PEA earned or paid itself, by date
    for account in accounts:
        for group in api_all(f"/accounts/{account['id']}/transactions", {"type": "all"}):
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
                    extras[kind].append({"date": t["date"][:10], "amount": abs(money(amount))})
                    continue
                month = t["date"][:7]
                monthly[month] = round(monthly.get(month, 0) + amount, 2)
                flows.append({"date": t["date"][:10], "amount": money(amount)})
    flows.sort(key=lambda f: f["date"])
    invested = money(sum(monthly.values()))

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
            positions.append({
                "symbol": line["symbol"], "label": line["label"], "quantity": line["quantity"],
                "price": price, "value": money(line["quantity"] * price) if price else None,
                "day": round((price / previous - 1) * 100, 2) if price and previous else None,
            })
    else:
        cash = balance
    return {"has_file": lines is not None, "balance": balance, "invested": invested,
            "contributions": monthly, "flows": flows,
            "dividends": sorted(extras["dividend"], key=lambda e: e["date"]),
            "fees": sorted(extras["fee"], key=lambda e: e["date"]), "positions": positions, "cash": money(cash),
            "benchmark": benchmark_data(flows)}


def read_goal_file() -> list[dict]:
    try:
        with open(GOALS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, ValueError):
        return []


def goals_data() -> dict:
    """Savings goals: every active Firefly III piggy bank, plus the account goals of the goals file
    (read-only here; a goal of the file naming a piggy bank overrides its target and deadline)."""
    today = dt.date.today()
    # Same window as the assistant's goals tool: from the end of the month 3 months ago, so that
    # the page and the assistant give the same pace and arrival date.
    year, month = divmod(today.year * 12 + today.month - 1 - 3, 12)
    month += 1
    since = min(today, dt.date(year, month, calendar.monthrange(year, month)[1]))
    months = max((today - since).days / 30.44, 1)
    file_goals = read_goal_file()
    by_piggy = {g["piggy"]: g for g in file_goals if g.get("piggy")}

    accounts = api_all("/accounts", {"type": "asset"})
    now = {a["attributes"]["name"]: money(a["attributes"]["current_balance"]) for a in accounts}
    before = {a["attributes"]["name"]: money(a["attributes"]["current_balance"])
              for a in api_all("/accounts", {"type": "asset", "date": since.isoformat()})}

    piggies = [p for p in api_all("/piggy-banks") if p["attributes"]["active"]]
    # Money of an account already put in piggy banks cannot go in another one.
    assigned: dict[str, float] = {}
    for p in piggies:
        for a in p["attributes"]["accounts"]:
            assigned[a["name"]] = assigned.get(a["name"], 0) + float(a["current_amount"])
    free = {n: money(now[n] - assigned.get(n, 0)) for n in now}

    rows = []
    for piggy in piggies:
        attr = piggy["attributes"]
        override = by_piggy.get(attr["name"], {})
        events = api_all(f"/piggy-banks/{piggy['id']}/events")
        pace = money(sum(float(e["attributes"]["amount"]) for e in events
                         if e["attributes"]["created_at"][:10] >= since.isoformat()) / months)
        source = attr["accounts"][0]["name"] if attr["accounts"] else ""
        rows.append({
            "name": attr["name"], "kind": "piggy", "editable": True, "source": source,
            "free": free.get(source), "balance": money(attr["current_amount"]),
            "target": money(override.get("target") or attr["target_amount"]),
            "deadline": override.get("date") or (attr["target_date"] or "")[:10] or None, "pace": pace,
        })
    for goal in file_goals:
        if goal.get("piggy") or goal.get("account") not in now:
            continue
        balance = now[goal["account"]]
        rows.append({
            "name": goal["name"], "kind": "account", "editable": False, "source": goal["account"],
            "balance": balance, "target": money(goal["target"]), "deadline": goal.get("date"),
            "pace": money((balance - before.get(goal["account"], balance)) / months),
        })
    for row in rows:
        remaining = money(row["target"] - row["balance"])
        row["remaining"] = max(remaining, 0)
        left = ((dt.date.fromisoformat(row["deadline"]) - today).days / 30.44) if row["deadline"] else None
        row["months_left"] = round(left, 1) if left is not None else None
        if remaining <= 0:
            row["status"] = "reached"
            continue
        if row["pace"] > 0:
            row["eta"] = (today + dt.timedelta(days=round(remaining / row["pace"] * 30.44))).isoformat()
        if left is not None and left > 0:
            row["needed_monthly"] = money(remaining / left)
        if row["pace"] <= 0:
            row["status"] = "stalled"
        elif not row["deadline"] or row["eta"] <= row["deadline"]:
            row["status"] = "on_track"
        else:
            row["status"] = "late"
    choices = [{"name": n, "free": free[n]} for n in sorted(now) if not n.startswith((DEBT_PREFIX, INVESTMENT_PREFIX))]
    return {"goals": rows, "accounts": choices}


def find_piggy(name: str) -> dict:
    for piggy in api_all("/piggy-banks"):
        if piggy["attributes"]["name"] == name:
            return piggy
    raise ValueError(f"Aucune tirelire nommée « {name} »")


def clean_date(value) -> str | None:
    if not value:
        return None
    dt.date.fromisoformat(value)
    return value


def create_piggy(body: dict) -> None:
    name = str(body.get("name", "")).strip()
    target = float(body["target"])
    if not name or len(name) > 60 or not 0 < target < 10_000_000:
        raise ValueError("Nom ou montant invalide")
    accounts = {a["attributes"]["name"]: a["id"] for a in api_all("/accounts", {"type": "asset"})}
    account = str(body.get("account", ""))
    if account not in accounts:
        raise ValueError("Compte inconnu")
    if any(p["attributes"]["name"] == name for p in api_all("/piggy-banks")):
        raise ValueError("Une tirelire porte déjà ce nom")
    payload = {"name": name, "accounts": [{"account_id": accounts[account], "current_amount": "0"}],
               "target_amount": f"{target:.2f}", "start_date": dt.date.today().isoformat(),
               "transaction_currency_code": "EUR"}
    date = clean_date(body.get("date"))
    if date:
        payload["target_date"] = date
    api_write("POST", "/piggy-banks", payload)


def update_piggy(body: dict) -> None:
    piggy = find_piggy(str(body.get("name", "")))
    payload: dict = {}
    if body.get("target") is not None:
        target = float(body["target"])
        if not 0 < target < 10_000_000:
            raise ValueError("Montant invalide")
        payload["target_amount"] = f"{target:.2f}"
    date = clean_date(body.get("date"))
    if date:
        payload["target_date"] = date
    new_name = str(body.get("new_name") or "").strip()
    if new_name and new_name != piggy["attributes"]["name"]:
        if len(new_name) > 60:
            raise ValueError("Nom trop long")
        payload["name"] = new_name
    if not payload:
        raise ValueError("Rien à modifier")
    api_write("PUT", f"/piggy-banks/{piggy['id']}", payload)


def move_piggy(body: dict) -> None:
    """Puts money in (positive) or takes it out (negative); it stays on the account."""
    amount = float(body["amount"])
    if amount == 0 or abs(amount) > 10_000_000:
        raise ValueError("Montant invalide")
    piggy = find_piggy(str(body.get("name", "")))
    attr = piggy["attributes"]
    first = attr["accounts"][0]
    total = round(float(first["current_amount"]) + amount, 2)
    if total < 0:
        raise ValueError(f"Il n'y a que {float(first['current_amount']):.2f} € dans cette tirelire")
    accounts = [{"account_id": a["account_id"],
                 "current_amount": f"{(total if a is first else float(a['current_amount'])):.2f}"}
                for a in attr["accounts"]]
    try:
        api_write("PUT", f"/piggy-banks/{piggy['id']}",
                  {"name": attr["name"], "transaction_currency_code": "EUR", "accounts": accounts})
    except ValueError as e:
        if "cannot be added" in str(e):
            raise ValueError(f"Pas assez d'argent libre sur {first['name']} (le reste est déjà dans d'autres tirelires)") from e
        raise


def delete_piggy(body: dict) -> None:
    piggy = find_piggy(str(body.get("name", "")))
    api_write("DELETE", f"/piggy-banks/{piggy['id']}")


def taxonomy() -> dict:
    """Names of the categories and budgets, for the pickers of the transaction editor."""
    names = lambda path: sorted((r["attributes"]["name"] for r in api_all(path)), key=str.casefold)
    accounts = [a["attributes"]["name"] for a in api_all("/accounts", {"type": "asset"})
                if a["attributes"]["active"] and not a["attributes"]["name"].startswith((DEBT_PREFIX, INVESTMENT_PREFIX))]
    return {"categories": [c for c in names("/categories") if c != "Valorisation"],
            "budgets": names("/budgets"), "accounts": sorted(accounts, key=str.casefold)}


RULE_GROUP = "Catégorisation automatique"


PAST_DAYS = 365
PAST_LIMIT = 200


def past_matches(text: str, kind: str) -> list[dict]:
    """Transactions of the last year without a category whose description contains `text`
    (kind: withdrawal or deposit), on everyday accounts, newest first. At most PAST_LIMIT."""
    text = " ".join(text.split()).replace('"', "")
    if len(text) < 3 or kind not in ("withdrawal", "deposit"):
        return []
    since = dt.date.today() - dt.timedelta(days=PAST_DAYS)
    query = f'description_contains:"{text}" has_no_category:true type:{kind} date_after:{since}'
    everyday = everyday_ids()
    found = []
    for group in api("/search/transactions", {"query": query, "limit": PAST_LIMIT})["data"]:
        for t in group["attributes"]["transactions"]:
            row = everyday_row(t, group["id"], everyday)
            if row and not t["category_name"]:
                found.append(row)
    return sorted(found, key=lambda t: (t["date"], t["id"]), reverse=True)[:PAST_LIMIT]


def categorize(body: dict) -> dict:
    """Set the category (and budget) of one transaction, and optionally file the next ones the same
    way with a Firefly III rule on a piece of the description. Valuation entries are never touched."""
    group, journal = str(body.get("group", "")), int(body.get("id", 0))
    category, budget = str(body.get("category") or "").strip(), str(body.get("budget") or "").strip()
    known = taxonomy()
    if category and category not in known["categories"]:
        raise ValueError("Catégorie inconnue")
    if budget and budget not in known["budgets"]:
        raise ValueError("Budget inconnu")
    current = next((t for t in api(f"/transactions/{group}")["data"]["attributes"]["transactions"]
                    if int(t["transaction_journal_id"]) == journal), None)
    if current is None:
        raise ValueError("Transaction introuvable")
    if current["category_name"] == "Valorisation":
        raise ValueError("Les valorisations du PEA sont gérées automatiquement")
    if current["type"] != "withdrawal":
        budget = ""  # only spending has a budget
    api_write("PUT", f"/transactions/{group}", {
        "apply_rules": False, "fire_webhooks": False,
        "transactions": [{"transaction_journal_id": str(journal),
                          "category_name": category, "budget_name": budget}]})
    text, applied = str(body.get("rule") or "").strip(), 0
    if text:
        if len(text) < 3 or not category:
            raise ValueError("Pour une règle, il faut une catégorie et au moins 3 caractères")
        add_rule(text, category, budget, current["type"])
        if body.get("past"):
            for row in past_matches(text, current["type"]):
                if str(row["id"]) == str(journal):
                    continue
                api_write("PUT", f"/transactions/{row['group']}", {
                    "apply_rules": False, "fire_webhooks": False,
                    "transactions": [{"transaction_journal_id": str(row["id"]), "category_name": category,
                                      **({"budget_name": budget} if budget else {})}]})
                applied += 1
    return {"applied": applied}


def create_transaction(body: dict) -> None:
    """Record an expense or an income on an everyday account (cash, a payment the bank import will
    not bring). Firefly III's rules run on it, so it is filed like the imported ones unless a
    category is given."""
    kind = body.get("kind")
    if kind not in ("expense", "income"):
        raise ValueError("Type inconnu")
    try:
        amount = round(float(str(body.get("amount", "")).replace(",", ".").replace(" ", "")), 2)
    except ValueError:
        raise ValueError("Montant invalide") from None
    if not 0 < amount <= 1_000_000:
        raise ValueError("Montant invalide")
    description = " ".join(str(body.get("description") or "").split())
    if not 1 <= len(description) <= 120:
        raise ValueError("Il faut un libellé (120 caractères au plus)")
    try:
        date = dt.date.fromisoformat(str(body.get("date")))
    except ValueError:
        raise ValueError("Date invalide") from None
    if not dt.date(2000, 1, 1) <= date <= dt.date.today():
        raise ValueError("La date ne peut pas être dans le futur")
    known = taxonomy()
    account, category = str(body.get("account") or ""), str(body.get("category") or "").strip()
    budget = str(body.get("budget") or "").strip() if kind == "expense" else ""
    if account not in known["accounts"]:
        raise ValueError("Compte inconnu")
    if category and category not in known["categories"]:
        raise ValueError("Catégorie inconnue")
    if budget and budget not in known["budgets"]:
        raise ValueError("Budget inconnu")
    entry = {"type": "withdrawal" if kind == "expense" else "deposit", "date": date.isoformat(),
             "amount": f"{amount:.2f}", "description": description,
             "source_name": account if kind == "expense" else description,
             "destination_name": description if kind == "expense" else account}
    if category:
        entry["category_name"] = category
    if budget:
        entry["budget_name"] = budget
    api_write("POST", "/transactions", {"apply_rules": True, "fire_webhooks": False, "error_if_duplicate_hash": False,
                                        "transactions": [entry]})


def add_rule(text: str, category: str, budget: str, kind: str) -> None:
    title = f"{text} → {category}"
    groups = {g["attributes"]["title"]: g["id"] for g in api_all("/rule-groups")}
    if RULE_GROUP not in groups:
        groups[RULE_GROUP] = api_write("POST", "/rule-groups", {"title": RULE_GROUP, "active": True})["data"]["id"]
    action = lambda kind, value: {"type": kind, "value": value, "active": True, "stop_processing": False}
    rule = {"title": title, "rule_group_id": groups[RULE_GROUP], "trigger": "store-journal",
            "active": True, "strict": True,
            "triggers": [{"type": "description_contains", "value": text, "active": True,
                          "prohibited": False, "stop_processing": False},
                         {"type": "transaction_type", "value": kind, "active": True,
                          "prohibited": False, "stop_processing": False}],
            "actions": [action("set_category", category)] + ([action("set_budget", budget)] if budget else [])}
    existing = [r["id"] for r in api_all("/rules") if r["attributes"]["title"] == title]
    api_write("PUT" if existing else "POST", f"/rules/{existing[0]}" if existing else "/rules", rule)


def read_review_file(month: str, kind: str):
    """A file of the monthly review, parsed when JSON; None when missing or unreadable."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("Mois invalide")
    try:
        with open(os.path.join(BILANS_DIR, f"{month}.{kind}"), encoding="utf-8") as f:
            return json.load(f) if kind.endswith("json") else f.read()
    except (OSError, ValueError):
        return None


def reviews_list() -> list[dict]:
    """The months that have a review, newest first, with their one-line summary."""
    try:
        names = os.listdir(BILANS_DIR)
    except OSError:
        return []
    out = []
    for month in sorted({n[:7] for n in names if re.fullmatch(r"\d{4}-\d{2}\.comments\.json", n)}, reverse=True):
        comments, facts = read_review_file(month, "comments.json"), read_review_file(month, "facts.json")
        if isinstance(comments, dict) and isinstance(facts, dict):
            out.append({"month": month, "headline": str(comments.get("headline", "")),
                        "saved": facts.get("saved")})
    return out


def review_data(month: str) -> dict:
    """One review for the page: the figures worth showing (not every transaction) and the comments."""
    facts, comments = read_review_file(month, "facts.json"), read_review_file(month, "comments.json")
    if not isinstance(facts, dict) or not isinstance(comments, dict):
        raise KeyError(month)
    keep = ("month", "start", "end", "earned", "spent", "saved", "net_worth", "net_worth_change", "pea_market",
            "net_worth_by_month", "groups", "categories", "uncategorised", "budgets", "upcoming_bills", "goals")
    shown = {k: facts[k] for k in keep if k in facts}
    shown["largest"] = [t for t in facts.get("largest", []) if t.get("type") == "withdrawal"][:6]
    return {"facts": shown, "comments": comments,
            "has_html": os.path.isfile(os.path.join(BILANS_DIR, f"{month}.html"))}


UNUSUAL_RECENT_DAYS = 14
UNUSUAL_MIN_AMOUNT = 50
UNUSUAL_FACTOR = 3
UNUSUAL_MIN_SAMPLES = 4
PRICE_CHANGE_DAYS = 45


def alerts_from(history: dict[str, list[dict]], today: dt.date) -> dict:
    """What deserves a look, from the transactions of the last months ({"YYYY-MM": [...]}):
    recent expenses far above the usual for their category, subscriptions whose last payment
    differs from the one before, and the transactions still without a category this month."""
    current = today.strftime("%Y-%m")
    everything = sorted((t for txs in history.values() for t in txs), key=lambda t: (t["date"], t["id"]))

    since = (today - dt.timedelta(days=UNUSUAL_RECENT_DAYS)).isoformat()
    amounts: dict[str, list[float]] = {}  # what each category usually costs, before the recent days
    for t in everything:
        if t["type"] == "withdrawal" and t["category"] and t["date"] < since:
            amounts.setdefault(t["category"], []).append(t["amount"])
    unusual = []
    for t in everything:
        usual = sorted(amounts.get(t["category"] or "", []))
        if (t["type"] != "withdrawal" or t["date"] < since or len(usual) < UNUSUAL_MIN_SAMPLES
                or t["amount"] < UNUSUAL_MIN_AMOUNT):
            continue
        median = usual[len(usual) // 2]
        if t["amount"] >= UNUSUAL_FACTOR * median:
            unusual.append({"description": t["description"], "date": t["date"], "amount": t["amount"],
                            "category": t["category"], "usual": money(median)})
    unusual = sorted(unusual, key=lambda u: -u["amount"] / max(u["usual"], 1))[:3]

    by_bill: dict[str, list[dict]] = {}
    for t in everything:
        if t["bill"] and t["type"] == "withdrawal":
            by_bill.setdefault(t["bill"], []).append(t)
    changes = []
    for name, payments in by_bill.items():
        if len(payments) >= 2:
            before, now = payments[-2]["amount"], payments[-1]["amount"]
            if (payments[-1]["date"] >= (today - dt.timedelta(days=PRICE_CHANGE_DAYS)).isoformat()
                    and abs(now - before) >= 0.5 and abs(now - before) >= 0.03 * before):
                changes.append({"name": name, "before": before, "now": now, "date": payments[-1]["date"]})

    months = sorted(m for m in history if m <= current)[-2:]
    missing = {"count": 0, "amount": 0.0, "month": None}
    for m in reversed(months):
        loose = [t for t in history[m] if t["type"] != "transfer" and not t["category"]]
        if loose:
            missing = {"count": len(loose), "amount": money(sum(t["amount"] for t in loose)), "month": m}
            break
    return {"unusual": unusual, "price_changes": changes, "uncategorised": missing}


def alerts_data() -> dict:
    today = dt.date.today()
    months = [f"{y}-{m:02d}" for y, m in months_back(5)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        history = dict(zip(months, pool.map(lambda m: cached(f"/api/transactions{m}", lambda: month_transactions(m)), months)))
    return alerts_from(history, today)


class Cache:
    """TTL cache with one lock per key: concurrent loads of the same page share one set of API
    calls, but a slow key (Yahoo quotes, a 24-month build) never blocks the others. When Firefly III
    fails, the last value is served instead of an error."""

    def __init__(self, ttl: float):
        self.ttl = ttl
        self._items: dict[str, tuple[float, object]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, key: str, make):
        with self._guard:
            hit = self._items.get(key)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            with self._guard:
                hit = self._items.get(key)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]  # filled while this call waited for the lock
            try:
                value = make()
            except Exception:
                if hit:
                    return hit[1]  # stale rather than an error page
                raise
            with self._guard:
                self._items[key] = (time.time(), value)
            return value

    def drop(self, key: str) -> None:
        with self._guard:
            self._items.pop(key, None)

    def expire_all(self) -> None:
        """Marks everything stale but keeps it as a fallback if the next refresh fails."""
        with self._guard:
            self._items = {k: (0.0, v) for k, (_, v) in self._items.items()}


cache = Cache(CACHE_SECONDS)
_lock = threading.Lock()  # serialises the piggy bank writes


def cached(key: str, make):
    return cache.get(key, make)


def tree(month: str) -> dict:
    return cache.get(f"flow{month}", lambda: expense_tree(month))


def data(months: int) -> dict:
    return cache.get(f"data{months}", lambda: build(months))


def warm_up() -> None:
    """Fills the main caches at start, so the first page load does not wait for ~100 API calls."""
    for attempt in range(5):
        try:
            data(24)
            return
        except Exception:
            time.sleep(10 * (attempt + 1))  # Firefly III may still be starting


# Logo, icons and web manifest (the name and logo of the app: Cairn).
ASSETS = {
    "/logo.svg": ("static/logo.svg", "image/svg+xml"),
    "/favicon.svg": ("static/favicon.svg", "image/svg+xml"),
    "/logo-512.png": ("static/logo-512.png", "image/png"),
    "/icon-192.png": ("static/icon-192.png", "image/png"),
    "/icon-512.png": ("static/icon-512.png", "image/png"),
    "/apple-touch-icon.png": ("static/apple-touch-icon.png", "image/png"),
    "/manifest.webmanifest": ("static/manifest.webmanifest", "application/manifest+json"),
}


COMPRESSIBLE = ("text/", "application/json", "application/javascript", "image/svg+xml",
                "application/manifest+json")
_static: dict[str, tuple[float, bytes, str]] = {}


def host_name(value: str) -> str:
    """Host header without its port, IPv6 literals included ("[::1]:8787" -> "[::1]")."""
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value[: value.find("]") + 1] if "]" in value else value
    return value.rsplit(":", 1)[0] if ":" in value else value


def allowed_hosts() -> set[str]:
    return {"localhost", "127.0.0.1", "[::1]"} | {h.lower() for h in ALLOWED}


class Handler(BaseHTTPRequestHandler):
    server_version = "dashboard"

    def reply(self, status: int, body: bytes, content_type: str, cache: str = "no-store",
              etag: str | None = None) -> None:
        if etag and self.headers.get("If-None-Match") == etag:
            status, body = 304, b""
        elif (len(body) > 1024 and content_type.startswith(COMPRESSIBLE)
              and "gzip" in (self.headers.get("Accept-Encoding") or "")):
            body = gzip.compress(body, 6)
            self.send_response(status)
            self.send_header("Content-Encoding", "gzip")
            return self._finish(body, content_type, cache, etag)
        self.send_response(status)
        self._finish(body, content_type, cache, etag)

    def _finish(self, body: bytes, content_type: str, cache: str, etag: str | None) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Vary", "Accept-Encoding")
        if etag:
            self.send_header("ETag", etag)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:
        if host_name(self.headers.get("Host")) not in allowed_hosts():
            return self.reply(403, b"forbidden", "text/plain")
        url = urllib.parse.urlparse(self.path)
        try:
            if url.path == "/healthz":
                return self.reply(200, b"ok", "text/plain")
            if url.path == "/":
                return self.serve("index.html", "text/html; charset=utf-8")
            if url.path in ASSETS:
                name, content_type = ASSETS[url.path]
                return self.serve(name, content_type, "public, max-age=86400")
            if url.path == "/chart.js":
                return self.serve("static/chart.umd.js", "application/javascript", "public, max-age=86400")
            if url.path == "/api/transactions" and "start" in urllib.parse.parse_qs(url.query):
                query = urllib.parse.parse_qs(url.query)
                start, end = (dt.date.fromisoformat(query.get(k, [""])[0]).isoformat() for k in ("start", "end"))
                return self.reply(200, json.dumps(cached(f"range{start}{end}", lambda: range_transactions(start, end))).encode(),
                                  "application/json")
            if url.path in ("/api/transactions", "/api/budgets"):
                month = urllib.parse.parse_qs(url.query).get("month", [""])[0]
                dt.datetime.strptime(month, "%Y-%m")
                make = month_transactions if url.path == "/api/transactions" else month_budgets
                return self.reply(200, json.dumps(cached(f"{url.path}{month}", lambda: make(month))).encode(),
                                  "application/json")
            if url.path == "/api/rule-preview":
                query = urllib.parse.parse_qs(url.query)
                rows = past_matches(query.get("text", [""])[0], query.get("type", [""])[0])
                return self.reply(200, json.dumps({"count": len(rows), "amount": money(sum(r["amount"] for r in rows)),
                                                   "capped": len(rows) >= PAST_LIMIT}).encode(), "application/json")
            if url.path == "/api/bilans":
                return self.reply(200, json.dumps(cached("bilans", reviews_list)).encode(), "application/json")
            if url.path in ("/api/bilan", "/api/bilan.html"):
                month = urllib.parse.parse_qs(url.query).get("month", [""])[0]
                try:
                    if url.path == "/api/bilan":
                        return self.reply(200, json.dumps(cached(f"bilan{month}", lambda: review_data(month))).encode(), "application/json")
                    page = read_review_file(month, "html")
                    if page is None:
                        raise KeyError(month)
                    return self.reply(200, page.encode(), "text/html; charset=utf-8")
                except KeyError:
                    return self.reply(404, json.dumps({"error": "Pas de bilan pour ce mois"}).encode(), "application/json")
            if url.path == "/api/search":
                text = urllib.parse.parse_qs(url.query).get("q", [""])[0]
                return self.reply(200, json.dumps(cached(f"search{text.casefold()}", lambda: search_transactions(text))).encode(),
                                  "application/json")
            if url.path == "/api/alerts":
                return self.reply(200, json.dumps(cached("alerts", alerts_data)).encode(), "application/json")
            if url.path == "/api/taxonomy":
                return self.reply(200, json.dumps(cached("taxonomy", taxonomy)).encode(), "application/json")
            if url.path == "/api/bills":
                return self.reply(200, json.dumps(cached("bills", bills_data)).encode(), "application/json")
            if url.path == "/api/goals":
                return self.reply(200, json.dumps(cached("goals", goals_data)).encode(), "application/json")
            if url.path == "/api/pea":
                return self.reply(200, json.dumps(cached("pea", pea_data)).encode(), "application/json")
            if url.path == "/sw.js":  # service worker: must be served from the root, always revalidated
                return self.serve("static/sw.js", "application/javascript")
            if re.fullmatch(r"/js/[a-z0-9-]+\.js", url.path):  # the page's ES modules
                if os.path.isfile(os.path.join(HERE, "static", url.path[1:])):
                    return self.serve("static" + url.path, "application/javascript")
            if url.path == "/app.css":
                return self.serve("static/app.css", "text/css; charset=utf-8")
            if url.path == "/api/flow":
                month = urllib.parse.parse_qs(url.query).get("month", [""])[0]
                dt.datetime.strptime(month, "%Y-%m")
                return self.reply(200, json.dumps(tree(month)).encode(), "application/json")
            if url.path == "/api/data":
                query = urllib.parse.parse_qs(url.query)
                months = max(1, min(MAX_MONTHS, int(query.get("months", ["12"])[0])))
                if query.get("refresh"):
                    cache.expire_all()
                return self.reply(200, json.dumps(data(months)).encode(), "application/json")
        except (urllib.error.URLError, ValueError, KeyError) as e:
            return self.reply(502, json.dumps({"error": str(e)}).encode(), "application/json")
        except Exception as e:  # a bug must give an error answer, not a dropped connection
            print(f"{self.path}: {type(e).__name__}: {e}", flush=True)
            return self.reply(500, json.dumps({"error": "Erreur interne"}).encode(), "application/json")
        self.reply(404, b"not found", "text/plain")

    do_HEAD = do_GET


    def do_POST(self) -> None:
        """Piggy bank changes and transaction categorisation (Firefly III is the source of truth).
        A JSON body, a custom header and a same-site Origin are required, so a page on another
        site cannot write."""
        host = host_name(self.headers.get("Host"))
        origin = self.headers.get("Origin") or ""
        origin_host = host_name(origin.split("//", 1)[-1]) if origin else host
        if host not in allowed_hosts() or origin_host not in allowed_hosts():
            return self.reply(403, b"forbidden", "text/plain")
        if (self.headers.get("X-Requested-With") != "dashboard"
                or "application/json" not in (self.headers.get("Content-Type") or "")):
            return self.reply(400, b"bad request", "text/plain")
        piggy = {"create": create_piggy, "update": update_piggy, "move": move_piggy, "delete": delete_piggy}
        routes = {"/api/piggy": (piggy, ("goals",)), "/api/transaction": ({"categorize": categorize, "create": create_transaction}, None)}
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 4000:
                raise ValueError("Requête invalide")
            body = json.loads(self.rfile.read(length))
            route = routes.get(urllib.parse.urlparse(self.path).path)
            if route is None:
                return self.reply(404, b"not found", "text/plain")
            actions, stale = route
            action = actions.get(body.get("action"))
            if action is None:
                raise ValueError("Action inconnue")
            with _lock:
                result = action(body)
                if stale is None:  # a transaction change shows in every total
                    cache.expire_all()
                else:
                    for key in stale:
                        cache.drop(key)
        except (ValueError, KeyError, TypeError) as e:
            return self.reply(400, json.dumps({"error": str(e)}).encode(), "application/json")
        except urllib.error.URLError as e:
            return self.reply(502, json.dumps({"error": str(e)}).encode(), "application/json")
        except Exception as e:
            print(f"POST {self.path}: {type(e).__name__}: {e}", flush=True)
            return self.reply(500, json.dumps({"error": "Erreur interne"}).encode(), "application/json")
        self.reply(200, json.dumps(result if isinstance(result, dict) else {}).encode(), "application/json")

    def serve(self, name: str, content_type: str, cache: str | None = None) -> None:
        """Static file with an ETag: app code revalidates (304 when unchanged), icons and Chart.js
        are kept a day."""
        path = os.path.join(HERE, name)
        mtime = os.path.getmtime(path)
        hit = _static.get(name)
        if not hit or hit[0] != mtime:
            with open(path, "rb") as f:
                body = f.read()
            hit = _static[name] = (mtime, body, f'"{hashlib.sha1(body).hexdigest()[:16]}"')
        self.reply(200, hit[1], content_type, cache or "no-cache", hit[2])

    def log_message(self, fmt: str, *args) -> None:
        pass


if __name__ == "__main__":
    threading.Thread(target=warm_up, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
