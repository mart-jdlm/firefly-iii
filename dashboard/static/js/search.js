/* Global search (Ctrl+K, "/" or the magnifier): pages, categories, budgets and transactions. */
import { json } from './api.js';
import { $, el } from './dom.js';
import { eur2 } from './format.js';
import { PAGES } from './consts.js';
import { all, gotoBudget, gotoCategory, gotoTransactions, memo, setSel } from './state.js';
import { chatToggle } from './chat.js';
import { matches } from './logic.js';
import { togglePrivate } from './privacy.js';

let root = null, input, list, items = [], active = 0, seq = 0, timer = 0, opener = null;

const go = hash => () => { location.hash = hash; };
const actions = [
  ['⟳', 'Actualiser les chiffres', () => $('refresh').click()],
  ['🙈', 'Masquer ou afficher les montants', togglePrivate],
  ['💬', "Ouvrir l'assistant", () => chatToggle(true)],
];

function groups(q) {
  const out = [];
  const pages = Object.entries(PAGES).filter(([, n]) => matches(q, n)).map(([k, n]) => ({ icon: '↗', text: n, hint: 'Page', run: go('#/' + k) }));
  const acts = actions.filter(([, n]) => matches(q, n)).map(([icon, text, run]) => ({ icon, text, hint: 'Action', run }));
  out.push(['Aller à', [...pages, ...acts]]);
  if (q) {
    const tax = memo.tax || { categories: [], budgets: [] };
    out.push(['Catégories', tax.categories.filter(c => matches(q, c)).slice(0, 5).map(c => ({ icon: '🏷️', text: c, hint: 'Transactions', run: () => gotoCategory(c) }))]);
    out.push(['Budgets', tax.budgets.filter(b => matches(q, b)).slice(0, 4).map(b => ({ icon: '🎯', text: b, hint: 'Dépenses', run: () => gotoBudget(b) }))]);
  }
  return out.filter(([, rows]) => rows.length);
}

function paint(found, state) {
  const q = input.value.trim(), nodes = [];
  items = [];
  const add = (title, rows) => {
    nodes.push(el('div', { className: 'sr-head', textContent: title, role: 'presentation' }));
    rows.forEach(r => {
      const i = items.length;
      const row = el('div', { className: 'sr-item', role: 'option', id: 'sr' + i, onclick: () => choose(i), onmousemove: () => highlight(i) },
        [el('span', { className: 'sr-ic', textContent: r.icon }), el('span', { className: 'sr-tx', textContent: r.text }), el('span', { className: 'sr-hint', textContent: r.hint })]);
      items.push({ ...r, row }); nodes.push(row);
    });
  };
  groups(q).forEach(([t, rows]) => add(t, rows));
  if (found && found.length) add('Transactions', found.map(t => ({
    icon: t.type === 'deposit' ? '＋' : '−', text: t.description, hint: `${eur2(t.amount)} · ${t.date.slice(8)}/${t.date.slice(5, 7)}/${t.date.slice(2, 4)}`,
    run: () => { const i = all.months.findIndex(m => m.month === t.date.slice(0, 7)); if (i >= 0) setSel(i); gotoTransactions({ q: t.description }); } })));
  if (!items.length) nodes.push(el('div', { className: 'sr-empty', textContent: state === 'loading' ? 'Recherche…' : q ? 'Aucun résultat' : '' }));
  else if (state === 'loading') nodes.push(el('div', { className: 'sr-empty', textContent: 'Recherche des transactions…' }));
  if (state === 'error') nodes.push(el('div', { className: 'sr-empty', textContent: 'Transactions indisponibles' }));
  list.replaceChildren(...nodes);
  highlight(Math.min(active, Math.max(items.length - 1, 0)));
}

function highlight(i) {
  active = i;
  items.forEach((it, j) => { it.row.classList.toggle('on', j === i); it.row.setAttribute('aria-selected', j === i); });
  input.setAttribute('aria-activedescendant', items[i] ? 'sr' + i : '');
  items[i]?.row.scrollIntoView({ block: 'nearest' });
}

function choose(i) { const it = items[i]; if (!it) return; close(); it.run(); }

async function update() {
  const q = input.value.trim(), mine = ++seq;
  active = 0;
  if (q.length < 2) { paint(null); return; }
  paint(null, 'loading');
  try {
    const found = await json('/api/search?q=' + encodeURIComponent(q));
    if (mine === seq && root) paint(found);
  } catch (e) { if (mine === seq && root) paint(null, 'error'); }
}

export function open() {
  if (root) return;
  opener = document.activeElement;
  input = el('input', { type: 'search', placeholder: 'Rechercher une page, une catégorie, une transaction…', autocomplete: 'off', spellcheck: false, role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'srList', 'aria-label': 'Recherche' });
  list = el('div', { id: 'srList', role: 'listbox', className: 'sr-list' });
  const box = el('div', { className: 'sr-box', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Recherche globale' }, [input, list, el('div', { className: 'sr-foot', textContent: '↑↓ choisir · ↵ ouvrir · Échap fermer' })]);
  root = el('div', { className: 'sr', onmousedown: e => { if (e.target === root) close(); } }, [box]);
  document.body.append(root);
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(update, 200); paint(null); });
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); highlight((active + 1) % Math.max(items.length, 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); highlight((active - 1 + items.length) % Math.max(items.length, 1)); }
    else if (e.key === 'Enter') { e.preventDefault(); choose(active); }
    else if (e.key === 'Escape') { e.preventDefault(); close(); }
    else if (e.key === 'Tab') e.preventDefault();
  });
  paint(null);
  input.focus();
  json('/api/taxonomy').then(t => { memo.tax = t; if (root) paint(null); }).catch(() => {});
}

function close() {
  clearTimeout(timer); seq++;
  root?.remove(); root = null;
  if (opener && document.contains(opener)) opener.focus();
}

addEventListener('keydown', e => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); root ? close() : open(); }
  else if (e.key === '/' && !typing && !root && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); open(); }
});
$('searchBtn').onclick = open;
