"""Monthly figures: income, spending, net worth, budgets, bills and the spending tree."""

import concurrent.futures
import datetime as dt

import firefly


def insight(path: str, start: str, end: str, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    return firefly.api(f"/insight/{path}", [("start", start), ("end", end)] + [("accounts[]", i) for i in ids])


def by_category(kind: str, start: str, end: str, ids: list[str]) -> dict[str, float]:
    rows = {r["name"]: firefly.money(r["difference"]) for r in insight(f"{kind}/category", start, end, ids)}
    other = sum(float(r["difference"]) for r in insight(f"{kind}/no-category", start, end, ids))
    if other:
        rows[firefly.UNCATEGORISED] = firefly.money(other)
    # Expenses come back negative; the page works with positive amounts.
    return {name: abs(v) for name, v in rows.items() if v}


def net_worth_at(date: str) -> dict:
    groups = {"courant": 0.0, "epargne": 0.0, "investissements": 0.0, "dettes": 0.0}
    accounts = []
    for kind in ("asset", "liabilities"):
        for a in firefly.api_all("/accounts", {"type": kind, "date": date}):
            attr = a["attributes"]
            if not attr["active"] or not attr["include_net_worth"]:
                continue
            name, balance = attr["name"], firefly.money(attr["current_balance"])
            if attr["type"] == "liabilities" or name.startswith(firefly.DEBT_PREFIX):
                group = "dettes"
            elif name.startswith(firefly.INVESTMENT_PREFIX):
                group = "investissements"
            elif attr["account_role"] == "savingAsset":
                group = "epargne"
            else:
                group = "courant"
            groups[group] += balance
            accounts.append({"name": name, "group": group, "balance": balance})
    groups = {g: firefly.money(v) for g, v in groups.items()}
    return {**groups, "total": firefly.money(sum(groups.values())), "accounts": accounts}


def month_figures(year: int, month: int, everyday: list[str], investments: list[str]) -> dict:
    start, end = firefly.month_bounds(year, month)
    today = dt.date.today()
    end_date = min(today, dt.date.fromisoformat(end))
    expenses = by_category("expense", start, end, everyday)
    income = by_category("income", start, end, everyday)
    market = firefly.money(sum(float(r["difference"]) for kind in ("income", "expense")
                       for r in insight(f"{kind}/total", start, end, investments)))
    return {
        "month": start[:7],
        "expenses": expenses,
        "income": income,
        "earned": firefly.money(sum(income.values())),
        "spent": firefly.money(sum(expenses.values())),
        "market": market,
        "net_worth": net_worth_at(end_date.isoformat()),
    }


def build(months: int) -> dict:
    accounts = firefly.api_all("/accounts", {"type": "asset"})
    names = {a["id"]: a["attributes"]["name"] for a in accounts}
    investments = [i for i, n in names.items() if n.startswith(firefly.INVESTMENT_PREFIX)]
    everyday = [i for i, n in names.items() if not n.startswith((firefly.DEBT_PREFIX, firefly.INVESTMENT_PREFIX))]

    # One extra month before the first, to know how much net worth moved during it.
    periods = firefly.months_back(months + 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(lambda p: month_figures(*p, everyday, investments), periods))

    result = []
    for previous, row in zip(rows, rows[1:]):
        change = firefly.money(row["net_worth"]["total"] - previous["net_worth"]["total"])
        row["change"] = change
        # What was really put aside: net worth growth without the PEA's market moves. Money
        # borrowed from family counts negatively.
        row["saved"] = firefly.money(change - row["market"])
        row["saved_simple"] = firefly.money(row["earned"] - row["spent"])
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
    start, end = firefly.month_bounds(year, mon)
    names = {a["id"]: a["attributes"]["name"] for a in firefly.api_all("/accounts", {"type": "asset"})}
    everyday = {i for i, n in names.items() if not n.startswith((firefly.DEBT_PREFIX, firefly.INVESTMENT_PREFIX))}
    # Widened by a day and checked below, so the bounds are inclusive whatever the operators do.
    query = (f"type:withdrawal date_after:{dt.date.fromisoformat(start) - dt.timedelta(days=1)} "
             f"date_before:{dt.date.fromisoformat(end) + dt.timedelta(days=1)}")
    tree: dict[str, dict[str, float]] = {}
    page = 1
    while True:
        body = firefly.api("/search/transactions", {"query": query, "limit": 200, "page": page})
        for group in body["data"]:
            for t in group["attributes"]["transactions"]:
                if (t["source_id"] not in everyday or t["category_name"] == "Valorisation"
                        or not start <= t["date"][:10] <= end):
                    continue
                budget = t["budget_name"] or "Sans budget"
                category = t["category_name"] or firefly.UNCATEGORISED
                tree.setdefault(budget, {})
                tree[budget][category] = tree[budget].get(category, 0) + float(t["amount"])
        if page >= body["meta"]["pagination"]["total_pages"]:
            break
        page += 1
    return {b: {c: firefly.money(v) for c, v in cats.items()} for b, cats in tree.items()}


def month_budgets(month: str) -> list[dict]:
    year, mon = map(int, month.split("-"))
    start, end = firefly.month_bounds(year, mon)
    result = []
    for b in firefly.api_all("/budgets"):
        attr = b["attributes"]
        if not attr["active"]:
            continue
        limits = firefly.api(f"/budgets/{b['id']}/limits", {"start": start, "end": end})["data"]
        amount = sum(float(l["attributes"]["amount"]) for l in limits)
        spent = sum(float(x["sum"]) for x in
                    firefly.api(f"/budgets/{b['id']}", {"start": start, "end": end})["data"]["attributes"]["spent"])
        result.append({"name": attr["name"], "limit": firefly.money(amount) if limits else None,
                       "spent": firefly.money(-spent)})
    return result


def bills_data() -> dict:
    today = dt.date.today()
    end = today + dt.timedelta(days=90)
    bills, upcoming = [], []
    for b in firefly.api_all("/bills", {"start": today.isoformat(), "end": end.isoformat()}):
        attr = b["attributes"]
        if not attr["active"]:
            continue
        average = firefly.money((float(attr["amount_min"]) + float(attr["amount_max"])) / 2)
        bills.append({"name": attr["name"], "amount": average, "frequency": attr["repeat_freq"],
                      "min": firefly.money(attr["amount_min"]), "max": firefly.money(attr["amount_max"])})
        for date in attr["pay_dates"]:
            if today.isoformat() <= date[:10] <= end.isoformat():
                upcoming.append({"date": date[:10], "name": attr["name"], "amount": average})
    piggies = [{"name": p["attributes"]["name"], "current": firefly.money(p["attributes"]["current_amount"]),
                "target": firefly.money(p["attributes"]["target_amount"]),
                "date": (p["attributes"]["target_date"] or "")[:10] or None}
               for p in firefly.api_all("/piggy-banks") if p["attributes"]["active"]]
    return {"bills": bills, "upcoming": sorted(upcoming, key=lambda u: u["date"]), "piggies": piggies}
