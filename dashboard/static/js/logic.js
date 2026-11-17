/* Pure logic of the dashboard: no DOM, no fetch, no shared state. Everything the pages decide
   (projections, alerts, insights, comparisons, sorting, CSV) is computed here from plain data,
   so it can be tested on its own (see dashboard/tests/js). */
import { avg, eur, eur2, mlabel } from './format.js';

export const INFLATION = 0.02;
export const PER_MONTH = { monthly: 1, yearly: 1 / 12, weekly: 52 / 12, quarterly: 1 / 3, 'half-year': 1 / 6 };
export const ORDER = ['weekly', 'monthly', 'quarterly', 'half-year', 'yearly'];
const DAY = 864e5;
const frDay = iso => new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'long' }).format(new Date(iso + 'T12:00:00'));

/** Net worth month by month: savings S per month, `share` of it paid into the PEA, yearly yields
 *  rc (savings accounts) and rp (PEA). Returns [{nw, paid}] for months 0..years*12. */
export function project(S, share, rc, rp, years, cash0, pea0, debts, infl = false) {
  const mc = Math.pow(1 + rc / 100, 1 / 12) - 1, mp = Math.pow(1 + rp / 100, 1 / 12) - 1;
  const out = [{ nw: cash0 + pea0 + debts, paid: 0 }];
  let c = cash0, p = pea0, paid = 0;
  for (let i = 1; i <= years * 12; i++) {
    c = c * (1 + mc) + S * (1 - share); p = p * (1 + mp) + S * share; paid += S;
    let nw = c + p + debts;
    if (infl) nw /= Math.pow(1 + INFLATION, i / 12);
    out.push({ nw, paid });
  }
  return out;
}

/** Cash and savings against the average spending of the last 3 complete months. */
export function runway(months) {
  const spend = avg(months.slice(-4, -1).map(m => m.spent));
  const last = months[months.length - 1].net_worth, liquid = last.courant + last.epargne;
  return { spend, liquid, months: spend > 0 ? liquid / spend : null };
}

export const billCost = b => b.amount * (PER_MONTH[b.frequency] || 1);

/** Subscriptions by cost (default), name, or frequency then cost. */
export function sortBills(bills, mode) {
  const by = mode === 'name' ? (a, b) => a.name.localeCompare(b.name, 'fr')
    : mode === 'freq' ? (a, b) => ORDER.indexOf(a.frequency) - ORDER.indexOf(b.frequency) || billCost(b) - billCost(a)
    : (a, b) => billCost(b) - billCost(a);
  return [...bills].sort(by);
}

/** Alerts of the overview as {items: [[emoji, tone, title, text]], budgetCount}. `budgets` is the
 *  current month's budgets and `bills` the upcoming payments (either may be null when unavailable). */
export function computeAlerts({ budgets, bills, months, now }) {
  const out = [];
  let budgetCount = 0;
  if (budgets) {
    const day = now.getDate(), dim = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
    budgets.filter(x => x.limit).forEach(x => {
      const pct = x.spent / x.limit * 100, proj = day >= 7 ? x.spent / day * dim : 0;
      if (pct >= 100) out.push(['🚨', 'down', `${x.name} : budget dépassé`, `Dépassé de ${eur(x.spent - x.limit)} (${eur(x.spent)} sur ${eur(x.limit)}).`, 2]);
      else if (pct >= 80) out.push(['⚠️', 'warn', `${x.name} : ${Math.round(pct)} % du budget utilisé`, `Il reste ${eur(x.limit - x.spent)} pour ${dim - day} jour${dim - day > 1 ? 's' : ''}.`, 1]);
      else if (pct >= 50 && proj > x.limit * 1.1) out.push(['📈', 'warn', `${x.name} : rythme trop rapide`, `À ce rythme, le budget serait dépassé d'environ ${eur(proj - x.limit)} d'ici la fin du mois.`, 0]);
    });
    budgetCount = out.length;
    out.sort((p, q) => q[4] - p[4]);
  }
  if (bills) {
    const today = new Date(now); today.setHours(12, 0, 0, 0);
    const inDays = u => Math.round((new Date(u.date + 'T12:00:00') - today) / DAY);
    bills.upcoming.filter(u => inDays(u) >= 0 && inDays(u) <= 3).forEach(u => {
      const n = inDays(u);
      out.push(['📅', '', `${u.name} : ${eur2(u.amount)}`, n === 0 ? "Prélèvement prévu aujourd'hui." : n === 1 ? 'Prélèvement prévu demain.' : `Prélèvement prévu dans ${n} jours.`, 0]);
    });
  }
  const { spend, months: rw } = runway(months);
  if (rw !== null && rw < 3) {
    const m = rw.toFixed(1).replace('.', ',');
    out.push(['🛟', rw < 1 ? 'down' : 'warn', `Autonomie : ${m} mois`, `Tes liquidités couvrent ${m} mois de dépenses (${eur(spend)}/mois). Les experts recommandent au moins 3 mois.`, 1]);
  }
  return { items: out.map(a => a.slice(0, 4)), budgetCount };
}

/** Alerts computed by the server (/api/alerts): unusual expenses, subscription price changes and
 *  transactions without a category. Items are [emoji, tone, title, text, link], where link says
 *  where a click leads: {month, cat?, q?} for the Transactions page. */
export function extraAlerts(data) {
  if (!data) return [];
  const out = [], m = data.uncategorised;
  (data.unusual || []).forEach(u => out.push(['🔍', 'warn', `Dépense inhabituelle : ${eur2(u.amount)}`,
    `${u.description.length > 48 ? u.description.slice(0, 47) + '…' : u.description} (${u.category}) : d'habitude environ ${eur(u.usual)}.`,
    { month: u.date.slice(0, 7), cat: u.category }]));
  (data.price_changes || []).forEach(c => out.push(['🏷️', c.now > c.before ? 'warn' : '', `${c.name} : ${c.now > c.before ? 'hausse' : 'baisse'} de prix`,
    `Dernier prélèvement ${eur2(c.now)} contre ${eur2(c.before)} le précédent.`, { month: c.date.slice(0, 7), q: c.name }]));
  if (m && m.count) out.push(['🗂️', '', `${m.count} transaction${m.count > 1 ? 's' : ''} sans catégorie`,
    `${eur(m.amount)} à classer en ${mlabel(m.month, true).split(' ')[0]}.`, { month: m.month, cat: 'none' }]);
  return out;
}

/** "À retenir": up to 5 [emoji, html] lines from the last complete month, the 3 before it and the
 *  next bill (`bills` may be null). */
export function computeInsights(months, bills) {
  const out = [], n = months.length, done = months[Math.max(0, n - 2)], prev = months.slice(Math.max(0, n - 5), n - 2);
  const monthName = mlabel(done.month, true).split(' ')[0];
  if (done.earned > 0 || done.saved) {
    const rate = done.earned > 0 ? Math.round(done.saved / done.earned * 100) : null;
    out.push(done.saved >= 0
      ? ['💰', `En ${monthName}, tu as mis <b>${eur(done.saved)}</b> de côté${rate !== null ? ` (${rate} % de tes revenus)` : ''}.`]
      : ['📉', `En ${monthName}, ton patrimoine a baissé de <b>${eur(-done.saved)}</b> hors marché.`]);
  }
  if (prev.length) {
    const a = avg(prev.map(p => p.spent)), d = done.spent - a;
    if (a > 0 && Math.abs(d / a) > .08) out.push([d < 0 ? '✅' : '⚠️', `Tes dépenses de ${monthName} sont <b>${Math.abs(Math.round(d / a * 100))} % ${d < 0 ? 'sous' : 'au-dessus de'}</b> ta moyenne des ${prev.length} mois précédents.`]);
    const rises = Object.entries(done.expenses).map(([c, v]) => [c, v, avg(prev.map(p => p.expenses[c] || 0))])
      .filter(([, v, m]) => v - m > 40 && v > m * 1.3).sort((x, y) => (y[1] - y[2]) - (x[1] - x[2]));
    if (rises.length) out.push(['🔺', `<b>${rises[0][0]}</b> grimpe : ${eur(rises[0][1])} contre ${eur(rises[0][2])} en moyenne.`]);
  }
  if (bills && bills.upcoming.length) {
    const u = bills.upcoming[0];
    out.push(['📅', `Prochain prélèvement : <b>${u.name}</b>, ${eur2(u.amount)} le ${frDay(u.date)}.`]);
  }
  return out.slice(0, 5);
}

/** Month `r` against the same month a year earlier `p`: the three totals, then the (up to 4)
 *  expense categories that moved by at least 20 €. Rows are [name, now, then, lowIsGood]. */
export function yoyRows(r, p) {
  const rows = [['Revenus', r.earned, p.earned, false], ['Dépenses', r.spent, p.spent, true], ['Épargne', r.saved, p.saved, false]];
  const cats = [...new Set([...Object.keys(r.expenses), ...Object.keys(p.expenses)])]
    .map(c => [c, r.expenses[c] || 0, p.expenses[c] || 0])
    .filter(([, a, b]) => Math.abs(a - b) >= 20)
    .sort((x, y) => Math.abs(y[1] - y[2]) - Math.abs(x[1] - x[2])).slice(0, 4);
  return { rows, cats };
}

/** CSV for French spreadsheets: BOM, `;` separator, decimal comma, expenses negative, oldest first.
 *  Text that starts with = + - @ is prefixed so a spreadsheet cannot run it as a formula. */
export function buildCsv(transactions) {
  const q = v => { let t = String(v ?? ''); if (/^[=+\-@\t\r]/.test(t)) t = "'" + t; return '"' + t.replace(/"/g, '""') + '"'; };
  const type = { withdrawal: 'Dépense', deposit: 'Revenu', transfer: 'Virement' };
  const num = t => (t.type === 'withdrawal' ? -t.amount : t.amount).toFixed(2).replace('.', ',');
  const lines = [['Date', 'Type', 'Libellé', 'Montant', 'Catégorie', 'Budget', 'Compte source', 'Compte destination', 'Notes'].join(';'),
    ...[...transactions].sort((a, b) => a.date.localeCompare(b.date)).map(t =>
      [t.date, type[t.type] || t.type, q(t.description), num(t), q(t.category), q(t.budget), q(t.source), q(t.destination), q(t.notes)].join(';'))];
  return '﻿' + lines.join('\r\n');
}

/** Accent- and case-insensitive match of every word of `query` in `text` (an empty query matches). */
export function matches(query, text) {
  const norm = s => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const t = norm(text);
  return norm(query).split(/\s+/).filter(Boolean).every(w => t.includes(w));
}
