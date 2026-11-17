/* Mobile tab bar: the four main tabs and a "Plus" button that opens a sheet with the other pages. */
import { $, el } from './dom.js';

const MAIN = ['overview', 'assets', 'budget', 'transactions'];
const SHORT = { overview: 'Accueil', assets: 'Patrimoine', budget: 'Budget', transactions: 'Opérations' };
const DOTS = '<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>';

const links = [...document.querySelectorAll('#nav a')];
const more = el('button', { className: 'more', type: 'button', 'aria-haspopup': 'dialog', 'aria-expanded': 'false', 'aria-controls': 'moreSheet' });
more.innerHTML = DOTS + '<span>Plus</span>';

const tab = a => { const c = a.cloneNode(true); c.querySelector('span').textContent = SHORT[a.dataset.page]; return c; };
const sheetLinks = links.filter(a => !MAIN.includes(a.dataset.page)).map(a => { const c = a.cloneNode(true); c.className = ''; return c; });
$('tabbar').replaceChildren(...MAIN.map(p => tab(links.find(a => a.dataset.page === p))), more);

const sheet = el('div', { id: 'moreSheet', className: 'sheet', hidden: true, role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Autres pages',
  onmousedown: e => { if (e.target === sheet) close(); }, onclick: e => { if (e.target.closest('a')) close(); } }, [el('div', { className: 'sheet-box' }, sheetLinks)]);
document.body.append(sheet);

function open() { sheet.hidden = false; more.setAttribute('aria-expanded', 'true'); sheet.querySelector('a')?.focus(); }
function close() { if (sheet.hidden) return; sheet.hidden = true; more.setAttribute('aria-expanded', 'false'); more.focus(); }

more.onclick = () => (sheet.hidden ? open() : close());
addEventListener('keydown', e => { if (e.key === 'Escape' && !sheet.hidden) close(); });
addEventListener('hashchange', () => { sheet.hidden = true; more.setAttribute('aria-expanded', 'false'); });

/** The Plus button looks active while one of the pages it holds is open. */
export const markMore = page => more.classList.toggle('on', !MAIN.includes(page));
