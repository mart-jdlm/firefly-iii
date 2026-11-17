/* Patrimoine page: assets, debts, allocation, one card per class. */
import { GROUPS } from './consts.js';
import { $, bubble, css, el, legend2, mk, pill, spark } from './dom.js';
import { eur, mlabel, sign } from './format.js';
import { all, range, shown } from './state.js';
import { runway } from './logic.js';

export function renderAssets(){
 const rows=shown(),last=rows[rows.length-1].net_worth,first=rows[0].net_worth;
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
 const{spend,liquid}=runway(all.months);
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
