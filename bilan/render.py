"""Builds the review e-mail from the month's facts and Claude's comments.

render.py FACTS.json COMMENTS.json OUT.html OUT.txt. The HTML only uses tables and inline styles,
the way e-mail clients (Gmail included) expect; the text version is the e-mail's fallback.
"""

import datetime as dt
import json
import sys
from html import escape

MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]
SHORT_MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.",
                "nov.", "déc."]

# Light theme only: e-mail clients ignore or rewrite dark-mode styles.
PAGE, CARD, INK, INK_2, MUTED = "#f9f9f7", "#ffffff", "#0b0b0b", "#52514e", "#898781"
HAIRLINE, TRACK, BAR = "#e1e0d9", "#efeee9", "#2a78d6"
GOOD, WARNING, CRITICAL, GOOD_TEXT = "#0ca30c", "#fab219", "#d03b3b", "#006300"
FONT = "system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif"
GROUPS = {"courant": "Comptes courants", "epargne": "Épargne", "investissements": "PEA",
          "dettes": "Dettes familiales"}


def eur(value: float, sign: bool = False) -> str:
    text = f"{abs(value):,.2f}".replace(",", " ").replace(".", ",") + " €"
    if value < 0:
        return "−" + text
    return ("+" + text) if sign and value > 0 else text


def pct(rate: float) -> str:
    return f"{rate * 100:.2f}".rstrip("0").rstrip(".").replace(".", ",") + "\u00a0%"


def month_name(month: str, short: bool = False) -> str:
    year, number = map(int, month.split("-"))
    return (SHORT_MONTHS if short else MONTHS)[number - 1] + ("" if short else f" {year}")


def day(date: str) -> str:
    return dt.date.fromisoformat(date).strftime("%d/%m")


def section(title: str, body: str) -> str:
    return f"""
<tr><td style="padding:28px 0 10px;font-size:13px;font-weight:600;letter-spacing:.06em;
text-transform:uppercase;color:{MUTED}">{escape(title)}</td></tr>
<tr><td style="background:{CARD};border:1px solid {HAIRLINE};border-radius:12px;padding:18px 20px">
{body}</td></tr>"""


def bullets(items: list[str]) -> str:
    return "".join(
        f'<p style="margin:0 0 10px;font-size:15px;line-height:1.5;color:{INK}">'
        f'<span style="color:{MUTED}">•&nbsp;</span>{escape(i)}</p>' for i in items
    )


def bar(fraction: float, color: str) -> str:
    width = max(0, min(100, round(fraction * 100)))
    fill = (f'<td width="{width}%" style="background:{color};height:8px;border-radius:4px;'
            f'font-size:0;line-height:0">&nbsp;</td>') if width else ""
    rest = f'<td style="font-size:0;line-height:0">&nbsp;</td>' if width < 100 else ""
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:{TRACK};border-radius:4px"><tr>{fill}{rest}</tr></table>')


def table(rows: list[list[str]], align: list[str]) -> str:
    out = []
    for i, row in enumerate(rows):
        border = f"border-top:1px solid {HAIRLINE};" if i else ""
        cells = "".join(
            f'<td align="{a}" style="{border}padding:8px 0 8px {0 if j == 0 else 12}px;font-size:14px;'
            f'color:{INK if j == 0 else INK_2};vertical-align:top;'
            f'{"white-space:nowrap;font-variant-numeric:tabular-nums;" if a == "right" else ""}">{c}</td>'
            for j, (c, a) in enumerate(zip(row, align))
        )
        out.append(f"<tr>{cells}</tr>")
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(out)}</table>'


def tile(label: str, value: str, note: str, note_color: str = MUTED) -> str:
    return f"""<td width="50%" style="padding:6px;vertical-align:top">
<div style="background:{CARD};border:1px solid {HAIRLINE};border-radius:12px;padding:14px 16px">
<div style="font-size:13px;color:{INK_2}">{escape(label)}</div>
<div style="font-size:24px;font-weight:600;color:{INK};padding:4px 0 2px;white-space:nowrap">{value}</div>
<div style="font-size:13px;color:{note_color}">{note}</div></div></td>"""


def kpis(f: dict) -> str:
    rate = f"{round(100 * f['saved'] / f['earned'])} % de tes revenus" if f["earned"] > 0 else "&nbsp;"
    change_color = GOOD_TEXT if f["net_worth_change"] >= 0 else CRITICAL
    market = f"dont PEA {eur(f['pea_market'], True)}" if f["pea_market"] else "sur le mois"
    return f"""<tr><td style="padding:14px 0 0"><table role="presentation" width="100%" cellpadding="0"
cellspacing="0" style="margin:0 -6px"><tr>
{tile("Revenus", eur(f["earned"]), "entrées du mois")}
{tile("Dépenses", eur(f["spent"]), "sorties du mois")}
</tr><tr>
{tile("Vraiment épargné", eur(f["saved"]), rate)}
{tile("Patrimoine net", eur(f["net_worth"]), f"{eur(f['net_worth_change'], True)} {market}", change_color)}
</tr></table></td></tr>"""


def categories(f: dict, comment: str) -> str:
    rows = sorted(f["categories"], key=lambda c: c["amount"], reverse=True)
    shown = [c for c in rows if c["amount"] > 0][:8]
    other = sum(c["amount"] for c in rows[len(shown):])
    if other > 0:
        shown.append({"name": "Le reste", "amount": other,
                      "average_3_months": sum(c["average_3_months"] for c in rows[len(shown):])})
    top = max((c["amount"] for c in shown), default=1) or 1
    body = []
    for c in shown:
        delta = c["amount"] - c["average_3_months"]
        trend = (f'{"▲" if delta > 0 else "▼"} {eur(abs(delta))} par rapport à la moyenne '
                 f'({eur(c["average_3_months"])})') if abs(delta) >= 1 else "comme d'habitude"
        body.append(f"""<div style="padding:0 0 14px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td style="font-size:14px;color:{INK}">{escape(c["name"])}</td>
<td align="right" style="font-size:14px;font-weight:600;color:{INK};white-space:nowrap">{eur(c["amount"])}</td>
</tr></table>
<div style="padding:5px 0 4px">{bar(c["amount"] / top, BAR)}</div>
<div style="font-size:12px;color:{MUTED}">{trend}</div></div>""")
    quiet = [c["name"] for c in rows if c["amount"] == 0]
    if quiet:
        body.append(f'<div style="font-size:12px;color:{MUTED};padding:0 0 12px">Rien ce mois-ci en '
                    f'{escape(", ".join(quiet))}.</div>')
    body.append(f'<p style="margin:4px 0 0;font-size:14px;line-height:1.5;color:{INK_2}">{escape(comment)}</p>')
    return section("Dépenses par catégorie", "".join(body))


def largest(f: dict) -> str:
    rows = [[escape(t["description"]) + f'<div style="font-size:12px;color:{MUTED}">{day(t["date"])}'
             f' · {escape(t["category"] or "sans catégorie")}</div>', eur(t["amount"])]
            for t in f["largest"]]
    return section("Plus grosses dépenses", table(rows, ["left", "right"])) if rows else ""


def budgets(f: dict) -> str:
    body = []
    for b in f["budgets"]:
        if b["amount"] > 0:
            used = -b["spent"] / b["amount"]
            status = (("✕ Dépassé", CRITICAL) if used > 1 else ("! Presque atteint", WARNING) if used >= 0.8
                      else ("✓ Dans les clous", GOOD))
            figures = f'{eur(-b["spent"])} sur {eur(b["amount"])}'
        elif b["spent"] < 0:
            used, status = 0, ("Pas de montant prévu ce mois-là", MUTED)
            figures = eur(-b["spent"])
        else:
            continue
        body.append(f"""<div style="padding:0 0 14px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td style="font-size:14px;color:{INK}">{escape(b["name"])}</td>
<td align="right" style="font-size:14px;color:{INK_2};white-space:nowrap">{figures}</td>
</tr></table>
<div style="padding:5px 0 4px">{bar(used, status[1])}</div>
<div style="font-size:12px;color:{INK_2}">{status[0]}</div></div>""")
    return section("Budgets", "".join(body)) if body else ""


def worth(f: dict) -> str:
    months = f["net_worth_by_month"]
    top = max((m["net_worth"] for m in months), default=1) or 1
    columns, labels = [], []
    for i, m in enumerate(months):
        height = max(2, round(90 * max(m["net_worth"], 0) / top))
        last = i == len(months) - 1
        columns.append(f'<td width="{100 // len(months)}%" align="center" valign="bottom" style="padding:0 5px">'
                       f'<div style="background:{BAR if last else "#9ec5f4"};height:{height}px;'
                       f'border-radius:4px 4px 0 0;font-size:0;line-height:0">&nbsp;</div></td>')
        labels.append(f'<td align="center" style="padding:6px 0 0;font-size:12px;color:{MUTED}">'
                      f'{month_name(m["month"], short=True)}</td>')
    chart = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="height:120px">'
             f'<tr>{"".join(columns)}</tr><tr><td colspan="{len(months)}" style="border-top:1px solid #c3c2b7;'
             f'font-size:0;line-height:0">&nbsp;</td></tr><tr>{"".join(labels)}</tr></table>')
    rows = [[GROUPS[g], eur(v)] for g, v in f["groups"].items() if v]
    for name, balance in f["accounts"]["dettes"].items():
        if balance:
            rows.append([f'<span style="color:{INK_2}">dont {escape(name)}</span>', eur(balance)])
    rows.append([f"<b>Patrimoine net</b>", f'<b style="color:{INK}">{eur(f["net_worth"])}</b>'])
    return section("Patrimoine net, 6 derniers mois",
                   chart + '<div style="height:16px"></div>' + table(rows, ["left", "right"]))


def to_sort(f: dict, comments: dict) -> str:
    proposed = {u["id"]: u["category"] for u in comments["uncategorised"]}
    rows = []
    for t in f["uncategorised"]:
        guess = proposed.get(t["id"])
        guess = f"→ {escape(guess)}" if guess else f'<span style="color:{MUTED}">sans catégorie, à laisser</span>'
        rows.append([escape(t["description"]) + f'<div style="font-size:12px;color:{MUTED};padding:2px 0 0">'
                     f'{day(t["date"])} · {eur(t["amount"])}</div>'
                     f'<div style="font-size:14px;color:{INK};padding:3px 0 0">{guess}</div>'])
    if not rows:
        return ""
    note = (f'<p style="margin:10px 0 0;font-size:13px;color:{MUTED}">Pour les ranger, demande-le à '
            f"l'assistant dans Claude Code.</p>")
    return section("À ranger", table(rows, ["left"]) + note)


def upcoming(f: dict) -> str:
    bills = f["upcoming_bills"]
    if not bills:
        return ""
    rows = [[escape(b["name"]) + f'<div style="font-size:12px;color:{MUTED}">{day(b["date"])}</div>', eur(b["amount"])]
            for b in bills]
    rows.append(["<b>Total</b>", f'<b style="color:{INK}">{eur(sum(b["amount"] for b in bills))}</b>'])
    return section("Prélèvements à venir", table(rows, ["left", "right"]))


def outlook(f: dict, comments: dict) -> str:
    p = f["projection"]
    a, last = p["assumptions"], p["years"][-1]
    line = (f'<p style="margin:0 0 4px;font-size:15px;line-height:1.5;color:{INK}">Au rythme actuel, '
            f'ton patrimoine net serait de <b>{eur(last["net_worth"])}</b> en {month_name(last["date"])} '
            f'(soit {eur(last["net_worth_today_eur"])} en euros d’aujourd’hui).</p>'
            f'<p style="margin:0 0 16px;font-size:12px;line-height:1.5;color:{MUTED}">Hypothèses : '
            f'{eur(a["monthly_saving"])} épargnés par mois (médiane des 12 derniers mois), '
            f'PEA à {pct(a["pea_return"])} par an, livrets à {pct(a["savings_rate"])}, '
            f'inflation {pct(a["inflation"])}.</p>')
    advice = "".join(
        f'<div style="border-left:3px solid {BAR};padding:2px 0 2px 12px;margin:0 0 14px">'
        f'<div style="font-size:15px;font-weight:600;color:{INK};padding:0 0 3px">{escape(x["title"])}</div>'
        f'<div style="font-size:14px;line-height:1.5;color:{INK_2}">{escape(x["text"])}</div></div>'
        for x in comments["advice"]
    )
    return section("Cap", line + advice)


def html(f: dict, c: dict) -> str:
    parts = [
        kpis(f),
        section("Ce qu'il faut retenir", bullets(c["highlights"])),
        categories(f, c["categories_comment"]),
        largest(f),
        budgets(f),
        worth(f),
        section("À vérifier", bullets(c["watch"])) if c["watch"] else "",
        to_sort(f, c),
        upcoming(f),
        outlook(f, c),
    ]
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<title>Bilan de {month_name(f["month"])}</title></head>
<body style="margin:0;padding:0;background:{PAGE};font-family:{FONT};color:{INK}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAGE}">
<tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px">
<tr><td style="font-size:13px;color:{MUTED}">Bilan financier</td></tr>
<tr><td style="font-size:28px;font-weight:700;color:{INK};padding:2px 0 8px">{month_name(f["month"]).capitalize()}</td></tr>
<tr><td style="font-size:16px;line-height:1.5;color:{INK_2}">{escape(c["headline"])}</td></tr>
{"".join(parts)}
<tr><td style="padding:24px 0 0;font-size:12px;line-height:1.5;color:{MUTED}">
Chiffres tirés de Firefly III, commentaires rédigés par Claude. « Vraiment épargné » est la variation
du patrimoine net hors gains et pertes du PEA, emprunts à la famille compris.</td></tr>
</table></td></tr></table></body></html>"""


def text(f: dict, c: dict) -> str:
    lines = [f"BILAN DE {month_name(f['month']).upper()}", "", c["headline"], "",
             f"Revenus : {eur(f['earned'])}", f"Dépenses : {eur(f['spent'])}",
             f"Vraiment épargné : {eur(f['saved'])}",
             f"Patrimoine net : {eur(f['net_worth'])} ({eur(f['net_worth_change'], True)})", ""]
    lines += [f"- {h}" for h in c["highlights"]] + ["", c["categories_comment"], ""]
    if c["watch"]:
        lines += ["À VÉRIFIER"] + [f"- {w}" for w in c["watch"]] + [""]
    lines += ["CONSEILS"] + [f"- {x['title']} : {x['text']}" for x in c["advice"]]
    return "\n".join(lines).replace(" ", " ").replace(" ", " ") + "\n"


def main() -> None:
    facts_path, comments_path, html_path, text_path = sys.argv[1:5]
    with open(facts_path, encoding="utf-8") as fp:
        facts = json.load(fp)
    with open(comments_path, encoding="utf-8") as fp:
        comments = json.load(fp)
    with open(html_path, "w", encoding="utf-8") as fp:
        fp.write(html(facts, comments))
    with open(text_path, "w", encoding="utf-8") as fp:
        fp.write(text(facts, comments))


if __name__ == "__main__":
    main()
