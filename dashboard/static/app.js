"use strict";
const $=id=>document.getElementById(id);
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const nf=d=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:d,minimumFractionDigits:d});
const eur=(v,d=0)=>nf(d).format(v);
const eur2=v=>eur(v,Math.abs(v)<100&&v%1!==0?2:0);
const sign=v=>(v>0?'+':v<0?'−':'')+eur(Math.abs(v));
const mlabel=(m,long)=>{const[y,mo]=m.split('-').map(Number);return new Intl.DateTimeFormat('fr-FR',long?{month:'long',year:'numeric'}:{month:'short',year:'2-digit'}).format(new Date(y,mo-1,1))};
const dlabel=d=>new Intl.DateTimeFormat('fr-FR',{weekday:'long',day:'numeric',month:'long'}).format(new Date(d+'T12:00:00'));
const GROUPS=[['courant','Comptes courants','--c1'],['epargne','Épargne','--c3'],['investissements','Investissements','--c4'],['dettes','Dettes','--c2']];
const GCOL=['--c2','--c4','--c5','--c6','--c7','--c3'];
const CATS=['--c1','--c2','--c3','--c4','--c5','--c6'];
const PAGES={overview:"Vue d'ensemble",assets:'Patrimoine',budget:'Budget',transactions:'Transactions',invest:'Placements',future:'Avenir',recurring:'Récurrent'};
const ICONS=[[/abonnement/i,'🔁'],[/aide|famil/i,'🤝'],[/cadeau/i,'🎁'],[/course|alimentaire/i,'🛒'],[/hygi/i,'🧴'],[/int[ée]r[êe]t/i,'📈'],[/jeux/i,'🎲'],[/rembours/i,'↩️'],[/restaurant|fast/i,'🍔'],[/salaire/i,'💼'],[/sant[ée]/i,'🩺'],[/shopping/i,'🛍️'],[/sortie/i,'🎟️'],[/transport/i,'🚇'],[/vente/i,'🏷️'],[/virement/i,'💸'],[/voiture/i,'🚗'],[/voyage/i,'✈️'],[/autres/i,'📦']];
const icon=name=>{const m=ICONS.find(([re])=>re.test(name||''));return m?m[1]:(name||'?').trim().charAt(0).toUpperCase()};

let range=12,all=null,sel=0,page='overview',charts={};
const memo={tx:{},bud:{},flow:{},bills:null,pea:null,goals:null};
const txf={q:'',cat:'',type:'all'};

function el(tag,props={},kids=[]){const e=document.createElement(tag);Object.assign(e,props);kids.forEach(k=>e.append(k));return e}
function mk(id,cfg){if(charts[id])charts[id].destroy();charts[id]=new Chart($(id),cfg)}
function pill(id,text,good){const e=$(id);e.textContent=text||' ';e.className='pill'+(good===true?' up':good===false?' down':good==='warn'?' warn':'')}
const avg=l=>l.length?l.reduce((a,b)=>a+b,0)/l.length:0;
const shown=()=>all.months.slice(-range);
const isCurrent=i=>i===all.months.length-1;
const json=async url=>{const r=await fetch(url);if(!r.ok)throw new Error((await r.json().catch(()=>({}))).error||r.status);return r.json()};
function clean(d){
 let s=(d||'').replace(/^(paiement par carte|paiement carte)\s*x?\d{4}\s*/i,'').replace(/^(pr[ée]l[èe]vement)\s*(europ[ée]en)?\s*/i,'')
  .replace(/^virement\s+(?:[ée]mis\s*)?(?:vir inst|web|wero|inst)?\s*(?:vers\s*)?/i,m=>/vers/i.test(m)||/[ée]mis/i.test(m)?'Virement · ':'Virement · ')
  .replace(/en votre faveur\s*/i,'').replace(/\bvir inst( de)?\s*/i,'').replace(/\b[A-Za-z0-9]{16,}\b/g,'').replace(/\s+\d{1,2}\/\d{1,2}(\s+-.*)?$/,'').replace(/\s{2,}/g,' ').trim();
 if(s&&s===s.toUpperCase())s=s.toLowerCase().replace(/(^|[\s·-])([a-zà-ÿ])/g,(_,a,b)=>a+b.toUpperCase());
 return s||d;
}
function bubble(name,color){const b=el('div',{className:'bubble',textContent:icon(name)});if(color)b.style.background=color;return b}
function spark(values,color){
 const w=96,h=30,min=Math.min(...values),max=Math.max(...values),span=(max-min)||1;
 const pts=values.map((v,i)=>`${(i/(values.length-1||1))*w},${h-3-((v-min)/span)*(h-6)}`).join(' ');
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${w} ${h}`);svg.setAttribute('class','spark');
 const p=document.createElementNS(ns,'polyline');p.setAttribute('points',pts);p.setAttribute('stroke',color);svg.append(p);return svg;
}

/* ---------- router ---------- */
function route(){
 const name=(location.hash.replace('#/','')||'overview');page=PAGES[name]?name:'overview';
 document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!=='p-'+page);
 document.querySelectorAll('#nav a,#tabbar a').forEach(a=>a.classList.toggle('on',a.dataset.page===page));
 $('pageTitle').textContent=PAGES[page];document.title=PAGES[page]+' · Patrimoine';
 $('monthnav').hidden=!(page==='budget'||page==='transactions');
 window.scrollTo(0,0);
 if(all)renderPage();
}
function renderPage(){
 if(page==='overview')renderOverview();
 else if(page==='assets')renderAssets();
 else if(page==='budget')renderBudget();
 else if(page==='transactions')renderTransactions();
 else if(page==='invest')renderInvest();
 else if(page==='future')renderFuture();
 else renderRecurring();
}
function setMonth(i){sel=Math.max(0,Math.min(all.months.length-1,i));renderPage()}
function gotoCategory(cat){txf.cat=cat;txf.type='all';txf.q='';location.hash='#/transactions'}

/* ---------- overview ---------- */
function setHero(i){
 const rows=shown(),r=rows[i],ref=rows[0].net_worth.total-rows[0].change;
 $('nw').textContent=eur(r.net_worth.total);
 const d=r.net_worth.total-ref,p=ref?d/Math.abs(ref)*100:0;
 pill('nwDelta',`${sign(d)}${ref?` (${p>=0?'+':'−'}${Math.abs(p).toFixed(1).replace('.',',')} %)`:''}`,d>=0);
 $('nwWhen').textContent=i===rows.length-1?`depuis ${range===12?'1 an':range+' mois'}`:`${mlabel(r.month,true)} · depuis le début`;
}
const crosshair={id:'crosshair',afterDatasetsDraw(c){const a=c.tooltip?.getActiveElements?.();if(!a||!a.length)return;
 const{ctx,chartArea:{top,bottom}}=c,x=a[0].element.x;ctx.save();ctx.strokeStyle=css('--mute');ctx.globalAlpha=.4;ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,bottom);ctx.stroke();ctx.restore()}};

function renderOverview(){
 const rows=shown(),line=css('--accent');
 setHero(rows.length-1);
 const ctx=$('cNw').getContext('2d'),h=$('cNw').parentElement.clientHeight||260;
 const g=ctx.createLinearGradient(0,0,0,h);g.addColorStop(0,css('--accent2'));g.addColorStop(1,'transparent');
 mk('cNw',{type:'line',plugins:[crosshair],data:{labels:rows.map(r=>mlabel(r.month)),datasets:[{data:rows.map(r=>r.net_worth.total),borderColor:line,backgroundColor:g,fill:true,tension:.25,borderWidth:2.5,pointRadius:0,pointHoverRadius:6,pointHoverBackgroundColor:line,pointHoverBorderColor:css('--card'),pointHoverBorderWidth:3}]},
  options:{responsive:true,maintainAspectRatio:false,animation:false,layout:{padding:{left:8,right:8,top:8}},interaction:{mode:'index',intersect:false},
   plugins:{legend:{display:false},tooltip:{enabled:false}},
   scales:{x:{grid:{display:false},border:{display:false},ticks:{color:css('--mute'),maxRotation:0,autoSkip:true,maxTicksLimit:7}},y:{display:false,grace:'10%'}},
   onHover:(e,els)=>{if(els.length)setHero(els[0].index)}}});
 $('cNw').onmouseleave=()=>{charts.cNw.setActiveElements([]);charts.cNw.update();setHero(rows.length-1)};
 const last=rows[rows.length-1].net_worth;
 const pos=GROUPS.filter(([k])=>last[k]>0),total=pos.reduce((a,[k])=>a+last[k],0)||1;
 $('seg').replaceChildren(...pos.map(([k,n,c])=>{const s=el('span');s.style.cssText=`flex:${last[k]};background:var(${c})`;s.title=`${n} ${eur(last[k])}`;return s}));
 $('groups').replaceChildren(...GROUPS.filter(([k])=>last[k]!==0).map(([k,n,c])=>{
  const d=el('span',{className:'dot'});d.style.background=`var(${c})`;
  return el('div',{className:'item'},[d,el('span',{className:'name',textContent:n}),el('span',{className:'pct',textContent:last[k]>0?Math.round(last[k]/total*100)+' %':''}),el('span',{className:'amt',textContent:eur(last[k])})])}));

 renderInsights();
}

async function renderInsights(){
 const out=[],n=all.months.length,done=all.months[Math.max(0,n-2)],prev=all.months.slice(Math.max(0,n-5),n-2);
 const add=(emoji,html)=>out.push([emoji,html]);
 if(done.earned>0||done.saved){
  const rate=done.earned>0?Math.round(done.saved/done.earned*100):null;
  add(done.saved>=0?'💰':'📉',done.saved>=0?`En ${mlabel(done.month,true).split(' ')[0]}, tu as mis <b>${eur(done.saved)}</b> de côté${rate!==null?` (${rate} % de tes revenus)`:''}.`
   :`En ${mlabel(done.month,true).split(' ')[0]}, ton patrimoine a baissé de <b>${eur(-done.saved)}</b> hors marché.`);
 }
 if(prev.length){
  const a=avg(prev.map(p=>p.spent)),d=done.spent-a;
  if(a>0&&Math.abs(d/a)>.08)add(d<0?'✅':'⚠️',`Tes dépenses de ${mlabel(done.month,true).split(' ')[0]} sont <b>${Math.abs(Math.round(d/a*100))} % ${d<0?'sous':'au-dessus de'}</b> ta moyenne des ${prev.length} mois précédents.`);
  const rises=Object.entries(done.expenses).map(([c,v])=>[c,v,avg(prev.map(p=>p.expenses[c]||0))]).filter(([,v,m])=>v-m>40&&v>m*1.3).sort((x,y)=>(y[1]-y[2])-(x[1]-x[2]));
  if(rises.length)add('🔺',`<b>${rises[0][0]}</b> grimpe : ${eur(rises[0][1])} contre ${eur(rises[0][2])} en moyenne.`);
 }
 try{
  const month=all.months[n-1].month,b=memo.bud[month]||(memo.bud[month]=await json('/api/budgets?month='+month));
  const over=b.filter(x=>x.limit&&x.spent>x.limit);
  if(over.length)add('🚨',`Budget dépassé ce mois-ci : <b>${over.map(x=>x.name).join(', ')}</b>.`);
  const bills=memo.bills||(memo.bills=await json('/api/bills'));
  if(bills.upcoming.length){const u=bills.upcoming[0];add('📅',`Prochain prélèvement : <b>${u.name}</b>, ${eur2(u.amount)} le ${new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'long'}).format(new Date(u.date+'T12:00:00'))}.`)}
 }catch(e){}
 $('insights').replaceChildren(...(out.length?out.slice(0,5).map(([e,h])=>{const d=el('span',{className:'name'});d.innerHTML=h;d.style.whiteSpace='normal';return el('div',{className:'item'},[el('div',{className:'bubble',textContent:e}),d])}):[el('div',{className:'empty',textContent:'Pas encore assez de données'})]));
}

/* ---------- budget ---------- */
function renderFlow(){
 const rows=shown(),labels=rows.map(r=>mlabel(r.month));
 const idx=sel-(all.months.length-rows.length);
 const inc=css('--up'),sp=css('--c2');
 mk('cFlow',{type:'bar',data:{labels,datasets:[
  {label:'Revenus',data:rows.map(r=>r.earned),backgroundColor:rows.map((_,j)=>j===idx?inc:inc+'55'),borderRadius:6,borderSkipped:false,maxBarThickness:18},
  {label:'Dépenses',data:rows.map(r=>r.spent),backgroundColor:rows.map((_,j)=>j===idx?sp:sp+'55'),borderRadius:6,borderSkipped:false,maxBarThickness:18}]},
  options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},
   plugins:{legend:{display:false},tooltip:{backgroundColor:css('--fg'),titleColor:css('--bg'),bodyColor:css('--bg'),padding:10,cornerRadius:10,boxPadding:4,callbacks:{label:c=>` ${c.dataset.label} : ${eur(c.parsed.y)}`}}},
   scales:{x:{grid:{display:false},border:{display:false},ticks:{color:css('--mute'),maxRotation:0,autoSkip:true,maxTicksLimit:12}},y:{grid:{color:css('--line')},border:{display:false},ticks:{color:css('--mute'),callback:v=>eur(v),maxTicksLimit:5}}},
   onClick:(e,els)=>{if(els.length)setMonth(els[0].index+(all.months.length-rows.length))}}});
}

function renderBudget(){
 const M=all.months,r=M[sel],prev=M.slice(Math.max(0,sel-3),sel);
 $('selLabel').textContent=mlabel(r.month,true)+(isCurrent(sel)?' · en cours':'');
 $('prev').disabled=sel===0;$('next').disabled=sel===M.length-1;
 const rate=r.earned>0?Math.round(r.saved/r.earned*100):null;
 $('kIncome').textContent=eur(r.earned);$('kSpend').textContent=eur(r.spent);$('kSave').textContent=eur(r.saved);
 const vs=(v,k,low)=>{if(!prev.length||isCurrent(sel))return[isCurrent(sel)?'mois partiel':'',null];const d=v-avg(prev.map(p=>p[k]));return[`${sign(d)} vs moy. ${prev.length} mois`,low?d<=0:d>=0]};
 pill('dIncome',...vs(r.earned,'earned',false));pill('dSpend',...vs(r.spent,'spent',true));
 const[t,g]=vs(r.saved,'saved',false);pill('dSave',rate!==null&&!isCurrent(sel)?`${rate} % des revenus`:t,rate!==null&&!isCurrent(sel)?(r.saved>=0):g);
 renderFlow();renderSankey(r);renderBudgets(r.month);

 const entries=Object.entries(r.expenses).sort((a,b)=>b[1]-a[1]),total=entries.reduce((a,[,v])=>a+v,0);
 $('donutTotal').textContent=eur(total);
 $('spendNote').textContent=prev.length&&!isCurrent(sel)?`Écart avec la moyenne des ${prev.length} mois précédents`:' ';
 const color=i=>i<CATS.length-1?css(CATS[i]):css('--c7');
 const top=entries.slice(0,CATS.length-1),rest=entries.slice(CATS.length-1);
 const donut=[...top,...(rest.length?[['Autres catégories',rest.reduce((a,[,v])=>a+v,0)]]:[])];
 if(entries.length)mk('cDonut',{type:'doughnut',data:{labels:donut.map(d=>d[0]),datasets:[{data:donut.map(d=>d[1]),backgroundColor:donut.map((_,i)=>color(i)),borderColor:css('--card'),borderWidth:3,borderRadius:6}]},
  options:{responsive:true,maintainAspectRatio:false,animation:false,cutout:'72%',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` ${c.label} : ${eur(c.parsed)}`}}}}});
 else if(charts.cDonut){charts.cDonut.destroy();delete charts.cDonut}
 const max=entries.length?entries[0][1]:1,rowsEl=[];
 entries.slice(0,8).forEach(([n,v],i)=>{
  const a=prev.length?avg(prev.map(p=>p.expenses[n]||0)):0,d=a>0&&!isCurrent(sel)?(v-a)/a*100:null;
  const dot=el('span',{className:'dot'});dot.style.background=color(i);
  const row=el('div',{className:'item click',title:'Voir les transactions'},[dot,el('span',{className:'name',textContent:n}),
   el('span',{className:'vs'+(d===null?'':d>15?' down':d<-15?' up':''),textContent:d===null?'':(d>0?'+':'−')+Math.abs(Math.round(d))+' %'}),el('span',{className:'amt',textContent:eur(v)})]);
  row.onclick=()=>gotoCategory(n==='(sans catégorie)'?'':n);rowsEl.push(row);
  const bar=el('div',{className:'sub'},[el('span')]);bar.firstChild.style.cssText=`width:${v/max*100}%;background:${color(i)}`;rowsEl.push(bar);
 });
 $('spendRows').replaceChildren(...(rowsEl.length?rowsEl:[el('div',{className:'empty',textContent:'Aucune dépense ce mois-ci'})]));
 const inc=Object.entries(r.income).sort((a,b)=>b[1]-a[1]),imax=inc.length?inc[0][1]:1,ir=[];
 inc.forEach(([n,v])=>{const dot=el('span',{className:'dot'});dot.style.background=css('--up');
  const row=el('div',{className:'item click'},[dot,el('span',{className:'name',textContent:n}),el('span',{className:'amt',textContent:eur(v)})]);row.onclick=()=>gotoCategory(n==='(sans catégorie)'?'':n);ir.push(row);
  const bar=el('div',{className:'sub'},[el('span')]);bar.firstChild.style.cssText=`width:${v/imax*100}%;background:${css('--up')}`;ir.push(bar)});
 $('incomeRows').replaceChildren(...(ir.length?ir:[el('div',{className:'empty',textContent:'Aucun revenu ce mois-ci'})]));
}

async function renderBudgets(month){
 const box=$('budgets');
 let data=memo.bud[month];
 try{if(!data)data=memo.bud[month]=await json('/api/budgets?month='+month)}catch(e){box.replaceChildren(el('div',{className:'empty',textContent:'Budgets indisponibles'}));return}
 if(month!==all.months[sel].month)return;
 data=data.filter(b=>b.limit!==null||b.spent>0);
 box.replaceChildren(...(data.length?data.map(b=>{
  const pct=b.limit?b.spent/b.limit*100:0,col=!b.limit?css('--c7'):pct>100?css('--down'):pct>80?css('--c5'):css('--up');
  const track=el('div',{className:'track'},[el('span')]);track.firstChild.style.cssText=`width:${Math.min(pct,100)}%;background:${col}`;
  const left=b.limit?b.limit-b.spent:null;
  return el('div',{className:'bud'},[
   el('div',{className:'row'},[el('b',{textContent:b.name}),el('span',{textContent:b.limit?`${eur(b.spent)} sur ${eur(b.limit)}`:eur(b.spent)})]),
   ...(b.limit?[track,el('div',{className:'left'+(left<0?' down':''),textContent:left>=0?`Reste ${eur(left)} · ${Math.round(pct)} % utilisé`:`Dépassé de ${eur(-left)}`})]:[])]);
 }):[el('div',{className:'empty',textContent:'Aucun budget ce mois-ci'})]));
}

/* Sankey: revenus -> budgets -> catégories */
async function renderSankey(r){
 const svg=$('sankey');
 let tree=memo.flow[r.month];
 if(!tree){try{tree=memo.flow[r.month]=await json('/api/flow?month='+r.month)}catch(e){svg.replaceChildren();return}}
 if(r.month!==all.months[sel].month||page!=='budget')return;
 const NS='http://www.w3.org/2000/svg',mk2=(t,a={},txt)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(txt!==undefined)e.textContent=txt;return e};
 const incomeEntries=Object.entries(r.income).sort((a,b)=>b[1]-a[1]);
 const groups=Object.entries(tree).map(([g,cats])=>({name:g,cats:Object.entries(cats).sort((a,b)=>b[1]-a[1]),total:Object.values(cats).reduce((a,b)=>a+b,0)})).filter(g=>g.total>0).sort((a,b)=>b.total-a.total);
 const spent=groups.reduce((a,g)=>a+g.total,0),earned=incomeEntries.reduce((a,[,v])=>a+v,0);
 if(!spent&&!earned){svg.replaceChildren(mk2('text',{x:340,y:120,'text-anchor':'middle',class:'m'},'Aucune donnée ce mois-ci'));svg.setAttribute('viewBox','0 0 680 240');return}
 const gap=earned-spent,saving=Math.max(gap,0),deficit=Math.max(-gap,0),total=Math.max(earned,spent)||1;
 const W=1000,PAD=13,NW=14,xs=[170,370,590,800];
 const left=[...incomeEntries.map(([n,v])=>({name:n,value:v,color:'--up'})),...(deficit?[{name:'Épargne utilisée',value:deficit,color:'--down'}]:[])];
 const mid=[{name:'Revenus',value:total,color:'--mute'}];
 const gcol=groups.map((g,i)=>({name:g.name,value:g.total,color:GCOL[i%GCOL.length],cats:g.cats}));
 const col2=[...gcol,...(saving?[{name:'Épargne',value:saving,color:'--accent'}]:[])];
 const col3=gcol.flatMap(g=>g.cats.map(([n,v])=>({name:n,value:v,color:g.color,group:g})));
 const cols=[left,mid,col2,col3];
 const maxN=Math.max(...cols.map(c=>c.length)),H=Math.max(300,maxN*26);
 const k=Math.min(...cols.map(c=>(H-(c.length-1)*PAD)/Math.max(c.reduce((a,n)=>a+n.value,0),1)));
 cols.forEach((c,ci)=>{const used=c.reduce((a,n)=>a+Math.max(n.value*k,9),0)+(c.length-1)*PAD;let y=Math.max(0,(H-used)/2);c.forEach(n=>{n.h=Math.max(n.value*k,9);n.x=xs[ci];n.y=y;n.in=0;n.out=0;y+=n.h+PAD})});
 const links=[],link=(a,b,v)=>{if(v<=0)return;const h=v*k,y0=a.y+a.out,y1=b.y+b.in;a.out+=h;b.in+=h;links.push({a,b,v,h,y0:y0+h/2,y1:y1+h/2})};
 left.forEach(n=>link(n,mid[0],n.value));
 col2.forEach(n=>link(mid[0],n,n.value));
 col3.forEach(n=>link(n.group,n,n.value));
 svg.setAttribute('viewBox',`0 0 ${W} ${H+20}`);
 const frag=[];
 links.forEach(l=>{const x0=l.a.x+NW,x1=l.b.x,m=(x0+x1)/2;
  const p=mk2('path',{class:'link',d:`M${x0},${l.y0} C${m},${l.y0} ${m},${l.y1} ${x1},${l.y1}`,stroke:css(l.b===mid[0]?l.a.color:l.b.color),'stroke-width':Math.max(l.h,1)});
  p.append(mk2('title',{},`${l.a.name} → ${l.b.name} : ${eur(l.v)}`));frag.push(p)});
 cols.forEach((c,ci)=>c.forEach(n=>{
  const rect=mk2('rect',{x:n.x,y:n.y,width:NW,height:n.h,rx:3,fill:css(n.color)});rect.append(mk2('title',{},`${n.name} : ${eur(n.value)}`));frag.push(rect);
  if(ci===1){frag.push(mk2('text',{x:n.x+NW/2,y:n.y-8,'text-anchor':'middle',style:'font-weight:600'},'Revenus '+eur(n.value)));return}
  const lx=ci===0?n.x-8:n.x+NW+8,anchor=ci===0?'end':'start',big=n.h>=22;
  const t=mk2('text',{x:lx,y:n.y+n.h/2+(big?-1:4),'text-anchor':anchor,style:ci===2?'font-weight:600':''},big?n.name:`${n.name} · ${eur(n.value)}`);
  frag.push(t);
  if(big)frag.push(mk2('text',{x:lx,y:n.y+n.h/2+14,'text-anchor':anchor,class:'m'},eur(n.value)));
 }));
 svg.replaceChildren(...frag);
}

/* ---------- transactions ---------- */
async function renderTransactions(){
 const month=all.months[sel].month;
 $('selLabel').textContent=mlabel(month,true)+(isCurrent(sel)?' · en cours':'');
 $('prev').disabled=sel===0;$('next').disabled=sel===all.months.length-1;
 let data=memo.tx[month];
 if(!data){$('txList').replaceChildren(el('div',{className:'empty',textContent:'Chargement…'}));
  try{data=memo.tx[month]=await json('/api/transactions?month='+month)}catch(e){$('txList').replaceChildren(el('div',{className:'empty',textContent:'Impossible de charger les transactions'}));return}}
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
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/* ---------- patrimoine ---------- */
function renderAssets(){
 const rows=shown(),last=rows[rows.length-1].net_worth,first=rows[0].net_worth,startNw=rows[0].net_worth.total-rows[0].change;
 const span=range===12?'1 an':range===24?'2 ans':range+' mois';
 const ASSET=GROUPS.filter(([k])=>k!=='dettes');
 const assets=ASSET.reduce((a,[k])=>a+last[k],0);
 const prevAssets=ASSET.reduce((a,[k])=>a+first[k],0);
 $('aAssets').textContent=eur(assets);
 pill('aAssetsD',`${sign(assets-prevAssets)} sur ${span}`,assets-prevAssets>=0);
 const debts=-last.dettes;
 $('aDebts').textContent=eur(Math.max(debts,0));
 const repaid=-first.dettes-Math.max(debts,0);
 pill('aDebtsD',debts>0?`${sign(repaid)} sur ${span}`:repaid>0?`${eur(repaid)} remboursés sur ${span}`:'aucune dette',debts>0?repaid>=0:repaid>0?true:null);
 // runway: cash and savings against the average monthly spending of the last 3 complete months
 const done=all.months.slice(-4,-1),spend=avg(done.map(m=>m.spent)),liquid=last.courant+last.epargne;
 $('aRunway').textContent=spend>0?(liquid/spend).toFixed(1).replace('.',',')+' mois':'—';
 pill('aRunwayD',spend>0?`de dépenses couvertes (${eur(spend)}/mois)`:'', spend>0?(liquid/spend>=3?true:liquid/spend>=1?'warn':false):null);

 // allocation
 const slices=ASSET.filter(([k])=>last[k]>0).map(([k,n,c])=>[k,n,c,last[k]]);
 $('aTotal').textContent=eur(assets);
 mk('cAlloc',{type:'doughnut',data:{labels:slices.map(x=>x[1]),datasets:[{data:slices.map(x=>x[3]),backgroundColor:slices.map(x=>css(x[2])),borderColor:css('--card'),borderWidth:3,borderRadius:6}]},
  options:{responsive:true,maintainAspectRatio:false,animation:false,cutout:'72%',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` ${c.label} : ${eur(c.parsed)}`}}}}});
 $('aAllocList').replaceChildren(...slices.map(([k,n,c,v])=>{const d=el('span',{className:'dot'});d.style.background=css(c);
  return el('div',{className:'item'},[d,el('span',{className:'name',textContent:n}),el('span',{className:'pct',textContent:(v/assets*100).toFixed(v/assets<.1?1:0).replace('.',',')+' %'}),el('span',{className:'amt fix',textContent:eur(v)})])}));

 // evolution by class (assets only)
 const active=ASSET.filter(([k])=>rows.some(r=>r.net_worth[k]>0));
 $('aEvoNote').textContent=`Sur ${span}, dettes non comprises`;
 mk('cAssets',{type:'bar',data:{labels:rows.map(r=>mlabel(r.month)),datasets:active.map(([k,n,c])=>({label:n,data:rows.map(r=>Math.max(r.net_worth[k],0)),backgroundColor:css(c),stack:'a',borderSkipped:false,maxBarThickness:26}))},
  options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},
   plugins:{legend:{display:false},tooltip:{backgroundColor:css('--fg'),titleColor:css('--bg'),bodyColor:css('--bg'),padding:10,cornerRadius:10,callbacks:{label:c=>` ${c.dataset.label} : ${eur(c.parsed.y)}`,footer:i=>'Total : '+eur(i.reduce((a,x)=>a+x.parsed.y,0))}},},
   scales:{x:{stacked:true,grid:{display:false},border:{display:false},ticks:{color:css('--mute'),maxRotation:0,autoSkip:true,maxTicksLimit:7}},y:{stacked:true,grid:{color:css('--line')},border:{display:false},ticks:{color:css('--mute'),callback:v=>eur(v),maxTicksLimit:5}}}}});
 legend2('aLegend',active.map(([,n,c])=>[n,c]));

 // one card per class, accounts inside
 const accounts=last.accounts,gtotal=k=>last[k];
 const cards=GROUPS.filter(([k])=>accounts.some(a=>a.group===k&&(a.balance!==0||k!=='dettes'))||last[k]!==0).map(([k,n,c])=>{
  const list=accounts.filter(a=>a.group===k&&(a.balance!==0||k!=='dettes')).sort((a,b)=>b.balance-a.balance);
  if(!list.length)return null;
  const d=last[k]-first[k],col=css(c),dot=el('span',{className:'dot'});dot.style.background=col;
  const share=k==='dettes'?'':`${(assets?last[k]/assets*100:0).toFixed(0)} % des actifs`;
  const head=el('div',{className:'chead'},[dot,el('b',{textContent:n}),el('span',{className:'cshare',textContent:share}),
   el('span',{className:'pill '+(Math.abs(d)<1?'':(k==='dettes'?d>=0:d>0)?'up':'down'),textContent:Math.abs(d)<1?'stable':sign(d)}),el('b',{className:'ctotal',textContent:eur(gtotal(k))})]);
  const items=list.map(a=>{
   const series=rows.map(r=>(r.net_worth.accounts.find(x=>x.name===a.name)||{balance:0}).balance);
   const dd=series[series.length-1]-series[0];
   const trend=el('span',{className:'vs'+(Math.abs(dd)<1?'':dd>0?' up':' down'),textContent:Math.abs(dd)<1?'':sign(dd)});trend.style.width='72px';
   return el('div',{className:'item'},[bubble(a.name,col+'22'),el('span',{className:'name',textContent:a.name}),spark(series,col),trend,el('span',{className:'amt fix',textContent:eur(a.balance)})]);
  });
  return el('section',{className:'card mb'},[head,el('div',{className:'list'},items)]);
 }).filter(Boolean);
 $('aClasses').replaceChildren(...cards);
}
function legend2(id,items){const box=$(id);box.replaceChildren(...items.map(([n,c])=>{const i=el('i');i.style.background=css(c);return el('span',{},[i,n])}))}

/* ---------- placements ---------- */
async function renderInvest(){
 let d=memo.pea;
 try{if(!d)d=memo.pea=await json('/api/pea')}catch(e){$('iValue').textContent='—';return}
 if(page!=='invest')return;
 const priced=d.positions.filter(p=>p.value!==null),holdings=priced.reduce((a,p)=>a+p.value,0);
 const value=d.has_file?holdings+d.cash:d.balance,gain=value-d.invested,pct=d.invested>0?gain/d.invested*100:null;
 $('iValue').textContent=eur2(value);$('iInvested').textContent=eur2(d.invested);$('iGain').textContent=(gain>0?'+':gain<0?'−':'')+eur2(Math.abs(gain));
 // day change of the positions, in euros
 const dayEur=priced.reduce((a,p)=>a+(p.day===null?0:p.value-p.value/(1+p.day/100)),0);
 pill('iDay',priced.length?`${dayEur>=0?'+':'−'}${eur2(Math.abs(dayEur))} aujourd'hui`:'liquidités',priced.length?dayEur>=0:null);
 pill('iGainPct',pct===null?'—':`${pct>=0?'+':'−'}${Math.abs(pct).toFixed(2).replace('.',',')} %`,Math.abs(gain)<0.005?null:gain>0);

 // value against contributions, month by month
 const worth=r=>r.net_worth.accounts.filter(a=>a.name.startsWith('PEA')).reduce((a,x)=>a+x.balance,0);
 let rows=shown();const opened=rows.findIndex(r=>worth(r)!==0);rows=rows.slice(Math.max(0,opened-1));
 const total=m=>Object.entries(d.contributions).filter(([k])=>k<=m).reduce((a,[,v])=>a+v,0);
 mk('cPea',{type:'line',data:{labels:rows.map(r=>mlabel(r.month)),datasets:[
  {label:'Valeur',data:rows.map(worth),borderColor:css('--accent'),backgroundColor:css('--accent2'),fill:true,tension:.25,borderWidth:2.5,pointRadius:0,pointHoverRadius:5},
  {label:'Versements',data:rows.map(r=>total(r.month)),borderColor:css('--c7'),borderDash:[5,4],stepped:true,borderWidth:2,pointRadius:0,pointHoverRadius:4}]},
  options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},
   plugins:{legend:{display:false},tooltip:{backgroundColor:css('--fg'),titleColor:css('--bg'),bodyColor:css('--bg'),padding:10,cornerRadius:10,callbacks:{label:c=>` ${c.dataset.label} : ${eur2(c.parsed.y)}`}}},
   scales:{x:{grid:{display:false},border:{display:false},ticks:{color:css('--mute'),maxRotation:0,autoSkip:true,maxTicksLimit:7}},y:{beginAtZero:true,grid:{color:css('--line')},border:{display:false},ticks:{color:css('--mute'),callback:v=>eur(v),maxTicksLimit:5}}}}});

 // positions and allocation
 const empty=!d.positions.length;
 $('iEmpty').hidden=!empty;$('iHoldings').hidden=empty;
 $('iNote').textContent=empty?'Aucun titre pour le moment':`${d.positions.length} ligne${d.positions.length>1?'s':''} · cours Yahoo Finance`;
 const wt=value||1,rowsEl=d.positions.map(p=>{
  const sub=el('small',{textContent:`${p.quantity.toLocaleString('fr-FR')} × ${p.price===null?'cours indisponible':eur2(p.price)}${p.label?' · '+p.label:''}`});
  const day=el('span',{className:'vs'+(p.day===null?'':p.day>0?' up':p.day<0?' down':''),textContent:p.day===null?'':`${p.day>0?'+':p.day<0?'−':''}${Math.abs(p.day).toFixed(2).replace('.',',')} %`});day.style.width='64px';
  return el('div',{className:'item'},[bubble(p.symbol),el('span',{className:'name'},[p.symbol,sub]),day,el('span',{className:'amt fix',textContent:p.value===null?'—':eur2(p.value)})]);
 });
 $('iPositions').replaceChildren(...(rowsEl.length?rowsEl:[el('div',{className:'empty',textContent:`Liquidités : ${eur2(d.cash)}`})]));
 const slices=[...priced.map(p=>[p.label||p.symbol,p.value]),...(d.cash>0?[['Liquidités',d.cash]]:[])];
 $('iTotal').textContent=eur2(value);
 const col=i=>css(CATS[i%CATS.length]);
 mk('cPeaDonut',{type:'doughnut',data:{labels:slices.map(x=>x[0]),datasets:[{data:slices.map(x=>x[1]),backgroundColor:slices.map((_,i)=>col(i)),borderColor:css('--card'),borderWidth:3,borderRadius:6}]},
  options:{responsive:true,maintainAspectRatio:false,animation:false,cutout:'72%',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` ${c.label} : ${eur2(c.parsed)}`}}}}});
 $('iAlloc').replaceChildren(...slices.map(([n,v],i)=>{const dot=el('span',{className:'dot'});dot.style.background=col(i);
  return el('div',{className:'item'},[dot,el('span',{className:'name',textContent:n}),el('span',{className:'pct',textContent:Math.round(v/wt*100)+' %'}),el('span',{className:'amt',textContent:eur2(v)})])}));
}

/* ---------- avenir ---------- */
const INFLATION=0.02;
const fut={S:null,share:0,rc:1.7,rp:5,years:10,infl:false,levers:{},ready:false};
const addMonths=(d,n)=>{const x=new Date(d.getFullYear(),d.getMonth()+n,1);return x};
const dlong=iso=>new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'long',year:'numeric'}).format(new Date(iso+'T12:00:00'));
const mlong=iso=>new Intl.DateTimeFormat('fr-FR',{month:'long',year:'numeric'}).format(new Date(iso+'T12:00:00'));

function project(S,share,rc,rp,years,cash0,pea0,debts){
 const mc=Math.pow(1+rc/100,1/12)-1,mp=Math.pow(1+rp/100,1/12)-1,out=[{nw:cash0+pea0+debts,paid:0}];
 let c=cash0,p=pea0,paid=0;
 for(let i=1;i<=years*12;i++){c=c*(1+mc)+S*(1-share);p=p*(1+mp)+S*share;paid+=S;
  let nw=c+p+debts;if(fut.infl)nw/=Math.pow(1+INFLATION,i/12);out.push({nw,paid})}
 return out;
}
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
 const mid=project(S,fut.share,fut.rc,fut.rp,Y,cash0,pea0,debts),
  low=project(S,fut.share,Math.max(fut.rc-.5,0),fut.rp-3,Y,cash0,pea0,debts),
  high=project(S,fut.share,fut.rc+.5,fut.rp+3,Y,cash0,pea0,debts);
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
let goalsData=null,editing=null;
async function renderGoals(){
 let d=memo.goals;
 try{if(!d)d=memo.goals=await json('/api/goals')}catch(e){$('goals').replaceChildren(el('div',{className:'empty',textContent:'Tirelires indisponibles'}));return}
 if(page!=='future')return;
 goalsData=d;
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

function renderFuture(){
 if(!fut.ready){initFuture();renderLevers()}
 updateFuture();renderGoals();
}

/* ---------- recurring ---------- */
const PER_MONTH={monthly:1,yearly:1/12,weekly:52/12,quarterly:1/3,'half-year':1/6};
const FREQ={monthly:'Mensuel',yearly:'Annuel',weekly:'Hebdo',quarterly:'Trimestriel','half-year':'Semestriel'};
async function renderRecurring(){
 let d=memo.bills;
 try{if(!d)d=memo.bills=await json('/api/bills')}catch(e){return}
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
 $('billList').replaceChildren(...(d.bills.length?[...d.bills].sort((a,b)=>b.amount*(PER_MONTH[b.frequency]||1)-a.amount*(PER_MONTH[a.frequency]||1)).map(b=>{
  const m=b.amount*(PER_MONTH[b.frequency]||1);
  return el('div',{className:'item'},[bubble(b.name),el('span',{className:'name'},[b.name,el('small',{textContent:b.min===b.max?eur2(b.min):`${eur2(b.min)} à ${eur2(b.max)}`})]),el('span',{className:'chip',textContent:FREQ[b.frequency]||b.frequency}),el('span',{className:'amt',textContent:eur2(m)+'/mois'})]);
 }):[el('div',{className:'empty',textContent:'Aucun abonnement déclaré'})]));
 $('piggies').replaceChildren(...(d.piggies.length?d.piggies.map(p=>{
  const pct=p.target?Math.min(p.current/p.target*100,100):0,track=el('div',{className:'track'},[el('span')]);
  track.firstChild.style.cssText=`width:${pct}%;background:${pct>=100?css('--up'):css('--accent')}`;
  return el('div',{className:'bud'},[el('div',{className:'row'},[el('b',{textContent:p.name}),el('span',{textContent:`${eur(p.current)} sur ${eur(p.target)}`})]),track,
   el('div',{className:'left',textContent:pct>=100?'Objectif atteint 🎉':`${Math.round(pct)} % · reste ${eur(p.target-p.current)}`+(p.date?` · avant le ${new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'long',year:'numeric'}).format(new Date(p.date+'T12:00:00'))}`:'')})]);
 }):[el('div',{className:'empty',textContent:'Aucune tirelire'})]));
}


/* ---------- assistant ---------- */
const SUGGEST={
 overview:["Fais-moi un point sur mon patrimoine","Comment évolue mon épargne ces derniers mois ?","Puis-je me payer un voyage à 600 € en mars ?"],
 budget:["Où puis-je réduire mes dépenses ce mois-ci ?","Pourquoi mon budget Divers est-il dépassé ?","Compare ce mois à mes moyennes"],
 transactions:["Y a-t-il des dépenses inhabituelles ce mois-ci ?","Quelles transactions n'ont pas de catégorie ?"],
 invest:["Simule 50 € par mois sur mon PEA pendant 10 ans","Que faut-il savoir avant d'acheter mon premier ETF ?"],
 recurring:["Quels abonnements pourrais-je résilier ?","Combien me coûtent mes abonnements par an ?"]};
let chatSession=null,chatBusy=false;
const msgs=$('msgs');
const fmt=t=>esc(t).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>');
function say(text,cls){const d=el('div',{className:'m '+cls});if(cls==='bot')d.innerHTML=fmt(text);else d.textContent=text;msgs.append(d);msgs.scrollTop=msgs.scrollHeight;return d}
function chatStart(){
 chatSession=null;msgs.replaceChildren();
 const box=el('div',{className:'sugg'},[el('p',{textContent:'Quelques idées :'})]);
 (SUGGEST[page]||SUGGEST.overview).forEach(t=>box.append(el('button',{type:'button',textContent:t,onclick:()=>chatAsk(t)})));
 msgs.append(box);
}
function context(){
 const m=all?mlabel(all.months[sel].month,true):'';
 return `(Contexte : l'utilisateur consulte la page « ${PAGES[page]} »${page==='budget'||page==='transactions'?`, mois affiché : ${m}`:''}.)\n`;
}
async function chatAsk(text){
 text=(text||'').trim();if(!text||chatBusy)return;
 msgs.querySelector('.sugg')?.remove();
 say(text,'me');$('chatQ').value='';$('chatQ').style.height='';
 chatBusy=true;$('chatSend').disabled=true;const w=say('…','bot wait');
 try{
  const r=await fetch('/chat/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:context()+text,session:chatSession})});
  const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);
  chatSession=j.session;w.className='m bot';w.innerHTML=fmt(j.answer||'(pas de réponse)');
  // the assistant may have changed data (categories, goals, PEA): drop what is cached
  memo.tx={};memo.bud={};memo.flow={};memo.bills=null;memo.pea=null;memo.goals=null;
 }catch(e){w.className='m err';w.textContent='Erreur : '+e.message}
 chatBusy=false;$('chatSend').disabled=false;msgs.scrollTop=msgs.scrollHeight;
}
function chatToggle(open){$('chat').hidden=!open;$('chatOpen').hidden=open;if(open){if(!msgs.children.length)chatStart();$('chatQ').focus()}}
$('chatOpen').onclick=()=>chatToggle(true);$('chatClose').onclick=()=>chatToggle(false);$('chatNew').onclick=chatStart;
$('chatForm').onsubmit=e=>{e.preventDefault();chatAsk($('chatQ').value)};
$('chatQ').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!/Mobi|Android/.test(navigator.userAgent)){e.preventDefault();chatAsk($('chatQ').value)}});
$('chatQ').addEventListener('input',e=>{e.target.style.height='auto';e.target.style.height=e.target.scrollHeight+'px'});
addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('chat').hidden)chatToggle(false)});

/* ---------- boot ---------- */
async function load(refresh){
 $('err').style.display='none';document.body.classList.add('loading');
 if(refresh){memo.tx={};memo.bud={};memo.flow={};memo.bills=null;memo.pea=null;memo.goals=null}
 try{
  all=await json(`/api/data?months=24${refresh?'&refresh=1':''}`);
  sel=Math.max(0,all.months.length-2); // last complete month
  $('stamp').textContent='Mis à jour à '+new Date(all.generated).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'});
  renderPage();
 }catch(e){$('err').textContent='Impossible de charger les données : '+e.message;$('err').style.display='block'}
 finally{document.body.classList.remove('loading')}
}
$('tabbar').replaceChildren(...[...document.querySelectorAll('#nav a')].map(a=>{const c=a.cloneNode(true);c.querySelector('span').textContent={overview:'Accueil',assets:'Patrimoine',budget:'Budget',transactions:'Opérations',invest:'Placements',future:'Avenir',recurring:'Récurrent'}[a.dataset.page];return c}));
$('ranges').addEventListener('click',e=>{const b=e.target.closest('button');if(!b||!all)return;range=+b.dataset.m;
 document.querySelectorAll('#ranges button').forEach(x=>x.setAttribute('aria-pressed',x===b));renderPage()});
$('prev').onclick=()=>setMonth(sel-1);$('next').onclick=()=>setMonth(sel+1);
$('refresh').onclick=$('refreshM').onclick=()=>load(true);
$('q').addEventListener('input',e=>{txf.q=e.target.value;renderTransactions()});
$('fcat').addEventListener('change',e=>{txf.cat=e.target.value;renderTransactions()});
$('ftype').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;txf.type=b.dataset.t;renderTransactions()});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>all&&renderPage());
addEventListener('hashchange',route);
route();load(false);
if(new URLSearchParams(location.search).has('assistant'))chatToggle(true);
