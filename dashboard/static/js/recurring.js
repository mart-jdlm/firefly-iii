/* Récurrent page: upcoming payments, subscriptions, piggy banks. */
import { json } from './api.js';
import { $, bubble, css, el, fail, pill } from './dom.js';
import { eur, eur2 } from './format.js';
import { memo, page } from './state.js';
import { PER_MONTH, billCost, sortBills } from './logic.js';

const FREQ={monthly:'Mensuel',yearly:'Annuel',weekly:'Hebdo',quarterly:'Trimestriel','half-year':'Semestriel'};

let billSort='cost';

export async function renderRecurring(){
 let d=memo.bills;
 try{if(!d)d=memo.bills=await json('/api/bills')}catch(e){fail($('upcoming'),'Prélèvements indisponibles',renderRecurring);fail($('billList'),'Abonnements indisponibles',renderRecurring);return}
 if(page!=='recurring')return;
 const today=new Date();today.setHours(12,0,0,0);
 const days=s=>Math.round((new Date(s+'T12:00:00')-today)/864e5);
 const in30=d.upcoming.filter(u=>days(u.date)<=30);
 const monthly=d.bills.reduce((a,b)=>a+b.amount*(PER_MONTH[b.frequency]||1),0);
 $('rNext').textContent=eur2(in30.reduce((a,u)=>a+u.amount,0));pill('rNextN',`${in30.length} prélèvement${in30.length>1?'s':''}`);
 $('rMonth').textContent=eur2(monthly);pill('rMonthN',`${d.bills.length} abonnement${d.bills.length>1?'s':''}`);
 $('rYear').textContent=eur(monthly*12);
 $('upcoming').replaceChildren(...(d.upcoming.length?d.upcoming.map(u=>{
  const dt=new Date(u.date+'T12:00:00'),n=days(u.date);
  const date=el('div',{className:'date'},[el('div',{},[el('b',{textContent:dt.getDate()}),el('small',{textContent:new Intl.DateTimeFormat('fr-FR',{month:'short'}).format(dt).replace('.','')})])]);
  return el('div',{className:'item'},[date,el('span',{className:'name'},[u.name,el('small',{textContent:n<=0?"aujourd'hui":n===1?'demain':`dans ${n} jours`})]),el('span',{className:'amt',textContent:eur2(u.amount)})]);
 }):[el('div',{className:'empty',textContent:'Rien de prévu'})]));
 document.querySelectorAll('#bSort button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.s===billSort));
 const sorted=sortBills(d.bills,billSort);
 const billRows=[];let lastFreq=null;
 sorted.forEach(b=>{
  if(billSort==='freq'&&b.frequency!==lastFreq){lastFreq=b.frequency;billRows.push(el('div',{className:'sep',textContent:FREQ[b.frequency]||b.frequency}))}
  billRows.push(el('div',{className:'item'},[bubble(b.name),el('span',{className:'name'},[b.name,el('small',{textContent:(FREQ[b.frequency]||b.frequency)+' · '+(b.min===b.max?eur2(b.min):`${eur2(b.min)} à ${eur2(b.max)}`)})]),el('span',{className:'chip',textContent:FREQ[b.frequency]||b.frequency}),el('span',{className:'amt',textContent:eur2(billCost(b))+'/mois'})]));
 });
 $('billList').replaceChildren(...(billRows.length?billRows:[el('div',{className:'empty',textContent:'Aucun abonnement déclaré'})]));
 $('piggies').replaceChildren(...(d.piggies.length?d.piggies.map(p=>{
  const pct=p.target?Math.min(p.current/p.target*100,100):0,track=el('div',{className:'track'},[el('span')]);
  track.firstChild.style.cssText=`width:${pct}%;background:${pct>=100?css('--up'):css('--accent')}`;
  return el('div',{className:'bud'},[el('div',{className:'row'},[el('b',{textContent:p.name}),el('span',{textContent:`${eur(p.current)} sur ${eur(p.target)}`})]),track,
   el('div',{className:'left',textContent:pct>=100?'Objectif atteint 🎉':`${Math.round(pct)} % · reste ${eur(p.target-p.current)}`+(p.date?` · avant le ${new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'long',year:'numeric'}).format(new Date(p.date+'T12:00:00'))}`:'')})]);
 }):[el('div',{className:'empty',textContent:'Aucune tirelire'})]));
}

$('bSort').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;billSort=b.dataset.s;renderRecurring()});
