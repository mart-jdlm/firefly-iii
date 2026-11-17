/* Private mode: blurs every amount on the page (and its tooltips) for when someone can see the
   screen. A page draws its figures in many ways (text, SVG, canvas), so instead of tagging each
   one this finds every element whose own text holds a euro sign and marks it, again after every
   redraw. The choice is kept on this device. */
import { all, hooks } from './state.js';
import { $ } from './dom.js';

const KEY = 'cairn-private';
let on = false, queued = false;

const stored = () => { try { return localStorage.getItem(KEY) === '1'; } catch (e) { return false; } };
const store = v => { try { localStorage.setItem(KEY, v ? '1' : '0'); } catch (e) { /* private window: not kept */ } };

function hideTooltips(root) {
  root.querySelectorAll('[title]').forEach(e => { if (e.getAttribute('title').includes('€')) { e.dataset.title = e.getAttribute('title'); e.removeAttribute('title'); } });
  root.querySelectorAll('svg title').forEach(t => { if (t.textContent.includes('€')) { t.dataset.text = t.textContent; t.textContent = ''; } });
}

function mark() {
  queued = false;
  if (!on) return;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: n => n.nodeValue.includes('€') && !/^(SCRIPT|STYLE|TITLE|TEXTAREA)$/.test(n.parentElement?.tagName) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
  for (let n = walker.nextNode(); n; n = walker.nextNode()) n.parentElement.classList.add('mny');
  hideTooltips(document.body);
}

const observer = new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(mark); } });

function restore() {
  document.querySelectorAll('.mny').forEach(e => e.classList.remove('mny'));
  document.querySelectorAll('[data-title]').forEach(e => { e.setAttribute('title', e.dataset.title); delete e.dataset.title; });
  document.querySelectorAll('svg title[data-text]').forEach(t => { t.textContent = t.dataset.text; delete t.dataset.text; });
}

export function setPrivate(value) {
  const was = on;
  on = value;
  document.body.classList.toggle('priv', on);
  const b = $('privBtn');
  b.setAttribute('aria-pressed', on);
  b.textContent = on ? '🙈' : '👁';
  b.title = on ? 'Afficher les montants' : 'Masquer les montants';
  b.setAttribute('aria-label', b.title);
  store(on);
  if (on) { observer.observe(document.body, { childList: true, subtree: true, characterData: true }); mark(); }
  else { observer.disconnect(); restore(); if (was && all) hooks.render(); }
}

export const togglePrivate = () => setPrivate(!on);

$('privBtn').onclick = togglePrivate;
setPrivate(stored());
