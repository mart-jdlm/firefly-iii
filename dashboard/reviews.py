"""The monthly reviews written by bilan/bilan.sh, read from BILANS_DIR."""

import datetime as dt
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import firefly


# Read-only: the monthly reviews written by bilan/bilan.sh (YYYY-MM.facts.json, .comments.json, .html).
BILANS_DIR = os.environ.get("BILANS_DIR", "/bilans")


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


def still_uncategorised(rows: list[dict], start: str, end: str) -> list[dict]:
    """The review was written at the start of the month: drop what has been filed since. Kept as
    is when Firefly III cannot be asked."""
    if not rows:
        return rows
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    query = f"has_no_category:true date_after:{first - dt.timedelta(days=1)} date_before:{last + dt.timedelta(days=1)}"
    try:
        body = firefly.api("/search/transactions", {"query": query, "limit": 200})
    except (urllib.error.URLError, ValueError):
        return rows
    open_ids = {str(t["transaction_journal_id"]) for g in body["data"] for t in g["attributes"]["transactions"]}
    return [r for r in rows if str(r.get("id")) in open_ids]


def review_data(month: str) -> dict:
    """One review for the page: the figures worth showing (not every transaction) and the comments."""
    facts, comments = read_review_file(month, "facts.json"), read_review_file(month, "comments.json")
    if not isinstance(facts, dict) or not isinstance(comments, dict):
        raise KeyError(month)
    keep = ("month", "start", "end", "earned", "spent", "saved", "net_worth", "net_worth_change", "pea_market",
            "net_worth_by_month", "groups", "categories", "uncategorised", "budgets", "upcoming_bills", "goals")
    shown = {k: facts[k] for k in keep if k in facts}
    shown["largest"] = [t for t in facts.get("largest", []) if t.get("type") == "withdrawal"][:6]
    shown["uncategorised"] = still_uncategorised(shown.get("uncategorised", []), *firefly.month_bounds(*map(int, month.split("-"))))
    return {"facts": shown, "comments": comments,
            "has_html": os.path.isfile(os.path.join(BILANS_DIR, f"{month}.html"))}
