"""어휘 세트 정의(JSON) + WAV → .aacpkg 변환."""
import json, wave, struct, os
from . import adpcm
from .format import Package, Entry, Zone, build_package, CODEC_IMA_ADPCM, CODEC_PCM16, CATEGORIES, NO_VOCAB

PRIO = {"normal": 0, "system": 1, "emergency": 2}


def read_wav_mono16(path, expect_rate):
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path}: 모노 16bit WAV 필요(음원 생성 도구의 '본체 포맷' 출력 사용)")
        if w.getframerate() != expect_rate:
            raise ValueError(f"{path}: 샘플레이트 {w.getframerate()} ≠ {expect_rate}")
        raw = w.readframes(w.getnframes())
    return list(struct.unpack("<%dh" % (len(raw) // 2), raw))


def build_from_json(vocab_json, out_path, codec="adpcm"):
    spec = json.load(open(vocab_json, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(vocab_json))
    sr = spec.get("sample_rate", 16000)
    c = CODEC_IMA_ADPCM if codec == "adpcm" else CODEC_PCM16
    entries = []
    for it in spec["entries"]:
        samples = read_wav_mono16(os.path.join(base, it["device_wav"]), sr)
        audio = adpcm.encode(samples) if c == CODEC_IMA_ADPCM else struct.pack("<%dh" % len(samples), *samples)
        sym = b""
        if it.get("symbol"):
            sym = open(os.path.join(base, it["symbol"]), "rb").read()
        entries.append(Entry(it["id"], it["text"], CATEGORIES.get(it.get("category", "생활"), 1),
                             PRIO[it.get("priority", "normal")], 0, audio, len(samples), sym))
    zones = [Zone(z["zone"], z["id"], tuple(z["rgb"]), z.get("long_press_id", NO_VOCAB)) for z in spec["zones"]]
    pkg = Package(spec["set_version"], c, sr, entries, zones, spec.get("prev_set_version", 0))
    data = build_package(pkg)
    open(out_path, "wb").write(data)
    return data
