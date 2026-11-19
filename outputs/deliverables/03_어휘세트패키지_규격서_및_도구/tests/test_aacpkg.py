"""aacpkg v2 단위 시험: python -m unittest discover tests -v"""
import math, os, random, struct, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aacpkg import *
from aacpkg import adpcm, upload as up
from aacpkg.format import active_set


def tone(n, f=440, sr=16000, a=0.5):
    return [int(a * 32767 * math.sin(2 * math.pi * f * i / sr)) for i in range(n)]


def sample_pkg(ver=1):
    ents, maps = [], []
    for s in range(2):
        for b in range(4):
            vid = 1000 * (s + 1) + 100 * (b + 1) + 1
            x = tone(1600 + vid % 97 * 10, 300 + b * 50)
            ents.append(Entry(vid, f"문장{s}{b}", SRC_LIBRARY, PRIO_HELP if b == 3 else PRIO_NORMAL, adpcm.encode(x), len(x)))
            maps.append(ButtonMap(s, b, vid, (10 * b, 20, 30)))
    return Package(ver, CODEC_IMA_ADPCM, 16000, ents, maps, [Schedule(0b0011111, 540, 960)], ver - 1, 1001)


class TestAdpcm(unittest.TestCase):
    def test_roundtrip_snr(self):
        s = tone(16000); d = adpcm.decode(adpcm.encode(s), len(s))
        err = sum((a - b) ** 2 for a, b in zip(s, d)) / len(s); sig = sum(a * a for a in s) / len(s)
        self.assertGreater(10 * math.log10(sig / err), 20.0)


class TestFormat(unittest.TestCase):
    def test_roundtrip(self):
        p2 = parse_package(build_package(sample_pkg()))
        self.assertEqual(len(p2.entries), 8)
        self.assertEqual(p2.button(1, 3).vocab_id, 2401)
        self.assertEqual(p2.entry(2401).priority, PRIO_HELP)
        self.assertEqual((p2.schedule[0].start_min, p2.schedule[0].end_min, p2.device_id), (540, 960, 1001))

    def test_schedule_rule(self):
        sc = sample_pkg().schedule                       # 월~금 09:00~16:00 작업장
        self.assertEqual(active_set(sc, 0, 9 * 60), SET_WORKPLACE)
        self.assertEqual(active_set(sc, 4, 16 * 60 - 1), SET_WORKPLACE)
        self.assertEqual(active_set(sc, 4, 16 * 60), SET_GENERAL)
        self.assertEqual(active_set(sc, 5, 10 * 60), SET_GENERAL)   # 토요일

    def test_reject_corruption(self):
        data = build_package(sample_pkg()); rnd = random.Random(1)
        for _ in range(200):
            d = bytearray(data); i = rnd.randrange(len(d)); d[i] ^= 1 << rnd.randrange(8)
            with self.assertRaises(PackageError): parse_package(bytes(d))

    def test_validation(self):
        p = sample_pkg(); p.buttons.pop()
        with self.assertRaises(PackageError): build_package(p)      # 8개 매핑 필수
        p = sample_pkg(); p.entries[0].text = "열여섯 글자가 넘는 아주 긴 문장입니다"
        with self.assertRaises(PackageError): build_package(p)      # 15자 제한
        p = sample_pkg(); p.schedule[0].end_min = 1500
        with self.assertRaises(PackageError): build_package(p)


class TestTransfer(unittest.TestCase):
    def setUp(self):
        self.dev = up.SimulatedDevice(); self.u = up.Uploader(self.dev, timeout=0.2, log=lambda *_: None)

    def send(self, ver):
        data = build_package(sample_pkg(ver)); self.u.upload(data, ver, parse_package(data).payload_crc)

    def test_upload_rollback(self):
        self.send(1); self.send(2)
        self.assertEqual(self.u.query(), (2, 1))
        self.assertEqual(self.u.rollback(), up.ST_OK); self.assertEqual(self.u.query(), (1, 2))

    def test_corrupt_upload_keeps_active(self):
        self.send(1); bad = bytearray(build_package(sample_pkg(2))); bad[300] ^= 0xFF
        with self.assertRaises(RuntimeError): self.u.upload(bytes(bad), 2, 0)
        self.assertEqual(self.dev.active_package().config_version, 1)

    def test_packet_loss(self):
        dev = up.SimulatedDevice(drop_every=7); u = up.Uploader(dev, timeout=0.05, retries=5, log=lambda *_: None)
        data = build_package(sample_pkg(1)); u.upload(data, 1, parse_package(data).payload_crc)
        self.assertEqual(dev.active_package().config_version, 1)

    def test_events_and_time(self):
        for k in range(45): self.dev.press(k % 2, k % 4, 1101, 1_790_000_000 + k, 1)
        evs, dropped = self.u.fetch_events()
        self.assertEqual((len(evs), dropped), (45, 0))
        self.assertEqual(evs[0][0], 1_790_000_000); self.assertEqual(self.dev.events, [])
        self.assertEqual(self.u.set_time(1_790_000_000, 540), up.ST_OK); self.assertEqual(self.dev.time, 1_790_000_000)

    def test_event_overflow(self):
        for k in range(130): self.dev.press(0, 0, 1101, k)
        evs, dropped = self.u.fetch_events()
        self.assertEqual((len(evs), dropped, evs[0][0]), (128, 2, 2))


if __name__ == "__main__":
    unittest.main()
