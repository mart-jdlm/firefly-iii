// End-to-end check of the running dashboard in headless Chrome (Playwright).
//   node snap.js save      writes the visible text of every page and interaction to baseline.json
//   node snap.js           checks, then compares with baseline.json when there is one
// Checks that need no baseline: no JavaScript error, every page renders, no horizontal scroll at
// 390 px. The comparison catches any change of what the pages show (refactors must change nothing).
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = process.env.CAIRN_URL || 'http://127.0.0.1:8787';
const FILE = process.env.BASELINE || '/d/tests/e2e/baseline.json';
const PAGES = ['overview', 'assets', 'budget', 'transactions', 'invest', 'future', 'recurring'];
const save = process.argv[2] === 'save';
const problems = [];

async function snapshot(browser) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: 'block' });
  const p = await ctx.newPage(), snap = {};
  p.on('pageerror', e => problems.push('JavaScript error: ' + e.message));
  p.on('console', m => { if (m.type() === 'error') problems.push('console error: ' + m.text()); });
  await p.goto(BASE + '/#/overview'); await p.waitForTimeout(3500);
  const txt = async () => (await p.evaluate(() => document.getElementById('main').innerText)).replace(/[ \t]+/g, ' ');
  const go = async n => { await p.evaluate(h => { location.hash = h; }, '#/' + n); await p.waitForTimeout(2200); };
  const click = async s => { await p.click(s); await p.waitForTimeout(700); };
  for (const n of PAGES) { await go(n); snap[n] = await txt(); if (snap[n].trim().length < 40) problems.push(`page "${n}" looks empty`); }
  await go('overview'); await click('#ranges [data-m="6"]'); snap['overview-6m'] = await txt();
  await go('assets'); snap['assets-6m'] = await txt();
  await go('overview'); await click('#ranges [data-m="24"]'); await go('assets'); snap['assets-24m'] = await txt();
  await go('budget'); await click('#prev'); snap['budget-prev'] = await txt(); await click('#prev'); snap['budget-prev2'] = await txt();
  await go('transactions'); await p.fill('#q', 'a'); await p.waitForTimeout(500); snap['tx-search'] = await txt();
  await p.fill('#q', ''); await click('#ftype [data-t="expense"]'); snap['tx-expense'] = await txt();
  await click('#ftype [data-t="income"]'); snap['tx-income'] = await txt();
  await go('recurring'); for (const s of ['name', 'freq', 'cost']) { await click(`#bSort [data-s="${s}"]`); snap['bills-' + s] = await txt(); }
  await go('future'); await p.fill('#fS', '250'); await p.fill('#fYears', '20'); await p.dispatchEvent('#fYears', 'input'); await p.waitForTimeout(500);
  snap['future-250-20y'] = await txt();
  await click('#levers .lrow:nth-child(1) [data-p="20"]'); snap['future-lever'] = await txt();
  await click('#gNew'); snap['future-goalform-open'] = String(!(await p.evaluate(() => document.getElementById('gForm').hidden)));
  await go('transactions');
  let csv = ''; await p.exposeFunction('grab', t => { csv = t; });
  await p.evaluate(() => { const O = Blob; window.Blob = class extends O { constructor(parts, o) { super(parts, o); window.grab(parts[0]); } }; HTMLAnchorElement.prototype.click = function () {}; });
  await click('#txCsv'); snap.csv = csv; if (!csv.startsWith('﻿Date;Type')) problems.push('CSV export is not what is expected');
  snap.nav = await p.evaluate(() => [...document.querySelectorAll('#nav a')].map(a => a.innerText.trim() + (a.querySelector('.badge') && !a.querySelector('.badge').hidden ? '[' + a.querySelector('.badge').textContent + ']' : '')));
  snap.title = await p.title();
  await ctx.close();
  return snap;
}

async function mobile(browser) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
  const p = await ctx.newPage();
  p.on('pageerror', e => problems.push('JavaScript error (mobile): ' + e.message));
  await p.goto(BASE + '/#/overview'); await p.waitForTimeout(3000);
  for (const n of PAGES) {
    await p.evaluate(h => { location.hash = h; }, '#/' + n); await p.waitForTimeout(2000);
    const o = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (o > 0) problems.push(`page "${n}" scrolls sideways by ${o}px at 390px`);
  }
  await fab(p, 'phone');
  await ctx.close();
}

// The assistant button must step aside while reading and never cover the end of a page.
async function fab(p, where) {
  const state = () => p.evaluate(() => document.getElementById('chatOpen').classList.contains('away'));
  const overlap = () => p.evaluate(() => {
    const f = document.getElementById('chatOpen').getBoundingClientRect(), pg = document.querySelector('.page:not([hidden])');
    const l = pg.lastElementChild.getBoundingClientRect();
    return f.top < l.bottom && f.bottom > l.top && f.left < l.right && f.right > l.left;
  });
  for (const n of PAGES) {
    await p.evaluate(h => { location.hash = h; }, '#/' + n); await p.waitForTimeout(1800);
    const tall = await p.evaluate(() => document.documentElement.scrollHeight - innerHeight > 900);
    if (tall) {
      await p.mouse.wheel(0, 500); await p.waitForTimeout(500);
      if (!(await state())) problems.push(`assistant button stays in the way when scrolling down on "${n}" (${where})`);
      await p.mouse.wheel(0, -120); await p.waitForTimeout(500);
      if (await state()) problems.push(`assistant button does not come back when scrolling up on "${n}" (${where})`);
    }
    await p.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight)); await p.waitForTimeout(600);
    if (await state()) problems.push(`assistant button hidden at the bottom of "${n}" (${where})`);
    if (await overlap()) problems.push(`assistant button covers the end of "${n}" (${where})`);
  }
}

function compare(now, before) {
  const keys = [...new Set([...Object.keys(before), ...Object.keys(now)])];
  for (const k of keys) {
    const a = JSON.stringify(before[k]), b = JSON.stringify(now[k]);
    if (a === b) continue;
    const x = String(before[k] ?? '(missing)').split('\n'), y = String(now[k] ?? '(missing)').split('\n');
    const i = x.findIndex((l, j) => l !== y[j]);
    problems.push(`"${k}" differs from the baseline, first at line ${i + 1}:\n      was: ${x[i] ?? '(none)'}\n      now: ${y[i] ?? '(none)'}`);
  }
  return keys.length;
}

(async () => {
  const browser = await chromium.launch();
  const snap = await snapshot(browser);
  await mobile(browser);
  { const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, serviceWorkers: 'block' }), p = await ctx.newPage();
    await p.goto(BASE + '/#/overview'); await p.waitForTimeout(3000); await fab(p, 'desktop'); await ctx.close(); }
  await browser.close();
  const uniq = [...new Set(problems)]; problems.length = 0; problems.push(...uniq);
  if (save) {
    if (problems.length) { console.log('Not saved, fix first:\n  - ' + problems.join('\n  - ')); process.exit(1); }
    fs.writeFileSync(FILE, JSON.stringify(snap, null, 1));
    console.log(`  baseline saved: ${Object.keys(snap).length} states`); return;
  }
  let compared = 0;
  if (fs.existsSync(FILE)) compared = compare(snap, JSON.parse(fs.readFileSync(FILE, 'utf-8')));
  else console.log('  (no baseline yet: run with --save to record one)');
  if (problems.length) { console.log(`  FAILED:\n  - ${problems.join('\n  - ')}`); process.exit(1); }
  console.log(`  ok: no JavaScript error, no sideways scroll at 390px, ${compared ? compared + ' states identical to the baseline' : 'nothing compared'}`);
})().catch(e => { console.log('  FAILED:', e.message); process.exit(1); });
