#!/usr/bin/env python3
"""에이블톡 기기 음원 패키지 도구 (변환·검사·추출·전송·기록 회수).

  python aacpkg_cli.py build    device_config.json out.aacpkg [--codec adpcm|pcm16]
  python aacpkg_cli.py inspect  out.aacpkg
  python aacpkg_cli.py extract  out.aacpkg 폴더
  python aacpkg_cli.py upload   out.aacpkg --ble AA:BB:.. | --serial COM5
  python aacpkg_cli.py query    --ble ..        (활성/이전 설정 버전)
  python aacpkg_cli.py rollback --ble ..
  python aacpkg_cli.py settime  --ble .. [--tz 540]
  python aacpkg_cli.py events   --ble ..        (누름 기록 회수, CSV 출력)
  python aacpkg_cli.py sync     --ble .. --server https://.. --device 1001 --token 기기토큰   (중계 1회: 패키지·시각·기록)
"""
import argparse, os, struct, sys, time, wave
from aacpkg import parse_package, CODEC_IMA_ADPCM, SET_NAMES, adpcm
from aacpkg.build import build_from_json
from aacpkg import upload as up

SRC = {0: "목록", 1: "직접입력", 2: "녹음"}
DAYS = "월화수목금토일"


def transport(a):
    if a.serial: return up.SerialTransport(a.serial, a.baud)
    if a.ble: return up.BleTransport(a.ble)
    sys.exit("--serial 또는 --ble 지정 필요")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build"); b.add_argument("config"); b.add_argument("out"); b.add_argument("--codec", default="adpcm", choices=["adpcm", "pcm16"])
    i = sp.add_parser("inspect"); i.add_argument("pkg")
    e = sp.add_parser("extract"); e.add_argument("pkg"); e.add_argument("outdir")
    for name in ("upload", "query", "rollback", "settime", "events", "sync"):
        s = sp.add_parser(name)
        if name == "upload": s.add_argument("pkg")
        if name in ("settime", "sync"): s.add_argument("--tz", type=int, default=540)
        if name == "sync": s.add_argument("--server", required=True); s.add_argument("--device", required=True); s.add_argument("--token", required=True)
        s.add_argument("--serial"); s.add_argument("--baud", type=int, default=115200); s.add_argument("--ble")
    a = p.parse_args()

    if a.cmd == "build":
        data = build_from_json(a.config, a.out, a.codec); print(f"생성: {a.out} ({len(data):,} bytes)")
    elif a.cmd == "inspect":
        pk = parse_package(open(a.pkg, "rb").read())
        print(f"기기 {pk.device_id} · 설정 v{pk.config_version}(이전 v{pk.prev_config_version}) · "
              f"{'IMA-ADPCM' if pk.codec == CODEC_IMA_ADPCM else 'PCM16'} {pk.sample_rate}Hz · CRC {pk.payload_crc:08X} 검증 OK")
        for bm in sorted(pk.buttons, key=lambda x: (x.set_id, x.button)):
            en = pk.entry(bm.vocab_id)
            print(f"  {SET_NAMES[bm.set_id]:3s} 버튼{bm.button + 1} [{en.vocab_id:5d}] {SRC[en.source]:4s} {en.duration_ms:5d}ms  {en.text}")
        for s in pk.schedule:
            d = "".join(DAYS[k] for k in range(7) if s.days >> k & 1)
            print(f"  시간표: {d} {s.start_min // 60:02d}:{s.start_min % 60:02d}~{s.end_min // 60:02d}:{s.end_min % 60:02d} → {SET_NAMES[s.set_id]} 세트")
    elif a.cmd == "extract":
        pk = parse_package(open(a.pkg, "rb").read()); os.makedirs(a.outdir, exist_ok=True)
        for en in pk.entries:
            s = adpcm.decode(en.audio, en.sample_count) if pk.codec == CODEC_IMA_ADPCM else list(struct.unpack("<%dh" % en.sample_count, en.audio))
            with wave.open(os.path.join(a.outdir, f"{en.vocab_id}.wav"), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(pk.sample_rate); w.writeframes(struct.pack("<%dh" % len(s), *s))
        print(f"{len(pk.entries)}개 WAV 추출 → {a.outdir}")
    elif a.cmd == "sync":
        from aacpkg.relay import Relay
        print(Relay(a.server, a.device, a.token, transport(a), a.tz).sync_all())
    else:
        u = up.Uploader(transport(a))
        if a.cmd == "query":
            print("활성 v%d, 이전 v%d" % u.query())
        elif a.cmd == "rollback":
            print("롤백:", up.STATUS_TEXT[u.rollback()])
        elif a.cmd == "settime":
            print("시각 설정:", up.STATUS_TEXT[u.set_time(time.time(), a.tz)])
        elif a.cmd == "events":
            evs, dropped = u.fetch_events()
            print("unix_time,vocab_id,set,button,config_version")
            for t, vid, s, btn, cfg in evs: print(f"{t},{vid},{s},{btn + 1},{cfg}")
            if dropped: print(f"# 기기 버퍼 초과로 유실 {dropped}건", file=sys.stderr)
        else:
            data = open(a.pkg, "rb").read(); pk = parse_package(data)
            u.upload(data, pk.config_version, pk.payload_crc, lambda d, t: print(f"\r  {d:,}/{t:,} bytes", end=""))
            print("\n전송 완료:", u.query())


if __name__ == "__main__":
    main()
