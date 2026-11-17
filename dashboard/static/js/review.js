/* Monthly review page: the review written by bilan/bilan.sh (figures + Claude's comments). */
import { json } from './api.js';
import { CATS } from './consts.js';
import { $, css, el, fail, mk, skel } from './dom.js';
import { eur, eur2, mlabel } from './format.js';
import { NONE, all, gotoTransactions, hooks, memo, page, setSel } from './state.js';
import { toast } from './edit.js';

let chosen = null;

const dm = d => `${d.slice(8)}/${d.slice(5, 7)}`;

function openMonth(month, filters) {
  const i = all.months.findIndex(m => m.month === month);
  if (i >= 0) setSel(i);
  gotoTransactions(filters);
}

const card = (title, kids, note) => el('section', { className: 'card mb' }, [el('h3', { textContent: title }), ...(note ? [el('p', { className: 'note', textContent: note })] : []), ...kids]);

const bullets = (items, emoji) => el('div', { className: 'list insights' }, items.map(t => el('div', { className: 'item' }, [el('div', { className: 'bubble', textContent: emoji }), el('span', { className: 'name', textContent: t, style: 'white-space:normal' })])));

function tile(tag, color, value, pillText, good) {
  const dot = el('span', { className: 'dot' }); dot.style.background = color;
  return el('div', { className: 'card tile' }, [el('div', { className: 'tag' }, [dot, tag]), el('div', { className: 'kpi', textContent: value }),
    el('span', { className: 'pill' + (good === true ? ' up' : good === false ? ' down' : ''), textContent: pillText || ' ' })]);
}

function categories(f, c) {
  const rows = [...f.categories].sort((a, b) => b.amount - a.amount), max = rows.length ? rows[0].amount : 1;
  const out = rows.flatMap((r, i) => {
    const d = r.average_3_months > 0 ? (r.amount - r.average_3_months) / r.average_3_months * 100 : null;
    const dot = el('span', { className: 'dot' }); dot.style.background = css(CATS[i % CATS.length]);
    const bar = el('div', { className: 'sub' }, [el('span')]); bar.firstChild.style.cssText = `width:${r.amount / max * 100}%;background:${css(CATS[i % CATS.length])}`;
    return [el('div', { className: 'item click', title: 'Voir les transactions', onclick: () => openMonth(f.month, { cat: r.name }) }, [dot, el('span', { className: 'name', textContent: r.name }),
      el('span', { className: 'vs' + (d === null ? '' : d > 15 ? ' down' : d < -15 ? ' up' : ''), textContent: d === null ? '' : (d > 0 ? '+' : '−') + Math.abs(Math.round(d)) + ' %' }),
      el('span', { className: 'amt', textContent: eur(r.amount) })]), bar];
  });
  return card('Dépenses par catégorie', [el('div', { className: 'list' }, out.length ? out : [el('div', { className: 'empty', textContent: 'Aucune dépense' })]),
    ...(c.categories_comment ? [el('p', { className: 'note', textContent: c.categories_comment, style: 'margin-top:14px' })] : [])], 'Écart avec la moyenne des 3 mois précédents.');
}

function budgets(f) {
  const rows = (f.budgets || []).filter(b => b.amount || b.spent);
  if (!rows.length) return null;
  return card('Budgets', rows.map(b => {
    const spent = Math.abs(b.spent), pct = b.amount ? spent / b.amount * 100 : 0, col = !b.amount ? css('--c7') : pct > 100 ? css('--down') : pct > 80 ? css('--c5') : css('--up');
    const track = el('div', { className: 'track' }, [el('span')]); track.firstChild.style.cssText = `width:${Math.min(pct, 100)}%;background:${col}`;
    const left = b.amount - spent;
    return el('div', { className: 'bud' }, [el('div', { className: 'row' }, [el('b', { textContent: b.name }), el('span', { textContent: b.amount ? `${eur(spent)} sur ${eur(b.amount)}` : eur(spent) })]),
      ...(b.amount ? [track, el('div', { className: 'left' + (left < 0 ? ' down' : ''), textContent: left >= 0 ? `Il restait ${eur(left)}` : `Dépassé de ${eur(-left)}` })] : [])]);
  }));
}

function netWorth(f) {
  const rows = f.net_worth_by_month || [];
  if (rows.length < 2) return null;
  const c = el('canvas', { id: 'cRvNw', role: 'img', ariaLabel: 'Patrimoine net sur les derniers mois' });
  queueMicrotask(() => {
    if (!c.isConnected) return;
    const line = css('--accent');
    mk('cRvNw', { type: 'line', data: { labels: rows.map(r => mlabel(r.month)), datasets: [{ data: rows.map(r => r.net_worth), borderColor: line, backgroundColor: css('--accent2'), fill: true, tension: .25, borderWidth: 2.5, pointRadius: 3, pointBackgroundColor: line }] },
      options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: x => ' ' + eur(x.parsed.y) } } },
        scales: { x: { grid: { display: false }, border: { display: false }, ticks: { color: css('--mute') } }, y: { grid: { color: css('--line') }, border: { display: false }, ticks: { color: css('--mute'), callback: v => eur(v), maxTicksLimit: 5 } } } } });
  });
  const change = f.net_worth_change;
  return card('Patrimoine net', [el('div', { className: 'chart' }, [c])], `${eur(f.net_worth)} à la fin du mois (${change >= 0 ? '+' : '−'}${eur(Math.abs(change))} sur le mois).`);
}

async function suggest(id, category) {
  const r = await fetch('/api/transaction', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'dashboard' }, body: JSON.stringify({ action: 'suggest', id, category }) });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || 'erreur ' + r.status);
}

/* Transactions still without a category, with the category the review suggests and a button to apply it. */
function toFile(f, c) {
  const hint = Object.fromEntries((c.uncategorised || []).map(u => [u.id, u.category]));
  const short = t => t.description.length > 44 ? t.description.slice(0, 43) + '…' : t.description;
  const buttons = [];
  const rows = f.uncategorised.map(t => {
    const cat = hint[t.id], status = el('span', { className: 'err2' });
    const btn = cat ? el('button', { className: 'btn small', type: 'button', textContent: 'Classer', title: `Classer en « ${cat} »` }) : null;
    const run = async () => {
      btn.disabled = true; status.textContent = '';
      try { await suggest(t.id, cat); btn.replaceWith(el('span', { className: 'when', textContent: '✓ classée' })); return true; }
      catch (e) { status.textContent = e.message; btn.disabled = false; return false; }
    };
    if (btn) { btn.onclick = async e => { e.stopPropagation(); if (await run()) { toast('Transaction classée'); hooks.reload(); } }; buttons.push(run); }
    return el('div', { className: 'item click', title: 'Voir dans les transactions', onclick: () => openMonth(f.month, { cat: NONE, q: '' }) },
      [el('span', { className: 'name' }, [short(t), el('small', { textContent: cat ? `Suggestion : ${cat}` : dm(t.date) }), status]), ...(btn ? [btn] : []), el('span', { className: 'amt', textContent: eur2(t.amount) })]);
  });
  const all = buttons.length > 1 ? el('button', { className: 'btn small', type: 'button', textContent: `Tout classer (${buttons.length})` }) : null;
  if (all) all.onclick = async () => {
    all.disabled = true;
    let done = 0;
    for (const run of buttons) if (await run()) done++;
    toast(`${done} transaction${done > 1 ? 's' : ''} classée${done > 1 ? 's' : ''}`); hooks.reload();
  };
  return card('À classer', [el('div', { className: 'list' }, rows), ...(all ? [el('div', { className: 'edit-row' }, [all])] : [])],
    'Ce qui n\'a pas encore de catégorie. « Classer » applique la suggestion de Claude, sans toucher au reste.');
}

function view(d) {
  const f = d.facts, c = d.comments, rate = f.earned > 0 ? Math.round(f.saved / f.earned * 100) : null;
  const out = [el('div', { className: 'tiles' }, [tile('Revenus', css('--up'), eur(f.earned)), tile('Dépenses', css('--c2'), eur(f.spent)),
    tile('Épargne', css('--accent'), eur(f.saved), rate === null ? '' : `${rate} % des revenus`, f.saved >= 0)])];
  if (c.highlights?.length) out.push(card('Points marquants', [bullets(c.highlights, '✨')]));
  out.push(categories(f, c));
  const b = budgets(f); if (b) out.push(b);
  if (c.watch?.length) out.push(card('À surveiller', [bullets(c.watch, '⚠️')]));
  if (f.largest?.length) out.push(card('Plus grosses dépenses', [el('div', { className: 'list' }, f.largest.map(t => el('div', { className: 'item click', title: 'Voir les transactions', onclick: () => openMonth(f.month, { q: t.description }) },
    [el('span', { className: 'name' }, [t.description.length > 44 ? t.description.slice(0, 43) + '…' : t.description, el('small', { textContent: `${dm(t.date)}${t.category ? ' · ' + t.category : ''}` })]), el('span', { className: 'amt', textContent: eur2(t.amount) })])))]));
  if (f.uncategorised?.length) out.push(toFile(f, c));
  const nw = netWorth(f); if (nw) out.push(nw);
  if (c.advice?.length) out.push(card('Conseils', c.advice.map(a => el('div', { className: 'advice' }, [el('b', { textContent: a.title }), el('p', { textContent: a.text })]))));
  if (f.upcoming_bills?.length) out.push(card('À venir', [el('div', { className: 'list' }, f.upcoming_bills.slice(0, 6).map(u => el('div', { className: 'item' }, [el('span', { className: 'name', textContent: u.name }), el('span', { className: 'when', textContent: dm(u.date) }), el('span', { className: 'amt', textContent: eur2(u.amount) })])))], 'Prélèvements des prochaines semaines.'));
  return out;
}

export async function renderReview() {
  const body = $('rvBody');
  let list;
  try { list = memo.reviews || (memo.reviews = await json('/api/bilans')); } catch (e) { fail(body, 'Bilans indisponibles', renderReview); return; }
  if (page !== 'review') return;
  $('rvHead').hidden = !list.length;
  if (!list.length) { body.replaceChildren(card('Pas encore de bilan', [el('p', { className: 'note', textContent: 'Le premier bilan est écrit au début du mois suivant, puis chaque mois. Pour en lancer un tout de suite : bilan/bilan.sh sur le serveur.' })])); return; }
  if (!chosen || !list.some(r => r.month === chosen)) chosen = list[0].month;
  const sel = $('rvMonth');
  sel.replaceChildren(...list.map(r => el('option', { value: r.month, textContent: mlabel(r.month, true) })));
  sel.value = chosen;
  const month = chosen, row = list.find(r => r.month === month);
  $('rvTitle').textContent = row.headline;
  const mail = $('rvMail'); mail.hidden = false; mail.href = '/api/bilan.html?month=' + month;
  let d = memo.review[month];
  if (!d) { body.replaceChildren(...skel(4)); try { d = memo.review[month] = await json('/api/bilan?month=' + month); } catch (e) { fail(body, 'Impossible de charger ce bilan', renderReview); return; } }
  if (page !== 'review' || month !== chosen) return;
  mail.hidden = !d.has_html;
  body.replaceChildren(...view(d));
}

$('rvMonth').addEventListener('change', e => { chosen = e.target.value; renderReview(); });
