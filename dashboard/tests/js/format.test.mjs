import { test } from 'node:test';
import assert from 'node:assert/strict';
import { avg, clean, dlabel, esc, eur, eur2, icon, mlabel, sign } from '../../static/js/format.js';

// Intl puts narrow no-break spaces in French numbers: compare with plain spaces.
const plain = s => s.replace(/[  ]/g, ' ');

test('eur formats euros the French way', () => {
  assert.equal(plain(eur(1234)), '1 234 €');
  assert.equal(plain(eur(-5, 2)), '-5,00 €');
  assert.equal(plain(eur(0)), '0 €');
});

test('eur2 shows cents only for small non-round amounts', () => {
  assert.equal(plain(eur2(50.5)), '50,50 €');
  assert.equal(plain(eur2(50)), '50 €');
  assert.equal(plain(eur2(150.4)), '150 €');
});

test('sign always shows the direction, with a real minus sign', () => {
  assert.equal(plain(sign(5)), '+5 €');
  assert.equal(plain(sign(-5)), '−5 €');
  assert.equal(plain(sign(0)), '0 €');
});

test('month and day labels are in French', () => {
  assert.equal(mlabel('2026-10', true), 'octobre 2026');
  assert.equal(mlabel('2026-10'), 'oct. 26');
  assert.equal(dlabel('2026-10-28'), 'mercredi 28 octobre');
});

test('avg of nothing is 0', () => {
  assert.equal(avg([]), 0);
  assert.equal(avg([1, 2, 3]), 2);
});

test('esc neutralises HTML', () => {
  assert.equal(esc('<a href="x">&\'</a>'), '&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;');
  assert.equal(esc(null), '');
  assert.equal(esc(undefined), '');
});

test('clean turns bank labels into readable names', () => {
  assert.equal(clean('PAIEMENT PAR CARTE X1234 CARREFOUR CITY'), 'Carrefour City');
  assert.equal(clean('Paiement par carte x5678 Boulangerie'), 'Boulangerie');
  assert.equal(clean('PRELEVEMENT EUROPEEN AXA ASSURANCE'), 'Axa Assurance');
  assert.equal(clean('Virement en votre faveur Salaire 12/10 - ref'), 'Virement · Salaire');
  assert.equal(clean('VIREMENT EMIS VIR INST VERS PAPA'), 'Virement · PAPA');
  assert.equal(clean('A'.repeat(20) + ' Loyer'), 'Loyer', 'long reference codes are dropped');
});

test('clean falls back to the original label when nothing is left', () => {
  assert.equal(clean(''), '');
  assert.equal(clean('PAIEMENT PAR CARTE X1234'), 'PAIEMENT PAR CARTE X1234');
});

test('icon picks an emoji by category, else the first letter', () => {
  assert.equal(icon('Courses Alimentaires'), '🛒');
  assert.equal(icon('Abonnements'), '🔁');
  assert.equal(icon('Zzz'), 'Z');
  assert.equal(icon(''), '?');
  assert.equal(icon(null), '?');
});
