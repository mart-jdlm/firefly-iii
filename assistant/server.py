"""MCP server giving Claude Code read-only access to Firefly III (see the README, "Assistant").

Runs over stdio in the `assistant` container, launched on demand by Claude Code (.mcp.json).
Needs FIREFLY_URL and FIREFLY_TOKEN; reads the PEA positions from PEA_POSITIONS.
"""

import calendar
import datetime as dt
import json
import os
import urllib.parse
import urllib.request

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

FIREFLY_URL = os.environ.get("FIREFLY_URL", "http://app:8080").rstrip("/")
FIREFLY_TOKEN = os.environ["FIREFLY_TOKEN"]
PEA_POSITIONS = os.environ.get("PEA_POSITIONS", "/patrimoine/pea.txt")

# Asset accounts that are not money the user spends from: family debts (negative balance = what
# the user owes) and the PEA (balance kept at market value by cron/valuation.sh).
DEBT_PREFIX = "Dette"
INVESTMENT_PREFIX = "PEA"

INSTRUCTIONS = f"""\
Personal finances of one person in France, from their Firefly III instance. Amounts are in EUR.
- Accounts named "{DEBT_PREFIX} <person>" are informal family debts kept as asset accounts: a negative
  balance is what the user owes that person. They are already counted (negatively) in net worth.
- The "{INVESTMENT_PREFIX} ..." account is a stock savings plan whose balance is set to its market value every
  day; category "Valorisation" holds those unrealised gains and losses, which are not income or spending.
- Spending and income tools (summary, by_category, monthly_history) only look at everyday accounts,
  so debt adjustments and PEA valuations are left out. search_transactions returns everything.
- Dates are YYYY-MM-DD. Without dates, tools cover the current month.
These tools are read-only."""

mcp = MCPServer("firefly", instructions=INSTRUCTIONS)
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def api(path: str, params: dict | list | None = None):
    url = f"{FIREFLY_URL}/api/v1{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {FIREFLY_TOKEN}", "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def api_all(path: str, params: dict | None = None) -> list[dict]:
    """Every item of a paginated list endpoint."""
    items, page = [], 1
    while True:
        body = api(path, {**(params or {}), "limit": 200, "page": page})
        items += body["data"]
        if page >= body["meta"]["pagination"]["total_pages"]:
            return items
        page += 1


def period(start: str | None, end: str | None) -> tuple[str, str]:
    today = dt.date.today()
    first = today.replace(day=1)
    last = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    return start or first.isoformat(), end or last.isoformat()


def money(value) -> float:
    return round(float(value or 0), 2)


def assets() -> list[dict]:
    return api_all("/accounts", {"type": "asset"})


def everyday_account_ids() -> list[str]:
    return [
        a["id"]
        for a in assets()
        if not a["attributes"]["name"].startswith((DEBT_PREFIX, INVESTMENT_PREFIX))
    ]


def insight(path: str, start: str, end: str) -> list[dict]:
    params = [("start", start), ("end", end)] + [("accounts[]", i) for i in everyday_account_ids()]
    return api(f"/insight/{path}", params)


def insight_total(kind: str, start: str, end: str) -> float:
    return money(sum(float(r["difference"]) for r in insight(f"{kind}/total", start, end)))


@mcp.tool(annotations=READ_ONLY)
def accounts() -> list[dict]:
    """Asset and liability accounts with their current balance and role."""
    result = []
    for kind in ("asset", "liabilities"):
        for a in api_all("/accounts", {"type": kind}):
            attr = a["attributes"]
            result.append({
                "name": attr["name"],
                "type": attr["type"],
                "role": attr["account_role"],
                "balance": money(attr["current_balance"]),
                "active": attr["active"],
                "in_net_worth": attr["include_net_worth"],
                "last_activity": attr["last_activity"],
            })
    return result


@mcp.tool(annotations=READ_ONLY)
def net_worth() -> dict:
    """Current net worth, split into everyday accounts, savings, investments and debts."""
    groups: dict[str, dict[str, float]] = {"courant": {}, "epargne": {}, "investissements": {}, "dettes": {}}
    for a in assets() + api_all("/accounts", {"type": "liabilities"}):
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
        groups[group][name] = balance
    totals = {g: money(sum(v.values())) for g, v in groups.items()}
    return {"accounts": groups, "totals": totals, "net_worth": money(sum(totals.values()))}


@mcp.tool(annotations=READ_ONLY)
def summary(start: str | None = None, end: str | None = None) -> dict:
    """Total income, spending and savings over a period (everyday accounts only)."""
    start, end = period(start, end)
    earned = insight_total("income", start, end)
    spent = insight_total("expense", start, end)
    return {"start": start, "end": end, "earned": earned, "spent": spent, "saved": money(earned + spent)}


@mcp.tool(annotations=READ_ONLY)
def by_category(start: str | None = None, end: str | None = None, kind: str = "expense") -> dict:
    """Spending (kind="expense") or income (kind="income") per category over a period, largest first."""
    if kind not in ("expense", "income"):
        raise ValueError('kind must be "expense" or "income"')
    start, end = period(start, end)
    rows = {r["name"]: money(r["difference"]) for r in insight(f"{kind}/category", start, end)}
    uncategorised = sum(float(r["difference"]) for r in insight(f"{kind}/no-category", start, end))
    if uncategorised:
        rows["(sans catégorie)"] = money(uncategorised)
    ordered = dict(sorted(rows.items(), key=lambda kv: abs(kv[1]), reverse=True))
    return {"start": start, "end": end, "categories": ordered, "total": money(sum(rows.values()))}


@mcp.tool(annotations=READ_ONLY)
def monthly_history(months: int = 12) -> list[dict]:
    """Income, spending and savings for each of the last `months` months, the current one included."""
    today = dt.date.today()
    result = []
    for back in range(months - 1, -1, -1):
        year, month = divmod(today.year * 12 + today.month - 1 - back, 12)
        month += 1
        start = dt.date(year, month, 1).isoformat()
        end = dt.date(year, month, calendar.monthrange(year, month)[1]).isoformat()
        earned = insight_total("income", start, end)
        spent = insight_total("expense", start, end)
        result.append({"month": start[:7], "earned": earned, "spent": spent, "saved": money(earned + spent)})
    return result


@mcp.tool(annotations=READ_ONLY)
def search_transactions(query: str, limit: int = 50) -> list[dict]:
    """Search transactions with Firefly III's query syntax, newest first.

    Free words match the description. Useful operators: date_after:2026-01-01, date_before:...,
    category_is:"Restaurants & Fast Food", budget_is:..., tag_is:..., source_account_is:...,
    destination_account_is:..., amount_more:50, amount_less:..., type:withdrawal|deposit|transfer.
    """
    body = api("/search/transactions", {"query": query, "limit": min(limit, 200)})
    result = []
    for group in body["data"]:
        for t in group["attributes"]["transactions"]:
            result.append({
                "id": t["transaction_journal_id"],
                "date": t["date"][:10],
                "type": t["type"],
                "description": t["description"],
                "amount": money(t["amount"]),
                "source": t["source_name"],
                "destination": t["destination_name"],
                "category": t["category_name"],
                "budget": t["budget_name"],
                "tags": t["tags"],
            })
    return result[:limit]


@mcp.tool(annotations=READ_ONLY)
def budgets(start: str | None = None, end: str | None = None) -> list[dict]:
    """Each active budget with its amount and what was spent over a period."""
    start, end = period(start, end)
    result = []
    for b in api_all("/budgets"):
        attr = b["attributes"]
        if not attr["active"]:
            continue
        limits = api(f"/budgets/{b['id']}/limits", {"start": start, "end": end})["data"]
        amount = sum(float(l["attributes"]["amount"]) for l in limits)
        spent = sum(float(s["sum"]) for l in limits for s in l["attributes"]["spent"])
        result.append({
            "name": attr["name"],
            "amount": money(amount),
            "spent": money(spent),
            "left": money(amount + spent),
            "auto_budget": attr["auto_budget_type"] and f'{attr["auto_budget_amount"]} {attr["auto_budget_period"]}',
        })
    return result


@mcp.tool(annotations=READ_ONLY)
def upcoming_bills(days: int = 60) -> list[dict]:
    """Expected bill payments (subscriptions, insurance...) in the next `days` days, by date."""
    start = dt.date.today()
    end = start + dt.timedelta(days=days)
    result = []
    for b in api_all("/bills", {"start": start.isoformat(), "end": end.isoformat()}):
        attr = b["attributes"]
        if not attr["active"]:
            continue
        for date in attr["pay_dates"]:
            if not start.isoformat() <= date[:10] <= end.isoformat():
                continue
            result.append({
                "date": date[:10],
                "name": attr["name"],
                "amount": money(attr["amount_avg"]),
                "frequency": attr["repeat_freq"],
            })
    return sorted(result, key=lambda r: r["date"])


def yahoo_price(symbol: str) -> float:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=1d&interval=1d"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        meta = json.load(response)["chart"]["result"][0]["meta"]
    if meta["currency"] != "EUR":
        raise ValueError(f"{symbol} is quoted in {meta['currency']}, not EUR")
    return meta["regularMarketPrice"]


@mcp.tool(annotations=READ_ONLY)
def pea_positions() -> dict:
    """Holdings of the PEA at today's prices (from patrimoine/pea.txt), with each line's weight."""
    lines = []
    with open(PEA_POSITIONS, encoding="utf-8") as f:
        for raw in f:
            parts = raw.split(None, 2)
            if not parts or parts[0].startswith("#"):
                continue
            symbol, quantity = parts[0], float(parts[1])
            label = parts[2].strip() if len(parts) > 2 else ""
            if symbol == "especes":
                lines.append({"symbol": "especes", "label": "Liquidités", "value": money(quantity)})
            else:
                price = yahoo_price(symbol)
                lines.append({"symbol": symbol, "label": label, "quantity": quantity,
                              "price": price, "value": money(quantity * price)})
    total = sum(line["value"] for line in lines)
    for line in lines:
        line["weight"] = round(line["value"] / total, 4) if total else 0
    return {"positions": lines, "total": money(total)}


if __name__ == "__main__":
    mcp.run()
