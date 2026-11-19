"""기기 설정 JSON + 본체 포맷 WAV → .aacpkg v2.

설정 JSON 예:
{ "config_version": 3, "prev_config_version": 2, "device_id": 1001, "sample_rate": 16000,
  "buttons": [ {"set": 0, "button": 0, "id": 1101, "text": "물 주세요", "source": "library", "wav": "audio/1101.wav"}, ... 8개 ],
  "schedule": [ {"days": [0,1,2,3,4], "start": "09:00", "end": "16:00"} ] }
"""
import json, os, struct, wave
from . import adpcm
from .format import (Package, Entry, ButtonMap, Schedule, build_package, CODEC_IMA_ADPCM, CODEC_PCM16, PRIO_NORMAL,
                     PRIO_HELP, SRC_LIBRARY, SRC_TEXT, SRC_RECORDING, DEFAULT_RGB, SET_WORKPLACE)

SRC = {"library": SRC_LIBRARY, "text": SRC_TEXT, "recording": SRC_RECORDING}


def read_wav_mono16(path, expect_rate):
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path}: 모노 16bit WAV 필요")
        if w.getframerate() != expect_rate:
            raise ValueError(f"{path}: 샘플레이트 {w.getframerate()} ≠ {expect_rate}")
        raw = w.readframes(w.getnframes())
    return list(struct.unpack("<%dh" % (len(raw) // 2), raw))


def hhmm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def package_from_config(cfg, base_dir=".", codec="adpcm"):
    sr = cfg.get("sample_rate", 16000)
    c = CODEC_IMA_ADPCM if codec == "adpcm" else CODEC_PCM16
    entries, maps, seen = [], [], {}
    for b in cfg["buttons"]:
        vid = b["id"]
        if vid not in seen:
            s = read_wav_mono16(os.path.join(base_dir, b["wav"]), sr)
            audio = adpcm.encode(s) if c == CODEC_IMA_ADPCM else struct.pack("<%dh" % len(s), *s)
            prio = PRIO_HELP if b["button"] == 3 else PRIO_NORMAL
            seen[vid] = Entry(vid, b["text"], SRC[b.get("source", "library")], prio, audio, len(s))
            entries.append(seen[vid])
        maps.append(ButtonMap(b["set"], b["button"], vid, tuple(b.get("rgb", DEFAULT_RGB[b["button"]]))))
    sched = []
    for s in cfg.get("schedule", []):
        days = sum(1 << d for d in s["days"])
        sched.append(Schedule(days, hhmm(s["start"]), hhmm(s["end"]), s.get("set", SET_WORKPLACE)))
    return Package(cfg["config_version"], c, sr, entries, maps, sched, cfg.get("prev_config_version", 0), cfg.get("device_id", 0))


def build_from_json(config_json, out_path, codec="adpcm"):
    cfg = json.load(open(config_json, encoding="utf-8"))
    data = build_package(package_from_config(cfg, os.path.dirname(os.path.abspath(config_json)), codec))
    open(out_path, "wb").write(data)
    return data
