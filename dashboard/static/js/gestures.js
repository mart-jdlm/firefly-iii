/* Touch gestures (phones and tablets): swipe sideways to move between pages, pull down at the top
   to refresh, swipe a sheet or dialog down to close it. Nothing happens on a swipe that starts on a
   chart, a form control, a horizontally scrolling area or the assistant, so those keep working. */
import { $, el } from './dom.js';

const ORDER = [...document.querySelectorAll('#nav a')].map(a => a.dataset.page);
const SKIP = 'canvas, input, select, textarea, .seg2, .ranges, .sankey-wrap, .toolbar, .chat, [data-noswipe]';
const SWIPE = 90, PULL = 110;

const hint = el('div', { id: 'ptr', role: 'status', textContent: '↓ Relâche pour actualiser' });
document.body.append(hint);

let start = null;

const scrollsSideways = node => {
  for (let e = node; e && e !== document.body; e = e.parentElement) {
    const o = getComputedStyle(e).overflowX;
    if ((o === 'auto' || o === 'scroll') && e.scrollWidth > e.clientWidth + 1) return true;
  }
  return false;
};

addEventListener('touchstart', e => {
  if (e.touches.length !== 1) { start = null; return; }
  const t = e.touches[0], target = e.target;
  start = { x: t.clientX, y: t.clientY, at: Date.now(), target, top: scrollY <= 0,
    overlay: target.closest('.sheet, .md, .sr'), skip: !!target.closest(SKIP) || scrollsSideways(target) };
}, { passive: true });

addEventListener('touchmove', e => {
  if (!start || start.overlay || start.skip || !start.top) return;
  const dy = e.touches[0].clientY - start.y, dx = e.touches[0].clientX - start.x;
  hint.classList.toggle('on', dy > PULL && Math.abs(dx) < dy / 2);
}, { passive: true });

addEventListener('touchend', e => {
  const s = start; start = null; hint.classList.remove('on');
  if (!s || !e.changedTouches.length) return;
  const dx = e.changedTouches[0].clientX - s.x, dy = e.changedTouches[0].clientY - s.y;
  if (s.overlay) {  // a sheet or dialog: swipe down closes it (their own handlers close on a press of the backdrop)
    const box = s.target.closest('.sheet-box, .md-box, .sr-box');
    if (dy > SWIPE && dy > 2 * Math.abs(dx) && !(box && box.scrollTop > 0)) s.overlay.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    return;
  }
  if (s.skip || document.querySelector('.sheet:not([hidden]), .md, .sr') || !$('chat').hidden) return;
  if (Math.abs(dx) > SWIPE && Math.abs(dx) > 2 * Math.abs(dy) && Date.now() - s.at < 700) {
    const here = ORDER.indexOf(location.hash.replace('#/', '') || 'overview'), next = ORDER[here + (dx < 0 ? 1 : -1)];
    if (here >= 0 && next) location.hash = '#/' + next;
  } else if (s.top && dy > PULL && dy > 2 * Math.abs(dx) && scrollY <= 0) {
    $('refresh').click();
  }
}, { passive: true });
