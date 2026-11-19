"""aacpkg 단위 시험: python -m unittest discover tests -v"""
import math, os, random, struct, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aacpkg import *
from aacpkg import adpcm, upload as up
from aacpkg.format import ENTRY_SIZE, HEADER_SIZE


def tone(n, f=440, sr=16000, a=0.5):
    return [int(a * 32767 * math.sin(2 * math.pi * f * i / sr)) for i in range(n)]


def sample_pkg(ver=1, n_entries=31):
    ids = list(range(1, 21)) + list(range(51, 56)) + list(range(101, 107))
    ents = []
    for vid in ids[:n_entries]:
        s = tone(1600 + vid * 10, 300 + vid * 5)
        prio = PRIO_EMERGENCY if vid in (3, 4, 11, 12) else PRIO_SYSTEM if vid > 100 else PRIO_NORMAL
        ents.append(Entry(vid, f"문구{vid}", 1, prio, 0, adpcm.encode(s), len(s)))
    zones = [Zone(0, 1, (217, 71, 58)), Zone(1, 2, (232, 164, 0)), Zone(2, 3, (58, 154, 74), 104), Zone(3, 4, (47, 111, 191))]
    return Package(ver, CODEC_IMA_ADPCM, 16000, ents, zones, ver - 1)


class TestAdpcm(unittest.TestCase):
    def test_roundtrip_snr(self):
        s = tone(16000)
        d = adpcm.decode(adpcm.encode(s), len(s))
        err = sum((a - b) ** 2 for a, b in zip(s, d)) / len(s)
        sig = sum(a * a for a in s) / len(s)
        self.assertGreater(10 * math.log10(sig / err), 20.0)   # 4bit ADPCM 음성 품질 기준
        self.assertEqual(len(adpcm.encode(s)), len(s) // 2)


class TestFormat(unittest.TestCase):
    def test_roundtrip(self):
        pkg = sample_pkg()
        p2 = parse_package(build_package(pkg))
        self.assertEqual(len(p2.entries), 31)
        self.assertEqual([e.vocab_id for e in p2.entries], sorted(e.vocab_id for e in pkg.entries))
        self.assertEqual(p2.zones[2].long_press_vocab_id, 104)
        for e in pkg.entries:
            self.assertEqual(p2.entry(e.vocab_id).audio, e.audio)

    def test_alignment(self):
        data = build_package(sample_pkg())
        hdr = struct.unpack_from("<4sHHIIHBBIIIIIIIIIIII8s", data)
        self.assertEqual(hdr[16] % 4, 0)    # audio_off 4바이트 정렬

    def test_reject_corruption(self):
        data = bytearray(build_package(sample_pkg()))
        rnd = random.Random(1)
        rejected = 0
        for _ in range(200):                # 무작위 1바이트 손상 200회 → 전부 거부되어야 함
            d = bytearray(data); i = rnd.randrange(len(d)); d[i] ^= 1 << rnd.randrange(8)
            with self.assertRaises(PackageError):
                parse_package(bytes(d))
            rejected += 1
        self.assertEqual(rejected, 200)
        with self.assertRaises(PackageError):
            parse_package(bytes(data[:-10]))      # 잘린 파일

    def test_bad_zone(self):
        pkg = sample_pkg(); pkg.zones[0].vocab_id = 999
        with self.assertRaises(PackageError):
            build_package(pkg)


class TestUpload(unittest.TestCase):
    def test_upload_and_rollback(self):
        dev = up.SimulatedDevice()
        u = up.Uploader(dev, timeout=0.2, log=lambda *_: None)
        for ver in (1, 2):
            data = build_package(sample_pkg(ver)); p = parse_package(data)
            u.upload(data, ver, p.payload_crc)
        self.assertEqual(u.query(), (2, 1))
        self.assertEqual(u.rollback(), up.ST_OK)
        self.assertEqual(u.query(), (1, 2))

    def test_corrupt_upload_keeps_active(self):
        dev = up.SimulatedDevice(); u = up.Uploader(dev, timeout=0.2, log=lambda *_: None)
        good = build_package(sample_pkg(1)); u.upload(good, 1, parse_package(good).payload_crc)
        bad = bytearray(build_package(sample_pkg(2))); bad[500] ^= 0xFF
        with self.assertRaises(RuntimeError):
            u.upload(bytes(bad), 2, 0)
        self.assertEqual(dev.active_package().set_version, 1)

    def test_packet_loss_retry(self):
        dev = up.SimulatedDevice(drop_every=7)          # 7번째 프레임마다 손실
        u = up.Uploader(dev, timeout=0.05, retries=5, log=lambda *_: None)
        data = build_package(sample_pkg(1)); u.upload(data, 1, parse_package(data).payload_crc)
        self.assertEqual(dev.active_package().set_version, 1)

    def test_frame_crc(self):
        f = bytearray(up.make_frame(up.T_DATA, 1, b"abc")); f[7] ^= 1
        (_, _, _, ok), = up.FrameReader().feed(bytes(f))
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
