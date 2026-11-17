/* Transaction editor: change the category and budget of one transaction, and optionally file the
   next ones the same way with a Firefly III rule. Writes go through POST /api/transaction. */
import { json } from './api.js';
import { el } from './dom.js';
import { clean, eur } from './format.js';
import { hooks, memo } from './state.js';

async function post(body){
 const r=await fetch('/api/transaction',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'dashboard'},body:JSON.stringify(body)});
 const out=await r.json().catch(()=>({}));
 if(!r.ok)throw new Error(out.error||('erreur '+r.status));
 return out;
}

export function toast(text,bad){
 const t=el('div',{className:'toast'+(bad?' bad':''),role:'status',textContent:text});
 document.body.append(t);setTimeout(()=>t.remove(),3500);
}

const picker=(label,names,none,value)=>{
 const s=el('select',{},[el('option',{value:'',textContent:none}),...names.map(n=>el('option',{value:n,textContent:n}))]);
 if(value&&!names.includes(value))s.append(el('option',{value,textContent:value}));
 s.value=value||'';
 return[el('label',{className:'fld'},[el('span',{textContent:label}),s]),s];
};

/* Returns the form for transaction t, or a short message when it cannot be edited. */
export function editor(t){
 const box=el('div',{className:'edit'});
 if(t.category==='Valorisation'){return box}
 const load=async()=>{
  let tax=memo.tax;
  if(!tax){try{tax=memo.tax=await json('/api/taxonomy')}catch(e){box.textContent='Catégories indisponibles';return}}
  const[cf,cat]=picker('Catégorie',tax.categories,'Aucune',t.category);
  const parts=[cf];let bud=null;
  if(t.type==='withdrawal'){const[bf,b]=picker('Budget',tax.budgets,'Aucun',t.budget);bud=b;parts.push(bf)}
  const text=el('input',{type:'text',value:clean(t.description),maxLength:80,'aria-label':'Texte à reconnaître'});
  const rule=el('input',{type:'checkbox'});
  const rl=el('label',{className:'chk2'},[rule,el('span',{textContent:'Classer pareil les prochaines transactions contenant '}),text]);
  const past=el('input',{type:'checkbox'});
  const pastNote=el('span',{textContent:''});
  const pl=el('label',{className:'chk2',hidden:true},[past,pastNote]);
  let timer=0,seq=0;
  const preview=()=>{
   clearTimeout(timer);past.checked=false;pl.hidden=true;
   if(!rule.checked||text.value.trim().length<3||t.type==='transfer')return;
   timer=setTimeout(async()=>{
    const mine=++seq;
    try{const p=await json(`/api/rule-preview?type=${t.type}&text=${encodeURIComponent(text.value)}`);
     if(mine!==seq||!p.count)return;
     pastNote.textContent=`Classer aussi les ${p.count>=2?p.count+' ':''}${p.capped?'(au moins) ':''}transaction${p.count>1?'s':''} passée${p.count>1?'s':''} sans catégorie (12 mois, ${eur(p.amount)})`;
     pl.hidden=false}catch(e){}
   },300);
  };
  rule.onchange=preview;text.oninput=preview;
  const save=el('button',{className:'btn primary small',type:'button',textContent:'Enregistrer'});
  const err=el('span',{className:'err2',role:'alert'});
  const changed=()=>cat.value!==(t.category||'')||(bud&&bud.value!==(t.budget||''));
  save.onclick=async()=>{
   if(!changed()&&!rule.checked){err.textContent='Rien à modifier';return}
   save.disabled=true;err.textContent='';
   try{
    const done=await post({action:'categorize',id:t.id,group:t.group,category:cat.value,budget:bud?bud.value:'',rule:rule.checked?text.value:'',past:rule.checked&&past.checked});
    toast(done.applied?`Enregistré : ${done.applied} transaction${done.applied>1?'s':''} passée${done.applied>1?'s':''} classée${done.applied>1?'s':''}, et une règle classera les prochaines`:rule.checked?'Enregistré, et une règle classera les prochaines':'Catégorie enregistrée');
    hooks.reload();
   }catch(e){err.textContent=e.message;save.disabled=false}
  };
  box.replaceChildren(el('div',{className:'edit-row'},parts),rl,pl,el('div',{className:'edit-row'},[save,err]));
 };
 box.append(el('button',{className:'btn small',type:'button',textContent:'Modifier la catégorie',onclick:e=>{e.stopPropagation();e.target.remove();load()}}));
 return box;
}
