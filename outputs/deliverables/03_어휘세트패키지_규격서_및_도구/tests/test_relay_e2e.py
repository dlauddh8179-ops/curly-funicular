"""종단 시험: 음원 생성 서버(HTTP) ↔ 중계(Relay) ↔ 기기 모델(SimulatedDevice)."""
import os, shutil, sys, tempfile, threading, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "02_음원생성서버"))
from http.server import ThreadingHTTPServer
from aacpkg import upload as up
from aacpkg.relay import Relay


class E2E(unittest.TestCase):
    def test_flow(self):
        try:
            from ablevoice_server.service import Service
            from ablevoice_server.api import make_handler
        except ImportError:
            self.skipTest("02_음원생성서버 없음")
        tmp = tempfile.mkdtemp()
        try:
            svc = Service(tmp, {"engine": "espeak"}); tok = svc.create_device("1001")
            srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(svc)); url = f"http://127.0.0.1:{srv.server_address[1]}"
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            dev = up.SimulatedDevice(); r = Relay(url, 1001, tok["device"], dev, log=lambda *_: None)
            r.u.timeout = 0.2
            self.assertEqual(r.sync_package(), "서버에 패키지 없음")
            svc.publish("1001")
            self.assertEqual(r.sync_package(), "v0 → v1 전송")
            self.assertEqual(r.sync_package(), "변경 없음")                     # ETag 304
            svc.set_slot("1001", 1, 2, {"mode": "text", "text": "우유 더 주세요"}); svc.publish("1001")
            self.assertEqual(r.sync_package(), "v1 → v2 전송")
            pk = dev.active_package()
            self.assertEqual(pk.entry(pk.button(1, 1).vocab_id).text, "우유 더 주세요")
            self.assertEqual(r.sync_time(), "OK")
            for k in range(30): dev.press(1, k % 4, pk.button(1, k % 4).vocab_id, 1794790800 + k, 2)
            self.assertEqual(r.sync_events(), 30)
            self.assertEqual(dev.events, [])
            got = svc.list_events("1001")
            self.assertEqual(len(got), 30)
            self.assertEqual(got[1]["text"], "우유 더 주세요"); self.assertEqual(got[1]["button"], 2)
            srv.shutdown(); srv.server_close()
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
