/* Shared state of the page. ES modules cannot assign to what they import, so every value that
   changes (the loaded data, the selected month, the page, the range) is written through a setter
   here and read as a live binding everywhere else. */
export let range = 12, all = null, sel = 0, page = 'overview', offline = false;
export const charts = {};
export const memo = { reviews: null, review: {}, alerts: null, tax: null, tx: {}, bud: {}, flow: {}, bills: null, pea: null, goals: null };
// txf.cat / txf.bud: '' = any, NONE = transactions without a category / budget
export const NONE = '__none__';
// period: a key of PERIODS; from / to hold the dates of the custom one
export const txf = { q: '', cat: '', bud: '', type: 'all', period: 'month', from: '', to: '' };
// main.js registers the page renderer here, so pages can ask for a redraw without importing it
export const hooks = { render: () => {}, reload: () => {} };

export const setRange = v => { range = v; };
export const setAll = v => { all = v; };
export const setSel = v => { sel = v; };
export const setPage = v => { page = v; };
export const setOffline = v => { offline = v; };

export const shown = () => all.months.slice(-range);
export const isCurrent = i => i === all.months.length - 1;
export function setMonth(i) { sel = Math.max(0, Math.min(all.months.length - 1, i)); hooks.render(); }
export const nav = { keep: false };  // true while a link has just set the Transactions filters
export const resetFilters = () => Object.assign(txf, { q: '', cat: '', bud: '', type: 'all', period: 'month' });
export const filtering = () => !!(txf.q || txf.cat || txf.bud || txf.type !== 'all' || txf.period !== 'month');
export function gotoTransactions(filters) {
  resetFilters(); Object.assign(txf, filters); nav.keep = true;
  if (location.hash === '#/transactions') hooks.render(); else location.hash = '#/transactions';
}
export const gotoCategory = cat => gotoTransactions({ cat: cat === '(sans catégorie)' ? NONE : cat });
export const gotoBudget = bud => gotoTransactions({ bud: bud === 'Sans budget' ? NONE : bud, type: 'expense' });
