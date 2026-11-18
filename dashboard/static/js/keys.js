/* Keyboard shortcuts: "g" then a letter to change page, ← → to change month, "h" to hide the
   amounts, "?" for the list. "n" (add) and "/" or Ctrl+K (search) live in their own modules. */
import { PAGES } from './consts.js';
import { $, el } from './dom.js';
import { page, sel, setMonth, all } from './state.js';
import { togglePrivate } from './privacy.js';

const GO = { o: 'overview', p: 'assets', b: 'budget', t: 'transactions', l: 'invest', a: 'future', m: 'review', r: 'recurring' };
const KEYS = [
  [['n'], 'Ajouter une transaction'],
  [['/', 'Ctrl K'], 'Rechercher'],
  [['g', 'puis o p b t l a m r'], 'Aller à une page : vue d\'ensemble, patrimoine, budget, transactions, placements, avenir, bilan, récurrent'],
  [['←', '→'], 'Mois précédent ou suivant (Budget et Transactions)'],
  [['h'], 'Masquer ou afficher les montants'],
  [['?'], 'Cette aide'],
  [['Échap'], 'Fermer la fenêtre ouverte'],
];

let root = null, opener = null, waiting = 0;

const busy = () => !!document.querySelector('.sr, .md, .sheet:not([hidden])') || !$('chat').hidden;

export function openHelp() {
  if (root) return;
  opener = document.activeElement;
  const close = el('button', { className: 'btn', type: 'button', textContent: 'Fermer', onclick: closeHelp });
  const list = el('dl', { className: 'keys' }, KEYS.flatMap(([keys, text]) => [
    el('dt', {}, keys.flatMap((k, i) => [...(i ? [' '] : []), el('kbd', { textContent: k })])),
    el('dd', { textContent: text })]));
  const box = el('div', { className: 'md-box', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Raccourcis clavier' }, [el('h3', { textContent: 'Raccourcis clavier' }), list, el('div', { className: 'edit-row' }, [close])]);
  root = el('div', { className: 'md', onmousedown: e => { if (e.target === root) closeHelp(); } }, [box]);
  document.body.append(root);
  close.focus();
  box.addEventListener('keydown', e => { if (e.key === 'Tab') e.preventDefault(); });
}

function closeHelp() {
  root?.remove(); root = null;
  if (opener && document.contains(opener)) opener.focus();
}

addEventListener('keydown', e => {
  if (e.key === 'Escape' && root) { closeHelp(); return; }
  const tag = document.activeElement?.tagName;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || document.activeElement?.isContentEditable) return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (root && e.key !== '?') return;
  if (waiting) {
    const go = GO[e.key.toLowerCase()];
    waiting = 0;
    if (go) { e.preventDefault(); location.hash = '#/' + go; }
    return;
  }
  if (busy() && !root) return;
  if (e.key === 'g') { waiting = 1; setTimeout(() => { waiting = 0; }, 1200); }
  else if (e.key === '?') { e.preventDefault(); root ? closeHelp() : openHelp(); }
  else if (e.key === 'h') togglePrivate();
  else if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && all && !$('monthnav').hidden && PAGES[page]) setMonth(sel + (e.key === 'ArrowRight' ? 1 : -1));
});

$('helpBtn').onclick = openHelp;
