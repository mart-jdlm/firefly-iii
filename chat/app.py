"""Web chat for Firefly III (see the README, "Chat").

A single page to ask questions about the finances from any browser on the tailnet. Each question
runs `claude -p` (the host's Claude Code login, no API key) with only the firefly MCP server
(the assistant-http service) and no built-in tools. Listens on 127.0.0.1 only; `tailscale serve`
publishes it on the tailnet. CHAT_ALLOWED_HOSTS (comma separated, default localhost) lists the
Host names accepted, against DNS rebinding.
"""

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("CHAT_PORT", "8686"))
MCP_URL = os.environ.get("CHAT_MCP_URL", "http://127.0.0.1:8383/mcp")
ALLOWED = {h.strip() for h in os.environ.get("CHAT_ALLOWED_HOSTS", "").split(",") if h.strip()}
STATE = os.path.expanduser("~/.local/state/firefly-chat")
MCP_CONFIG = os.path.join(STATE, "mcp.json")
TIMEOUT = 300

SYSTEM = (
    "Tu réponds à la personne dont tu vois les finances, depuis une page de chat sur son téléphone: "
    "réponses courtes, en français, sans tableau markdown. Utilise les outils firefly pour les chiffres, "
    "n'invente rien. Avant toute modification (catégoriser, règle, position PEA), dis ce que tu vas faire "
    "et demande confirmation."
)

PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Finances</title>
<style>
:root{color-scheme:light dark;--bg:#f6f6f4;--fg:#1c1c1a;--card:#fff;--me:#1d6b4f;--line:#ddd}
@media(prefers-color-scheme:dark){:root{--bg:#161615;--fg:#eee;--card:#242422;--me:#2f8f6b;--line:#383836}}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,sans-serif;display:flex;flex-direction:column}
header{padding:10px 16px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}
header b{font-size:17px}button{font:inherit}
#new{background:none;border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:4px 10px}
#log{flex:1;overflow-y:auto;padding:12px 16px;display:flex;flex-direction:column;gap:10px}
.m{max-width:88%;padding:9px 13px;border-radius:14px;white-space:pre-wrap;word-wrap:break-word;background:var(--card);border:1px solid var(--line)}
.me{align-self:flex-end;background:var(--me);color:#fff;border-color:var(--me)}
.err{color:#c0392b}.wait{opacity:.6}
.hint{display:flex;flex-wrap:wrap;gap:6px}.hint button{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:16px;padding:6px 12px}
form{display:flex;gap:8px;padding:10px 16px calc(10px + env(safe-area-inset-bottom));border-top:1px solid var(--line)}
textarea{flex:1;resize:none;font:inherit;padding:9px 12px;border-radius:12px;border:1px solid var(--line);background:var(--card);color:var(--fg);max-height:120px}
#send{background:var(--me);color:#fff;border:0;border-radius:12px;padding:0 18px}#send:disabled{opacity:.5}
</style></head><body>
<header><b>Finances</b><button id="new" type="button">Nouvelle conversation</button></header>
<div id="log"></div>
<form id="f"><textarea id="q" rows="1" placeholder="Pose une question…" autocomplete="off"></textarea><button id="send">Envoyer</button></form>
<script>
const log=document.getElementById('log'),q=document.getElementById('q'),send=document.getElementById('send');
let session=null;
const hints=["Quel est mon patrimoine net ?","Combien j'ai dépensé ce mois-ci ?","Dépenses par catégorie le mois dernier","Où en sont mes objectifs d'épargne ?"];
function add(text,cls){const d=document.createElement('div');d.className='m '+cls;d.textContent=text;log.appendChild(d);log.scrollTop=log.scrollHeight;return d}
function start(){log.innerHTML='';session=null;const h=document.createElement('div');h.className='hint';
 hints.forEach(t=>{const b=document.createElement('button');b.type='button';b.textContent=t;b.onclick=()=>ask(t);h.appendChild(b)});log.appendChild(h)}
async function ask(text){text=text.trim();if(!text)return;const h=log.querySelector('.hint');if(h)h.remove();
 add(text,'me');q.value='';q.style.height='';send.disabled=true;const w=add('…','wait');
 try{const r=await fetch('ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,session})});
  const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);session=j.session;w.className='m';w.textContent=j.answer}
 catch(e){w.className='m err';w.textContent='Erreur : '+e.message}
 send.disabled=false;log.scrollTop=log.scrollHeight}
document.getElementById('f').onsubmit=e=>{e.preventDefault();ask(q.value)};
q.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!/Mobi|Android/.test(navigator.userAgent)){e.preventDefault();ask(q.value)}};
q.oninput=()=>{q.style.height='auto';q.style.height=q.scrollHeight+'px'};
document.getElementById('new').onclick=start;start();
</script></body></html>"""


def run_claude(message, session):
    cmd = [
        "claude", "-p", message, "--tools", "", "--strict-mcp-config", "--mcp-config", MCP_CONFIG,
        "--allowedTools", "mcp__firefly", "--permission-mode", "dontAsk", "--output-format", "json",
        "--append-system-prompt", SYSTEM,
    ]
    if session:
        cmd += ["--resume", session]
    p = subprocess.run(cmd, cwd=STATE, capture_output=True, text=True, timeout=TIMEOUT)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError((p.stderr or p.stdout or "pas de réponse").strip()[-300:])
    if out.get("is_error"):
        raise RuntimeError(str(out.get("result", "erreur"))[:300])
    return out.get("result", ""), out.get("session_id")


class Handler(BaseHTTPRequestHandler):
    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ALLOWED or host in ("localhost", "127.0.0.1")

    def _send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self):
        if not self._host_ok():
            return self._json(421, {"error": "host"})
        if self.path.split("?")[0] == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok():
            return self._json(421, {"error": "host"})
        origin = self.headers.get("Origin")
        if origin and (origin.split("//", 1)[-1].split(":")[0] not in ALLOWED | {"localhost", "127.0.0.1"}):
            return self._json(403, {"error": "origin"})
        if self.path != "/ask":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > 20000:
                raise ValueError
            body = json.loads(self.rfile.read(n))
            message = str(body["message"]).strip()
            session = body.get("session")
            if session is not None and not (isinstance(session, str) and len(session) <= 64 and session.replace("-", "").isalnum()):
                raise ValueError
            if not message:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return self._json(400, {"error": "requête invalide"})
        try:
            answer, sid = run_claude(message, session)
        except subprocess.TimeoutExpired:
            return self._json(504, {"error": "trop long"})
        except Exception as e:  # noqa: BLE001
            return self._json(502, {"error": str(e)})
        self._json(200, {"answer": answer, "session": sid})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    os.makedirs(STATE, exist_ok=True)
    with open(MCP_CONFIG, "w") as f:
        json.dump({"mcpServers": {"firefly": {"type": "http", "url": MCP_URL}}}, f)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
