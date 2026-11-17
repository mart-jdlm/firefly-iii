/* Avenir page: savings simulator, piggy banks (goals), levers. */
import { json } from './api.js';
import { $, bubble, css, el, fail, mk } from './dom.js';
import { avg, eur, eur2, mlabel } from './format.js';
import { all, memo, page } from './state.js';
import { project } from './logic.js';

const fut={S:null,share:0,rc:1.7,rp:5,years:10,infl:false,levers:{},ready:false};

const addMonths=(d,n)=>{const x=new Date(d.getFullYear(),d.getMonth()+n,1);return x};

const dlong=iso=>new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'long',year:'numeric'}).format(new Date(iso+'T12:00:00'));

const mlong=iso=>new Intl.DateTimeFormat('fr-FR',{month:'long',year:'numeric'}).format(new Date(iso+'T12:00:00'));


function leverGain(){return Object.values(fut.levers).reduce((a,l)=>a+l.gain,0)}

function lastDone(n){return all.months.slice(-1-n,-1)}

function initFuture(){
 const saved=lastDone(6).map(m=>m.saved),base=Math.max(0,Math.round(avg(saved)/10)*10);
 fut.S0=base;fut.S=base;fut.ready=true;
 $('fS').value=fut.S;$('fYears').value=fut.years;$('fShare').value=Math.round(fut.share*100);$('fRc').value=fut.rc;$('fRp').value=fut.rp;$('fInfl').checked=fut.infl;
 const avg3=avg(lastDone(3).map(m=>m.saved)),lastM=lastDone(1)[0].saved;fut.avg3=Math.max(0,avg3);
 $('fSHint').replaceChildren('Utiliser : ',...[['moy. 6 mois',avg(saved)],['3 derniers mois',avg3],['dernier mois',lastM]].map(([n,v])=>{
  const b=el('button',{type:'button',className:'chip pick',textContent:`${n} ${eur(v)}`});b.onclick=e=>{e.preventDefault();$('fS').value=Math.max(0,Math.round(v/10)*10);$('fS').dispatchEvent(new Event('input'))};return b}));
 const read=()=>{fut.S=Math.max(0,parseFloat($('fS').value)||0);fut.years=+$('fYears').value;fut.share=+$('fShare').value/100;
  fut.rc=parseFloat($('fRc').value)||0;fut.rp=parseFloat($('fRp').value)||0;fut.infl=$('fInfl').checked;updateFuture()};
 ['fS','fYears','fShare','fRc','fRp','fInfl'].forEach(id=>$(id).addEventListener('input',read));
}

function updateFuture(){
 const last=all.months[all.months.length-1].net_worth;
 const cash0=last.courant+last.epargne,pea0=last.investissements,debts=last.dettes;
 const S=fut.S+leverGain(),Y=fut.years;
 $('fYearsV').textContent=Y+(Y>1?' ans':' an');$('fShareV').textContent=Math.round(fut.share*100)+' %';
 const now=new Date();$('fEnd').textContent=new Intl.DateTimeFormat('fr-FR',{month:'long',year:'numeric'}).format(addMonths(now,Y*12));
 const mid=project(S,fut.share,fut.rc,fut.rp,Y,cash0,pea0,debts,fut.infl),
  low=project(S,fut.share,Math.max(fut.rc-.5,0),fut.rp-3,Y,cash0,pea0,debts,fut.infl),
  high=project(S,fut.share,fut.rc+.5,fut.rp+3,Y,cash0,pea0,debts,fut.infl);
 const end=mid[mid.length-1],start=mid[0].nw,gain=end.nw-start,interest=gain-end.paid;
 const yearOf=addMonths(now,Y*12).getFullYear();
 $('fHead').innerHTML=`En <b>${yearOf}</b>, ton patrimoine pourrait atteindre environ <b>${eur(end.nw)}</b>${fut.infl?" (en euros d'aujourd'hui)":''}, `+
  `entre ${eur(low[low.length-1].nw)} et ${eur(high[high.length-1].nw)} selon les marchés. `+
  (fut.infl?`Tu verseras <b>${eur(end.paid)}</b> sur la période.`:`Sur ${eur(gain)} de croissance, <b>${eur(end.paid)}</b> viendront de tes versements et <b>${eur(Math.max(interest,0))}</b> des intérêts et de la performance.`)+
  (leverGain()>0?` <br><small style="color:var(--mute)">Dont ${eur(leverGain())} par mois grâce aux leviers choisis plus bas.</small>`:'');

 // chart: 12 months of history, then the projection
 const hist=all.months.slice(-12),step=Y<=5?1:Y<=15?3:6;
 const idx=[];for(let i=0;i<=Y*12;i+=step)idx.push(i);if(idx[idx.length-1]!==Y*12)idx.push(Y*12);
 const labels=[...hist.map(r=>mlabel(r.month)),...idx.slice(1).map(i=>new Intl.DateTimeFormat('fr-FR',{month:'short',year:'2-digit'}).format(addMonths(now,i)))];
 const pad=hist.length-1,nulls=n=>Array(n).fill(null);
 const series=arr=>[...nulls(pad),arr[0].nw,...idx.slice(1).map(i=>arr[i].nw)];
 mk('cFuture',{type:'line',data:{labels,datasets:[
  {label:'Prudent',data:series(low),borderColor:css('--accent')+'55',borderWidth:1,pointRadius:0,tension:.2,fill:false},
  {label:'Optimiste',data:series(high),borderColor:css('--accent')+'55',borderWidth:1,pointRadius:0,tension:.2,fill:'-1',backgroundColor:css('--accent2')},
  {label:'Centrale',data:series(mid),borderColor:css('--accent'),borderWidth:3,pointRadius:0,pointHoverRadius:5,tension:.2,fill:false},
  {label:'Historique',data:[...hist.map(r=>r.net_worth.total),...nulls(idx.length-1)],borderColor:css('--fg'),borderWidth:2.5,pointRadius:0,pointHoverRadius:5,tension:.25,fill:false}]},
  options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},
   plugins:{legend:{display:false},tooltip:{backgroundColor:css('--fg'),titleColor:css('--bg'),bodyColor:css('--bg'),padding:10,cornerRadius:10,filter:c=>c.parsed.y!==null,itemSort:(a,b)=>b.parsed.y-a.parsed.y,callbacks:{label:c=>` ${c.dataset.label} : ${eur(c.parsed.y)}`}}},
   scales:{x:{grid:{display:false},border:{display:false},ticks:{color:css('--mute'),maxRotation:0,autoSkip:true,maxTicksLimit:8}},y:{grid:{color:css('--line')},border:{display:false},ticks:{color:css('--mute'),callback:v=>eur(v),maxTicksLimit:6}}}}});

 // milestones
 const marks=[...new Set([1,3,5,10,Y].filter(y=>y<=Y))].sort((a,b)=>a-b).slice(-4);
 $('fMiles').replaceChildren(...marks.map(y=>{const i=y*12,m=mid[i];
  return el('div',{className:'mile'},[el('div',{className:'when2',textContent:`Dans ${y} an${y>1?'s':''} · ${addMonths(now,i).getFullYear()}`}),el('div',{className:'val',textContent:eur(m.nw)}),
   el('small',{textContent:`entre ${eur(low[i].nw)} et ${eur(high[i].nw)}`}),el('small',{textContent:fut.infl?`${eur(m.paid)} versés`:`${eur(m.paid)} versés · ${eur(Math.max(m.nw-start-m.paid,0))} de croissance`})])}));
 renderLeverSum();
}

function renderLevers(){
 const done=lastDone(3),cats={};
 done.forEach(m=>Object.entries(m.expenses).forEach(([c,v])=>cats[c]=(cats[c]||0)+v/done.length));
 const top=Object.entries(cats).filter(([c])=>c!=='(sans catégorie)').sort((a,b)=>b[1]-a[1]).slice(0,6);
 $('levers').replaceChildren(...top.map(([c,avgv])=>{
  const g=el('span',{className:'gain'}),setPct=pct=>{if(pct)fut.levers[c]={pct,gain:avgv*pct/100};else delete fut.levers[c];
   g.textContent=pct?`+${eur(avgv*pct/100)}/mois`:'';row.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',+b.dataset.p===pct));updateFuture()};
  const seg=el('div',{className:'seg2'},[0,10,20,30].map(p=>{const b=el('button',{type:'button',textContent:p?`−${p} %`:'Aucune',onclick:()=>setPct(p)});b.dataset.p=p;b.setAttribute('aria-pressed',p===0);return b}));
  const row=el('div',{className:'lrow'},[bubble(c),el('span',{className:'name'},[c,el('small',{textContent:`${eur(avgv)} par mois en moyenne`})]),seg,g]);
  return row}));
}

function renderLeverSum(){
 const g=leverGain(),Y=fut.years,mc=Math.pow(1+fut.rc/100,1/12)-1,n=Y*12;
 const fv=g*(mc?(Math.pow(1+mc,n)-1)/mc:n);
 $('lSum').innerHTML=g>0?`En réduisant ces dépenses, tu libères <b>${eur(g)} par mois</b>, soit environ <b>${eur(fv)}</b> de plus dans ${Y} an${Y>1?'s':''} (placés sur un livret à ${String(fut.rc).replace('.',',')} %). C'est déjà compté dans le simulateur.`
  :`Aucun levier choisi. Un petit effort sur une seule catégorie, répété chaque mois, finit par peser lourd.`;
}

/* goals = Firefly III piggy banks (tirelires) */

const STATUS={reached:['Atteint ✓','up'],on_track:['Dans les temps','up'],late:['En retard','warn'],stalled:['Sans progrès','']};

let editing=null;

async function renderGoals(){
 let d=memo.goals;
 try{if(!d)d=memo.goals=await json('/api/goals')}catch(e){fail($('goals'),'Tirelires indisponibles',renderGoals);return}
 if(page!=='future')return;
 const keep=$('gAcc').value;
 $('gAcc').replaceChildren(...d.accounts.map(a=>el('option',{value:a.name,textContent:`${a.name} · ${eur2(a.free)} libre`})));
 if(keep)$('gAcc').value=keep;
 const capacity=fut.S0||0,due=d.goals.filter(g=>g.status!=='reached'&&g.needed_monthly),need=due.reduce((a,g)=>a+g.needed_monthly,0);
 const best=Math.max(capacity,fut.avg3||0);
 $('gSummary').textContent=!d.goals.length?'Aucune tirelire pour le moment.':
  due.length?`Pour tenir tes échéances, il faut ${eur(need)} par mois. Ton épargne est de ${eur(capacity)} par mois en moyenne sur 6 mois (${eur(fut.avg3||0)} sur les 3 derniers)${need<=capacity?' : c\'est jouable.':need<=best?' : c\'est jouable à ton rythme récent.':' : il manque '+eur(need-best)+' par mois. Décale une échéance ou utilise les leviers plus bas.'}`
  :`${d.goals.length} tirelire${d.goals.length>1?'s':''} suivie${d.goals.length>1?'s':''}.`;
 $('goals').replaceChildren(...(d.goals.length?d.goals.map(g=>{
  const pct=g.target?Math.min(g.balance/g.target*100,100):0,[label,cls]=STATUS[g.status]||['',''];
  const track=el('div',{className:'track'},[el('span')]);track.firstChild.style.cssText=`width:${pct}%;background:${g.status==='reached'?css('--up'):g.status==='late'?css('--c5'):css('--accent')}`;
  const facts=[['Rythme actuel',`${g.pace>=0?'+':'−'}${eur(Math.abs(g.pace))} / mois`]];
  if(g.eta)facts.push(['Arrivée estimée',mlong(g.eta)]);
  if(g.deadline)facts.push(['Échéance',dlong(g.deadline)]);
  if(g.needed_monthly)facts.push(['Pour tenir l\'échéance',`${eur(g.needed_monthly)} / mois`]);
  const head=el('div',{className:'gh'},[el('div',{className:'bubble',textContent:'🎯'}),el('div',{className:'gt'},[el('b',{textContent:g.name}),el('small',{textContent:(g.kind==='piggy'?'Tirelire · ':'Objectif sur compte · ')+g.source})]),el('span',{className:'pill '+cls,textContent:label})]);
  let act=null;
  if(g.kind==='piggy'){
   const amt=el('input',{type:'number',min:'0',step:'1',placeholder:'Montant',inputMode:'decimal',className:'mini'});
   const msg=el('small',{className:'down'});
   const go=sign=>async()=>{const v=parseFloat(amt.value);if(!(v>0)){msg.textContent='Entre un montant';return}
    try{await gPost({action:'move',name:g.name,amount:sign*v});renderGoals()}catch(e){msg.textContent=e.message}};
   act=el('div',{className:'gact'},[amt,el('button',{className:'btn small primary',type:'button',textContent:'Verser',onclick:go(1)}),el('button',{className:'btn small',type:'button',textContent:'Retirer',onclick:go(-1)}),
    el('button',{className:'btn small',type:'button',textContent:'Modifier',onclick:()=>openGoalForm(g)}),el('button',{className:'btn small',type:'button',textContent:'Supprimer',onclick:()=>removeGoal(g.name)}),
    el('small',{textContent:g.free!==null&&g.free!==undefined?`Libre sur le compte : ${eur2(g.free)}`:''}),msg]);
  }
  return el('div',{className:'goal'},[head,track,el('div',{className:'gnums'},[el('span',{},[el('b',{textContent:eur2(g.balance)}),' sur '+eur(g.target)]),el('span',{textContent:Math.round(pct)+' %'})]),
   el('div',{className:'facts'},facts.map(([k,v])=>el('span',{},[k+' : ',el('b',{textContent:v})]))),...(act?[act]:[])]);
 }):[el('div',{className:'empty',textContent:'Crée ta première tirelire avec le bouton ci-dessus.'})]));
}

function openGoalForm(g){
 editing=g?g.name:null;
 $('gForm').hidden=false;$('gErr').textContent='';
 $('gName').value=g?g.name:'';$('gTarget').value=g?g.target:'';$('gDate').value=g?.deadline||'';
 $('gAcc').disabled=!!g;if(g)$('gAcc').value=g.source;
 $('gSave').textContent=g?'Enregistrer les modifications':'Créer la tirelire';$('gName').focus();
}

async function gPost(body){
 const r=await fetch('/api/piggy',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'dashboard'},body:JSON.stringify(body)});
 if(!r.ok)throw new Error((await r.json().catch(()=>({}))).error||('erreur '+r.status));
 memo.goals=null;
}

async function removeGoal(name){
 if(!confirm(`Supprimer la tirelire « ${name} » ? L'argent reste sur le compte.`))return;
 try{await gPost({action:'delete',name});renderGoals()}catch(e){alert('Suppression impossible : '+e.message)}
}

$('gNew').onclick=()=>openGoalForm(null);

$('gCancel').onclick=()=>{$('gForm').hidden=true};

$('gForm').onsubmit=async e=>{e.preventDefault();$('gErr').textContent='';
 const name=$('gName').value.trim(),target=parseFloat($('gTarget').value),date=$('gDate').value||null;
 try{
  if(editing)await gPost({action:'update',name:editing,new_name:name!==editing?name:null,target,date});
  else await gPost({action:'create',name,account:$('gAcc').value,target,date});
  $('gForm').hidden=true;renderGoals()}catch(err){$('gErr').textContent='Impossible d\'enregistrer : '+err.message}};

export function renderFuture(){
 if(!fut.ready){initFuture();renderLevers()}
 updateFuture();renderGoals();
}
