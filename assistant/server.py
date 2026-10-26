"""MCP server giving Claude Code access to Firefly III (see the README, "Assistant").

Runs over stdio in the `assistant` container, launched on demand by Claude Code (.mcp.json).
Needs FIREFLY_URL and FIREFLY_TOKEN; reads and edits the PEA positions in PEA_POSITIONS and the
savings goals in GOALS_FILE.
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
GOALS_FILE = os.environ.get("GOALS_FILE", "/patrimoine/objectifs.json")

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
- To know how much the user really saves, use net_worth_history (its "saved" counts money borrowed
  from family); projection builds on it. A projection is an estimate: always state its assumptions
  and offer to rerun it with other ones (higher saving, PEA contributions, debt repayment, returns).
- Dates are YYYY-MM-DD. Without dates, tools cover the current month.
- Firefly III rules file new transactions automatically (category, budget, bill...). To fix how
  transactions get filed for good, prefer a rule (rules, save_rule) over editing them one by one;
  run preview_rule to see what a rule matches before apply_rule runs it on past transactions.
- update_transaction, create_transaction, set_budget, save_rule and apply_rule change the user's data.
  Before calling one, say exactly what will change (transaction or rule, field, old and new value;
  for apply_rule, the transactions preview_rule lists) and wait for the user's go-ahead.
  Never use them on transactions in category "Valorisation": cron/valuation.sh manages those.
- set_pea_position also changes the user's data (the PEA positions file): say the old and new
  quantity first and wait for the go-ahead. The valuation books the gap at its next daily run.
- Savings goals are balance targets on an account (a savings account reaching 3000, a family debt
  reaching 0) or Firefly III piggy banks, with an optional deadline. goals shows progress at the pace of the last 3 months;
  set_goal and remove_goal change the goals file: say what will change and wait for the go-ahead."""

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
            content = response.read()
            return json.loads(content) if content else None
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


def investment_account_ids() -> list[str]:
    return [a["id"] for a in assets() if a["attributes"]["name"].startswith(INVESTMENT_PREFIX)]


def insight(path: str, start: str, end: str, account_ids: list[str] | None = None) -> list[dict]:
    if account_ids is None:
        account_ids = everyday_account_ids()
    params = [("start", start), ("end", end)] + [("accounts[]", i) for i in account_ids]
    return api(f"/insight/{path}", params)


def insight_total(kind: str, start: str, end: str, account_ids: list[str] | None = None) -> float:
    return money(sum(float(r["difference"]) for r in insight(f"{kind}/total", start, end, account_ids)))


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


def net_worth_at(date: str | None = None) -> dict:
    """Net worth by group and account, as of the end of `date` (today without one)."""
    groups: dict[str, dict[str, float]] = {"courant": {}, "epargne": {}, "investissements": {}, "dettes": {}}
    params = {"date": date} if date else {}
    for a in api_all("/accounts", {"type": "asset", **params}) + api_all("/accounts", {"type": "liabilities", **params}):
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
def net_worth() -> dict:
    """Current net worth, split into everyday accounts, savings, investments and debts."""
    return net_worth_at()


def month_ends(months: int) -> list[dt.date]:
    """The last day of each of the last `months` months (today for the current one), preceded by
    the end of the month before them."""
    today = dt.date.today()
    ends = []
    for back in range(months, -1, -1):
        year, month = divmod(today.year * 12 + today.month - 1 - back, 12)
        month += 1
        ends.append(min(today, dt.date(year, month, calendar.monthrange(year, month)[1])))
    return ends


def history(months: int) -> tuple[dict, list[dict]]:
    """Net worth before the first of the last `months` months, then one row per month."""
    ends = month_ends(months)
    pea_ids = investment_account_ids()
    base = previous = net_worth_at(ends[0].isoformat())
    rows = []
    for end in ends[1:]:
        start = end.replace(day=1).isoformat()
        current = net_worth_at(end.isoformat())
        # Unrealised gains and losses booked on the PEA by cron/valuation.sh (deposits from
        # "Plus-values latentes", withdrawals to "Moins-values latentes").
        market = money(insight_total("income", start, end.isoformat(), pea_ids)
                       + insight_total("expense", start, end.isoformat(), pea_ids)) if pea_ids else 0.0
        change = money(current["net_worth"] - previous["net_worth"])
        rows.append({
            "month": start[:7],
            **current["totals"],
            "net_worth": current["net_worth"],
            "change": change,
            "market": market,
            "saved": money(change - market),
            "accounts": current["accounts"],
        })
        previous = current
    return base, rows


@mcp.tool(annotations=READ_ONLY)
def net_worth_history(months: int = 12) -> list[dict]:
    """Net worth at the end of each of the last `months` months (today for the current one), by group.

    change is the month's net worth change, market the PEA's unrealised gains or losses in it, and
    saved = change - market: what the user really put aside, debt movements included (money
    borrowed from family lowers it). This is a better measure of saving than monthly_history.
    """
    if not 1 <= months <= 60:
        raise ToolError("months must be between 1 and 60")
    return [{k: v for k, v in row.items() if k != "accounts"} for row in history(months)[1]]


@mcp.tool(annotations=READ_ONLY)
def projection(
    years: int = 5,
    monthly_saving: float | None = None,
    pea_monthly: float | None = None,
    debt_repayment: float | None = None,
    pea_return: float = 0.05,
    savings_rate: float = 0.015,
    inflation: float = 0.02,
) -> dict:
    """Project net worth month by month over `years` years from today, under stated assumptions.

    - monthly_saving: net worth added each month before returns (default: median `saved` of the
      last 12 full months, see net_worth_history).
    - pea_monthly: part of it paid into the PEA (default: average net contribution over 12 months).
    - debt_repayment: part of it repaying family debts, smallest first, until they are cleared
      (default: average monthly decrease of the debts over 12 months, 0 if they grew).
      The rest of monthly_saving goes to cash and savings accounts.
    - pea_return: yearly PEA return; savings_rate: yearly interest on cash and savings accounts;
      inflation: to also give net worth in today's euros. Rates are fractions (0.05 = 5 %).
    Returns the assumptions used (with how defaults were derived), one row per year, and the month
    each debt would be cleared (null if not within the horizon).
    """
    if not 1 <= years <= 50:
        raise ToolError("years must be between 1 and 50")
    base, rows = history(13)
    now, past = rows[-1], rows[:-1]  # today, and the 12 full months before the current one
    derived = {}
    if monthly_saving is None:
        saved = sorted(row["saved"] for row in past)
        monthly_saving = money((saved[5] + saved[6]) / 2)
        derived["monthly_saving"] = "median of the last 12 months"
    if pea_monthly is None:
        contributed = past[-1]["investissements"] - base["totals"]["investissements"] - sum(r["market"] for r in past)
        pea_monthly = money(max(contributed, 0) / 12)
        derived["pea_monthly"] = "average of the last 12 months"
    if debt_repayment is None:
        debt_repayment = money(max(past[-1]["dettes"] - base["totals"]["dettes"], 0) / 12)
        derived["debt_repayment"] = "average of the last 12 months"

    pea = now["investissements"]
    cash = now["courant"] + now["epargne"]
    debts = {name: -balance for name, balance in now["accounts"]["dettes"].items() if balance < 0}
    cleared = {name: None for name in debts}
    put_in = gains = 0.0
    month = dt.date.today().replace(day=1)
    yearly = []
    for step in range(1, years * 12 + 1):
        month = (month + dt.timedelta(days=32)).replace(day=1)
        market = pea * ((1 + pea_return) ** (1 / 12) - 1)
        interest = max(cash, 0) * savings_rate / 12
        repay = left = min(debt_repayment, sum(debts.values()))
        for name in sorted(debts, key=debts.get):
            part = min(left, debts[name])
            debts[name] -= part
            left -= part
            if debts[name] < 0.005 and cleared[name] is None:
                cleared[name] = month.isoformat()[:7]
        pea += market + pea_monthly
        cash += interest + monthly_saving - pea_monthly - repay
        put_in += monthly_saving
        gains += market + interest
        if step % 12 == 0:
            total = cash + pea - sum(debts.values())
            yearly.append({
                "date": month.isoformat()[:7],
                "cash_and_savings": money(cash),
                "pea": money(pea),
                "debts": money(-sum(debts.values())),
                "net_worth": money(total),
                "net_worth_today_eur": money(total / (1 + inflation) ** (step / 12)),
                "total_saved": money(put_in),
                "total_returns": money(gains),
            })
    return {
        "assumptions": {
            "monthly_saving": monthly_saving, "pea_monthly": pea_monthly, "debt_repayment": debt_repayment,
            "pea_return": pea_return, "savings_rate": savings_rate, "inflation": inflation,
            "derived_from_history": derived,
        },
        "today": {"cash_and_savings": money(now["courant"] + now["epargne"]),
                  "pea": now["investissements"], "debts": now["dettes"], "net_worth": now["net_worth"]},
        "years": yearly,
        "debts_cleared": cleared,
    }


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
        # Everything spent in the budget over the period, including days no amount covers.
        spent_in = api(f"/budgets/{b['id']}", {"start": start, "end": end})["data"]["attributes"]["spent"]
        spent = sum(float(s["sum"]) for s in spent_in)
        result.append({
            "name": attr["name"],
            "amount": money(amount),
            "spent": money(spent),
            "left": money(amount + spent) if limits else None,
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
def set_pea_position(symbol: str, quantity: float, label: str | None = None) -> dict:
    """Sets the quantity held of one PEA position in patrimoine/pea.txt (0 removes the line).

    symbol is the Yahoo Finance symbol (CW8.PA for Paris; checked to be quoted in euros), or
    "especes" for the PEA's cash in euros. quantity is the new total held, not the amount bought.
    label is a free comment, kept from the existing line when omitted.
    Returns the position before and after, and the positions file's total at today's prices.
    """
    if quantity < 0:
        raise ToolError("quantity cannot be negative")
    if symbol != "especes" and quantity:
        try:
            yahoo_price(symbol)
        except (urllib.error.URLError, KeyError, TypeError, IndexError) as error:
            raise ToolError(f"No euro price for {symbol} on Yahoo Finance ({error})") from error
    with open(PEA_POSITIONS, encoding="utf-8") as f:
        lines = f.read().splitlines()
    index = next((i for i, raw in enumerate(lines)
                  if raw.split(None, 1) and raw.split(None, 1)[0] == symbol), None)
    before = None
    old_label = ""
    if index is not None:
        parts = lines[index].split(None, 2)
        before = float(parts[1])
        old_label = parts[2].strip() if len(parts) > 2 else ""
    label = old_label if label is None else label
    if quantity == 0 and symbol != "especes":
        if index is None:
            raise ToolError(f"{symbol} is not in the positions file")
        del lines[index]
    else:
        text = f"{symbol:<9}{quantity:g}" + (f"      {label}" if label else "")
        if index is not None:
            lines[index] = text
        else:
            cash = next((i for i, raw in enumerate(lines) if raw.startswith("especes")), len(lines))
            lines.insert(cash, text)
    temp = PEA_POSITIONS + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(temp, PEA_POSITIONS)
    return {"symbol": symbol, "before": before, "after": quantity if quantity or symbol == "especes" else None,
            "positions": pea_positions()}


def read_goals() -> list[dict]:
    try:
        with open(GOALS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def write_goals(goals: list[dict]) -> None:
    temp = GOALS_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(goals, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(temp, GOALS_FILE)


def balances_at(date: str | None = None) -> dict[str, float]:
    params = {"date": date} if date else {}
    return {a["attributes"]["name"]: money(a["attributes"]["current_balance"])
            for a in api_all("/accounts", {"type": "asset", **params})}


def piggy_banks() -> dict[str, dict]:
    """Firefly III piggy banks by name: current and target amount, accounts, and contributions."""
    found = {}
    for piggy in api_all("/piggy-banks"):
        attr = piggy["attributes"]
        events = [(e["attributes"]["created_at"][:10], money(e["attributes"]["amount"]))
                  for e in api_all(f"/piggy-banks/{piggy['id']}/events")]
        found[attr["name"]] = {
            "balance": money(attr["current_amount"]),
            "target": money(attr["target_amount"]),
            "account": ", ".join(a["name"] for a in attr["accounts"]),
            "events": events,
        }
    return found


@mcp.tool(annotations=READ_ONLY)
def goals() -> list[dict]:
    """Savings goals with their progress, from patrimoine/objectifs.json.

    A goal is either a target balance on one account, or a Firefly III piggy bank (its amount
    against its target), with an optional deadline. pace is the monthly gain over about the last
    3 months (at least 1 month is assumed); eta is when the target is reached at that pace;
    needed_monthly is what must be added each month to meet the deadline. status: "reached",
    "on track", "late" or "no progress".
    """
    saved = read_goals()
    if not saved:
        return []
    today = dt.date.today()
    first = month_ends(3)[0]
    months_back = max((today - first).days / 30.44, 1)
    now = before = piggies = None
    result = []
    for goal in saved:
        if goal.get("piggy"):
            piggies = piggies or piggy_banks()
            piggy = piggies.get(goal["piggy"])
            if piggy is None:
                result.append({"name": goal["name"], "error": f'No piggy bank named "{goal["piggy"]}"'})
                continue
            source, balance = piggy["account"] + " (tirelire)", piggy["balance"]
            target = goal.get("target") or piggy["target"]
            pace = money(sum(a for d, a in piggy["events"] if d >= first.isoformat()) / months_back)
        else:
            now = now or balances_at()
            before = before or balances_at(first.isoformat())
            source, target = goal["account"], goal["target"]
            if source not in now:
                result.append({"name": goal["name"], "error": f'No asset account named "{source}"'})
                continue
            balance = now[source]
            pace = money((balance - before.get(source, balance)) / months_back)
        remaining = money(target - balance)
        deadline = goal.get("date")
        months_left = (dt.date.fromisoformat(deadline) - today).days / 30.44 if deadline else None
        row = {"name": goal["name"], "account": source, "balance": balance, "target": target,
               "remaining": max(remaining, 0), "deadline": deadline, "pace": pace}
        if remaining <= 0:
            row["status"] = "reached"
        else:
            if pace > 0:
                row["eta"] = (today + dt.timedelta(days=round(remaining / pace * 30.44))).isoformat()
            if months_left is not None and months_left > 0:
                row["needed_monthly"] = money(remaining / months_left)
            if pace <= 0:
                row["status"] = "no progress"
            elif deadline is None or row["eta"] <= deadline:
                row["status"] = "on track"
            else:
                row["status"] = "late"
        result.append(row)
    return result


@mcp.tool(annotations=WRITE)
def set_goal(
    name: str,
    account: str | None = None,
    target: float | None = None,
    date: str | None = None,
    piggy_bank: str | None = None,
) -> list[dict]:
    """Creates a savings goal, or replaces the one with the same name (patrimoine/objectifs.json).

    Either account + target: reached when that asset account (exact name) holds `target` euros,
    e.g. 3000 on a savings account, or 0 on a family debt account whose balance is negative.
    Or piggy_bank (exact name of a Firefly III piggy bank): reached when it is full; target
    overrides the piggy bank's own target. date (YYYY-MM-DD) is an optional deadline.
    Returns the goals with their progress.
    """
    if bool(account) == bool(piggy_bank):
        raise ToolError("Give either account (with target) or piggy_bank")
    goal = {"name": name}
    if piggy_bank:
        if piggy_bank not in piggy_banks():
            raise ToolError(f'No piggy bank named "{piggy_bank}"')
        goal["piggy"] = piggy_bank
        if target is not None:
            goal["target"] = money(target)
    else:
        if target is None:
            raise ToolError("target is required with an account")
        if account not in balances_at():
            raise ToolError(f'No asset account named "{account}"')
        goal.update(account=account, target=money(target))
    if date:
        try:
            dt.date.fromisoformat(date)
        except ValueError as error:
            raise ToolError("date must be YYYY-MM-DD") from error
        goal["date"] = date
    saved = [g for g in read_goals() if g["name"] != name]
    write_goals(saved + [goal])
    return goals()


@mcp.tool(annotations=WRITE)
def remove_goal(name: str) -> list[dict]:
    """Deletes the savings goal with that name. Returns the remaining goals with their progress."""
    saved = read_goals()
    kept = [g for g in saved if g["name"] != name]
    if len(kept) == len(saved):
        raise ToolError(f'No goal named "{name}"')
    write_goals(kept)
    return goals()


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


def rule_summary(rule: dict) -> dict:
    attr = rule["attributes"]
    return {
        "title": attr["title"],
        "group": attr["rule_group_title"],
        "active": attr["active"],
        "strict": attr["strict"],
        "triggers": [{"type": t["type"], "value": t["value"], **({"prohibited": True} if t["prohibited"] else {})}
                     for t in attr["triggers"]],
        "actions": [{"type": a["type"], "value": a["value"]} for a in attr["actions"]],
    }


def rule_id(title: str) -> str:
    for r in api_all("/rules"):
        if r["attributes"]["title"] == title:
            return r["id"]
    raise ToolError(f"No rule named {title!r}")


@mcp.tool(annotations=READ_ONLY)
def rules() -> list[dict]:
    """Every rule, in the order Firefly III runs them (group by group).

    Rules run when a transaction is created (imports included). With strict, every trigger must
    match; otherwise any one is enough.
    """
    groups = {g["attributes"]["title"]: g["attributes"]["order"] for g in api_all("/rule-groups")}
    found = sorted(api_all("/rules"), key=lambda r: (groups.get(r["attributes"]["rule_group_title"], 0),
                                                     r["attributes"]["order"]))
    return [rule_summary(r) for r in found]


@mcp.tool(annotations=WRITE)
def save_rule(
    title: str,
    triggers: list[dict],
    actions: list[dict],
    group: str = "Catégorisation automatique",
    strict: bool = False,
    active: bool = True,
) -> dict:
    """Create a rule, or replace the triggers and actions of the rule with that title.

    triggers: [{"type": ..., "value": ...}], optionally "prohibited": true to negate one. Common
    types: description_contains, description_starts, category_is, budget_is, amount_more,
    amount_less, source_account_is, destination_account_is, transaction_type (withdrawal...).
    actions: [{"type": ..., "value": ...}]. Common types: set_category, set_budget, add_tag,
    set_description, link_to_bill. Categories and budgets must already exist.
    strict: every trigger must match (otherwise any one). The group is created if missing; groups
    run in order, so a rule on category_is belongs in a group after the one that sets categories.
    It applies to new transactions only; use preview_rule and apply_rule for past ones.
    """
    if not triggers or not actions:
        raise ToolError("A rule needs at least one trigger and one action")
    groups = {g["attributes"]["title"]: g["id"] for g in api_all("/rule-groups")}
    if group not in groups:
        groups[group] = api("/rule-groups", method="POST", body={"title": group, "active": True})["data"]["id"]
    body = {
        "title": title,
        "rule_group_id": groups[group],
        "trigger": "store-journal",
        "active": active,
        "strict": strict,
        "triggers": [{"type": t["type"], "value": str(t["value"]), "active": True,
                      "prohibited": bool(t.get("prohibited")), "stop_processing": False} for t in triggers],
        "actions": [{"type": a["type"], "value": str(a["value"]), "active": True, "stop_processing": False}
                    for a in actions],
    }
    existing = [r["id"] for r in api_all("/rules") if r["attributes"]["title"] == title]
    if existing:
        result = api(f"/rules/{existing[0]}", method="PUT", body=body)
    else:
        result = api("/rules", method="POST", body=body)
    return rule_summary(result["data"])


@mcp.tool(annotations=READ_ONLY)
def preview_rule(title: str, start: str | None = None, end: str | None = None) -> list[dict]:
    """Past transactions a rule matches between start and end (default: this month). Changes nothing."""
    start, end = period(start, end)
    found = api(f"/rules/{rule_id(title)}/test", {"start": start, "end": end})["data"]
    return [t for group in found for t in journals(group)]


@mcp.tool(annotations=WRITE)
def apply_rule(title: str, start: str, end: str) -> dict:
    """Run a rule's actions on the past transactions it matches between start and end.

    Run preview_rule first and show the user what will change. Firefly III does the work in the
    background, so changes can take a few seconds to show.
    """
    api(f"/rules/{rule_id(title)}/trigger", {"start": start, "end": end}, method="POST")
    return {"rule": title, "start": start, "end": end, "status": "applied"}


if __name__ == "__main__":
    mcp.run()
