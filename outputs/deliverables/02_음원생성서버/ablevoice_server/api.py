"""REST API (Python 표준 라이브러리 HTTP 서버). 운영 시 앞단에 HTTPS 리버스 프록시(nginx 등)를 둔다.

인증: Authorization: Bearer <토큰>  — 기기마다 admin(관리자 보호자, 문장 변경) / viewer(보호자 웹 조회) / device(앱·거치대 중계)
"""
import json, os, re, threading, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from .service import Service, ServiceError

ROUTES = []


def route(method, pattern, roles=None):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), roles, fn)); return fn
    return deco


@route("GET", r"/api/health")
def health(svc, m, body, q): return {"ok": True}

@route("GET", r"/api/library")
def library(svc, m, body, q): return svc.library_view()

@route("GET", r"/api/devices/(\d+)", ("admin", "viewer"))
def device(svc, m, body, q): return svc.device_view(m[1])

@route("PUT", r"/api/devices/(\d+)/slots/([01])/([1-4])", ("admin",))
def slot(svc, m, body, q): return svc.set_slot(m[1], m[2], m[3], body)

@route("PUT", r"/api/devices/(\d+)/schedule", ("admin",))
def schedule(svc, m, body, q): return svc.set_schedule(m[1], body.get("schedule", []))

@route("PUT", r"/api/devices/(\d+)/voice", ("admin",))
def voice(svc, m, body, q): return svc.set_voice(m[1], body)

@route("POST", r"/api/devices/(\d+)/recordings", ("admin",))
def recording(svc, m, body, q): return svc.add_recording(m[1], body)

@route("POST", r"/api/devices/(\d+)/publish", ("admin",))
def publish(svc, m, body, q): return svc.publish(m[1])

@route("GET", r"/api/devices/(\d+)/preview/([01])/([1-4])", ("admin", "viewer"))
def preview(svc, m, body, q): return ("audio/wav", svc.preview_wav(m[1], m[2], m[3]))

@route("GET", r"/api/devices/(\d+)/package/latest", ("device", "admin"))
def package(svc, m, body, q):
    v, crc, data = svc.latest_package(m[1])
    return ("application/octet-stream", data, {"X-Config-Version": str(v), "ETag": f'"{v}-{crc:08x}"'})

@route("POST", r"/api/devices/(\d+)/events", ("device",))
def events_in(svc, m, body, q):
    r = svc.add_events(m[1], body.get("events", []))
    hook = svc.cfg.get("event_webhook")              # 보호자 웹(알림 판단)으로 전달
    if hook and r["events"]:
        threading.Thread(target=_post, args=(hook, {"device_id": int(m[1]), "events": r["events"]}), daemon=True).start()
    return {k: r[k] for k in ("received", "added")}

@route("GET", r"/api/devices/(\d+)/events", ("admin", "viewer"))
def events_out(svc, m, body, q): return {"events": svc.list_events(m[1], int(q.get("since", ["0"])[0]))}


def _post(url, obj):
    try:
        urllib.request.urlopen(urllib.request.Request(url, json.dumps(obj, ensure_ascii=False).encode(),
                                                      {"Content-Type": "application/json"}), timeout=5)
    except Exception:
        pass


def make_handler(svc):
    with open(os.path.join(os.path.dirname(__file__), "console.html"), "rb") as f:
        console = f.read()

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a): pass

        def _send(self, code, ctype, data, headers=None):
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items(): self.send_header(k, v)
            self.end_headers(); self.wfile.write(data)

        def _json(self, code, obj):
            self._send(code, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode())

        def _do(self, method):
            u = urllib.parse.urlparse(self.path)
            if method == "GET" and u.path in ("/", "/console"):
                return self._send(200, "text/html; charset=utf-8", console)
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n > 5 * 1024 * 1024: return self._json(413, {"error": "5MB 초과"})
            raw = self.rfile.read(n) if n else b""
            for meth, rx, roles, fn in ROUTES:
                mm = rx.match(u.path)
                if meth != method or not mm: continue
                try:
                    if roles:
                        tok = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                        svc.check(mm[1], tok, roles)
                    ctype = self.headers.get("Content-Type", "")
                    body = raw if ctype.startswith("audio/") or ctype == "application/octet-stream" else (json.loads(raw) if raw else {})
                    r = fn(svc, mm, body, urllib.parse.parse_qs(u.query))
                    if isinstance(r, tuple):
                        hdr = r[2] if len(r) > 2 else {}
                        if "ETag" in hdr and self.headers.get("If-None-Match") == hdr["ETag"]:
                            return self._send(304, r[0], b"", hdr)
                        return self._send(200, r[0], r[1], hdr)
                    return self._json(200, r)
                except ServiceError as e:
                    return self._json(e.code, {"error": str(e)})
                except (KeyError, ValueError, TypeError) as e:
                    return self._json(400, {"error": f"요청 형식 오류: {e}"})
                except Exception as e:  # 엔진 오류 등
                    return self._json(502, {"error": str(e)})
            self._json(404, {"error": "없는 경로"})

        def do_GET(self): self._do("GET")
        def do_POST(self): self._do("POST")
        def do_PUT(self): self._do("PUT")
    return H


def serve(data_dir, config, host="127.0.0.1", port=8080):
    svc = Service(data_dir, config)
    srv = ThreadingHTTPServer((host, port), make_handler(svc))
    print(f"에이블톡 음원 생성 서버: http://{host}:{port}  (콘솔 /console, 종료 Ctrl+C)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return srv
