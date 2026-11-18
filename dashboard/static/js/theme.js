/* Theme: automatic (follows the system), light or dark. The button cycles through the three; the
   choice is kept on this device. index.html applies it before the first paint, so there is no flash. */
import { $ } from './dom.js';
import { all, hooks } from './state.js';

const KEY = 'cairn-theme';
const MODES = ['auto', 'light', 'dark'];
const LABEL = { auto: 'Thème : automatique', light: 'Thème : clair', dark: 'Thème : sombre' };
const GLYPH = { auto: '◐', light: '☀', dark: '☾' };

const stored = () => { try { const v = localStorage.getItem(KEY); return MODES.includes(v) ? v : 'auto'; } catch (e) { return 'auto'; } };
const store = v => { try { v === 'auto' ? localStorage.removeItem(KEY) : localStorage.setItem(KEY, v); } catch (e) { /* private window: not kept */ } };

let mode = stored();

export const themeMode = () => mode;

export function setTheme(value) {
  mode = value;
  if (mode === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = mode;
  const b = $('themeBtn');
  b.textContent = GLYPH[mode];
  b.title = LABEL[mode] + ' (cliquer pour changer)';
  b.setAttribute('aria-label', b.title);
  store(mode);
  if (all) hooks.render(); // charts read their colours when drawn
}

export const cycleTheme = () => setTheme(MODES[(MODES.indexOf(mode) + 1) % MODES.length]);

$('themeBtn').onclick = cycleTheme;
setTheme(mode);
