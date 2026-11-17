/* DOM and Chart.js helpers. */
import { icon } from './format.js';
import { charts } from './state.js';

export const $=id=>document.getElementById(id);

export const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();

export function el(tag,props={},kids=[]){const e=document.createElement(tag);Object.assign(e,props);kids.forEach(k=>e.append(k));return e}

export function mk(id,cfg){if(charts[id])charts[id].destroy();charts[id]=new Chart($(id),cfg)}

export function pill(id,text,good){const e=$(id);e.textContent=text||' ';e.className='pill'+(good===true?' up':good===false?' down':good==='warn'?' warn':'')}

export const skel=(n=3)=>Array.from({length:n},()=>el('div',{className:'skel'}));

export function fail(box,msg,retry){box.replaceChildren(el('div',{className:'empty'},[msg,el('button',{className:'btn small',type:'button',textContent:'Réessayer',onclick:retry})]))}

export function bubble(name,color){const b=el('div',{className:'bubble',textContent:icon(name)});if(color)b.style.background=color;return b}

export function spark(values,color){
 const w=96,h=30,min=Math.min(...values),max=Math.max(...values),span=(max-min)||1;
 const pts=values.map((v,i)=>`${(i/(values.length-1||1))*w},${h-3-((v-min)/span)*(h-6)}`).join(' ');
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${w} ${h}`);svg.setAttribute('class','spark');
 const p=document.createElementNS(ns,'polyline');p.setAttribute('points',pts);p.setAttribute('stroke',color);svg.append(p);return svg;
}

export function legend2(id,items){const box=$(id);box.replaceChildren(...items.map(([n,c])=>{const i=el('i');i.style.background=css(c);return el('span',{},[i,n])}))}
