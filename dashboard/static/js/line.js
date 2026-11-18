/* Detail of one holding: its figures and its price over 1 month, 1 year or 5 years (Yahoo Finance
   closes, only for symbols of the positions file). Opens from a row of the Placements page. */
import { json } from './api.js';
import { $, css, el, fail, mk, skel } from './dom.js';
import { eur, eur2 } from './format.js';
import { charts } from './state.js';
import { lineGain } from './logic.js';

const SPANS = [['1m', '1 mois'], ['1y', '1 an'], ['max', '5 ans']];
let root = null, opener = null;

const signed = v => (v > 0 ? '+' : v < 0 ? '−' : '') + eur2(Math.abs(v));

function close() {
  if (charts.cLine) { charts.cLine.destroy(); delete charts.cLine; }
  root?.remove(); root = null;
  if (opener && document.contains(opener)) opener.focus();
}

async function draw(p, span, area) {
  area.replaceChildren(...skel(3));
  let data;
  try { data = await json(`/api/history?symbol=${encodeURIComponent(p.symbol)}&span=${span}`); }
  catch (e) { if (root) fail(area, 'Historique indisponible', () => draw(p, span, area)); return; }
  if (!root) return;
  area.replaceChildren(el('canvas', { id: 'cLine', role: 'img', 'aria-label': 'Cours de ' + p.symbol }));
  const prices = data.prices, first = prices[0]?.[1], last = prices[prices.length - 1]?.[1];
  const up = last >= first, color = css(up ? '--up' : '--down');
  mk('cLine', { type: 'line', data: { labels: prices.map(d => d[0]), datasets: [
    { label: p.symbol, data: prices.map(d => d[1]), borderColor: color, borderWidth: 2.2, pointRadius: 0, pointHoverRadius: 5, tension: .2 },
    ...(p.pru ? [{ label: 'Prix de revient', data: prices.map(() => p.pru), borderColor: css('--c7'), borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0 }] : [])] },
    options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: false }, tooltip: { backgroundColor: css('--fg'), titleColor: css('--bg'), bodyColor: css('--bg'), padding: 10, cornerRadius: 10,
        callbacks: { title: c => new Date(c[0].label + 'T12:00:00').toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }), label: c => ` ${c.dataset.label} : ${eur2(c.parsed.y)}` } } },
      scales: { x: { grid: { display: false }, border: { display: false }, ticks: { color: css('--mute'), maxRotation: 0, autoSkip: true, maxTicksLimit: 5, callback(v) { const d = this.getLabelForValue(v); return d.slice(8) + '/' + d.slice(5, 7); } } },
        y: { grid: { color: css('--line') }, border: { display: false }, ticks: { color: css('--mute'), callback: v => eur(v), maxTicksLimit: 5 } } } } });
  const change = first ? last / first - 1 : 0;
  $('lineChange').textContent = prices.length ? `${change >= 0 ? '+' : '−'}${Math.abs(change * 100).toFixed(1).replace('.', ',')} % sur la période` : '';
}

export function openLine(p) {
  if (root) return;
  opener = document.activeElement;
  const g = lineGain(p);
  const facts = [['Quantité', p.quantity.toLocaleString('fr-FR')], ['Cours', p.price === null ? '—' : eur2(p.price)], ['Valeur', p.value === null ? '—' : eur2(p.value)],
    ...(p.pru ? [['Prix de revient', eur2(p.pru)]] : []), ...(g ? [['Plus-value', `${signed(g.amount)} (${g.pct >= 0 ? '+' : '−'}${Math.abs(g.pct * 100).toFixed(1).replace('.', ',')} %)`]] : [])];
  const area = el('div', { className: 'line-chart' });
  const buttons = SPANS.map(([k, label]) => el('button', { type: 'button', textContent: label, 'aria-pressed': String(k === '1y'),
    onclick: () => { buttons.forEach((b, i) => b.setAttribute('aria-pressed', String(SPANS[i][0] === k))); draw(p, k, area); } }));
  const closeBtn = el('button', { className: 'btn', type: 'button', textContent: 'Fermer', onclick: close });
  const box = el('div', { className: 'md-box wide', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Détail de ' + p.symbol }, [
    el('div', { className: 'cardhead' }, [el('h3', { textContent: p.label ? `${p.symbol} · ${p.label}` : p.symbol }), el('div', { className: 'seg2', role: 'group', 'aria-label': 'Période' }, buttons)]),
    el('p', { className: 'note', id: 'lineChange' }), area,
    el('dl', { className: 'facts' }, facts.flatMap(([k, v]) => [el('dt', { textContent: k }), el('dd', { textContent: v })])),
    el('div', { className: 'edit-row' }, [closeBtn])]);
  root = el('div', { className: 'md', onmousedown: e => { if (e.target === root) close(); } }, [box]);
  document.body.append(root);
  closeBtn.focus();
  box.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  draw(p, '1y', area);
}
