/* Overview layout: which cards show and in what order, chosen in a small dialog and kept on this
   device. The hero (net worth curve) always stays on top. */
import { $, el } from './dom.js';
import { normalizeLayout } from './logic.js';

const KEY = 'cairn-overview';
const CARDS = { alerts: 'Alertes', split: 'Répartition', insights: 'À retenir', bills: 'Prochains prélèvements' };
const IDS = Object.keys(CARDS);

const load = () => { try { return normalizeLayout(JSON.parse(localStorage.getItem(KEY)), IDS); } catch (e) { return normalizeLayout(null, IDS); } };
const save = v => { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (e) { /* private window: not kept */ } };

let layout = load(), root = null, opener = null;

export function applyLayout() {
  layout.order.forEach((id, i) => {
    const card = document.querySelector(`#ovCards [data-card="${id}"]`);
    if (!card) return;
    card.style.order = i;
    card.classList.toggle('off', layout.hidden.includes(id));
  });
}

function paint(list) {
  list.replaceChildren(...layout.order.map((id, i) => {
    const on = !layout.hidden.includes(id);
    const check = el('input', { type: 'checkbox', checked: on, 'aria-label': 'Afficher ' + CARDS[id], onchange: () => { layout.hidden = on ? [...layout.hidden, id] : layout.hidden.filter(h => h !== id); change(list); } });
    const move = (d, label, glyph) => el('button', { className: 'icon', type: 'button', textContent: glyph, 'aria-label': `${label} : ${CARDS[id]}`, disabled: i + d < 0 || i + d >= layout.order.length,
      onclick: () => { const o = [...layout.order]; [o[i], o[i + d]] = [o[i + d], o[i]]; layout.order = o; change(list); setTimeout(() => list.querySelectorAll('.icon')[i * 2 + (d > 0 ? 1 : 0)]?.focus(), 0); } });
    return el('div', { className: 'lay-row' }, [el('label', {}, [check, ' ' + CARDS[id]]), el('span', {}, [move(-1, 'Monter', '↑'), move(1, 'Descendre', '↓')])]);
  }));
}

function change(list) { save(layout); applyLayout(); paint(list); }

function close() { root?.remove(); root = null; if (opener && document.contains(opener)) opener.focus(); }

function open() {
  if (root) return;
  opener = document.activeElement;
  const list = el('div', { className: 'lay' });
  const done = el('button', { className: 'btn', type: 'button', textContent: 'Terminé', onclick: close });
  const reset = el('button', { className: 'btn', type: 'button', textContent: 'Réinitialiser', onclick: () => { layout = normalizeLayout(null, IDS); change(list); } });
  const box = el('div', { className: 'md-box', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Personnaliser la vue d\'ensemble' }, [
    el('h3', { textContent: 'Personnaliser la vue d\'ensemble' }), el('p', { className: 'note', textContent: 'Choisis les cartes affichées et leur ordre. Le choix reste sur cet appareil.' }), list, el('div', { className: 'edit-row' }, [done, reset])]);
  root = el('div', { className: 'md', onmousedown: e => { if (e.target === root) close(); } }, [box]);
  document.body.append(root);
  paint(list);
  done.focus();
  box.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
}

$('ovEdit').onclick = open;
applyLayout();
