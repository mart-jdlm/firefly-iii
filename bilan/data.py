"""Facts for one month's review, as JSON on stdout: data.py YYYY-MM.

Runs in the assistant container (see bilan.sh), reusing the MCP server's helpers, so every figure
in the review comes from Firefly III rather than from Claude.
"""

import calendar
import datetime as dt
import json
import sys

sys.path.insert(0, "/app")
import server  # noqa: E402
from server import api_all, money  # noqa: E402


def month_range(year: int, month: int) -> tuple[dt.date, dt.date]:
    return dt.date(year, month, 1), dt.date(year, month, calendar.monthrange(year, month)[1])


def shift(year: int, month: int, by: int) -> tuple[int, int]:
    year, month = divmod(year * 12 + month - 1 + by, 12)
    return year, month + 1


def transactions(start: dt.date, end: dt.date) -> list[dict]:
    # date_after / date_before are widened by a day and the dates checked here, so the bounds
    # are inclusive whatever Firefly III's operators do.
    query = f"date_after:{start - dt.timedelta(days=1)} date_before:{end + dt.timedelta(days=1)}"
    found = server.search_transactions(query, limit=200)
    return [t for t in found
            if start.isoformat() <= t["date"] <= end.isoformat() and t["category"] != "Valorisation"]


def main() -> None:
    year, month = map(int, sys.argv[1].split("-"))
    start, end = month_range(year, month)
    s, e = start.isoformat(), end.isoformat()

    # Net worth at the end of this month and the 5 before it, plus the month before those.
    ends = [month_range(*shift(year, month, back))[1] for back in range(-6, 1)]
    worth = [server.net_worth_at(d.isoformat()) for d in ends]
    pea_ids = server.investment_account_ids()
    market = money(server.insight_total("income", s, e, pea_ids)
                   + server.insight_total("expense", s, e, pea_ids)) if pea_ids else 0.0
    change = money(worth[-1]["net_worth"] - worth[-2]["net_worth"])

    spent = server.by_category(s, e)["categories"]
    previous = []
    for back in (-3, -2, -1):
        ps, pe = month_range(*shift(year, month, back))
        previous.append(server.by_category(ps.isoformat(), pe.isoformat())["categories"])
    categories = [
        {"name": name, "amount": money(-amount),
         "average_3_months": money(-sum(p.get(name, 0) for p in previous) / 3)}
        for name, amount in spent.items() if amount < 0
    ]
    # Categories that had spending before but none this month are worth a mention too.
    for name in sorted({n for p in previous for n in p} - set(spent)):
        average = money(-sum(p.get(name, 0) for p in previous) / 3)
        if average > 0:
            categories.append({"name": name, "amount": 0.0, "average_3_months": average})

    month_transactions = transactions(start, end)
    withdrawals = [t for t in month_transactions if t["type"] == "withdrawal"]
    total = server.summary(s, e)
    facts = {
        "month": sys.argv[1],
        "start": s,
        "end": e,
        "earned": total["earned"],
        "spent": money(-total["spent"]),
        "saved": money(change - market),
        "net_worth": worth[-1]["net_worth"],
        "net_worth_change": change,
        "pea_market": market,
        "net_worth_by_month": [
            {"month": d.isoformat()[:7], "net_worth": w["net_worth"]} for d, w in zip(ends[1:], worth[1:])
        ],
        "groups": worth[-1]["totals"],
        "accounts": worth[-1]["accounts"],
        "categories": categories,
        "largest": sorted(withdrawals, key=lambda t: t["amount"], reverse=True)[:5],
        "uncategorised": [t for t in month_transactions
                          if not t["category"] and t["type"] in ("withdrawal", "deposit")],
        "transactions": month_transactions,
        "budgets": server.budgets(s, e),
        "upcoming_bills": server.upcoming_bills(35),
        "projection": server.projection(years=5),
        "goals": server.goals(),
        "category_names": sorted(c["attributes"]["name"] for c in api_all("/categories")),
    }
    json.dump(facts, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
