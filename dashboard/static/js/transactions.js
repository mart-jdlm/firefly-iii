/* Transactions page: search, filters, CSV export. */
import { json } from './api.js';
import { $, bubble, el, fail, skel } from './dom.js';
import { clean, dlabel, esc, eur, eur2, mlabel, sign } from './format.js';
import { all, isCurrent, memo, page, sel, txf } from './state.js';
import { buildCsv } from './logic.js';

export async function renderTransactions(){
 const month=all.months[sel].month;
 $('selLabel').textContent=mlabel(month,true)+(isCurrent(sel)?' · en cours':'');
 $('prev').disabled=sel===0;$('next').disabled=sel===all.months.length-1;
 let data=memo.tx[month];
 if(!data){$('txList').replaceChildren(...skel(5));
  try{data=memo.tx[month]=await json('/api/transactions?month='+month)}catch(e){fail($('txList'),'Impossible de charger les transactions',renderTransactions);return}}
 if(month!==all.months[sel].month||page!=='transactions')return;
 const kind=t=>t.type==='withdrawal'?'expense':t.type==='deposit'?'income':'transfer';
 const cats=[...new Set(data.map(t=>t.category).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'fr'));
 const fcat=$('fcat');
 fcat.replaceChildren(el('option',{value:'',textContent:'Toutes les catégories'}),...cats.map(c=>el('option',{value:c,textContent:c})));
 if(txf.cat&&!cats.includes(txf.cat))fcat.append(el('option',{value:txf.cat,textContent:txf.cat}));
 fcat.value=txf.cat;$('q').value=txf.q;
 document.querySelectorAll('#ftype button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.t===txf.type));
 const q=txf.q.trim().toLowerCase();
 const list=data.filter(t=>(txf.type==='all'||kind(t)===txf.type)&&(!txf.cat||t.category===txf.cat)&&(!q||(t.description+' '+(t.category||'')+' '+(t.budget||'')).toLowerCase().includes(q)));
 txShown=list;
 const spent=list.filter(t=>kind(t)==='expense').reduce((a,t)=>a+t.amount,0),got=list.filter(t=>kind(t)==='income').reduce((a,t)=>a+t.amount,0);
 $('txSum').replaceChildren(el('span',{},[el('b',{textContent:list.length}),' opération'+(list.length>1?'s':'')]),el('span',{},['Dépenses ',el('b',{textContent:eur(spent)})]),el('span',{},['Revenus ',el('b',{textContent:eur(got)})]));
 if(!list.length){$('txList').replaceChildren(el('div',{className:'empty',textContent:'Aucune transaction ne correspond'}));return}
 const byDay={};list.forEach(t=>(byDay[t.date]=byDay[t.date]||[]).push(t));
 const out=[];
 Object.keys(byDay).sort().reverse().forEach(d=>{
  const net=byDay[d].reduce((a,t)=>a+(kind(t)==='expense'?-t.amount:kind(t)==='income'?t.amount:0),0);
  out.push(el('div',{className:'day'},[el('span',{textContent:dlabel(d)}),el('span',{textContent:net?sign(net):''})]));
  byDay[d].forEach(t=>{
   const k=kind(t),amt=el('span',{className:'amt'+(k==='income'?' in':''),textContent:(k==='expense'?'−':k==='income'?'+':'')+eur2(t.amount)});
   const sub=[t.category,t.budget].filter(Boolean).join(' · ')||(k==='transfer'?'Virement entre comptes':'Sans catégorie');
   const det=el('div',{className:'det',hidden:true});
   det.innerHTML=`<b>Libellé</b> : ${esc(t.description)}<br><b>${esc(t.source)}</b> → <b>${esc(t.destination)}</b>`+(t.notes?`<br><b>Note</b> : ${esc(t.notes)}`:'');
   const row=el('div',{className:'tx'},[bubble(k==='transfer'?'virement':t.category),el('div',{className:'name'},[el('b',{textContent:clean(t.description)}),el('small',{textContent:sub})]),amt]);
   row.onclick=()=>det.hidden=!det.hidden;out.push(row,det);
  });
 });
 $('txList').replaceChildren(...out);
}

let txShown=[];

function exportCsv(){
 const url=URL.createObjectURL(new Blob([buildCsv(txShown)],{type:'text/csv;charset=utf-8'}));
 const a=el('a',{href:url,download:`cairn-transactions-${all.months[sel].month}.csv`});document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

$('txCsv').onclick=exportCsv;

$('q').addEventListener('input',e=>{txf.q=e.target.value;renderTransactions()});

$('fcat').addEventListener('change',e=>{txf.cat=e.target.value;renderTransactions()});

$('ftype').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;txf.type=b.dataset.t;renderTransactions()});
