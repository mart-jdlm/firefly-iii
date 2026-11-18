"""Dashboard for Firefly III: income, spending, saving and net worth (see the README, "Dashboard").

A web page in the spirit of Finary, served here with the standard library only. It reads the
Firefly III API and writes piggy banks, the category of a transaction (with its optional rule) and
new transactions typed by hand. Needs FIREFLY_URL and FIREFLY_TOKEN. Listens on port 8787;
`tailscale serve` publishes it on the tailnet. DASHBOARD_ALLOWED_HOSTS (comma separated, default
localhost) lists the Host names accepted, against DNS rebinding.

The code is split by subject: `firefly` (API access, shared helpers), `figures` (monthly figures),
`transactions` (search, categorising, quick add, alerts), `invest` (PEA, Yahoo Finance), `goals`
(goals and piggy banks), `reviews` (monthly reviews), `ttlcache`. This file holds the HTTP server.
"""

import datetime as dt
import gzip
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import figures
import firefly
import goals
import invest
import reviews
import transactions
import ttlcache


PORT = int(os.environ.get("DASHBOARD_PORT", "8787"))

ALLOWED = {h.strip() for h in os.environ.get("DASHBOARD_ALLOWED_HOSTS", "").split(",") if h.strip()}

HERE = os.path.dirname(os.path.abspath(__file__))

MAX_MONTHS = 36

_lock = threading.Lock()  # serialises the piggy bank writes


def tree(month: str) -> dict:
    return ttlcache.cache.get(f"flow{month}", lambda: figures.expense_tree(month))


def data(months: int) -> dict:
    return ttlcache.cache.get(f"data{months}", lambda: figures.build(months))


def warm_up() -> None:
    """Fills the main caches at start, so the first page load does not wait for ~100 API calls."""
    for attempt in range(5):
        try:
            data(24)
            return
        except Exception:
            time.sleep(10 * (attempt + 1))  # Firefly III may still be starting


# Logo, icons and web manifest (the name and logo of the app: Cairn).
ASSETS = {
    "/logo.svg": ("static/logo.svg", "image/svg+xml"),
    "/favicon.svg": ("static/favicon.svg", "image/svg+xml"),
    "/logo-512.png": ("static/logo-512.png", "image/png"),
    "/icon-192.png": ("static/icon-192.png", "image/png"),
    "/icon-512.png": ("static/icon-512.png", "image/png"),
    "/apple-touch-icon.png": ("static/apple-touch-icon.png", "image/png"),
    "/manifest.webmanifest": ("static/manifest.webmanifest", "application/manifest+json"),
}


COMPRESSIBLE = ("text/", "application/json", "application/javascript", "image/svg+xml",
                "application/manifest+json")


_static: dict[str, tuple[float, bytes, str]] = {}


def host_name(value: str) -> str:
    """Host header without its port, IPv6 literals included ("[::1]:8787" -> "[::1]")."""
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value[: value.find("]") + 1] if "]" in value else value
    return value.rsplit(":", 1)[0] if ":" in value else value


def allowed_hosts() -> set[str]:
    return {"localhost", "127.0.0.1", "[::1]"} | {h.lower() for h in ALLOWED}


class Handler(BaseHTTPRequestHandler):
    server_version = "dashboard"

    def reply(self, status: int, body: bytes, content_type: str, cache: str = "no-store",
              etag: str | None = None) -> None:
        if etag and self.headers.get("If-None-Match") == etag:
            status, body = 304, b""
        elif (len(body) > 1024 and content_type.startswith(COMPRESSIBLE)
              and "gzip" in (self.headers.get("Accept-Encoding") or "")):
            body = gzip.compress(body, 6)
            self.send_response(status)
            self.send_header("Content-Encoding", "gzip")
            return self._finish(body, content_type, cache, etag)
        self.send_response(status)
        self._finish(body, content_type, cache, etag)

    def _finish(self, body: bytes, content_type: str, cache: str, etag: str | None) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Vary", "Accept-Encoding")
        if etag:
            self.send_header("ETag", etag)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:
        if host_name(self.headers.get("Host")) not in allowed_hosts():
            return self.reply(403, b"forbidden", "text/plain")
        url = urllib.parse.urlparse(self.path)
        try:
            if url.path == "/healthz":
                return self.reply(200, b"ok", "text/plain")
            if url.path == "/":
                return self.serve("index.html", "text/html; charset=utf-8")
            if url.path in ASSETS:
                name, content_type = ASSETS[url.path]
                return self.serve(name, content_type, "public, max-age=86400")
            if url.path == "/chart.js":
                return self.serve("static/chart.umd.js", "application/javascript", "public, max-age=86400")
            if url.path == "/api/transactions" and "start" in urllib.parse.parse_qs(url.query):
                query = urllib.parse.parse_qs(url.query)
                start, end = (dt.date.fromisoformat(query.get(k, [""])[0]).isoformat() for k in ("start", "end"))
                return self.reply(200, json.dumps(ttlcache.cached(f"range{start}{end}", lambda: transactions.range_transactions(start, end))).encode(),
                                  "application/json")
            if url.path in ("/api/transactions", "/api/budgets"):
                month = urllib.parse.parse_qs(url.query).get("month", [""])[0]
                dt.datetime.strptime(month, "%Y-%m")
                make = transactions.month_transactions if url.path == "/api/transactions" else figures.month_budgets
                return self.reply(200, json.dumps(ttlcache.cached(f"{url.path}{month}", lambda: make(month))).encode(),
                                  "application/json")
            if url.path == "/api/rule-preview":
                query = urllib.parse.parse_qs(url.query)
                rows = transactions.past_matches(query.get("text", [""])[0], query.get("type", [""])[0])
                return self.reply(200, json.dumps({"count": len(rows), "amount": firefly.money(sum(r["amount"] for r in rows)),
                                                   "capped": len(rows) >= transactions.PAST_LIMIT}).encode(), "application/json")
            if url.path == "/api/bilans":
                return self.reply(200, json.dumps(ttlcache.cached("bilans", reviews.reviews_list)).encode(), "application/json")
            if url.path in ("/api/bilan", "/api/bilan.html"):
                month = urllib.parse.parse_qs(url.query).get("month", [""])[0]
                try:
                    if url.path == "/api/bilan":
                        return self.reply(200, json.dumps(ttlcache.cached(f"bilan{month}", lambda: reviews.review_data(month))).encode(), "application/json")
                    page = reviews.read_review_file(month, "html")
                    if page is None:
                        raise KeyError(month)
                    return self.reply(200, page.encode(), "text/html; charset=utf-8")
                except KeyError:
                    return self.reply(404, json.dumps({"error": "Pas de bilan pour ce mois"}).encode(), "application/json")
            if url.path == "/api/search":
                text = urllib.parse.parse_qs(url.query).get("q", [""])[0]
                return self.reply(200, json.dumps(ttlcache.cached(f"search{text.casefold()}", lambda: transactions.search_transactions(text))).encode(),
                                  "application/json")
            if url.path == "/api/alerts":
                return self.reply(200, json.dumps(ttlcache.cached("alerts", transactions.alerts_data)).encode(), "application/json")
            if url.path == "/api/taxonomy":
                return self.reply(200, json.dumps(ttlcache.cached("taxonomy", transactions.taxonomy)).encode(), "application/json")
            if url.path == "/api/bills":
                return self.reply(200, json.dumps(ttlcache.cached("bills", figures.bills_data)).encode(), "application/json")
            if url.path == "/api/goals":
                return self.reply(200, json.dumps(ttlcache.cached("goals", goals.goals_data)).encode(), "application/json")
            if url.path == "/api/pea":
                return self.reply(200, json.dumps(ttlcache.cached("pea", invest.pea_data)).encode(), "application/json")
            if url.path == "/api/history":
                query = urllib.parse.parse_qs(url.query)
                symbol, span = query.get("symbol", [""])[0], query.get("span", ["1y"])[0]
                return self.reply(200, json.dumps(ttlcache.cached(f"history{symbol}{span}", lambda: invest.line_history(symbol, span))).encode(),
                                  "application/json")
            if url.path == "/sw.js":  # service worker: must be served from the root, always revalidated
                return self.serve("static/sw.js", "application/javascript")
            if re.fullmatch(r"/js/[a-z0-9-]+\.js", url.path):  # the page's ES modules
                if os.path.isfile(os.path.join(HERE, "static", url.path[1:])):
                    return self.serve("static" + url.path, "application/javascript")
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
                    ttlcache.cache.expire_all()
                return self.reply(200, json.dumps(data(months)).encode(), "application/json")
        except (urllib.error.URLError, ValueError, KeyError) as e:
            return self.reply(502, json.dumps({"error": str(e)}).encode(), "application/json")
        except Exception as e:  # a bug must give an error answer, not a dropped connection
            print(f"{self.path}: {type(e).__name__}: {e}", flush=True)
            return self.reply(500, json.dumps({"error": "Erreur interne"}).encode(), "application/json")
        self.reply(404, b"not found", "text/plain")

    do_HEAD = do_GET


    def do_POST(self) -> None:
        """Piggy bank changes and transaction categorisation (Firefly III is the source of truth).
        A JSON body, a custom header and a same-site Origin are required, so a page on another
        site cannot write."""
        host = host_name(self.headers.get("Host"))
        origin = self.headers.get("Origin") or ""
        origin_host = host_name(origin.split("//", 1)[-1]) if origin else host
        if host not in allowed_hosts() or origin_host not in allowed_hosts():
            return self.reply(403, b"forbidden", "text/plain")
        if (self.headers.get("X-Requested-With") != "dashboard"
                or "application/json" not in (self.headers.get("Content-Type") or "")):
            return self.reply(400, b"bad request", "text/plain")
        piggy = {"create": goals.create_piggy, "update": goals.update_piggy, "move": goals.move_piggy, "delete": goals.delete_piggy}
        routes = {"/api/piggy": (piggy, ("goals",)), "/api/transaction": ({"categorize": transactions.categorize, "create": transactions.create_transaction, "suggest": transactions.apply_suggestion}, None)}
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 4000:
                raise ValueError("Requête invalide")
            body = json.loads(self.rfile.read(length))
            route = routes.get(urllib.parse.urlparse(self.path).path)
            if route is None:
                return self.reply(404, b"not found", "text/plain")
            actions, stale = route
            action = actions.get(body.get("action"))
            if action is None:
                raise ValueError("Action inconnue")
            with _lock:
                result = action(body)
                if stale is None:  # a transaction change shows in every total
                    ttlcache.cache.expire_all()
                else:
                    for key in stale:
                        ttlcache.cache.drop(key)
        except (ValueError, KeyError, TypeError) as e:
            return self.reply(400, json.dumps({"error": str(e)}).encode(), "application/json")
        except urllib.error.URLError as e:
            return self.reply(502, json.dumps({"error": str(e)}).encode(), "application/json")
        except Exception as e:
            print(f"POST {self.path}: {type(e).__name__}: {e}", flush=True)
            return self.reply(500, json.dumps({"error": "Erreur interne"}).encode(), "application/json")
        self.reply(200, json.dumps(result if isinstance(result, dict) else {}).encode(), "application/json")

    def serve(self, name: str, content_type: str, cache: str | None = None) -> None:
        """Static file with an ETag: app code revalidates (304 when unchanged), icons and Chart.js
        are kept a day."""
        path = os.path.join(HERE, name)
        mtime = os.path.getmtime(path)
        hit = _static.get(name)
        if not hit or hit[0] != mtime:
            with open(path, "rb") as f:
                body = f.read()
            hit = _static[name] = (mtime, body, f'"{hashlib.sha1(body).hexdigest()[:16]}"')
        self.reply(200, hit[1], content_type, cache or "no-cache", hit[2])

    def log_message(self, fmt: str, *args) -> None:
        pass


if __name__ == "__main__":
    threading.Thread(target=warm_up, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
