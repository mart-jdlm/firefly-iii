"""Tests of dashboard/app.py. Standard library only: python3 -m unittest discover -s dashboard/tests

Firefly III is never contacted: `api`, `api_all` and `api_write` are replaced by fakes, and the HTTP
tests run the real Handler on a local port.
"""
import datetime
import gzip
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
from http.server import ThreadingHTTPServer
from unittest import mock

os.environ.setdefault("FIREFLY_TOKEN", "test-token")
os.environ["DASHBOARD_ALLOWED_HOSTS"] = "cairn.test"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import app  # noqa: E402

TODAY = datetime.date(2026, 11, 17)


class FakeDate(datetime.date):
    @classmethod
    def today(cls):
        return cls(TODAY.year, TODAY.month, TODAY.day)


FAKE_DT = types.SimpleNamespace(date=FakeDate, datetime=datetime.datetime, timedelta=datetime.timedelta)


def router(routes):
    """A fake api_all: routes maps a path to a list, or to a function (path, params) -> list."""
    def fake(path, params=None):
        value = routes[path]
        return value(path, params) if callable(value) else value
    return fake


def account(id, name, balance, role=None, kind="asset", active=True, include=True):
    return {"id": id, "attributes": {"name": name, "current_balance": str(balance), "type": kind, "active": active,
                                     "include_net_worth": include, "account_role": role}}


class Helpers(unittest.TestCase):
    def test_host_name(self):
        for raw, want in [("localhost:8787", "localhost"), ("LocalHost", "localhost"), ("cairn.test:8787", "cairn.test"),
                          ("[::1]:8787", "[::1]"), ("[::1]", "[::1]"), ("", ""), (None, "")]:
            self.assertEqual(app.host_name(raw), want, raw)

    def test_month_bounds(self):
        self.assertEqual(app.month_bounds(2026, 2), ("2026-02-01", "2026-02-28"))
        self.assertEqual(app.month_bounds(2028, 2), ("2028-02-01", "2028-02-29"))
        self.assertEqual(app.month_bounds(2026, 12), ("2026-12-01", "2026-12-31"))

    def test_months_back_crosses_the_year_and_ends_now(self):
        with mock.patch.object(app, "dt", FAKE_DT):
            result = app.months_back(14)
        self.assertEqual(len(result), 14)
        self.assertEqual(result[-1], (2026, 11))
        self.assertEqual(result[0], (2025, 10))
        self.assertEqual(result[2], (2025, 12)); self.assertEqual(result[3], (2026, 1))

    def test_money_and_clean_date(self):
        self.assertEqual(app.money("12.5"), 12.5)
        self.assertEqual(app.money("3.14159"), 3.14)
        self.assertEqual(app.money(None), 0)
        self.assertIsNone(app.clean_date(""))
        self.assertEqual(app.clean_date("2027-01-31"), "2027-01-31")
        with self.assertRaises(ValueError):
            app.clean_date("31/01/2027")

    def test_read_positions(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("# symbol quantity label\nCW8.PA 2 ETF Monde\n\nespeces 3.2\nbad line\nXYZ notanumber\n")
        try:
            with mock.patch.object(app, "PEA_POSITIONS", f.name):
                self.assertEqual(app.read_positions(), [
                    {"symbol": "CW8.PA", "quantity": 2.0, "label": "ETF Monde"},
                    {"symbol": "especes", "quantity": 3.2, "label": ""}])
        finally:
            os.unlink(f.name)
        with mock.patch.object(app, "PEA_POSITIONS", "/nonexistent/pea.txt"):
            self.assertIsNone(app.read_positions())


class ApiLayerTests(unittest.TestCase):
    def test_api_all_follows_every_page(self):
        pages = {1: {"data": [1, 2], "meta": {"pagination": {"total_pages": 3}}}, 2: {"data": [3], "meta": {"pagination": {"total_pages": 3}}},
                 3: {"data": [4], "meta": {"pagination": {"total_pages": 3}}}}
        with mock.patch.object(app, "api", lambda path, params=None: pages[params["page"]]):
            self.assertEqual(app.api_all("/things"), [1, 2, 3, 4])

    def test_searches_read_every_page(self):
        def tx(id):
            return {"transaction_journal_id": id, "date": "2026-10-05T00:00:00+01:00", "type": "withdrawal", "description": "d", "amount": "1",
                    "category_name": None, "budget_name": None, "source_id": "1", "source_name": "s", "destination_id": "9", "destination_name": "d", "notes": None, "bill_name": None}
        pages = {1: {"data": [{"id": "g", "attributes": {"transactions": [tx(1)]}}], "meta": {"pagination": {"total_pages": 2}}},
                 2: {"data": [{"id": "g", "attributes": {"transactions": [tx(2)]}}], "meta": {"pagination": {"total_pages": 2}}}}
        with mock.patch.object(app, "api", lambda path, params=None: pages[params["page"]]), \
             mock.patch.object(app, "api_all", router({"/accounts": [account("1", "Compte", 0)]})):
            self.assertEqual([t["id"] for t in app.month_transactions("2026-10")], [2, 1])
            self.assertEqual(app.expense_tree("2026-10"), {"Sans budget": {app.UNCATEGORISED: 2.0}})

    def fail_with(self, code, payload):
        error = urllib.error.HTTPError("http://x", code, "err", {}, None)
        error.read = lambda: payload
        return mock.patch.object(app.urllib.request, "urlopen", mock.Mock(side_effect=error))

    def test_api_write_turns_firefly_validation_errors_into_messages(self):
        body = json.dumps({"message": "The given data was invalid.", "errors": {"name": ["Name is taken."], "amount": ["Too big.", "Too odd."]}}).encode()
        with self.fail_with(422, body), self.assertRaises(ValueError) as ctx:
            app.api_write("POST", "/piggy-banks", {})
        self.assertEqual(str(ctx.exception), "Name is taken. Too big. Too odd.")
        with self.fail_with(400, json.dumps({"message": "Nope"}).encode()), self.assertRaises(ValueError) as ctx:
            app.api_write("PUT", "/piggy-banks/1", {})
        self.assertEqual(str(ctx.exception), "Nope")
        with self.fail_with(500, b"<html>oops</html>"), self.assertRaises(ValueError) as ctx:
            app.api_write("DELETE", "/piggy-banks/1")
        self.assertEqual(str(ctx.exception), "Firefly III answered 500")

    def test_api_write_returns_the_json_answer_or_none(self):
        class Reply:
            def __init__(self, data): self.data = data
            def read(self): return self.data
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with mock.patch.object(app.urllib.request, "urlopen", return_value=Reply(b'{"a": 1}')):
            self.assertEqual(app.api_write("POST", "/x", {}), {"a": 1})
        with mock.patch.object(app.urllib.request, "urlopen", return_value=Reply(b"")):
            self.assertIsNone(app.api_write("DELETE", "/x"))


class CacheTests(unittest.TestCase):
    def test_hit_within_ttl_then_remake(self):
        cache, calls = app.Cache(60), []
        make = lambda: calls.append(1) or len(calls)
        self.assertEqual(cache.get("k", make), 1)
        self.assertEqual(cache.get("k", make), 1)
        cache.ttl = 0
        self.assertEqual(cache.get("k", make), 2)

    def test_concurrent_loads_share_one_call(self):
        cache, calls, release = app.Cache(60), [], threading.Event()

        def slow():
            calls.append(1); release.wait(2); return "v"
        results = []
        threads = [threading.Thread(target=lambda: results.append(cache.get("k", slow))) for _ in range(5)]
        for t in threads: t.start()
        time.sleep(0.2); release.set()
        for t in threads: t.join(3)
        self.assertEqual(results, ["v"] * 5)
        self.assertEqual(len(calls), 1)

    def test_a_slow_key_does_not_block_another_key(self):
        cache, release = app.Cache(60), threading.Event()
        threading.Thread(target=lambda: cache.get("slow", lambda: release.wait(3)), daemon=True).start()
        time.sleep(0.1)
        start = time.time()
        self.assertEqual(cache.get("fast", lambda: "ok"), "ok")
        self.assertLess(time.time() - start, 1)
        release.set()

    def test_stale_value_is_served_when_the_refresh_fails(self):
        cache = app.Cache(0)
        cache.get("k", lambda: "old")
        def boom(): raise urllib.error.URLError("down")
        self.assertEqual(cache.get("k", boom), "old")

    def test_failure_without_a_stale_value_propagates_and_is_not_cached(self):
        cache = app.Cache(60)
        with self.assertRaises(ValueError):
            cache.get("k", lambda: (_ for _ in ()).throw(ValueError("x")))
        self.assertEqual(cache.get("k", lambda: "now"), "now")

    def test_expire_all_keeps_a_fallback_and_drop_removes(self):
        cache, calls = app.Cache(60), []
        cache.get("a", lambda: calls.append(1) or "one")
        cache.expire_all()
        self.assertEqual(cache.get("a", lambda: "two"), "two")        # stale: rebuilt
        cache.expire_all()
        def boom(): raise RuntimeError
        self.assertEqual(cache.get("a", boom), "two")                 # but kept as fallback
        cache.drop("a")
        with self.assertRaises(RuntimeError):
            cache.get("a", boom)


class FigureTests(unittest.TestCase):
    def test_net_worth_groups_accounts(self):
        assets = [account("1", "Compte courant", 100, "defaultAsset"), account("2", "Livret A", 4000, "savingAsset"),
                  account("3", "PEA Bourse", 500.5, "defaultAsset"), account("4", "Dette papa", -300, "defaultAsset"),
                  account("5", "Fermé", 999, active=False), account("6", "Hors total", 999, include=False)]
        debts = [account("7", "Prêt", -50, kind="liabilities")]
        with mock.patch.object(app, "api_all", lambda path, params=None: debts if params["type"] == "liabilities" else assets):
            nw = app.net_worth_at("2026-10-31")
        self.assertEqual((nw["courant"], nw["epargne"], nw["investissements"], nw["dettes"]), (100, 4000, 500.5, -350))
        self.assertEqual(nw["total"], 4250.5)
        self.assertEqual(sorted(a["name"] for a in nw["accounts"]), ["Compte courant", "Dette papa", "Livret A", "PEA Bourse", "Prêt"])

    def test_by_category_uses_positive_amounts_and_the_uncategorised_rest(self):
        rows = {"expense/category": [{"name": "Courses", "difference": "-120.5"}, {"name": "Zero", "difference": "0"}],
                "expense/no-category": [{"difference": "-30"}]}
        with mock.patch.object(app, "insight", lambda path, start, end, ids: rows[path]):
            got = app.by_category("expense", "2026-10-01", "2026-10-31", ["1"])
        self.assertEqual(got, {"Courses": 120.5, app.UNCATEGORISED: 30.0})

    def test_bills_data(self):
        bills = [{"attributes": {"name": "Claude", "active": True, "amount_min": "20", "amount_max": "25", "repeat_freq": "monthly",
                                 "pay_dates": ["2026-11-21T00:00:00+01:00", "2026-12-21T00:00:00+01:00", "2025-01-01T00:00:00+01:00"]}},
                 {"attributes": {"name": "Old", "active": False, "amount_min": "1", "amount_max": "1", "repeat_freq": "monthly", "pay_dates": []}}]
        piggies = [{"attributes": {"name": "Voyage", "active": True, "current_amount": "10", "target_amount": "100", "target_date": "2027-01-31T00:00:00+01:00"}},
                   {"attributes": {"name": "Off", "active": False, "current_amount": "0", "target_amount": "1", "target_date": None}}]
        with mock.patch.object(app, "dt", FAKE_DT), mock.patch.object(app, "api_all", router({"/bills": bills, "/piggy-banks": piggies})):
            got = app.bills_data()
        self.assertEqual([b["name"] for b in got["bills"]], ["Claude"])
        self.assertEqual(got["bills"][0]["amount"], 22.5)
        self.assertEqual([(u["date"], u["amount"]) for u in got["upcoming"]], [("2026-11-21", 22.5), ("2026-12-21", 22.5)])
        self.assertEqual(got["piggies"], [{"name": "Voyage", "current": 10.0, "target": 100.0, "date": "2027-01-31"}])

    def test_month_transactions_filters_and_sorts(self):
        def t(id, date, kind, src, dst, cat="Courses", amount="10"):
            return {"transaction_journal_id": id, "date": date + "T10:00:00+01:00", "type": kind, "description": f"t{id}", "amount": amount,
                    "category_name": cat, "budget_name": None, "source_id": src, "source_name": "s", "destination_id": dst, "destination_name": "d", "notes": None, "bill_name": None}
        found = [t(1, "2026-10-05", "withdrawal", "1", "99"), t(2, "2026-10-09", "deposit", "99", "1"),
                 t(3, "2026-10-07", "withdrawal", "5", "99"),                  # from the PEA: not everyday
                 t(4, "2026-10-08", "withdrawal", "1", "99", cat="Valorisation"),
                 t(5, "2026-09-30", "withdrawal", "1", "99"),                  # outside the month
                 t(6, "2026-10-31", "transfer", "99", "1")]
        body = {"data": [{"id": "77", "attributes": {"transactions": found}}], "meta": {"pagination": {"total_pages": 1}}}
        with mock.patch.object(app, "api", lambda path, params=None: body), \
             mock.patch.object(app, "api_all", router({"/accounts": [account("1", "Compte", 0), account("5", "PEA Bourse", 0)]})):
            got = app.month_transactions("2026-10")
        self.assertEqual([x["id"] for x in got], [6, 2, 1])
        self.assertEqual(got[0]["date"], "2026-10-31")

    def test_expense_tree_groups_by_budget_then_category(self):
        def t(cat, budget, amount, src="1"):
            return {"date": "2026-10-10T00:00:00+01:00", "source_id": src, "category_name": cat, "budget_name": budget, "amount": amount}
        body = {"data": [{"attributes": {"transactions": [t("Courses", "Vie courante", "10"), t("Courses", "Vie courante", "5.5"),
                                                          t("Cinéma", "Loisirs", "8"), t(None, None, "3"), t("Valorisation", None, "99"), t("X", "Y", "50", src="5")]}}],
                "meta": {"pagination": {"total_pages": 1}}}
        with mock.patch.object(app, "api", lambda path, params=None: body), \
             mock.patch.object(app, "api_all", router({"/accounts": [account("1", "Compte", 0), account("5", "PEA Bourse", 0)]})):
            tree = app.expense_tree("2026-10")
        self.assertEqual(tree, {"Vie courante": {"Courses": 15.5}, "Loisirs": {"Cinéma": 8.0}, "Sans budget": {app.UNCATEGORISED: 3.0}})

    def test_pea_data_contributions_and_positions(self):
        pea = account("5", "PEA Bourse", 1000)
        def tx(date, src, dst, amount, cat=None):
            return {"attributes": {"transactions": [{"date": date + "T00:00:00+01:00", "source_id": src, "destination_id": dst, "amount": amount, "category_name": cat}]}}
        history = [tx("2026-08-10", "1", "5", "300"), tx("2026-08-20", "1", "5", "100"), tx("2026-09-05", "5", "1", "50"),
                   tx("2026-09-30", "9", "5", "40", cat="Valorisation"), tx("2026-10-02", "7", "8", "999")]
        quotes = {"CW8.PA": {"price": 100.0, "previous": 98.0}}
        positions = [{"symbol": "CW8.PA", "quantity": 2.0, "label": "ETF"}, {"symbol": "especes", "quantity": 3.2, "label": ""},
                     {"symbol": "NOPE.PA", "quantity": 1.0, "label": ""}]
        with mock.patch.object(app, "api_all", router({"/accounts": [pea, account("1", "Compte", 0)], "/accounts/5/transactions": history})), \
             mock.patch.object(app, "read_positions", lambda: positions), mock.patch.object(app, "yahoo_quote", lambda s: quotes.get(s)):
            d = app.pea_data()
        self.assertEqual(d["contributions"], {"2026-08": 400.0, "2026-09": -50.0})
        self.assertEqual(d["invested"], 350.0)
        self.assertEqual(d["cash"], 3.2)
        cw8 = d["positions"][0]
        self.assertEqual((cw8["value"], cw8["day"]), (200.0, 2.04))
        self.assertIsNone(d["positions"][1]["price"]); self.assertIsNone(d["positions"][1]["value"])

    def test_pea_data_without_a_positions_file_counts_the_balance_as_cash(self):
        with mock.patch.object(app, "api_all", router({"/accounts": [account("5", "PEA Bourse", 123.4)], "/accounts/5/transactions": []})), \
             mock.patch.object(app, "read_positions", lambda: None):
            d = app.pea_data()
        self.assertFalse(d["has_file"]); self.assertEqual(d["cash"], 123.4)


class GoalsTests(unittest.TestCase):
    def piggy(self, id, name, current, target, deadline=None, account="Livret A"):
        return {"id": id, "attributes": {"name": name, "active": True, "current_amount": str(current), "target_amount": str(target),
                                         "target_date": deadline, "accounts": [{"name": account, "current_amount": str(current)}]}}

    def run_goals(self, piggies, events, file_goals=(), now_balance=2000, before_balance=1000):
        def accounts(path, params):
            return [account("1", "Livret A", before_balance if params and params.get("date") else now_balance)]
        routes = {"/accounts": accounts, "/piggy-banks": piggies}
        routes.update({f"/piggy-banks/{p['id']}/events": events.get(p["id"], []) for p in piggies})
        with mock.patch.object(app, "dt", FAKE_DT), mock.patch.object(app, "api_all", router(routes)), \
             mock.patch.object(app, "read_goal_file", lambda: list(file_goals)):
            return app.goals_data()

    def by_name(self, data):
        return {g["name"]: g for g in data["goals"]}

    def test_statuses_pace_eta_and_needed_monthly(self):
        recent = [{"attributes": {"amount": "300", "created_at": "2026-10-01T00:00:00+01:00"}}]
        old = [{"attributes": {"amount": "5000", "created_at": "2026-01-01T00:00:00+01:00"}}]   # before the window: no pace
        piggies = [self.piggy("1", "Fini", 100, 100), self.piggy("2", "Bien parti", 400, 1000, "2027-12-31"),
                   self.piggy("3", "En retard", 400, 1000, "2027-01-31"), self.piggy("4", "Immobile", 50, 500, "2027-06-30")]
        goals = self.by_name(self.run_goals(piggies, {"2": recent, "3": recent, "4": old}))
        self.assertEqual(goals["Fini"]["status"], "reached"); self.assertEqual(goals["Fini"]["remaining"], 0)
        self.assertEqual(goals["Bien parti"]["status"], "on_track"); self.assertTrue(goals["Bien parti"]["eta"].startswith("2027-04"))
        self.assertGreater(goals["Bien parti"]["pace"], 100)
        self.assertEqual(goals["En retard"]["status"], "late")
        self.assertAlmostEqual(goals["En retard"]["needed_monthly"], 600 / (((datetime.date(2027, 1, 31) - TODAY).days) / 30.44), places=1)
        self.assertEqual(goals["Immobile"]["status"], "stalled"); self.assertNotIn("eta", goals["Immobile"])

    def test_free_money_excludes_what_other_piggy_banks_hold(self):
        data = self.run_goals([self.piggy("1", "A", 300, 1000), self.piggy("2", "B", 200, 1000)], {})
        self.assertEqual({a["name"]: a["free"] for a in data["accounts"]}, {"Livret A": 1500.0})
        self.assertEqual(self.by_name(data)["A"]["free"], 1500.0)

    def test_goals_file_adds_account_goals_but_never_piggy_ones_twice(self):
        file_goals = [{"name": "Apport", "account": "Livret A", "target": 5000, "date": "2027-11-17"},
                      {"name": "Fantôme", "account": "Inconnu", "target": 1},
                      {"name": "A", "piggy": "A", "target": 777}]
        data = self.run_goals([self.piggy("1", "A", 100, 1000)], {}, file_goals)
        goals = self.by_name(data)
        self.assertEqual(sorted(goals), ["A", "Apport"])
        self.assertEqual(goals["A"]["target"], 777.0, "a goal naming a piggy bank overrides its target")
        apport = goals["Apport"]
        self.assertFalse(apport["editable"]); self.assertEqual(apport["balance"], 2000.0)
        self.assertGreater(apport["pace"], 0)                    # balance grew 1000 over the window


class PiggyValidation(unittest.TestCase):
    ACCOUNTS = [account("1", "Livret A", 1000)]

    def patched(self, piggies=(), write=None):
        routes = {"/accounts": self.ACCOUNTS, "/piggy-banks": list(piggies)}
        return mock.patch.object(app, "api_all", router(routes)), mock.patch.object(app, "api_write", write or mock.Mock())

    def test_create_rejects_bad_input(self):
        good = {"name": "Voyage", "target": 500, "account": "Livret A"}
        for patch, message in [({"name": " "}, "Nom"), ({"name": "x" * 61}, "Nom"), ({"target": 0}, "Nom ou montant"),
                               ({"target": 10_000_000}, "Nom ou montant"), ({"account": "Inconnu"}, "Compte inconnu")]:
            a, w = self.patched()
            with a, w as write, self.assertRaises(ValueError, msg=str(patch)) as ctx:
                app.create_piggy({**good, **patch})
            self.assertIn(message, str(ctx.exception)); write.assert_not_called()
        a, w = self.patched([{"id": "9", "attributes": {"name": "Voyage"}}])
        with a, w, self.assertRaises(ValueError) as ctx:
            app.create_piggy(good)
        self.assertIn("déjà", str(ctx.exception))

    def test_create_sends_the_right_payload(self):
        a, w = self.patched()
        with a, w as write, mock.patch.object(app, "dt", FAKE_DT):
            app.create_piggy({"name": "Voyage", "target": "500", "account": "Livret A", "date": "2027-01-31"})
        method, path, payload = write.call_args.args
        self.assertEqual((method, path), ("POST", "/piggy-banks"))
        self.assertEqual(payload["target_amount"], "500.00"); self.assertEqual(payload["target_date"], "2027-01-31")
        self.assertEqual(payload["accounts"], [{"account_id": "1", "current_amount": "0"}]); self.assertEqual(payload["start_date"], "2026-11-17")

    def test_update_needs_something_to_change_and_a_known_piggy(self):
        piggy = {"id": "9", "attributes": {"name": "Voyage"}}
        a, w = self.patched([piggy])
        with a, w, self.assertRaises(ValueError) as ctx:
            app.update_piggy({"name": "Voyage"})
        self.assertIn("Rien", str(ctx.exception))
        with a, w, self.assertRaises(ValueError) as ctx:
            app.update_piggy({"name": "Inconnue", "target": 5})
        self.assertIn("Aucune tirelire", str(ctx.exception))
        with a, w, self.assertRaises(ValueError):
            app.update_piggy({"name": "Voyage", "target": -1})

    def test_move_money(self):
        piggy = {"id": "9", "attributes": {"name": "Voyage", "accounts": [{"account_id": "1", "name": "Livret A", "current_amount": "50"}]}}
        a, w = self.patched([piggy])
        with a, w as write:
            app.move_piggy({"name": "Voyage", "amount": 25})
            self.assertEqual(write.call_args.args[2]["accounts"], [{"account_id": "1", "current_amount": "75.00"}])
            for bad in (0, -60, 20_000_000):
                with self.assertRaises(ValueError, msg=str(bad)):
                    app.move_piggy({"name": "Voyage", "amount": bad})
            self.assertEqual(write.call_count, 1)

    def test_move_translates_firefly_s_not_enough_money_error(self):
        piggy = {"id": "9", "attributes": {"name": "Voyage", "accounts": [{"account_id": "1", "name": "Livret A", "current_amount": "0"}]}}
        a, w = self.patched([piggy], write=mock.Mock(side_effect=ValueError("amount cannot be added")))
        with a, w, self.assertRaises(ValueError) as ctx:
            app.move_piggy({"name": "Voyage", "amount": 10})
        self.assertIn("Pas assez d'argent libre", str(ctx.exception))


class CategorizeTests(unittest.TestCase):
    TAX = {"categories": ["Courses", "Transport"], "budgets": ["Vie courante"]}

    def run_categorize(self, body, current=None, rules=()):
        current = {"transaction_journal_id": "7", "category_name": None, "type": "withdrawal", **(current or {})}
        reads = {"/transactions/3": {"data": {"attributes": {"transactions": [current]}}}}
        lists = {"/rules": [{"id": "5", "attributes": {"title": t}} for t in rules],
                 "/rule-groups": [{"id": "1", "attributes": {"title": app.RULE_GROUP}}]}
        with mock.patch.object(app, "taxonomy", return_value=self.TAX), \
                mock.patch.object(app, "api", side_effect=lambda path, *a, **k: reads[path]), \
                mock.patch.object(app, "api_all", side_effect=lambda path, *a, **k: lists[path]), \
                mock.patch.object(app, "api_write") as write:
            app.categorize({"id": 7, "group": 3, **body})
        return write

    def test_sets_category_and_budget_without_firing_rules(self):
        write = self.run_categorize({"category": "Courses", "budget": "Vie courante"})
        (method, path, payload), = [c.args for c in write.call_args_list]
        self.assertEqual((method, path), ("PUT", "/transactions/3"))
        self.assertEqual(payload["transactions"], [{"transaction_journal_id": "7", "category_name": "Courses", "budget_name": "Vie courante"}])
        self.assertFalse(payload["apply_rules"])

    def test_unknown_names_and_valuations_are_refused(self):
        for patch, message in (({"category": "Inventée"}, "Catégorie"), ({"category": "Courses", "budget": "Zzz"}, "Budget")):
            with self.assertRaises(ValueError) as ctx:
                self.run_categorize(patch)
            self.assertIn(message, str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            self.run_categorize({"category": "Courses"}, {"category_name": "Valorisation"})
        self.assertIn("PEA", str(ctx.exception))

    def test_only_spending_has_a_budget(self):
        write = self.run_categorize({"category": "Courses", "budget": "Vie courante"}, {"type": "deposit"})
        self.assertEqual(write.call_args.args[2]["transactions"][0]["budget_name"], "")

    def test_a_rule_is_created_or_replaced(self):
        write = self.run_categorize({"category": "Courses", "budget": "Vie courante", "rule": "Carrefour"})
        method, path, rule = write.call_args.args
        self.assertEqual((method, path, rule["title"]), ("POST", "/rules", "Carrefour → Courses"))
        self.assertEqual([a["type"] for a in rule["actions"]], ["set_category", "set_budget"])
        self.assertEqual(rule["triggers"][0], {**rule["triggers"][0], "type": "description_contains", "value": "Carrefour"})
        again = self.run_categorize({"category": "Courses", "rule": "Carrefour"}, rules=["Carrefour → Courses"])
        self.assertEqual(again.call_args.args[:2], ("PUT", "/rules/5"))
        with self.assertRaises(ValueError):
            self.run_categorize({"category": "Courses", "rule": "ab"})


class AlertsTests(unittest.TestCase):
    TODAY = datetime.date(2026, 11, 17)

    @staticmethod
    def tx(i, date, amount, cat="Courses", bill=None, kind="withdrawal"):
        return {"id": i, "date": date, "type": kind, "amount": amount, "category": cat, "bill": bill, "description": f"t{i}"}

    def history(self, current):
        tx = self.tx
        return {"2026-09": [tx(1, "2026-09-03", 20), tx(2, "2026-09-10", 25), tx(3, "2026-09-12", 22, bill="Netflix")],
                "2026-10": [tx(4, "2026-10-03", 18), tx(5, "2026-10-12", 22, bill="Netflix")], "2026-11": current}

    def test_an_expense_far_above_the_usual_is_flagged_only_when_recent(self):
        tx = self.tx
        got = app.alerts_from(self.history([tx(6, "2026-11-10", 120), tx(7, "2026-11-01", 900), tx(8, "2026-11-12", 40)]), self.TODAY)
        self.assertEqual([(u["description"], u["usual"]) for u in got["unusual"]], [("t6", 22.0)])

    def test_few_samples_or_small_amounts_are_not_unusual(self):
        tx = self.tx
        self.assertEqual(app.alerts_from({"2026-11": [tx(1, "2026-11-10", 400)]}, self.TODAY)["unusual"], [])
        self.assertEqual(app.alerts_from(self.history([tx(6, "2026-11-10", 49)]), self.TODAY)["unusual"], [])

    def test_a_subscription_price_change_shows_for_a_while(self):
        got = app.alerts_from(self.history([self.tx(8, "2026-11-14", 30, bill="Netflix")]), self.TODAY)
        self.assertEqual(got["price_changes"], [{"name": "Netflix", "before": 22, "now": 30, "date": "2026-11-14"}])
        same = app.alerts_from(self.history([self.tx(8, "2026-11-14", 22.1, bill="Netflix")]), self.TODAY)
        self.assertEqual(same["price_changes"], [])
        old = app.alerts_from(self.history([]), self.TODAY)  # the change of October is over by now
        self.assertEqual(old["price_changes"], [])

    def test_uncategorised_counts_spending_and_income_but_not_transfers(self):
        tx = self.tx
        got = app.alerts_from(self.history([tx(7, "2026-11-12", 14, cat=None), tx(8, "2026-11-13", 6.5, cat=None, kind="deposit"),
                                             tx(9, "2026-11-15", 500, cat=None, kind="transfer")]), self.TODAY)
        self.assertEqual(got["uncategorised"], {"count": 2, "amount": 20.5, "month": "2026-11"})
        self.assertEqual(app.alerts_from(self.history([]), self.TODAY)["uncategorised"], {"count": 0, "amount": 0.0, "month": None})


class HttpTests(unittest.TestCase):
    """The real Handler on a local port, the data layer faked."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()

    def setUp(self):
        patcher = mock.patch.object(app, "cache", app.Cache(300))
        patcher.start(); self.addCleanup(patcher.stop)

    def request(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        r = conn.getresponse(); data = r.read(); conn.close()
        return r, data

    def test_health_and_unknown_paths(self):
        r, body = self.request("GET", "/healthz"); self.assertEqual((r.status, body), (200, b"ok"))
        self.assertEqual(self.request("GET", "/nope")[0].status, 404)

    def test_host_header_is_checked_against_dns_rebinding(self):
        self.assertEqual(self.request("GET", "/healthz", {"Host": "evil.example"})[0].status, 403)
        self.assertEqual(self.request("GET", "/healthz", {"Host": "cairn.test:8787"})[0].status, 200)
        self.assertEqual(self.request("GET", "/healthz", {"Host": "localhost"})[0].status, 200)

    def test_security_headers_on_every_answer(self):
        r, _ = self.request("GET", "/healthz")
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertEqual(r.getheader("Referrer-Policy"), "no-referrer")

    def test_page_is_gzipped_with_an_etag_and_revalidates(self):
        r, raw = self.request("GET", "/", {"Accept-Encoding": "gzip"})
        self.assertEqual(r.status, 200); self.assertEqual(r.getheader("Content-Encoding"), "gzip")
        self.assertIn(b"<title>Cairn</title>", gzip.decompress(raw))
        etag = r.getheader("ETag"); self.assertTrue(etag)
        self.assertEqual(r.getheader("Cache-Control"), "no-cache")
        r2, body2 = self.request("GET", "/", {"If-None-Match": etag})
        self.assertEqual((r2.status, body2), (304, b""))
        r3, plain = self.request("GET", "/")
        self.assertIsNone(r3.getheader("Content-Encoding")); self.assertIn(b"<title>Cairn</title>", plain)

    def test_modules_are_served_but_nothing_else_under_js(self):
        r, body = self.request("GET", "/js/main.js")
        self.assertEqual(r.status, 200); self.assertIn("javascript", r.getheader("Content-Type")); self.assertIn(b"import", body)
        for path in ("/js/package.json", "/js/missing.js", "/js/../app.py", "/js/%2e%2e/app.py", "/js/Main.js", "/js/", "/static/js/main.js", "/app.js"):
            self.assertEqual(self.request("GET", path)[0].status, 404, path)

    def test_every_module_imported_by_the_page_exists(self):
        import re
        base = os.path.join(app.HERE, "static", "js")
        for name in os.listdir(base):
            if not name.endswith(".js"): continue
            with open(os.path.join(base, name), encoding="utf-8") as f:
                imported = re.findall(r"from '\./([\w-]+\.js)'", f.read())
            for target in imported:
                self.assertTrue(os.path.isfile(os.path.join(base, target)), f"{name} imports missing {target}")

    def test_service_worker_precaches_exactly_the_modules(self):
        import re
        with open(os.path.join(app.HERE, "static", "sw.js"), encoding="utf-8") as f:
            listed = set(re.search(r"const MODULES = \[(.*?)\]", f.read()).group(1).replace("'", "").replace(" ", "").split(","))
        on_disk = {n[:-3] for n in os.listdir(os.path.join(app.HERE, "static", "js")) if n.endswith(".js")}
        self.assertEqual(listed, on_disk, "update MODULES in static/sw.js when a module is added or removed")

    def test_head_has_no_body(self):
        r, body = self.request("HEAD", "/healthz"); self.assertEqual((r.status, body), (200, b""))

    def test_api_data_is_cached_and_refresh_rebuilds(self):
        with mock.patch.object(app, "build", mock.Mock(side_effect=lambda m: {"months": m, "n": time.time()})) as build:
            a = json.loads(self.request("GET", "/api/data?months=24")[1]); b = json.loads(self.request("GET", "/api/data?months=24")[1])
            self.assertEqual(a, b); self.assertEqual(build.call_count, 1)
            self.request("GET", "/api/data?months=24&refresh=1")
            self.assertEqual(build.call_count, 2)
            self.assertEqual(json.loads(self.request("GET", "/api/data?months=999")[1])["months"], app.MAX_MONTHS, "months is clamped")
            self.assertEqual(json.loads(self.request("GET", "/api/data?months=0")[1])["months"], 1)

    def test_refresh_serves_the_last_figures_if_firefly_is_down(self):
        with mock.patch.object(app, "build", mock.Mock(return_value={"ok": 1})):
            self.request("GET", "/api/data?months=24")
        with mock.patch.object(app, "build", mock.Mock(side_effect=urllib.error.URLError("down"))):
            r, body = self.request("GET", "/api/data?months=24&refresh=1")
        self.assertEqual((r.status, json.loads(body)), (200, {"ok": 1}))

    def test_errors_become_json_without_leaking_internals(self):
        with mock.patch.object(app, "bills_data", mock.Mock(side_effect=urllib.error.URLError("refused"))):
            r, body = self.request("GET", "/api/bills")
        self.assertEqual(r.status, 502); self.assertIn("error", json.loads(body))
        app.cache = app.Cache(300)
        with mock.patch.object(app, "bills_data", mock.Mock(side_effect=RuntimeError("secret token abc"))), mock.patch("builtins.print"):
            r, body = self.request("GET", "/api/bills")
        self.assertEqual(r.status, 500); self.assertNotIn(b"secret", body); self.assertEqual(json.loads(body), {"error": "Erreur interne"})

    def test_bad_month_is_a_502_not_a_crash(self):
        for path in ("/api/flow?month=zz", "/api/transactions?month=", "/api/budgets?month=2026-13"):
            self.assertEqual(self.request("GET", path)[0].status, 502, path)

    POST_HEADERS = {"Content-Type": "application/json", "X-Requested-With": "dashboard"}

    def post(self, body, headers=None, path="/api/piggy"):
        return self.request("POST", path, {**self.POST_HEADERS, **(headers or {})}, body if isinstance(body, (bytes, str)) else json.dumps(body))

    def test_post_needs_the_custom_header_json_and_a_same_site_origin(self):
        with mock.patch.object(app, "create_piggy") as create:
            self.assertEqual(self.post({"action": "create"}, {"X-Requested-With": "other"})[0].status, 400)
            self.assertEqual(self.post({"action": "create"}, {"Content-Type": "text/plain"})[0].status, 400)
            self.assertEqual(self.post({"action": "create"}, {"Origin": "https://evil.example"})[0].status, 403)
            self.assertEqual(self.post({"action": "create"}, {"Host": "evil.example"})[0].status, 403)
            create.assert_not_called()
            self.assertEqual(self.post({"action": "create"}, {"Origin": "http://cairn.test:8787"})[0].status, 200)
            create.assert_called_once()

    def test_post_validates_the_body(self):
        self.assertEqual(self.post(b"not json")[0].status, 400)
        self.assertEqual(self.post({"action": "drop-everything"})[0].status, 400)
        self.assertEqual(self.post(json.dumps({"action": "create", "pad": "x" * 5000}))[0].status, 400, "body size is capped")
        self.assertEqual(self.post({"action": "create"}, path="/api/other")[0].status, 404)

    def test_post_returns_the_validation_message_and_refreshes_goals(self):
        with mock.patch.object(app, "goals_data", mock.Mock(side_effect=lambda: {"n": time.time()})) as goals:
            self.request("GET", "/api/goals"); self.request("GET", "/api/goals"); self.assertEqual(goals.call_count, 1)
            with mock.patch.object(app, "move_piggy", mock.Mock(side_effect=ValueError("Montant invalide"))):
                r, body = self.post({"action": "move"})
            self.assertEqual((r.status, json.loads(body)), (400, {"error": "Montant invalide"}))
            self.assertEqual(goals.call_count, 1, "a failed write keeps the cache")
            with mock.patch.object(app, "move_piggy"):
                self.assertEqual(self.post({"action": "move"})[0].status, 200)
            self.request("GET", "/api/goals"); self.assertEqual(goals.call_count, 2, "a successful write drops the goals cache")

    def test_categorize_route_expires_every_cache(self):
        with mock.patch.object(app, "categorize") as cat, mock.patch.object(app, "bills_data", mock.Mock(side_effect=lambda: {"n": time.time()})) as bills:
            self.request("GET", "/api/bills")
            self.assertEqual(self.post({"action": "categorize"}, path="/api/transaction")[0].status, 200)
            cat.assert_called_once()
            self.request("GET", "/api/bills"); self.assertEqual(bills.call_count, 2)
        self.assertEqual(self.post({"action": "create"}, path="/api/transaction")[0].status, 400)

    def test_post_unexpected_error_is_a_500(self):
        with mock.patch.object(app, "delete_piggy", mock.Mock(side_effect=RuntimeError("boom"))), mock.patch("builtins.print"):
            r, body = self.post({"action": "delete"})
        self.assertEqual(r.status, 500); self.assertNotIn(b"boom", body)


if __name__ == "__main__":
    unittest.main()
