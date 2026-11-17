"""Savings goals and piggy banks (tirelires)."""

import calendar
import datetime as dt
import json
import os

import firefly


# Read-only here: goals of the assistant's goals file that follow an account's balance.
GOALS_FILE = os.environ.get("GOALS_FILE", "/patrimoine/objectifs.json")


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

    accounts = firefly.api_all("/accounts", {"type": "asset"})
    now = {a["attributes"]["name"]: firefly.money(a["attributes"]["current_balance"]) for a in accounts}
    before = {a["attributes"]["name"]: firefly.money(a["attributes"]["current_balance"])
              for a in firefly.api_all("/accounts", {"type": "asset", "date": since.isoformat()})}

    piggies = [p for p in firefly.api_all("/piggy-banks") if p["attributes"]["active"]]
    # Money of an account already put in piggy banks cannot go in another one.
    assigned: dict[str, float] = {}
    for p in piggies:
        for a in p["attributes"]["accounts"]:
            assigned[a["name"]] = assigned.get(a["name"], 0) + float(a["current_amount"])
    free = {n: firefly.money(now[n] - assigned.get(n, 0)) for n in now}

    rows = []
    for piggy in piggies:
        attr = piggy["attributes"]
        override = by_piggy.get(attr["name"], {})
        events = firefly.api_all(f"/piggy-banks/{piggy['id']}/events")
        pace = firefly.money(sum(float(e["attributes"]["amount"]) for e in events
                         if e["attributes"]["created_at"][:10] >= since.isoformat()) / months)
        source = attr["accounts"][0]["name"] if attr["accounts"] else ""
        rows.append({
            "name": attr["name"], "kind": "piggy", "editable": True, "source": source,
            "free": free.get(source), "balance": firefly.money(attr["current_amount"]),
            "target": firefly.money(override.get("target") or attr["target_amount"]),
            "deadline": override.get("date") or (attr["target_date"] or "")[:10] or None, "pace": pace,
        })
    for goal in file_goals:
        if goal.get("piggy") or goal.get("account") not in now:
            continue
        balance = now[goal["account"]]
        rows.append({
            "name": goal["name"], "kind": "account", "editable": False, "source": goal["account"],
            "balance": balance, "target": firefly.money(goal["target"]), "deadline": goal.get("date"),
            "pace": firefly.money((balance - before.get(goal["account"], balance)) / months),
        })
    for row in rows:
        remaining = firefly.money(row["target"] - row["balance"])
        row["remaining"] = max(remaining, 0)
        left = ((dt.date.fromisoformat(row["deadline"]) - today).days / 30.44) if row["deadline"] else None
        row["months_left"] = round(left, 1) if left is not None else None
        if remaining <= 0:
            row["status"] = "reached"
            continue
        if row["pace"] > 0:
            row["eta"] = (today + dt.timedelta(days=round(remaining / row["pace"] * 30.44))).isoformat()
        if left is not None and left > 0:
            row["needed_monthly"] = firefly.money(remaining / left)
        if row["pace"] <= 0:
            row["status"] = "stalled"
        elif not row["deadline"] or row["eta"] <= row["deadline"]:
            row["status"] = "on_track"
        else:
            row["status"] = "late"
    choices = [{"name": n, "free": free[n]} for n in sorted(now) if not n.startswith((firefly.DEBT_PREFIX, firefly.INVESTMENT_PREFIX))]
    return {"goals": rows, "accounts": choices}


def find_piggy(name: str) -> dict:
    for piggy in firefly.api_all("/piggy-banks"):
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
    accounts = {a["attributes"]["name"]: a["id"] for a in firefly.api_all("/accounts", {"type": "asset"})}
    account = str(body.get("account", ""))
    if account not in accounts:
        raise ValueError("Compte inconnu")
    if any(p["attributes"]["name"] == name for p in firefly.api_all("/piggy-banks")):
        raise ValueError("Une tirelire porte déjà ce nom")
    payload = {"name": name, "accounts": [{"account_id": accounts[account], "current_amount": "0"}],
               "target_amount": f"{target:.2f}", "start_date": dt.date.today().isoformat(),
               "transaction_currency_code": "EUR"}
    date = clean_date(body.get("date"))
    if date:
        payload["target_date"] = date
    firefly.api_write("POST", "/piggy-banks", payload)


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
    firefly.api_write("PUT", f"/piggy-banks/{piggy['id']}", payload)


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
        firefly.api_write("PUT", f"/piggy-banks/{piggy['id']}",
                  {"name": attr["name"], "transaction_currency_code": "EUR", "accounts": accounts})
    except ValueError as e:
        if "cannot be added" in str(e):
            raise ValueError(f"Pas assez d'argent libre sur {first['name']} (le reste est déjà dans d'autres tirelires)") from e
        raise


def delete_piggy(body: dict) -> None:
    piggy = find_piggy(str(body.get("name", "")))
    firefly.api_write("DELETE", f"/piggy-banks/{piggy['id']}")
