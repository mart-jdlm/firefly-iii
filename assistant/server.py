"""MCP server giving Claude Code access to Firefly III (see the README, "Assistant").

Runs over stdio in the `assistant` container, launched on demand by Claude Code (.mcp.json).
Needs FIREFLY_URL and FIREFLY_TOKEN; reads the PEA positions from PEA_POSITIONS.
"""

import calendar
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
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
- update_transaction, create_transaction and set_budget change the user's data. Before calling one,
  say exactly what will change (transaction, field, old and new value) and wait for the user's go-ahead.
  Never use them on transactions in category "Valorisation": cron/valuation.sh manages those."""

mcp = MCPServer("firefly", instructions=INSTRUCTIONS)
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


def api(path: str, params: dict | list | None = None, method: str = "GET", body: dict | None = None):
    url = f"{FIREFLY_URL}/api/v1{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {FIREFLY_TOKEN}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        # Firefly III explains validation errors in the body; pass them on.
        raise ToolError(f"Firefly III answered {e.code}: {e.read().decode(errors='replace')[:1000]}") from e


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
        raise ToolError('kind must be "expense" or "income"')
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
    return [t for group in body["data"] for t in journals(group)][:limit]


def journals(group: dict) -> list[dict]:
    """The transactions (splits) of a transaction group, in the shape the tools return."""
    return [
        {
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
            "notes": t["notes"],
        }
        for t in group["attributes"]["transactions"]
    ]


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
        raise ToolError(f"{symbol} is quoted in {meta['currency']}, not EUR")
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


@mcp.tool(annotations=WRITE)
def update_transaction(
    id: str,
    category: str | None = None,
    budget: str | None = None,
    tags: list[str] | None = None,
    description: str | None = None,
    notes: str | None = None,
) -> list[dict]:
    """Change fields of one transaction (id from search_transactions). Only the fields given change.

    category and budget take an existing name ("" removes it); budgets only apply to withdrawals.
    tags replaces the whole list.
    Returns the transaction as it is now.
    """
    group = api(f"/transaction-journals/{id}")["data"]
    changes = {"transaction_journal_id": id}
    for field, value in (("category_name", category), ("budget_name", budget), ("tags", tags),
                         ("description", description), ("notes", notes)):
        if value is not None:
            changes[field] = value
    if len(changes) == 1:
        raise ToolError("Nothing to change")
    if budget:
        changes["budget_id"] = budget_id(budget)
        del changes["budget_name"]
    elif budget == "":
        changes["budget_id"] = 0
        del changes["budget_name"]
    updated = api(f"/transactions/{group['id']}", method="PUT",
                  body={"apply_rules": False, "transactions": [changes]})
    return [t for t in journals(updated["data"]) if t["id"] == id]


@mcp.tool(annotations=WRITE)
def create_transaction(
    type: str,
    amount: float,
    description: str,
    source: str,
    destination: str,
    date: str | None = None,
    category: str | None = None,
    budget: str | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> list[dict]:
    """Record a transaction. type is "withdrawal" (spending), "deposit" (income) or "transfer".

    source and destination are account names: for a withdrawal, an asset account to the payee
    (expense account, created if new); for a deposit, the payer (revenue account) to an asset
    account; for a transfer, two asset accounts. amount is positive. date defaults to today.
    budget (an existing one) only applies to withdrawals.
    Firefly III rules are applied. Returns the transaction as recorded.
    """
    if type not in ("withdrawal", "deposit", "transfer"):
        raise ToolError('type must be "withdrawal", "deposit" or "transfer"')
    if amount <= 0:
        raise ToolError("amount must be positive")
    split = {
        "type": type,
        "amount": f"{amount:.2f}",
        "description": description,
        "date": date or dt.date.today().isoformat(),
        "source_name": source,
        "destination_name": destination,
    }
    for field, value in (("category_name", category), ("tags", tags), ("notes", notes)):
        if value:
            split[field] = value
    if budget:
        split["budget_id"] = budget_id(budget)
    created = api("/transactions", method="POST", body={
        "error_if_duplicate_hash": True,
        "apply_rules": True,
        "transactions": [split],
    })
    return journals(created["data"])


def budget_id(name: str) -> str:
    for b in api_all("/budgets"):
        if b["attributes"]["name"] == name:
            return b["id"]
    raise ToolError(f"No budget named {name!r}")


@mcp.tool(annotations=WRITE)
def set_budget(name: str, amount: float, period: str = "monthly", rollover: bool = False) -> dict:
    """Create a budget, or change an existing one's automatic amount.

    Each period (daily, weekly, monthly, quarterly, half_year or yearly) the budget gets `amount`.
    With rollover, what is left (or overspent) carries over to the next period; otherwise it resets.
    A change applies from the next period; the current one keeps its amount.
    """
    if period not in ("daily", "weekly", "monthly", "quarterly", "half_year", "yearly"):
        raise ToolError("period must be daily, weekly, monthly, quarterly, half_year or yearly")
    body = {
        "name": name,
        "active": True,
        "auto_budget_type": "rollover" if rollover else "reset",
        "auto_budget_amount": f"{amount:.2f}",
        "auto_budget_period": period,
        "auto_budget_currency_code": "EUR",
    }
    existing = [b["id"] for b in api_all("/budgets") if b["attributes"]["name"] == name]
    if existing:
        result = api(f"/budgets/{existing[0]}", method="PUT", body=body)
    else:
        result = api("/budgets", method="POST", body=body)
    attr = result["data"]["attributes"]
    return {
        "name": attr["name"],
        "auto_budget": f'{attr["auto_budget_amount"]} {attr["auto_budget_period"]} ({attr["auto_budget_type"]})',
    }


if __name__ == "__main__":
    mcp.run()
