/* Transactions page: search, filters, CSV export. */
import { json } from './api.js';
import { $, bubble, el, fail, skel } from './dom.js';
import { clean, dlabel, esc, eur, eur2, mlabel, sign } from './format.js';
import { NONE, all, filtering, isCurrent, memo, page, resetFilters, sel, txf } from './state.js';
import { editor } from './edit.js';
import { PERIODS, buildCsv, periodRange } from './logic.js';

/* The span shown: the selected month, a preset or two chosen dates. {key, url, range} or null (custom dates not chosen yet). */
function span(){
 if(txf.period==='month'){const m=all.months[sel].month;return{key:m,url:'month='+m,range:null}}
 const r=txf.period==='custom'?(txf.from&&txf.to&&txf.from<=txf.to?[txf.from,txf.to]:null):periodRange(txf.period,new Date());
 return r&&{key:r.join('_'),url:`start=${r[0]}&end=${r[1]}`,range:r};
}

function syncPeriod(){
 const fper=$('fper');
 if(!fper.options.length)fper.replaceChildren(...PERIODS.map(([k,n])=>el('option',{value:k,textContent:n})));
 fper.value=txf.period;
 $('fdates').hidden=txf.period!=='custom';$('fFrom').value=txf.from;$('fTo').value=txf.to;
 $('monthnav').hidden=txf.period!=='month';
}

export async function renderTransactions(){
 const month=all.months[sel].month;
 $('selLabel').textContent=mlabel(month,true)+(isCurrent(sel)?' · en cours':'');
 $('prev').disabled=sel===0;$('next').disabled=sel===all.months.length-1;
 syncPeriod();
 $('txReset').hidden=!filtering();
 const sp=span();
 let data=sp?memo.tx[sp.key]:[];
 if(!data){$('txList').replaceChildren(...skel(5));
  try{data=memo.tx[sp.key]=await json('/api/transactions?'+sp.url)}catch(e){fail($('txList'),'Impossible de charger les transactions',renderTransactions);return}}
 txKey=sp?sp.key:'';
 if(page!=='transactions'||(span()?.key||'')!==txKey)return;
 const kind=t=>t.type==='withdrawal'?'expense':t.type==='deposit'?'income':'transfer';
 const cats=[...new Set(data.map(t=>t.category).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'fr'));
 const fcat=$('fcat');
 const none=el('option',{value:NONE,textContent:'Sans catégorie'});
 fcat.replaceChildren(el('option',{value:'',textContent:'Toutes les catégories'}),none,...cats.map(c=>el('option',{value:c,textContent:c})));
 const buds=[...new Set(data.map(t=>t.budget).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'fr'));
 const fbud=$('fbud');
 fbud.replaceChildren(el('option',{value:'',textContent:'Tous les budgets'}),el('option',{value:NONE,textContent:'Sans budget'}),...buds.map(c=>el('option',{value:c,textContent:c})));
 if(txf.cat&&txf.cat!==NONE&&!cats.includes(txf.cat))fcat.append(el('option',{value:txf.cat,textContent:txf.cat}));
 if(txf.bud&&txf.bud!==NONE&&!buds.includes(txf.bud))fbud.append(el('option',{value:txf.bud,textContent:txf.bud}));
 fcat.value=txf.cat;fbud.value=txf.bud;$('q').value=txf.q;
 document.querySelectorAll('#ftype button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.t===txf.type));
 const q=txf.q.trim().toLowerCase();
 const list=data.filter(t=>(txf.type==='all'||kind(t)===txf.type)&&(!txf.cat||(txf.cat===NONE?!t.category:t.category===txf.cat))&&(!txf.bud||(txf.bud===NONE?!t.budget:t.budget===txf.bud))&&(!q||(t.description+' '+(t.category||'')+' '+(t.budget||'')).toLowerCase().includes(q)));
 txShown=list;
 const spent=list.filter(t=>kind(t)==='expense').reduce((a,t)=>a+t.amount,0),got=list.filter(t=>kind(t)==='income').reduce((a,t)=>a+t.amount,0);
 $('txSum').replaceChildren(...(sp&&sp.range?[el('span',{textContent:`Du ${dshort(sp.range[0])} au ${dshort(sp.range[1])}`})]:[]),el('span',{},[el('b',{textContent:list.length}),' opération'+(list.length>1?'s':'')]),el('span',{},['Dépenses ',el('b',{textContent:eur(spent)})]),el('span',{},['Revenus ',el('b',{textContent:eur(got)})]));
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
   if(k!=='transfer')det.append(editor(t));
   const row=el('div',{className:'tx'},[bubble(k==='transfer'?'virement':t.category),el('div',{className:'name'},[el('b',{textContent:clean(t.description)}),el('small',{textContent:sub})]),amt]);
   row.onclick=()=>det.hidden=!det.hidden;out.push(row,det);
  });
 });
 $('txList').replaceChildren(...out);
}

let txShown=[],txKey='';

function exportCsv(){
 const url=URL.createObjectURL(new Blob([buildCsv(txShown)],{type:'text/csv;charset=utf-8'}));
 const a=el('a',{href:url,download:`cairn-transactions-${txKey}.csv`});document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

$('txCsv').onclick=exportCsv;

$('q').addEventListener('input',e=>{txf.q=e.target.value;renderTransactions()});

$('fcat').addEventListener('change',e=>{txf.cat=e.target.value;renderTransactions()});

$('fbud').addEventListener('change',e=>{txf.bud=e.target.value;renderTransactions()});

$('ftype').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;txf.type=b.dataset.t;renderTransactions()});

const dshort=d=>new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short',year:'numeric'}).format(new Date(d+'T12:00:00'));

$('fper').addEventListener('change',e=>{
 txf.period=e.target.value;
 if(txf.period==='custom'&&!(txf.from&&txf.to)){const t=new Date(),iso=d=>d.toISOString().slice(0,10);txf.to=iso(new Date(t.getTime()-t.getTimezoneOffset()*6e4));txf.from=txf.to.slice(0,8)+'01'}
 renderTransactions();
});

$('fFrom').addEventListener('change',e=>{txf.from=e.target.value;renderTransactions()});

$('fTo').addEventListener('change',e=>{txf.to=e.target.value;renderTransactions()});

$('txReset').addEventListener('click',()=>{resetFilters();renderTransactions()});
