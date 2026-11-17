/* Overview page: net worth, split, insights and alerts. */
import { json } from './api.js';
import { GROUPS } from './consts.js';
import { $, css, el, mk, pill } from './dom.js';
import { eur, mlabel, sign } from './format.js';
import { all, charts, memo, page, range, shown } from './state.js';
import { computeAlerts, computeInsights } from './logic.js';

function setHero(i){
 const rows=shown(),r=rows[i],ref=rows[0].net_worth.total-rows[0].change;
 $('nw').textContent=eur(r.net_worth.total);
 const d=r.net_worth.total-ref,p=ref?d/Math.abs(ref)*100:0;
 pill('nwDelta',`${sign(d)}${ref?` (${p>=0?'+':'−'}${Math.abs(p).toFixed(1).replace('.',',')} %)`:''}`,d>=0);
 $('nwWhen').textContent=i===rows.length-1?`depuis ${range===12?'1 an':range+' mois'}`:`${mlabel(r.month,true)} · depuis le début`;
}

const crosshair={id:'crosshair',afterDatasetsDraw(c){const a=c.tooltip?.getActiveElements?.();if(!a||!a.length)return;
 const{ctx,chartArea:{top,bottom}}=c,x=a[0].element.x;ctx.save();ctx.strokeStyle=css('--mute');ctx.globalAlpha=.4;ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,bottom);ctx.stroke();ctx.restore()}};

export function renderOverview(){
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

 renderInsights();renderAlerts();
}

async function renderInsights(){
 let bills=null;
 try{bills=memo.bills||(memo.bills=await json('/api/bills'))}catch(e){}
 const out=computeInsights(all.months,bills);
 $('insights').replaceChildren(...(out.length?out.map(([e,h])=>{const d=el('span',{className:'name'});d.innerHTML=h;d.style.whiteSpace='normal';return el('div',{className:'item'},[el('div',{className:'bubble',textContent:e}),d])}):[el('div',{className:'empty',textContent:'Pas encore assez de données'})]));
}

/* alerts: budgets near or over their limit, bills due soon, thin safety margin */
async function renderAlerts(){
 let budgets=null,bills=null;
 try{const month=all.months[all.months.length-1].month;budgets=memo.bud[month]||(memo.bud[month]=await json('/api/budgets?month='+month))}catch(e){}
 try{bills=memo.bills||(memo.bills=await json('/api/bills'))}catch(e){}
 const{items,budgetCount}=computeAlerts({budgets,bills,months:all.months,now:new Date()});
 document.querySelectorAll('[data-page=budget] .badge').forEach(b=>{b.hidden=!budgetCount;b.textContent=budgetCount});
 if(page!=='overview')return;
 $('alerts').hidden=!items.length;
 $('alertList').replaceChildren(...items.map(([e,cls,title,text])=>el('div',{className:'item alert '+cls},[el('div',{className:'bubble',textContent:e}),el('span',{className:'name'},[el('b',{textContent:title}),el('small',{textContent:text})])])));
}
