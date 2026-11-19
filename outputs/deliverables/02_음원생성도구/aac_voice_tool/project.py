"""프로젝트(문구 목록) 관리 · 일괄 합성 · 버전 이력 · 패키지 내보내기."""
import json, os, sys, time, tempfile
from . import audio
from .engines import make_engine, EngineError

PRESETS = {
    "고령자 기본": {"rate": 0.85, "pitch": 1.0, "volume": 1.0},
    "또렷하게(느리게)": {"rate": 0.75, "pitch": 1.05, "volume": 1.0},
    "보통": {"rate": 1.0, "pitch": 1.0, "volume": 1.0},
}


class Project:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.root = os.path.dirname(self.path)
        self.data = json.load(open(self.path, encoding="utf-8"))
        cfg_path = os.path.join(self.root, "config.json")
        self.cfg = json.load(open(cfg_path, encoding="utf-8")) if os.path.exists(cfg_path) else {"engine": "abletalk"}
        self.sr = self.data.get("sample_rate", 16000)
        for d in ("originals", "device", "packages"):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)
        hp = os.path.join(self.root, "history.json")
        self.history = json.load(open(hp, encoding="utf-8")) if os.path.exists(hp) else []

    # ---- 문구 편집 ----
    @property
    def entries(self):
        return self.data["entries"]

    def get(self, vid):
        return next((e for e in self.entries if e["id"] == vid), None)

    def upsert(self, e):
        cur = self.get(e["id"])
        if cur: cur.update(e)
        else: self.entries.append(e); self.entries.sort(key=lambda x: x["id"])
        self.save()

    def delete(self, vid):
        self.data["entries"] = [e for e in self.entries if e["id"] != vid]
        self.data["zones"] = [z for z in self.data["zones"] if z["id"] != vid]
        self.save()

    def save(self):
        json.dump(self.data, open(self.path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        json.dump(self.history, open(os.path.join(self.root, "history.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # ---- 합성 ----
    def settings_for(self, e):
        d = dict(self.data.get("voice_defaults", {}))
        for k in ("voice", "rate", "pitch", "volume"):
            if e.get(k) is not None: d[k] = e[k]
        return d

    def synthesize(self, vid, engine=None, eq=True):
        e = self.get(vid)
        engine = engine or make_engine(self.cfg)
        s = self.settings_for(e)
        ver = 1 + max((h["version"] for h in self.history if h["id"] == vid), default=0)
        orig = os.path.join("originals", f"{vid:03d}_v{ver}.wav")
        engine.synthesize(e["text"], os.path.join(self.root, orig), s.get("voice") or None,
                          s.get("rate", 1.0), s.get("pitch", 1.0), s.get("volume", 1.0))
        x, sr = audio.read_wav(os.path.join(self.root, orig))
        y = audio.speaker_chain(audio.resample(x, sr, self.sr), self.sr, eq)
        dev = os.path.join("device", f"{vid:03d}.wav")
        audio.write_wav(os.path.join(self.root, dev), y, self.sr)
        st = audio.stats(y, self.sr)
        self.history.append({"id": vid, "text": e["text"], "version": ver, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "engine": engine.name, **s, "original": orig, "device": dev, **st})
        e["device_wav"], e["original_wav"], e["version"] = dev, orig, ver
        self.save()
        return st

    def synthesize_all(self, only_missing=False, log=print):
        engine = make_engine(self.cfg)
        ok, fail = 0, []
        for e in self.entries:
            if only_missing and e.get("device_wav") and os.path.exists(os.path.join(self.root, e["device_wav"])):
                continue
            try:
                st = self.synthesize(e["id"], engine)
                log(f"[{e['id']:3d}] {e['text']} → {st['duration_ms']}ms, 피크 {st['peak_dbfs']}dBFS")
                ok += 1
            except (EngineError, OSError, ValueError) as ex:
                fail.append((e["id"], str(ex))); log(f"[{e['id']:3d}] 실패: {ex}")
        return ok, fail

    # ---- 내보내기 ----
    def export_vocab_json(self):
        out = {"set_version": self.data["set_version"], "prev_set_version": self.data.get("prev_set_version", 0),
               "sample_rate": self.sr, "entries": [], "zones": self.data["zones"]}
        for e in self.entries:
            if not e.get("device_wav"):
                raise ValueError(f"[{e['id']}] 음원 미생성")
            out["entries"].append({k: e[k] for k in ("id", "text", "category", "priority", "device_wav") if k in e}
                                  | ({"symbol": e["symbol"]} if e.get("symbol") else {}))
        p = os.path.join(self.root, "vocab_export.json")
        json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return p

    def build_package(self, codec="adpcm"):
        try:
            from aacpkg.build import build_from_json
        except ImportError:
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            sys.path.insert(0, os.path.join(os.path.dirname(here), "03_어휘세트패키지_규격서_및_도구"))
            from aacpkg.build import build_from_json
        vj = self.export_vocab_json()
        out = os.path.join(self.root, "packages", f"aac_vocab_v{self.data['set_version']}.aacpkg")
        data = build_from_json(vj, out, codec)
        return out, len(data)
