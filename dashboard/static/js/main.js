/* Entry point: router, loading, boot. */
import { json } from './api.js';
import { renderAssets } from './assets.js';
import { renderBudget } from './budget.js';
import { chatToggle } from './chat.js';
import { PAGES } from './consts.js';
import { $ } from './dom.js';
import { renderFuture } from './future.js';
import { renderInvest } from './invest.js';
import { renderOverview } from './overview.js';
import { renderRecurring } from './recurring.js';
import { renderReview } from './review.js';
import { all, hooks, memo, nav, offline, page, resetFilters, sel, setAll, setMonth, setOffline, setPage, setRange, setSel } from './state.js';
import { renderTransactions } from './transactions.js';
import './add.js';
import './privacy.js';
import './search.js';

function route(){
 const name=(location.hash.replace('#/','')||'overview'),was=page;setPage(PAGES[name]?name:'overview');
 // coming to Transactions from the menu starts clean; a link from another page brings its own filters
 if(page==='transactions'&&was!=='transactions'&&!nav.keep)resetFilters();
 nav.keep=false;
 document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!=='p-'+page);
 document.querySelectorAll('#nav a,#tabbar a').forEach(a=>a.classList.toggle('on',a.dataset.page===page));
 document.querySelector('#tabbar a.on')?.scrollIntoView({inline:'center',block:'nearest'});
 $('pageTitle').textContent=PAGES[page];document.title=PAGES[page]+' · Cairn';
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
 else if(page==='review')renderReview();
 else renderRecurring();
}

hooks.render=renderPage;
hooks.reload=()=>load(false,true);

function stamp(){
 if(!all)return;
 const t=new Date(all.generated),m=Math.max(0,Math.round((Date.now()-t)/60000));
 $('stamp').textContent=(m<1?"Mis à jour à l'instant":m<60?`Mis à jour il y a ${m} min`:'Mis à jour à '+t.toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'}));
 $('offline').hidden=!offline;
}

async function load(refresh,keep){
 const was=keep&&all?all.months[sel].month:null;
 if(!keep)$('err').style.display='none';
 document.body.classList.add('loading');
 if(refresh||keep){memo.tx={};memo.bud={};memo.flow={};memo.bills=null;memo.reviews=null;memo.review={};memo.alerts=null;memo.tax=null;memo.pea=null;memo.goals=null}
 setOffline(false);
 try{
  setAll(await json(`/api/data?months=24${refresh?'&refresh=1':''}`));
  const i=was?all.months.findIndex(m=>m.month===was):-1;
  setSel(i>=0?i:Math.max(0,all.months.length-2)); // last complete month
  $('err').style.display='none';
  renderPage();
 }catch(e){if(!keep||!all){$('err').textContent='Impossible de charger les données : '+e.message;$('err').style.display='block'}}
 finally{document.body.classList.remove('loading');stamp()}
}

setInterval(stamp,30000);

// come back to a tab left open for a while: show fresh figures

document.addEventListener('visibilitychange',()=>{if(!document.hidden&&all&&Date.now()-new Date(all.generated)>10*60000)load(false,true)});

addEventListener('online',()=>{if(all)load(false,true)});

$('tabbar').replaceChildren(...[...document.querySelectorAll('#nav a')].map(a=>{const c=a.cloneNode(true);c.querySelector('span').textContent={overview:'Accueil',assets:'Patrimoine',budget:'Budget',transactions:'Opérations',invest:'Placements',future:'Avenir',recurring:'Récurrent',review:'Bilan'}[a.dataset.page];return c}));

$('ranges').addEventListener('click',e=>{const b=e.target.closest('button');if(!b||!all)return;setRange(+b.dataset.m);
 document.querySelectorAll('#ranges button').forEach(x=>x.setAttribute('aria-pressed',x===b));renderPage()});

$('prev').onclick=()=>setMonth(sel-1);$('next').onclick=()=>setMonth(sel+1);

$('refresh').onclick=$('refreshM').onclick=()=>load(true);

matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>all&&renderPage());

addEventListener('hashchange',route);

route();load(false);

if(new URLSearchParams(location.search).has('assistant'))chatToggle(true);

if('serviceWorker' in navigator)addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{}));
