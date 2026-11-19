"""서버 통합 시험(HTTP 포함). 개발용 엔진(espeak-ng) 필요: python -m unittest discover tests -v"""
import io, json, math, os, random, shutil, struct, sys, tempfile, threading, unittest, urllib.request, urllib.error, wave
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "03_어휘세트패키지_규격서_및_도구"))
from http.server import ThreadingHTTPServer
from ablevoice_server.service import Service
from ablevoice_server.api import make_handler
from ablevoice_server import audio
from aacpkg import parse_package, SET_WORKPLACE


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.svc = Service(cls.tmp, {"engine": "espeak"})
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.svc))
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.tok = cls.svc.create_device("1001", "시험 기기")

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close(); shutil.rmtree(cls.tmp)

    def req(self, method, path, role="admin", body=None, ctype="application/json", headers=None):
        data = body if isinstance(body, (bytes, bytearray)) else (json.dumps(body).encode() if body is not None else None)
        h = {"Authorization": "Bearer " + self.tok[role]} if role else {}
        if data is not None: h["Content-Type"] = ctype
        h.update(headers or {})
        r = urllib.request.Request(self.url + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if "json" in resp.headers.get("Content-Type", "") else raw), resp.headers
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, (json.loads(raw) if raw and "json" in e.headers.get("Content-Type", "") else raw), e.headers

    def test_1_library(self):
        st, lib, _ = self.req("GET", "/api/library", role=None)
        self.assertEqual(st, 200)
        n = sum(len(b["sentences"]) for s in lib["sets"] for b in s["buttons"])
        self.assertEqual(n, 160)
        self.assertEqual(lib["sets"][1]["buttons"][3]["sentences"][1]["text"], "담당자를 불러 주세요")

    def test_2_auth(self):
        self.assertEqual(self.req("GET", "/api/devices/1001", role="viewer")[0], 200)
        self.assertEqual(self.req("PUT", "/api/devices/1001/slots/0/1", role="viewer", body={"mode": "library", "index": 2})[0], 403)
        self.assertEqual(self.req("GET", "/api/devices/1001", role="device")[0], 403)
        self.assertEqual(self.req("GET", "/api/devices/1001", role=None)[0], 403)

    def test_3_slots(self):
        st, d, _ = self.req("PUT", "/api/devices/1001/slots/0/1", body={"mode": "library", "index": 2})
        self.assertEqual((st, d["slots"][0]["text"]), (200, "배고파요"))
        st, d, _ = self.req("PUT", "/api/devices/1001/slots/0/2", body={"mode": "library", "id": 1101})
        self.assertEqual(st, 400)                                     # 버튼 1 문장을 버튼 2에 넣을 수 없음
        st, d, _ = self.req("PUT", "/api/devices/1001/slots/1/1", body={"mode": "text", "text": "오늘의 빵은 소금빵이에요"})
        self.assertEqual((st, d["slots"][4]["text"]), (200, "오늘의 빵은 소금빵이에요"))
        st, d, _ = self.req("PUT", "/api/devices/1001/slots/1/1", body={"mode": "text", "text": "가" * 16})
        self.assertEqual(st, 400)                                     # 15자 초과

    def test_4_recording(self):
        raw = os.path.join(self.tmp, "voice.wav")
        self.svc.engine.synthesize("우리 딸 보고 싶어", raw)
        x, sr = audio.read_wav(raw); rnd = random.Random(3)
        noisy = [0.0] * int(sr * 0.6) + x + [0.0] * int(sr * 0.6)
        noisy = [v + rnd.gauss(0, 0.02) for v in noisy]                # 배경 잡음
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes(struct.pack("<%dh" % len(noisy), *[max(-32768, min(32767, int(v * 32767))) for v in noisy]))
        st, r, _ = self.req("POST", "/api/devices/1001/recordings", body=buf.getvalue(), ctype="audio/wav")
        self.assertEqual(st, 200, r)
        self.assertGreater(r["noise_ratio_after_db"], r["noise_ratio_before_db"] + 6)   # 잡음 6dB 이상 감소
        self.assertEqual(r["clipped"], 0)
        type(self).rec = r
        st, d, _ = self.req("PUT", "/api/devices/1001/slots/0/3", body={"mode": "recording", "recording_id": r["recording_id"], "label": "딸 보고 싶어"})
        self.assertEqual((st, d["slots"][2]["mode"]), (200, "recording"))
        self.assertEqual(self.req("POST", "/api/devices/1001/recordings", body=b"not wav", ctype="audio/wav")[0], 400)

    def test_5_schedule(self):
        st, d, _ = self.req("PUT", "/api/devices/1001/schedule", body={"schedule": [{"days": [0, 1, 2, 3, 4], "start": "10:00", "end": "15:30"}]})
        self.assertEqual(st, 200)
        self.assertEqual(self.req("PUT", "/api/devices/1001/schedule", body={"schedule": [{"days": [0], "start": "18:00", "end": "09:00"}]})[0], 400)

    def test_6_publish_download(self):
        self.assertEqual(self.req("GET", "/api/devices/1001/package/latest", role="device")[0], 404)
        st, r, _ = self.req("POST", "/api/devices/1001/publish")
        self.assertEqual((st, r["version"]), (200, 1))
        st, data, h = self.req("GET", "/api/devices/1001/package/latest", role="device")
        pk = parse_package(data)
        self.assertEqual((pk.config_version, pk.device_id, len(pk.buttons)), (1, 1001, 8))
        self.assertEqual(pk.entry(pk.button(0, 0).vocab_id).text, "배고파요")
        self.assertEqual(pk.entry(pk.button(1, 0).vocab_id).text, "오늘의 빵은 소금빵이에요")
        self.assertEqual(pk.entry(pk.button(0, 2).vocab_id).source, 2)            # 녹음
        self.assertEqual((pk.schedule[0].start_min, pk.schedule[0].end_min, pk.schedule[0].set_id), (600, 930, SET_WORKPLACE))
        st, _, _ = self.req("GET", "/api/devices/1001/package/latest", role="device", headers={"If-None-Match": h["ETag"]})
        self.assertEqual(st, 304)
        self.assertEqual(self.req("GET", "/api/devices/1001/package/latest", role="viewer")[0], 403)
        st, wav, _ = self.req("GET", "/api/devices/1001/preview/1/4", role="viewer")
        self.assertTrue(wav.startswith(b"RIFF"))

    def test_7_events(self):
        evs = [{"unix_time": 1794790800 + i, "set": 1, "button": (i % 4) + 1, "vocab_id": 2101 if i % 4 == 1 else 0, "config_version": 1} for i in range(6)]
        pk = parse_package(self.req("GET", "/api/devices/1001/package/latest", role="device")[1])
        for e in evs: e["vocab_id"] = pk.button(1, e["button"] - 1).vocab_id
        st, r, _ = self.req("POST", "/api/devices/1001/events", role="device", body={"events": evs})
        self.assertEqual((st, r["added"]), (200, 6))
        st, r, _ = self.req("POST", "/api/devices/1001/events", role="device", body={"events": evs})
        self.assertEqual(r["added"], 0)                               # 중복 무시(재전송 안전)
        st, r, _ = self.req("GET", "/api/devices/1001/events", role="viewer")
        self.assertEqual(len(r["events"]), 6)
        self.assertEqual(r["events"][0]["text"], "오늘의 빵은 소금빵이에요")
        self.assertTrue(r["events"][3]["help"])                       # 버튼 4 = 도움 요청
        self.assertEqual(self.req("POST", "/api/devices/1001/events", role="admin", body={"events": evs})[0], 403)


if __name__ == "__main__":
    unittest.main()
