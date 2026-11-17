/* Fetch helper for the dashboard API. */
import { setOffline } from './state.js';

export const json=async url=>{const r=await fetch(url);if(!r.ok)throw new Error((await r.json().catch(()=>({}))).error||r.status);if(r.headers.get('X-From-Cache'))setOffline(true);return r.json()};
