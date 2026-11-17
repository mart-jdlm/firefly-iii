/* Pure formatting helpers (no DOM): euros, dates, labels, text cleanup. */
import { ICONS } from './consts.js';

const nf=d=>new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR',maximumFractionDigits:d,minimumFractionDigits:d});

export const eur=(v,d=0)=>nf(d).format(v);

export const eur2=v=>eur(v,Math.abs(v)<100&&v%1!==0?2:0);

export const sign=v=>(v>0?'+':v<0?'−':'')+eur(Math.abs(v));

export const mlabel=(m,long)=>{const[y,mo]=m.split('-').map(Number);return new Intl.DateTimeFormat('fr-FR',long?{month:'long',year:'numeric'}:{month:'short',year:'2-digit'}).format(new Date(y,mo-1,1))};

export const dlabel=d=>new Intl.DateTimeFormat('fr-FR',{weekday:'long',day:'numeric',month:'long'}).format(new Date(d+'T12:00:00'));

export const icon=name=>{const m=ICONS.find(([re])=>re.test(name||''));return m?m[1]:(name||'?').trim().charAt(0).toUpperCase()};

export const avg=l=>l.length?l.reduce((a,b)=>a+b,0)/l.length:0;

export function clean(d){
 let s=(d||'').replace(/^(paiement par carte|paiement carte)\s*x?\d{4}\s*/i,'').replace(/^(pr[ée]l[èe]vement)\s*(europ[ée]en)?\s*/i,'')
  .replace(/^virement\s+(?:[ée]mis\s*)?(?:vir inst|web|wero|inst)?\s*(?:vers\s*)?/i,m=>/vers/i.test(m)||/[ée]mis/i.test(m)?'Virement · ':'Virement · ')
  .replace(/en votre faveur\s*/i,'').replace(/\bvir inst( de)?\s*/i,'').replace(/\b[A-Za-z0-9]{16,}\b/g,'').replace(/\s+\d{1,2}\/\d{1,2}(\s+-.*)?$/,'').replace(/\s{2,}/g,' ').trim();
 if(s&&s===s.toUpperCase())s=s.toLowerCase().replace(/(^|[\s·-])([a-zà-ÿ])/g,(_,a,b)=>a+b.toUpperCase());
 return s||d;
}

export const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
