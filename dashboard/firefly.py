"""Firefly III API access and the small helpers every module shares (money, month bounds)."""

import calendar
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request


FIREFLY_URL = os.environ.get("FIREFLY_URL", "http://app:8080").rstrip("/")

FIREFLY_TOKEN = os.environ["FIREFLY_TOKEN"]

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


def everyday_ids() -> set[str]:
    return {a["id"] for a in api_all("/accounts", {"type": "asset"})
            if not a["attributes"]["name"].startswith((DEBT_PREFIX, INVESTMENT_PREFIX))}
