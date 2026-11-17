import { test } from 'node:test';
import assert from 'node:assert/strict';
import { billCost, buildCsv, computeAlerts, computeInsights, project, runway, sortBills, yoyRows } from '../../static/js/logic.js';

const plain = s => s.replace(/[  ]/g, ' ');
const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} is not ${b}`);

/* ---------- project ---------- */
test('project without yield adds the savings each month', () => {
  const out = project(100, 0, 0, 0, 1, 1000, 0, -200);
  assert.equal(out.length, 13);
  assert.deepEqual(out[0], { nw: 800, paid: 0 });
  near(out[12].nw, 800 + 1200); assert.equal(out[12].paid, 1200);
});

test('project compounds the yearly yield monthly: 12 % a year on cash gives exactly 12 %', () => {
  const out = project(0, 0, 12, 0, 1, 1000, 0, 0);
  near(out[12].nw, 1120, 1e-6);
});

test('project sends the share to the PEA and the rest to savings', () => {
  const out = project(100, 0.5, 0, 0, 1, 0, 0, 0);
  near(out[12].nw, 1200);                                  // split does not matter without yield
  const pea = project(100, 1, 0, 10, 1, 0, 0, 0)[12].nw, cash = project(100, 0, 10, 0, 1, 0, 0, 0)[12].nw;
  assert.ok(pea > 1200, 'PEA yield applies to the PEA share');
  near(pea, cash, 1e-9);                                   // same yield on the same money
});

test('project in today\'s euros divides by 2 % inflation a year', () => {
  const real = project(0, 0, 0, 0, 1, 1000, 0, 0, true);
  near(real[12].nw, 1000 / 1.02);
  near(project(0, 0, 0, 0, 1, 1000, 0, 0, false)[12].nw, 1000);
});

test('project with a zero horizon is just the starting point', () => {
  assert.deepEqual(project(100, 0.5, 2, 5, 0, 10, 20, -5), [{ nw: 25, paid: 0 }]);
});

/* ---------- runway ---------- */
const month = (m, o = {}) => ({ month: m, earned: 0, spent: 0, saved: 0, expenses: {}, income: {}, net_worth: { courant: 0, epargne: 0, investissements: 0, dettes: 0, total: 0, accounts: [] }, ...o });

test('runway: liquidity over the average spending of the last 3 complete months', () => {
  const months = [month('2026-06', { spent: 9999 }), month('2026-07', { spent: 1000 }), month('2026-08', { spent: 2000 }),
    month('2026-09', { spent: 3000 }), month('2026-10', { spent: 50, net_worth: { courant: 1000, epargne: 5000, investissements: 800, dettes: 0, total: 0, accounts: [] } })];
  const r = runway(months);
  assert.equal(r.spend, 2000); assert.equal(r.liquid, 6000); assert.equal(r.months, 3);
});

test('runway is null without spending', () => {
  assert.equal(runway([month('2026-08'), month('2026-09'), month('2026-10'), month('2026-11')]).months, null);
});

/* ---------- computeAlerts ---------- */
const NOW = new Date(2026, 10, 17, 9, 0);                  // 17 November: day 17 of 30
const richMonths = [month('2026-08', { spent: 1000 }), month('2026-09', { spent: 1000 }), month('2026-10', { spent: 1000 }),
  month('2026-11', { net_worth: { courant: 9000, epargne: 9000, investissements: 0, dettes: 0, total: 0, accounts: [] } })];
const alerts = (budgets, bills = null, months = richMonths) => computeAlerts({ budgets, bills, months, now: NOW });

test('alerts: a budget over its limit', () => {
  const { items, budgetCount } = alerts([{ name: 'Loisirs', limit: 100, spent: 120 }]);
  assert.equal(budgetCount, 1);
  assert.equal(items[0][0], '🚨'); assert.equal(items[0][1], 'down');
  assert.equal(items[0][2], 'Loisirs : budget dépassé');
  assert.match(plain(items[0][3]), /Dépassé de 20 € \(120 € sur 100 €\)/);
});

test('alerts: 80 % used says how much is left and for how many days', () => {
  const { items } = alerts([{ name: 'Sorties', limit: 100, spent: 85 }]);
  assert.equal(items[0][0], '⚠️'); assert.equal(items[0][1], 'warn');
  assert.equal(items[0][2], 'Sorties : 85 % du budget utilisé');
  assert.match(plain(items[0][3]), /Il reste 15 € pour 13 jours/);
});

test('alerts: a pace that will break the budget is flagged only with enough history', () => {
  assert.equal(alerts([{ name: 'A', limit: 100, spent: 60 }]).items.length, 0, '60 at day 17 projects 106: under +10 %');
  const hot = alerts([{ name: 'A', limit: 100, spent: 70 }]).items;
  assert.equal(hot[0][0], '📈'); assert.match(plain(hot[0][3]), /dépassé d'environ 24 €/);
  const early = computeAlerts({ budgets: [{ name: 'A', limit: 100, spent: 70 }], bills: null, months: richMonths, now: new Date(2026, 10, 5) });
  assert.equal(early.items.length, 0, 'before day 7 the pace says nothing');
  assert.equal(alerts([{ name: 'A', limit: 100, spent: 40 }]).items.length, 0, 'under 50 % no projection');
});

test('alerts: budgets without a limit are ignored, worst first, count is for budgets only', () => {
  const { items, budgetCount } = alerts([
    { name: 'Sans plafond', limit: null, spent: 999 },
    { name: 'Presque', limit: 100, spent: 90 },
    { name: 'Dépassé', limit: 100, spent: 130 },
  ], { upcoming: [{ name: 'Loyer', amount: 500, date: '2026-11-18' }] });
  assert.equal(budgetCount, 2);
  assert.deepEqual(items.map(i => i[2].split(' :')[0]), ['Dépassé', 'Presque', 'Loyer']);
});

test('alerts: bills due in the next 3 days only', () => {
  const bills = { upcoming: [
    { name: 'Hier', amount: 1, date: '2026-11-16' }, { name: 'Auj', amount: 2, date: '2026-11-17' },
    { name: 'Demain', amount: 3, date: '2026-11-18' }, { name: 'Dans 3', amount: 4, date: '2026-11-20' }, { name: 'Dans 4', amount: 5, date: '2026-11-21' }] };
  const { items } = alerts(null, bills);
  assert.deepEqual(items.map(i => i[2].split(' :')[0]), ['Auj', 'Demain', 'Dans 3']);
  assert.equal(items[0][3], "Prélèvement prévu aujourd'hui.");
  assert.equal(items[1][3], 'Prélèvement prévu demain.');
  assert.equal(items[2][3], 'Prélèvement prévu dans 3 jours.');
});

test('alerts: thin safety margin, warn under 3 months and down under 1', () => {
  const thin = (liquid) => [month('2026-08', { spent: 1000 }), month('2026-09', { spent: 1000 }), month('2026-10', { spent: 1000 }),
    month('2026-11', { net_worth: { courant: liquid, epargne: 0, investissements: 0, dettes: 0, total: 0, accounts: [] } })];
  const warn = alerts(null, null, thin(2000)).items[0];
  assert.equal(warn[0], '🛟'); assert.equal(warn[1], 'warn'); assert.equal(warn[2], 'Autonomie : 2,0 mois');
  assert.equal(alerts(null, null, thin(500)).items[0][1], 'down');
  assert.equal(alerts(null, null, thin(3000)).items.length, 0, 'exactly 3 months is fine');
});

test('alerts: nothing available gives no alerts, and every item has 4 fields', () => {
  assert.deepEqual(alerts(null, null), { items: [], budgetCount: 0 });
  const { items } = alerts([{ name: 'A', limit: 100, spent: 120 }]);
  assert.equal(items[0].length, 4);
});

/* ---------- computeInsights ---------- */
const series = [
  month('2026-05', { spent: 1000, earned: 2000, saved: 500 }),
  month('2026-06', { spent: 1000, earned: 2000, saved: 500 }),
  month('2026-07', { spent: 1000, earned: 2000, saved: 500 }),
  month('2026-08', { spent: 1500, earned: 2000, saved: 400, expenses: { Sorties: 400, Courses: 300 } }),
  month('2026-09', { spent: 10 }),                          // the current month, ignored
];

test('insights: saving, spending against the 3 months before, rising category', () => {
  const prev = series.slice(0, 3).map(m => ({ ...m, expenses: { Sorties: 100, Courses: 290 } }));
  const out = computeInsights([...prev, series[3], series[4]], null).map(([e, h]) => [e, plain(h)]);
  assert.deepEqual(out.map(o => o[0]), ['💰', '⚠️', '🔺']);
  assert.match(out[0][1], /En août, tu as mis <b>400 €<\/b> de côté \(20 % de tes revenus\)/);
  assert.match(out[1][1], /<b>50 % au-dessus de<\/b> ta moyenne des 3 mois précédents/);
  assert.match(out[2][1], /<b>Sorties<\/b> grimpe : 400 € contre 100 € en moyenne/);
});

test('insights: a month spent below average is good news; a negative saving is a drop', () => {
  const m = [month('2026-05', { spent: 1000 }), month('2026-06', { spent: 1000 }), month('2026-07', { spent: 1000 }),
    month('2026-08', { spent: 500, earned: 1000, saved: -80 }), month('2026-09')];
  const out = computeInsights(m, null);
  assert.deepEqual(out.map(o => o[0]), ['📉', '✅']);
  assert.match(plain(out[0][1]), /baissé de <b>80 €<\/b> hors marché/);
});

test('insights: next bill, and never more than 5 lines', () => {
  const out = computeInsights(series, { upcoming: [{ name: 'Netflix', amount: 13.5, date: '2026-11-21' }] });
  const last = out[out.length - 1];
  assert.equal(last[0], '📅'); assert.match(plain(last[1]), /Netflix<\/b>, 13,50 € le 21 novembre/);
  const full = computeInsights(series, { upcoming: [{ name: 'X', amount: 1, date: '2026-11-21' }] });
  assert.ok(full.length <= 5);
});

test('insights: not enough data gives nothing', () => {
  assert.deepEqual(computeInsights([month('2026-08'), month('2026-09')], null), []);
});

/* ---------- yoyRows ---------- */
test('yoy: totals first, then up to 4 categories by size of change (20 € minimum)', () => {
  const now = month('2026-10', { earned: 1000, spent: 500, saved: 500, expenses: { A: 100, B: 300, C: 50, D: 10, E: 0, F: 80 } });
  const then = month('2025-10', { earned: 2000, spent: 900, saved: -100, expenses: { A: 100, B: 100, C: 10, D: 5, E: 400, F: 0, G: 25 } });
  const { rows, cats } = yoyRows(now, then);
  assert.deepEqual(rows, [['Revenus', 1000, 2000, false], ['Dépenses', 500, 900, true], ['Épargne', 500, -100, false]]);
  assert.deepEqual(cats, [['E', 0, 400], ['B', 300, 100], ['F', 80, 0], ['C', 50, 10]]);
});

/* ---------- bills ---------- */
const bills = [
  { name: 'Strava', amount: 60, frequency: 'yearly' },
  { name: 'Claude', amount: 22.5, frequency: 'monthly' },
  { name: 'Assurance', amount: 30, frequency: 'quarterly' },
  { name: 'Abo hebdo', amount: 2, frequency: 'weekly' },
  { name: 'AXA', amount: 10, frequency: 'monthly' },
];

test('billCost is the monthly equivalent', () => {
  near(billCost({ amount: 60, frequency: 'yearly' }), 5);
  near(billCost({ amount: 30, frequency: 'quarterly' }), 10);
  near(billCost({ amount: 2, frequency: 'weekly' }), 2 * 52 / 12);
  assert.equal(billCost({ amount: 7, frequency: 'unknown' }), 7);
});

test('sortBills by cost, name or frequency, without touching the input', () => {
  const copy = JSON.stringify(bills);
  const costs = sortBills(bills, 'cost').map(billCost);
  assert.deepEqual(costs, [...costs].sort((a, b) => b - a));
  assert.deepEqual(sortBills(bills, 'name').map(b => b.name), ['Abo hebdo', 'Assurance', 'AXA', 'Claude', 'Strava']);
  assert.deepEqual(sortBills(bills, 'freq').map(b => b.frequency), ['weekly', 'monthly', 'monthly', 'quarterly', 'yearly']);
  assert.deepEqual(sortBills(bills, 'freq').filter(b => b.frequency === 'monthly').map(b => b.name), ['Claude', 'AXA'], 'cost breaks ties inside a frequency');
  assert.equal(JSON.stringify(bills), copy);
});

/* ---------- buildCsv ---------- */
const tx = (o) => ({ date: '2026-10-05', type: 'withdrawal', description: 'Café', amount: 3.5, category: 'Sorties', budget: 'Loisirs', source: 'Compte', destination: 'Bar', notes: null, ...o });

test('csv: BOM, header, CRLF, oldest first, signed amounts with decimal comma', () => {
  const csv = buildCsv([tx({ date: '2026-10-09', type: 'deposit', description: 'Salaire', amount: 1200 }), tx({}), tx({ date: '2026-10-07', type: 'transfer', amount: 50.25 })]);
  assert.equal(csv[0], '﻿');
  const lines = csv.slice(1).split('\r\n');
  assert.equal(lines[0], 'Date;Type;Libellé;Montant;Catégorie;Budget;Compte source;Compte destination;Notes');
  assert.deepEqual(lines.slice(1).map(l => l.split(';').slice(0, 4)), [
    ['2026-10-05', 'Dépense', '"Café"', '-3,50'], ['2026-10-07', 'Virement', '"Café"', '50,25'], ['2026-10-09', 'Revenu', '"Salaire"', '1200,00']]);
});

test('csv: quotes are doubled and formulas are defused', () => {
  const lines = buildCsv([tx({ description: 'Il dit "oui"; ok' }), tx({ description: '=HYPERLINK("http://x")' }), tx({ description: '+33 1', notes: '@cmd' }), tx({ description: '-1' })]).slice(1).split('\r\n');
  assert.equal(lines[1].split(';')[2], '"Il dit ""oui""', 'a ; inside quotes still splits naive readers, so check the raw field');
  assert.ok(lines[1].includes('"Il dit ""oui""; ok"'));
  assert.ok(lines[2].includes(`"'=HYPERLINK(""http://x"")"`));
  assert.ok(lines[3].includes(`"'+33 1"`) && lines[3].includes(`"'@cmd"`));
  assert.ok(lines[4].includes(`"'-1"`));
});

test('csv: missing fields become empty strings, empty list is just the header', () => {
  const line = buildCsv([tx({ category: null, budget: undefined })]).slice(1).split('\r\n')[1];
  assert.ok(line.includes(';"";"";'));
  assert.equal(buildCsv([]).slice(1).split('\r\n').length, 1);
});

test('csv does not modify its input order', () => {
  const list = [tx({ date: '2026-10-09' }), tx({ date: '2026-10-01' })];
  buildCsv(list);
  assert.deepEqual(list.map(t => t.date), ['2026-10-09', '2026-10-01']);
});
