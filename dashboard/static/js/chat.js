/* Assistant panel. */
import { PAGES } from './consts.js';
import { $, el } from './dom.js';
import { esc, mlabel } from './format.js';
import { all, memo, page, sel } from './state.js';

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
  memo.tx={};memo.bud={};memo.flow={};memo.bills=null;memo.alerts=null;memo.tax=null;memo.pea=null;memo.goals=null;
 }catch(e){w.className='m err';w.textContent='Erreur : '+e.message}
 chatBusy=false;$('chatSend').disabled=false;msgs.scrollTop=msgs.scrollHeight;
}

export function chatToggle(open){$('chat').hidden=!open;$('chatOpen').hidden=open;if(open){if(!msgs.children.length)chatStart();$('chatQ').focus()}}

$('chatOpen').onclick=()=>chatToggle(true);$('chatClose').onclick=()=>chatToggle(false);$('chatNew').onclick=chatStart;

$('chatForm').onsubmit=e=>{e.preventDefault();chatAsk($('chatQ').value)};

$('chatQ').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!/Mobi|Android/.test(navigator.userAgent)){e.preventDefault();chatAsk($('chatQ').value)}});

$('chatQ').addEventListener('input',e=>{e.target.style.height='auto';e.target.style.height=e.target.scrollHeight+'px'});

addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('chat').hidden)chatToggle(false)});

// The floating button steps aside while reading (scrolling down) and comes back on the way up,
// at the very top, at the very bottom, or when it takes keyboard focus.
let lastY=scrollY;
addEventListener('scroll',()=>{
 const y=scrollY,fab=$('chatOpen');
 if(Math.abs(y-lastY)<6)return;
 const atBottom=innerHeight+y>=document.documentElement.scrollHeight-8;
 fab.classList.toggle('away',y>lastY&&y>80&&!atBottom);
 lastY=y;
},{passive:true});
$('chatOpen').addEventListener('focus',()=>$('chatOpen').classList.remove('away'));
