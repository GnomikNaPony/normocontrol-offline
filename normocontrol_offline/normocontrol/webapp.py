from __future__ import annotations

import json
import os
import socketserver
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .config import DEFAULT_DB
from .db import Database
from .service import (
    add_mapping,
    import_source,
    preview_corrections,
    run_analysis,
    run_corrections,
    run_learning,
)


HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Нормоконтроль Offline</title>
<style>
:root { --ink:#17201b; --paper:#f2efe6; --card:#fffdf6; --line:#c8c0ad;
  --accent:#b8482d; --green:#315d4d; --muted:#6d6a60; }
* { box-sizing:border-box; }
body { margin:0; color:var(--ink); background:
  radial-gradient(circle at 15% 10%, #fff8db 0, transparent 28%),
  repeating-linear-gradient(0deg,#0000 0 27px,#c8c0ad22 28px),var(--paper);
  font-family:"Palatino Linotype","Book Antiqua",serif; }
header { padding:28px clamp(18px,5vw,70px) 18px; border-bottom:2px solid var(--ink); }
h1 { margin:0; font-size:clamp(30px,5vw,58px); line-height:.95; letter-spacing:-.04em; }
.subtitle { color:var(--muted); margin-top:10px; }
main { padding:22px clamp(18px,5vw,70px) 50px; }
.stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; }
.stat,.panel { background:color-mix(in srgb,var(--card) 94%,transparent); border:1px solid var(--line);
  box-shadow:4px 4px 0 #17201b12; }
.stat { padding:14px; }
.stat b { display:block; color:var(--accent); font:700 28px/1 Georgia,serif; }
.grid { display:grid; grid-template-columns:minmax(260px,.8fr) minmax(420px,2fr); gap:16px; margin-top:16px; }
.panel { padding:16px; overflow:auto; }
h2 { margin:0 0 12px; font-size:20px; }
input,select,button { width:100%; border:1px solid var(--line); background:#fff; color:var(--ink);
  padding:10px; margin:4px 0; font:14px/1.2 "Trebuchet MS",sans-serif; }
button { cursor:pointer; background:var(--green); color:#fff; border-color:var(--green); font-weight:bold; }
button.alt { background:var(--card); color:var(--ink); border-color:var(--ink); }
.row { display:grid; grid-template-columns:1fr 1fr; gap:7px; }
table { width:100%; border-collapse:collapse; font:13px/1.35 "Trebuchet MS",sans-serif; }
th,td { text-align:left; vertical-align:top; border-bottom:1px solid var(--line); padding:8px 6px; }
th { position:sticky; top:-16px; background:var(--card); }
.high { color:#a22920; font-weight:bold; } .medium { color:#9a5c00; } .low { color:var(--muted); }
#status { min-height:22px; color:var(--accent); font-weight:bold; margin:10px 0; }
@media (max-width:850px) { .grid { grid-template-columns:1fr; } }
</style>
</head>
<body>
<header><h1>Нормоконтроль<br>Offline</h1><div class="subtitle">Локальная база документов. Без отправки данных в интернет.</div></header>
<main>
<div id="stats" class="stats"></div>
<div id="status"></div>
<div class="grid">
<section class="panel">
<h2>Операции</h2>
<button onclick="act('/api/analyze')">Проверить базу</button>
<button onclick="act('/api/learn')">Обучиться на примерах</button>
<input id="source" placeholder="Полный путь к папке документов">
<select id="role"><option value="document">Рабочие документы</option><option value="standard">Стандарты</option><option value="example">Примеры до/после</option></select>
<button class="alt" onclick="importDocs()">Импортировать путь</button>
<h2 style="margin-top:20px">Обновить ссылку</h2>
<input id="oldRef" placeholder="Старая ссылка">
<input id="newRef" placeholder="Новая ссылка">
<button class="alt" onclick="mapRef()">Добавить замену</button>
<input id="output" placeholder="Папка для исправленных копий">
<button onclick="applyFixes()">Выпустить исправленные копии</button>
<h2 style="margin-top:20px">Поиск</h2>
<div class="row"><input id="query" placeholder="Запрос"><button class="alt" onclick="search()">Найти</button></div>
<div id="searchResults"></div>
</section>
<section class="panel">
<h2>Замечания</h2>
<table><thead><tr><th>Важность</th><th>Документ</th><th>Проверка</th><th>Предложение</th></tr></thead><tbody id="findings"></tbody></table>
</section>
</div>
<section class="panel" style="margin-top:16px">
<h2>Правила, извлеченные из примеров</h2>
<p>Включайте только универсальные исправления, не меняющие технический смысл.</p>
<table><thead><tr><th>Статус</th><th>Достоверность</th><th>Было</th><th>Стало</th><th></th></tr></thead><tbody id="rules"></tbody></table>
</section>
</main>
<script>
const statusBox=document.getElementById('status');
async function api(path,data){const r=await fetch(path,{method:data?'POST':'GET',headers:{'Content-Type':'application/json'},body:data?JSON.stringify(data):null});const x=await r.json();if(!r.ok)throw Error(x.error||'Ошибка');return x;}
function esc(v){const e=document.createElement('span');e.textContent=v??'';return e.innerHTML;}
async function refresh(){const x=await api('/api/state');document.getElementById('stats').innerHTML=Object.entries(x.stats).map(([k,v])=>`<div class="stat"><b>${v}</b>${esc(k)}</div>`).join('');document.getElementById('findings').innerHTML=x.findings.map(f=>`<tr><td class="${f.severity}">${esc(f.severity)}</td><td>${esc(f.title)}<br>абзац ${f.paragraph_index??'-'}</td><td>${esc(f.message)}<br><small>${esc(f.original)}</small></td><td>${esc(f.suggestion)}</td></tr>`).join('');document.getElementById('rules').innerHTML=x.rules.map(r=>`<tr><td>${r.enabled?'включено':'отключено'}</td><td>${Math.round(r.confidence*100)}%</td><td>${esc(r.old_text)}</td><td>${esc(r.new_text)}</td><td><button class="alt" onclick="toggleRule(${r.id})">Переключить</button></td></tr>`).join('');}
async function run(fn){statusBox.textContent='Выполняется...';try{const x=await fn();statusBox.textContent=JSON.stringify(x);await refresh();}catch(e){statusBox.textContent=e.message;}}
const val=id=>document.getElementById(id).value;
const act=path=>run(()=>api(path,{}));
const importDocs=()=>run(()=>api('/api/import',{source:val('source'),role:val('role')}));
const mapRef=()=>run(()=>api('/api/map',{old:val('oldRef'),new:val('newRef')}));
async function applyFixes(){await run(async()=>{const preview=await api('/api/preview',{});if(!preview.items.length)return {message:'Подтвержденных замен для DOCX-документов не найдено'};const docs=preview.items.slice(0,10).map(x=>`- ${x.title}: ${x.replacement_count} замен`).join('\\n');if(!confirm(`Будут созданы исправленные копии. Исходные документы не изменяются.\\n\\nДокументов: ${preview.documents}\\nЗамен: ${preview.replacements}\\n\\n${docs}\\n\\nПрименить эти изменения?`))return {message:'Изменения отменены пользователем'};return api('/api/apply',{output:val('output'),confirmed:true});});}
const toggleRule=id=>run(()=>api('/api/toggle-rule',{id}));
async function search(){await run(async()=>{const x=await api('/api/search',{query:val('query')});document.getElementById('searchResults').innerHTML=x.results.map(r=>`<p><b>${esc(r.title)}</b><br>${esc(r.text)}</p>`).join('');return {найдено:x.results.length};});}
refresh();
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    db: Database

    def log_message(self, _format: str, *_args) -> None:
        return

    def _send(self, payload, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            data = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/state":
            findings = [
                dict(row)
                for row in self.db.rows(
                    """
                    SELECT findings.severity, documents.title, findings.paragraph_index,
                           findings.message, findings.original, findings.suggestion
                    FROM findings JOIN documents ON documents.id = findings.document_id
                    ORDER BY CASE findings.severity WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2 ELSE 3 END, documents.title
                    LIMIT 1000
                    """
                )
            ]
            rules = [
                dict(row)
                for row in self.db.rows(
                    """
                    SELECT id, enabled, confidence, occurrences, old_text, new_text
                    FROM learned_rules
                    ORDER BY enabled DESC, confidence DESC
                    LIMIT 500
                    """
                )
            ]
            self._send({"stats": self.db.stats(), "findings": findings, "rules": rules})
            return
        self._send({"error": "Не найдено"}, 404)

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            path = urlparse(self.path).path
            if path == "/api/analyze":
                result = {"findings": run_analysis(self.db)}
            elif path == "/api/learn":
                result = run_learning(self.db)
            elif path == "/api/import":
                result = import_source(
                    self.db, Path(payload["source"]).expanduser(), payload["role"]
                )
            elif path == "/api/map":
                add_mapping(self.db, payload["old"], payload["new"])
                result = {"mapping": f"{payload['old']} -> {payload['new']}"}
            elif path == "/api/preview":
                result = preview_corrections(self.db)
            elif path == "/api/apply":
                result = run_corrections(
                    self.db,
                    Path(payload["output"]).expanduser(),
                    confirmed=bool(payload.get("confirmed")),
                )
            elif path == "/api/toggle-rule":
                self.db.execute(
                    """
                    UPDATE learned_rules
                    SET enabled = CASE enabled WHEN 1 THEN 0 ELSE 1 END
                    WHERE id = ?
                    """,
                    (int(payload["id"]),),
                )
                result = {"rule": int(payload["id"])}
            elif path == "/api/search":
                result = {
                    "results": [
                        dict(row)
                        for row in self.db.rows(
                            """
                            SELECT documents.title, paragraph_fts.paragraph_index,
                                   paragraph_fts.text
                            FROM paragraph_fts
                            JOIN documents ON documents.id = paragraph_fts.document_id
                            WHERE paragraph_fts MATCH ? LIMIT 100
                            """,
                            (payload["query"],),
                        )
                    ]
                }
            else:
                self._send({"error": "Не найдено"}, 404)
                return
            self._send(result)
        except Exception as exc:
            self._send({"error": str(exc)}, 400)


class LocalHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        # Avoid a reverse-DNS lookup that can block on isolated computers.
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]


def main() -> None:
    db_path = Path(os.environ.get("NORMOCONTROL_DB", DEFAULT_DB))
    Handler.db = Database(db_path)
    server = LocalHTTPServer(("127.0.0.1", 8765), Handler)
    url = "http://127.0.0.1:8765"
    print(f"Нормоконтроль запущен: {url}", flush=True)
    if not os.environ.get("NORMOCONTROL_NO_BROWSER"):
        opener = threading.Timer(0.2, webbrowser.open, args=(url,))
        opener.daemon = True
        opener.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
