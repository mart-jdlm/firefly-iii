/* Placements page: PEA value, contributions, positions. */
import { json } from './api.js';
import { CATS } from './consts.js';
import { $, bubble, css, el, fail, mk, pill } from './dom.js';
import { eur, eur2, mlabel } from './format.js';
import { all, memo, page, shown } from './state.js';
import { simulate, twr, xirr } from './logic.js';

export async function renderInvest(){
 let d=memo.pea;
 try{if(!d)d=memo.pea=await json('/api/pea')}catch(e){$('iValue').textContent='—';$('iHoldings').hidden=false;$('iEmpty').hidden=true;fail($('iPositions'),'Cours indisponibles',renderInvest);return}
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
 const today=new Date(),todayIso=new Date(today.getTime()-today.getTimezoneOffset()*6e4).toISOString().slice(0,10);
 const flows=d.flows||[],bench=d.benchmark&&flows.length?{label:d.benchmark.label,at:simulate(flows,d.benchmark.prices)}:null;
 const eom=m=>{const[y,mo]=m.split('-').map(Number),e=new Date(Date.UTC(y,mo,0)).toISOString().slice(0,10);return e<todayIso?e:todayIso};
 const total=m=>Object.entries(d.contributions).filter(([k])=>k<=m).reduce((a,[,v])=>a+v,0);
 mk('cPea',{type:'line',data:{labels:rows.map(r=>mlabel(r.month)),datasets:[
  {label:'Valeur',data:rows.map(worth),borderColor:css('--accent'),backgroundColor:css('--accent2'),fill:true,tension:.25,borderWidth:2.5,pointRadius:0,pointHoverRadius:5},
  {label:'Versements',data:rows.map(r=>total(r.month)),borderColor:css('--c7'),borderDash:[5,4],stepped:true,borderWidth:2,pointRadius:0,pointHoverRadius:4},
  ...(bench?[{label:'Même argent en '+bench.label,data:rows.map(r=>bench.at(eom(r.month))),borderColor:css('--c3'),borderDash:[2,3],tension:.25,borderWidth:2,pointRadius:0,pointHoverRadius:4}]:[])]},
  options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},
   plugins:{legend:{display:false},tooltip:{backgroundColor:css('--fg'),titleColor:css('--bg'),bodyColor:css('--bg'),padding:10,cornerRadius:10,callbacks:{label:c=>` ${c.dataset.label} : ${eur2(c.parsed.y)}`}}},
   scales:{x:{grid:{display:false},border:{display:false},ticks:{color:css('--mute'),maxRotation:0,autoSkip:true,maxTicksLimit:7}},y:{beginAtZero:true,grid:{color:css('--line')},border:{display:false},ticks:{color:css('--mute'),callback:v=>eur(v),maxTicksLimit:5}}}}});

 $('iLegB').hidden=!bench;if(bench)$('iLegBn').textContent=bench.label;
 renderPerf({value,flows,bench,todayIso,worth});

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

/* Performance card: yearly return, return without the deposits, and the same deposits in an index. */
function renderPerf({value,flows,bench,todayIso,worth}){
 const pc=(v,d=1)=>`${v>=0?'+':'−'}${Math.abs(v*100).toFixed(d).replace('.',',')} %`;
 const row=(name,hint,text,tone)=>el('div',{className:'item'},[el('span',{className:'name',style:'white-space:normal'},[name,el('small',{textContent:hint})]),el('span',{className:'vs'+(tone===true?' up':tone===false?' down':''),textContent:text})]);
 if(!flows.length){$('iPerf').hidden=true;return}
 $('iPerf').hidden=false;
 const r=xirr(flows,value,todayIso),t=twr(all.months.map(m=>({month:m.month,value:worth(m)})),flows);
 const out=[
  row('Rendement annualisé','Tient compte de la date de chaque versement',r===null?'après 3 mois':pc(r),r===null?null:r>=0),
  row('Performance des placements','Sans l\'effet des versements',t===null?'—':pc(t),t===null?null:t>=0)];
 if(bench){
  const b=bench.at(todayIso),invested=flows.reduce((a,f)=>a+f.amount,0),diff=value-b;
  out.push(row(`Même argent en ${bench.label}`,"Tes versements, placés le jour où tu les as faits",eur2(b),null),
   row(diff>=0?'Ton PEA devance l\'indice':'Ton PEA est derrière l\'indice',invested>0?`Indice : ${pc(b/invested-1)} sur les versements`:'',(diff>=0?'+':'−')+eur2(Math.abs(diff)),diff>=0));
 }
 $('iPerfNote').textContent=bench?'L\'indice sert de repère : un ETF monde coté en euros, sans frais ni fiscalité.':'Calculé à partir de tes versements et de la valeur du PEA.';
 $('iPerfRows').replaceChildren(...out);
}
