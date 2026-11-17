/* Budget page: month tiles, cash-flow diagram, budgets, categories, year over year. */
import { json } from './api.js';
import { CATS, GCOL } from './consts.js';
import { $, css, el, fail, mk, pill } from './dom.js';
import { avg, eur, mlabel, sign } from './format.js';
import { all, charts, gotoCategory, isCurrent, memo, page, sel, setMonth, shown } from './state.js';
import { yoyRows } from './logic.js';

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

export function renderBudget(){
 const M=all.months,r=M[sel],prev=M.slice(Math.max(0,sel-3),sel);
 $('selLabel').textContent=mlabel(r.month,true)+(isCurrent(sel)?' · en cours':'');
 $('prev').disabled=sel===0;$('next').disabled=sel===M.length-1;
 const rate=r.earned>0?Math.round(r.saved/r.earned*100):null;
 $('kIncome').textContent=eur(r.earned);$('kSpend').textContent=eur(r.spent);$('kSave').textContent=eur(r.saved);
 const vs=(v,k,low)=>{if(!prev.length||isCurrent(sel))return[isCurrent(sel)?'mois partiel':'',null];const d=v-avg(prev.map(p=>p[k]));return[`${sign(d)} vs moy. ${prev.length} mois`,low?d<=0:d>=0]};
 pill('dIncome',...vs(r.earned,'earned',false));pill('dSpend',...vs(r.spent,'spent',true));
 const[t,g]=vs(r.saved,'saved',false);pill('dSave',rate!==null&&!isCurrent(sel)?`${rate} % des revenus`:t,rate!==null&&!isCurrent(sel)?(r.saved>=0):g);
 renderFlow();renderSankey(r);renderBudgets(r.month);renderYoy(r);

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

function renderYoy(r){
 const box=$('yoy'),i=sel-12;
 if(i<0||isCurrent(sel)){box.hidden=true;return}
 const p=all.months[i];box.hidden=false;
 $('yoyNote').textContent=`${mlabel(r.month,true)} contre ${mlabel(p.month,true)}`;
 const row=([name,now,then,lowGood])=>{const d=now-then,flat=Math.abs(d)<1,good=lowGood?d<0:d>0;
  return el('div',{className:'item'},[el('span',{className:'name'},[name,el('small',{textContent:`avant : ${eur(then)}`})]),
   el('span',{className:'vs'+(flat?'':good?' up':' down'),textContent:flat?'stable':sign(d)}),el('span',{className:'amt',textContent:eur(now)})])};
 const{rows,cats}=yoyRows(r,p);
 $('yoyRows').replaceChildren(...rows.map(row),
  ...(cats.length?[el('div',{className:'sep',textContent:'Plus gros écarts par catégorie'}),...cats.map(([c,a,b])=>row([c,a,b,true]))]:[]));
}

async function renderBudgets(month){
 const box=$('budgets');
 let data=memo.bud[month];
 try{if(!data)data=memo.bud[month]=await json('/api/budgets?month='+month)}catch(e){fail(box,'Budgets indisponibles',()=>renderBudgets(month));return}
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
 if(!tree){try{tree=memo.flow[r.month]=await json('/api/flow?month='+r.month)}catch(e){const t=document.createElementNS('http://www.w3.org/2000/svg','text');t.setAttribute('x',340);t.setAttribute('y',60);t.setAttribute('text-anchor','middle');t.setAttribute('class','m');t.textContent='Flux indisponible';svg.setAttribute('viewBox','0 0 680 120');svg.replaceChildren(t);return}}
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
