"""Dashboard for Firefly III: income, spending, saving and net worth (see the README, "Dashboard").

Read-only web page in the spirit of Finary. It only issues GET requests to the Firefly III API,
needs FIREFLY_URL and FIREFLY_TOKEN, and has no dependency beyond the standard library.
Listens on port 8787; `tailscale serve` publishes it on the tailnet. DASHBOARD_ALLOWED_HOSTS
(comma separated, default localhost) lists the Host names accepted, against DNS rebinding.
"""

import calendar
import concurrent.futures
import datetime as dt
import json
import os
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
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
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


def month_transactions(month: str) -> list[dict]:
    """Every transaction of a month touching an everyday account, newest first."""
    year, mon = map(int, month.split("-"))
    start, end = month_bounds(year, mon)
    everyday = everyday_ids()
    query = (f"date_after:{dt.date.fromisoformat(start) - dt.timedelta(days=1)} "
             f"date_before:{dt.date.fromisoformat(end) + dt.timedelta(days=1)}")
    found, page = [], 1
    while True:
        body = api("/search/transactions", {"query": query, "limit": 200, "page": page})
        for group in body["data"]:
            for t in group["attributes"]["transactions"]:
                day = t["date"][:10]
                if not start <= day <= end or t["category_name"] == "Valorisation":
                    continue
                kind = t["type"]
                mine = (t["source_id"] in everyday if kind == "withdrawal"
                        else t["destination_id"] in everyday if kind == "deposit"
                        else t["source_id"] in everyday or t["destination_id"] in everyday)
                if not mine:
                    continue
                found.append({
                    "id": t["transaction_journal_id"], "date": day, "type": kind,
                    "description": t["description"], "amount": money(t["amount"]),
                    "category": t["category_name"], "budget": t["budget_name"],
                    "source": t["source_name"], "destination": t["destination_name"],
                    "notes": t["notes"],
                })
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


def pea_data() -> dict:
    accounts = [a for a in api_all("/accounts", {"type": "asset"})
                if a["attributes"]["name"].startswith(INVESTMENT_PREFIX)]
    balance = money(sum(float(a["attributes"]["current_balance"]) for a in accounts))
    monthly: dict[str, float] = {}
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
                month = t["date"][:7]
                monthly[month] = round(monthly.get(month, 0) + amount, 2)
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
            "contributions": monthly, "positions": positions, "cash": money(cash)}


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


_store: dict[str, tuple[float, object]] = {}


def cached(key: str, make):
    with _lock:
        hit = _store.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        value = make()
        _store[key] = (time.time(), value)
        return value


_trees: dict[str, tuple[float, dict]] = {}


def tree(month: str) -> dict:
    with _lock:
        hit = _trees.get(month)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        value = expense_tree(month)
        _trees[month] = (time.time(), value)
        return value


_cache: dict[int, tuple[float, dict]] = {}
_lock = threading.Lock()


def data(months: int) -> dict:
    with _lock:
        hit = _cache.get(months)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        # Held through the build on purpose: concurrent page loads share one set of API calls.
        value = build(months)
        _cache[months] = (time.time(), value)
        return value


class Handler(BaseHTTPRequestHandler):
    server_version = "dashboard"

    def reply(self, status: int, body: bytes, content_type: str, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        if host not in {"localhost", "127.0.0.1", "[::1]"} | {h.lower() for h in ALLOWED}:
            return self.reply(403, b"forbidden", "text/plain")
        url = urllib.parse.urlparse(self.path)
        try:
            if url.path == "/":
                return self.serve("index.html", "text/html; charset=utf-8")
            if url.path == "/chart.js":
                return self.serve("static/chart.umd.js", "application/javascript", "public, max-age=86400")
            if url.path in ("/api/transactions", "/api/budgets"):
                month = urllib.parse.parse_qs(url.query).get("month", [""])[0]
                dt.datetime.strptime(month, "%Y-%m")
                make = month_transactions if url.path == "/api/transactions" else month_budgets
                return self.reply(200, json.dumps(cached(f"{url.path}{month}", lambda: make(month))).encode(),
                                  "application/json")
            if url.path == "/api/bills":
                return self.reply(200, json.dumps(cached("bills", bills_data)).encode(), "application/json")
            if url.path == "/api/goals":
                return self.reply(200, json.dumps(cached("goals", goals_data)).encode(), "application/json")
            if url.path == "/api/pea":
                return self.reply(200, json.dumps(cached("pea", pea_data)).encode(), "application/json")
            if url.path == "/app.js":
                return self.serve("static/app.js", "application/javascript")
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
                    _cache.clear()
                    _store.clear()
                    _trees.clear()
                return self.reply(200, json.dumps(data(months)).encode(), "application/json")
        except (urllib.error.URLError, ValueError, KeyError) as e:
            return self.reply(502, json.dumps({"error": str(e)}).encode(), "application/json")
        self.reply(404, b"not found", "text/plain")


    def do_POST(self) -> None:
        """Piggy bank changes only (Firefly III is the source of truth). A JSON body, a custom header
        and a same-site Origin are required, so a page on another site cannot write."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        allowed = {"localhost", "127.0.0.1", "[::1]"} | {h.lower() for h in ALLOWED}
        origin = self.headers.get("Origin") or ""
        origin_host = origin.split("//", 1)[-1].rsplit(":", 1)[0].lower() if origin else host
        if host not in allowed or origin_host not in allowed:
            return self.reply(403, b"forbidden", "text/plain")
        if (self.headers.get("X-Requested-With") != "dashboard"
                or "application/json" not in (self.headers.get("Content-Type") or "")):
            return self.reply(400, b"bad request", "text/plain")
        actions = {"create": create_piggy, "update": update_piggy, "move": move_piggy, "delete": delete_piggy}
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 4000:
                raise ValueError("Requête invalide")
            body = json.loads(self.rfile.read(length))
            if urllib.parse.urlparse(self.path).path != "/api/piggy":
                return self.reply(404, b"not found", "text/plain")
            action = actions.get(body.get("action"))
            if action is None:
                raise ValueError("Action inconnue")
            with _lock:
                action(body)
                _store.pop("goals", None)
        except (ValueError, KeyError, TypeError) as e:
            return self.reply(400, json.dumps({"error": str(e)}).encode(), "application/json")
        except urllib.error.URLError as e:
            return self.reply(502, json.dumps({"error": str(e)}).encode(), "application/json")
        self.reply(200, b"{}", "application/json")

    def serve(self, name: str, content_type: str, cache: str = "no-store") -> None:
        with open(os.path.join(HERE, name), "rb") as f:
            self.reply(200, f.read(), content_type, cache)

    def log_message(self, fmt: str, *args) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
