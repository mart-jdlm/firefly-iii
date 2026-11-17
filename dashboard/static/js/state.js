/* Shared state of the page. ES modules cannot assign to what they import, so every value that
   changes (the loaded data, the selected month, the page, the range) is written through a setter
   here and read as a live binding everywhere else. */
export let range = 12, all = null, sel = 0, page = 'overview', offline = false;
export const charts = {};
export const memo = { tx: {}, bud: {}, flow: {}, bills: null, pea: null, goals: null };
export const txf = { q: '', cat: '', type: 'all' };
// main.js registers the page renderer here, so pages can ask for a redraw without importing it
export const hooks = { render: () => {} };

export const setRange = v => { range = v; };
export const setAll = v => { all = v; };
export const setSel = v => { sel = v; };
export const setPage = v => { page = v; };
export const setOffline = v => { offline = v; };

export const shown = () => all.months.slice(-range);
export const isCurrent = i => i === all.months.length - 1;
export function setMonth(i) { sel = Math.max(0, Math.min(all.months.length - 1, i)); hooks.render(); }
export function gotoCategory(cat) { txf.cat = cat; txf.type = 'all'; txf.q = ''; location.hash = '#/transactions'; }
