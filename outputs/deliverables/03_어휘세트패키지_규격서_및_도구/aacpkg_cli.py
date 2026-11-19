#!/usr/bin/env python3
"""AAC 어휘 세트 패키지 도구 (변환·검사·업로드).

  python aacpkg_cli.py build   vocab.json out.aacpkg [--codec adpcm|pcm16]
  python aacpkg_cli.py inspect out.aacpkg
  python aacpkg_cli.py extract out.aacpkg 폴더      # 패키지 안 음원을 WAV로 꺼내 청취 확인
  python aacpkg_cli.py upload  out.aacpkg --serial COM5 | --ble AA:BB:CC:DD:EE:FF
  python aacpkg_cli.py query   --serial COM5
  python aacpkg_cli.py rollback --serial COM5
"""
import argparse, sys, os, wave, struct
from aacpkg import parse_package, CODEC_IMA_ADPCM, adpcm
from aacpkg.build import build_from_json
from aacpkg import upload as up

PRIO_NAME = {0: "일반", 1: "시스템", 2: "응급"}


def transport(a):
    if a.serial: return up.SerialTransport(a.serial, a.baud)
    if a.ble: return up.BleTransport(a.ble)
    sys.exit("--serial 또는 --ble 지정 필요")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build"); b.add_argument("vocab"); b.add_argument("out"); b.add_argument("--codec", default="adpcm", choices=["adpcm", "pcm16"])
    i = sp.add_parser("inspect"); i.add_argument("pkg")
    e = sp.add_parser("extract"); e.add_argument("pkg"); e.add_argument("outdir")
    for name in ("upload", "query", "rollback"):
        s = sp.add_parser(name)
        if name == "upload": s.add_argument("pkg")
        s.add_argument("--serial"); s.add_argument("--baud", type=int, default=115200); s.add_argument("--ble")
    a = p.parse_args()

    if a.cmd == "build":
        data = build_from_json(a.vocab, a.out, a.codec)
        print(f"생성: {a.out} ({len(data):,} bytes)")
    elif a.cmd == "inspect":
        pkg = parse_package(open(a.pkg, "rb").read())
        print(f"세트 버전 {pkg.set_version} (이전 {pkg.prev_set_version}) · 코덱 {'IMA-ADPCM' if pkg.codec == CODEC_IMA_ADPCM else 'PCM16'} · {pkg.sample_rate}Hz · CRC {pkg.payload_crc:08X} 검증 OK")
        for en in pkg.entries:
            print(f"  [{en.vocab_id:3d}] {PRIO_NAME[en.priority]:3s} {en.duration_ms:5d}ms {len(en.audio):7,}B  {en.text}")
        for z in pkg.zones:
            print(f"  영역{z.zone_id} → {z.vocab_id} RGB{z.rgb} 길게누르기→{z.long_press_vocab_id if z.long_press_vocab_id != 0xFFFF else '-'}")
    elif a.cmd == "extract":
        pkg = parse_package(open(a.pkg, "rb").read()); os.makedirs(a.outdir, exist_ok=True)
        for en in pkg.entries:
            s = adpcm.decode(en.audio, en.sample_count) if pkg.codec == CODEC_IMA_ADPCM else list(struct.unpack("<%dh" % en.sample_count, en.audio))
            with wave.open(os.path.join(a.outdir, f"{en.vocab_id:03d}.wav"), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(pkg.sample_rate); w.writeframes(struct.pack("<%dh" % len(s), *s))
        print(f"{len(pkg.entries)}개 WAV 추출 → {a.outdir}")
    else:
        u = up.Uploader(transport(a))
        if a.cmd == "query":
            act, prev = u.query(); print(f"활성 세트 {act}, 이전 세트 {prev}")
        elif a.cmd == "rollback":
            print("롤백:", up.STATUS_TEXT[u.rollback()])
        else:
            data = open(a.pkg, "rb").read(); pkg = parse_package(data)
            u.upload(data, pkg.set_version, pkg.payload_crc, lambda d, t: print(f"\r  {d:,}/{t:,} bytes", end=""))
            print("\n업로드 완료:", u.query())


if __name__ == "__main__":
    main()
