"""Transactions: search, categorising, quick add, rules, the pickers and the alerts built from them."""

import concurrent.futures
import datetime as dt

import firefly
import ttlcache


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
            "description": t["description"], "amount": firefly.money(t["amount"]),
            "category": t["category_name"], "budget": t["budget_name"],
            "source": t["source_name"], "destination": t["destination_name"],
            "notes": t["notes"], "bill": t["bill_name"]}


def search_transactions(text: str) -> list[dict]:
    """The 30 most recent transactions whose description matches `text`, on any date."""
    text = " ".join(text.split())[:80]
    if len(text) < 2:
        return []
    everyday = firefly.everyday_ids()
    found = []
    for group in firefly.api("/search/transactions", {"query": f'description_contains:"{text.replace(chr(34), "")}"', "limit": 100})["data"]:
        for t in group["attributes"]["transactions"]:
            row = everyday_row(t, group["id"], everyday)
            if row:
                found.append(row)
    return sorted(found, key=lambda t: (t["date"], t["id"]), reverse=True)[:30]


def month_transactions(month: str) -> list[dict]:
    """Every transaction of a month touching an everyday account, newest first."""
    year, mon = map(int, month.split("-"))
    return range_transactions(*firefly.month_bounds(year, mon))


MAX_RANGE_DAYS = 1100


def range_transactions(start: str, end: str) -> list[dict]:
    """Every transaction from `start` to `end` (inclusive, YYYY-MM-DD) touching an everyday
    account, newest first."""
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if last < first or (last - first).days > MAX_RANGE_DAYS:
        raise ValueError("Période invalide")
    everyday = firefly.everyday_ids()
    query = (f"date_after:{dt.date.fromisoformat(start) - dt.timedelta(days=1)} "
             f"date_before:{dt.date.fromisoformat(end) + dt.timedelta(days=1)}")
    found, page = [], 1
    while True:
        body = firefly.api("/search/transactions", {"query": query, "limit": 200, "page": page})
        for group in body["data"]:
            for t in group["attributes"]["transactions"]:
                row = everyday_row(t, group["id"], everyday)
                if row and start <= row["date"] <= end:
                    found.append(row)
        if page >= body["meta"]["pagination"]["total_pages"]:
            break
        page += 1
    return sorted(found, key=lambda t: (t["date"], t["id"]), reverse=True)


def taxonomy() -> dict:
    """Names of the categories and budgets, for the pickers of the transaction editor."""
    names = lambda path: sorted((r["attributes"]["name"] for r in firefly.api_all(path)), key=str.casefold)
    accounts = [a["attributes"]["name"] for a in firefly.api_all("/accounts", {"type": "asset"})
                if a["attributes"]["active"] and not a["attributes"]["name"].startswith((firefly.DEBT_PREFIX, firefly.INVESTMENT_PREFIX))]
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
    everyday = firefly.everyday_ids()
    found = []
    for group in firefly.api("/search/transactions", {"query": query, "limit": PAST_LIMIT})["data"]:
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
    current = next((t for t in firefly.api(f"/transactions/{group}")["data"]["attributes"]["transactions"]
                    if int(t["transaction_journal_id"]) == journal), None)
    if current is None:
        raise ValueError("Transaction introuvable")
    if current["category_name"] == "Valorisation":
        raise ValueError("Les valorisations du PEA sont gérées automatiquement")
    if current["type"] != "withdrawal":
        budget = ""  # only spending has a budget
    firefly.api_write("PUT", f"/transactions/{group}", {
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
                firefly.api_write("PUT", f"/transactions/{row['group']}", {
                    "apply_rules": False, "fire_webhooks": False,
                    "transactions": [{"transaction_journal_id": str(row["id"]), "category_name": category,
                                      **({"budget_name": budget} if budget else {})}]})
                applied += 1
    return {"applied": applied}


def apply_suggestion(body: dict) -> None:
    """File one uncategorised transaction under a category suggested by the review. Never replaces
    a category, and keeps the budget and everything else as is."""
    journal, category = int(body.get("id", 0)), str(body.get("category") or "").strip()
    if not category or category not in taxonomy()["categories"]:
        raise ValueError("Catégorie inconnue")
    group = firefly.api(f"/transaction-journals/{journal}")["data"]
    current = next((t for t in group["attributes"]["transactions"] if int(t["transaction_journal_id"]) == journal), None)
    if current is None:
        raise ValueError("Transaction introuvable")
    if current["category_name"]:
        raise ValueError("Cette transaction a déjà une catégorie")
    firefly.api_write("PUT", f"/transactions/{group['id']}", {
        "apply_rules": False, "fire_webhooks": False,
        "transactions": [{"transaction_journal_id": str(journal), "category_name": category}]})


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
    firefly.api_write("POST", "/transactions", {"apply_rules": True, "fire_webhooks": False, "error_if_duplicate_hash": False,
                                        "transactions": [entry]})


def add_rule(text: str, category: str, budget: str, kind: str) -> None:
    title = f"{text} → {category}"
    groups = {g["attributes"]["title"]: g["id"] for g in firefly.api_all("/rule-groups")}
    if RULE_GROUP not in groups:
        groups[RULE_GROUP] = firefly.api_write("POST", "/rule-groups", {"title": RULE_GROUP, "active": True})["data"]["id"]
    action = lambda kind, value: {"type": kind, "value": value, "active": True, "stop_processing": False}
    rule = {"title": title, "rule_group_id": groups[RULE_GROUP], "trigger": "store-journal",
            "active": True, "strict": True,
            "triggers": [{"type": "description_contains", "value": text, "active": True,
                          "prohibited": False, "stop_processing": False},
                         {"type": "transaction_type", "value": kind, "active": True,
                          "prohibited": False, "stop_processing": False}],
            "actions": [action("set_category", category)] + ([action("set_budget", budget)] if budget else [])}
    existing = [r["id"] for r in firefly.api_all("/rules") if r["attributes"]["title"] == title]
    firefly.api_write("PUT" if existing else "POST", f"/rules/{existing[0]}" if existing else "/rules", rule)


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
                            "category": t["category"], "usual": firefly.money(median)})
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
            missing = {"count": len(loose), "amount": firefly.money(sum(t["amount"] for t in loose)), "month": m}
            break
    return {"unusual": unusual, "price_changes": changes, "uncategorised": missing}


def alerts_data() -> dict:
    today = dt.date.today()
    months = [f"{y}-{m:02d}" for y, m in firefly.months_back(5)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        history = dict(zip(months, pool.map(lambda m: ttlcache.cached(f"/api/transactions{m}", lambda: month_transactions(m)), months)))
    return alerts_from(history, today)
