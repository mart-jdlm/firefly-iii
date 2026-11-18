/* Quick add: record an expense or an income by hand (cash, anything the bank import will not
   bring). Opens from the "+" button, from the search palette or with the "n" key. */
import { json } from './api.js';
import { $, el } from './dom.js';
import { hooks, memo } from './state.js';
import { toast } from './edit.js';

let root = null, opener = null;

const today = () => { const t = new Date(); return new Date(t.getTime() - t.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); };

const field = (label, control, cls = '') => el('label', { className: 'fld ' + cls }, [el('span', { textContent: label }), control]);

const picker = (names, none) => el('select', {}, [el('option', { value: '', textContent: none }), ...names.map(n => el('option', { value: n, textContent: n }))]);

export async function openAdd() {
  if (root) return;
  opener = document.activeElement;
  const box = el('div', { className: 'md-box', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Ajouter une transaction' }, [el('div', { className: 'empty', textContent: 'Chargement…' })]);
  root = el('div', { className: 'md', onmousedown: e => { if (e.target === root) closeAdd(); } }, [box]);
  document.body.append(root);
  let tax = memo.tax;
  if (!tax || !tax.accounts) { try { tax = memo.tax = await json('/api/taxonomy'); } catch (e) { box.replaceChildren(el('div', { className: 'empty', textContent: 'Impossible de charger les comptes et catégories' })); return; } }
  if (!root) return;

  let kind = 'expense';
  const seg = el('div', { className: 'seg2', role: 'group', 'aria-label': 'Type' }, [['expense', 'Dépense'], ['income', 'Revenu']].map(([k, n]) =>
    el('button', { type: 'button', textContent: n, 'aria-pressed': k === kind, onclick: () => { kind = k; [...seg.children].forEach(b => b.setAttribute('aria-pressed', b === seg.children[k === 'expense' ? 0 : 1])); bf.hidden = k !== 'expense'; } }))
    .flat());
  const amount = el('input', { type: 'text', inputMode: 'decimal', placeholder: '0,00', autocomplete: 'off', 'aria-label': 'Montant en euros' });
  const desc = el('input', { type: 'text', maxLength: 120, placeholder: 'Boulangerie, remboursement…', autocomplete: 'off' });
  const date = el('input', { type: 'date', value: today(), max: today() });
  const account = el('select', {}, tax.accounts.map(n => el('option', { value: n, textContent: n })));
  const cat = picker(tax.categories, 'Selon les règles'), bud = picker(tax.budgets, 'Aucun');
  const bf = field('Budget', bud);
  const err = el('div', { className: 'err2', role: 'alert' });
  const save = el('button', { className: 'btn primary', type: 'submit', textContent: 'Ajouter' });
  const form = el('form', { noValidate: true, onsubmit: async e => {
    e.preventDefault(); err.textContent = '';
    save.disabled = true;
    try {
      const r = await fetch('/api/transaction', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'dashboard' },
        body: JSON.stringify({ action: 'create', kind, amount: amount.value, description: desc.value, date: date.value, account: account.value, category: cat.value, budget: kind === 'expense' ? bud.value : '' }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || 'erreur ' + r.status);
      toast(kind === 'expense' ? 'Dépense ajoutée' : 'Revenu ajouté');
      closeAdd(); hooks.reload();
    } catch (x) { err.textContent = x.message; save.disabled = false; }
  } }, [seg, field('Montant (€)', amount, 'big-in'), field('Libellé', desc), el('div', { className: 'edit-row' }, [field('Date', date), field('Compte', account)]),
    el('div', { className: 'edit-row' }, [field('Catégorie', cat), bf]), err,
    el('div', { className: 'edit-row' }, [save, el('button', { className: 'btn', type: 'button', textContent: 'Annuler', onclick: closeAdd })])]);
  box.replaceChildren(el('h3', { textContent: 'Ajouter une transaction' }), form);
  amount.focus();
}

function closeAdd() {
  root?.remove(); root = null;
  if (opener && document.contains(opener)) opener.focus();
}

addEventListener('keydown', e => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
  if (e.key === 'Escape' && root) closeAdd();
  else if (e.key === 'n' && !typing && !root && !e.ctrlKey && !e.metaKey && !e.altKey && !document.querySelector('.sr, .md')) { e.preventDefault(); openAdd(); }
});
$('addBtn').onclick = openAdd;
