"""브라우저 기반 GUI (Python 표준 라이브러리만 사용, Windows에서 추가 설치 없이 실행).
실행하면 기본 브라우저에서 http://127.0.0.1:8765 이 열림. 외부 접속은 받지 않음(127.0.0.1 바인딩)."""
import json, os, threading, webbrowser, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from .project import PRESETS
from .engines import EngineError

PAGE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>AAC 음원 생성 도구</title>
<style>
body{font-family:'Malgun Gothic','Noto Sans KR',sans-serif;margin:0;background:#f6f6f3;color:#111}
header{background:#1c5cab;color:#fff;padding:12px 20px;display:flex;gap:16px;align-items:center}
header h1{font-size:18px;margin:0;flex:1}button{font:inherit;padding:6px 12px;border-radius:6px;border:1px solid #bbb;background:#fff;cursor:pointer}
button.p{background:#eb6834;color:#fff;border-color:#eb6834}main{display:grid;grid-template-columns:1fr 360px;gap:16px;padding:16px}
table{width:100%;border-collapse:collapse;background:#fff;font-size:14px}th,td{border-bottom:1px solid #e3e2dd;padding:6px 8px;text-align:left}
th{background:#eceae4;position:sticky;top:0}tr.sel{background:#fdeee7}.tag{font-size:12px;padding:1px 6px;border-radius:10px;background:#e6f0fb}
.tag.emergency{background:#fbe1e1}.tag.system{background:#eee}aside{background:#fff;padding:14px;border-radius:8px;align-self:start;position:sticky;top:16px}
label{display:block;font-size:13px;margin:8px 0 2px;color:#555}input,select{width:100%;padding:6px;font:inherit;box-sizing:border-box}
#log{white-space:pre-wrap;font-size:12px;background:#111;color:#cfc;padding:8px;height:140px;overflow:auto;margin-top:10px}
.row{display:flex;gap:6px}.row>*{flex:1}
</style></head><body>
<header><h1>AAC 핵심문구 음원 생성 도구 <small id="eng"></small></h1>
<button onclick="synthAll(true)">미생성분 합성</button><button onclick="synthAll(false)">전체 일괄 합성</button>
<button class="p" onclick="pkg()">패키지 내보내기</button></header>
<main><div><table><thead><tr><th>ID</th><th>문구</th><th>분류</th><th>우선순위</th><th>영역</th><th>길이</th><th>버전</th><th>미리듣기</th></tr></thead><tbody id="tb"></tbody></table></div>
<aside><b>문구 편집</b>
<label>어휘 ID</label><input id="f_id" type="number">
<label>문구</label><input id="f_text">
<div class="row"><div><label>분류</label><select id="f_cat"></select></div><div><label>우선순위</label><select id="f_prio"><option value="normal">일반</option><option value="emergency">응급</option><option value="system">시스템</option></select></div></div>
<label>음성 프리셋</label><select id="f_preset"></select>
<div class="row"><div><label>화자</label><input id="f_voice" placeholder="기본값"></div><div><label>속도</label><input id="f_rate" type="number" step="0.05"></div></div>
<div class="row"><div><label>높낮이</label><input id="f_pitch" type="number" step="0.05"></div><div><label>음량</label><input id="f_vol" type="number" step="0.05"></div></div>
<label>그림상징 파일(선택)</label><input id="f_sym" placeholder="symbols/xxx.png">
<div class="row" style="margin-top:10px"><button onclick="save()">저장</button><button class="p" onclick="saveSynth()">저장 후 합성</button><button onclick="del()">삭제</button></div>
<audio id="player" controls style="width:100%;margin-top:10px"></audio><div id="log"></div></aside></main>
<script>
const CATS=["생활","응급","가정용","의료용","감정표현","외출용","시스템","맞춤"];let D=null,sel=null;
const $=id=>document.getElementById(id);CATS.forEach(c=>$('f_cat').add(new Option(c,c)));
const log=m=>{$('log').textContent+=m+"\n";$('log').scrollTop=1e9};
async function api(p,b){const r=await fetch(p,{method:b?'POST':'GET',headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});const j=await r.json();if(j.error){log('오류: '+j.error);throw j.error}return j}
async function load(){D=await api('/api/project');$('eng').textContent='· 엔진: '+D.engine;$('f_preset').innerHTML='<option value="">(개별 설정)</option>'+Object.keys(D.presets).map(k=>`<option>${k}</option>`).join('');render()}
function zoneOf(id){const z=D.project.zones.find(z=>z.id==id);return z?['좌상','우상','좌하','우하'][z.zone]:''}
function render(){$('tb').innerHTML=D.project.entries.map(e=>`<tr class="${e.id==sel?'sel':''}" onclick="pick(${e.id})"><td>${e.id}</td><td>${e.text}</td><td>${e.category||''}</td><td><span class="tag ${e.priority}">${{normal:'일반',emergency:'응급',system:'시스템'}[e.priority||'normal']}</span></td><td>${zoneOf(e.id)}</td><td>${e.duration_ms?e.duration_ms+'ms':'-'}</td><td>${e.version?'v'+e.version:'-'}</td><td>${e.device_wav?`<button onclick="event.stopPropagation();play('${e.device_wav}')">▶</button>`:''}</td></tr>`).join('')}
function pick(id){sel=id;const e=D.project.entries.find(e=>e.id==id);$('f_id').value=e.id;$('f_text').value=e.text;$('f_cat').value=e.category||'생활';$('f_prio').value=e.priority||'normal';$('f_voice').value=e.voice||'';$('f_rate').value=e.rate??'';$('f_pitch').value=e.pitch??'';$('f_vol').value=e.volume??'';$('f_sym').value=e.symbol||'';render()}
$('f_preset').onchange=()=>{const p=D.presets[$('f_preset').value];if(p){$('f_rate').value=p.rate;$('f_pitch').value=p.pitch;$('f_vol').value=p.volume}}
const num=v=>v===''?null:parseFloat(v);
function form(){return{id:parseInt($('f_id').value),text:$('f_text').value.trim(),category:$('f_cat').value,priority:$('f_prio').value,voice:$('f_voice').value||null,rate:num($('f_rate').value),pitch:num($('f_pitch').value),volume:num($('f_vol').value),symbol:$('f_sym').value||null}}
async function save(){const f=form();if(!f.id||!f.text)return log('ID와 문구 필수');await api('/api/entry',f);sel=f.id;await load();log(`[${f.id}] 저장`)}
async function saveSynth(){await save();log(`[${sel}] 합성 중...`);const r=await api('/api/synth',{id:sel});log(`[${sel}] ${r.duration_ms}ms, 피크 ${r.peak_dbfs}dBFS`);await load();play(D.project.entries.find(e=>e.id==sel).device_wav)}
async function del(){if(sel&&confirm(sel+'번 삭제?')){await api('/api/delete',{id:sel});sel=null;await load()}}
function play(p){$('player').src='/file/'+encodeURIComponent(p)+'?t='+Date.now();$('player').play()}
async function synthAll(m){log('일괄 합성 시작...');const r=await api('/api/synth_all',{missing:m});r.log.forEach(log);await load()}
async function pkg(){const r=await api('/api/package',{});log(`패키지: ${r.path} (${r.size.toLocaleString()} bytes)`)}
load();
</script></body></html>"""


def serve(project, port=8765, open_browser=True):
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _json(self, obj, code=200):
            b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/":
                b = PAGE.encode("utf-8"); self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(b)))
                self.end_headers(); self.wfile.write(b)
            elif u.path == "/api/project":
                last = {}
                for h in project.history: last[h["id"]] = h
                ents = [dict(e, duration_ms=last.get(e["id"], {}).get("duration_ms")) for e in project.entries]
                self._json({"project": dict(project.data, entries=ents), "presets": PRESETS, "engine": project.cfg.get("engine")})
            elif u.path.startswith("/file/"):
                rel = urllib.parse.unquote(u.path[6:])
                full = os.path.realpath(os.path.join(project.root, rel))
                if not full.startswith(os.path.realpath(project.root)) or not os.path.isfile(full):
                    return self._json({"error": "파일 없음"}, 404)
                b = open(full, "rb").read(); self.send_response(200)
                self.send_header("Content-Type", "audio/wav"); self.send_header("Content-Length", str(len(b)))
                self.end_headers(); self.wfile.write(b)
            else:
                self._json({"error": "없는 경로"}, 404)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            try:
                with lock:
                    if self.path == "/api/entry":
                        project.upsert({k: v for k, v in body.items()}); return self._json({"ok": True})
                    if self.path == "/api/delete":
                        project.delete(body["id"]); return self._json({"ok": True})
                    if self.path == "/api/synth":
                        return self._json(project.synthesize(body["id"]))
                    if self.path == "/api/synth_all":
                        lines = []; ok, fail = project.synthesize_all(body.get("missing", False), lines.append)
                        lines.append(f"완료 {ok}건, 실패 {len(fail)}건"); return self._json({"log": lines})
                    if self.path == "/api/package":
                        p, n = project.build_package(); return self._json({"path": p, "size": n})
                self._json({"error": "없는 경로"}, 404)
            except (EngineError, ValueError, KeyError, OSError) as e:
                self._json({"error": str(e)}, 400)

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{port}"
    print(f"AAC 음원 생성 도구 실행 중: {url}  (종료: Ctrl+C)")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
