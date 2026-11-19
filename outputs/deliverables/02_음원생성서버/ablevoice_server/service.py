"""서버 핵심 로직(HTTP 와 분리). 저장소는 파일 시스템(data_dir)."""
import hashlib, json, os, secrets, sys, threading, time
from . import audio
from .engines import make_engine, EngineError

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 16000
MAX_CHARS = 15
MAX_REC_SEC = 6.0
SET_NAMES = {0: "일반", 1: "작업장"}


def _aacpkg():
    try:
        import aacpkg  # noqa
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "03_어휘세트패키지_규격서_및_도구"))
    from aacpkg.build import package_from_config
    from aacpkg import build_package, parse_package
    return package_from_config, build_package, parse_package


class ServiceError(ValueError):
    def __init__(self, msg, code=400):
        super().__init__(msg); self.code = code


def _rj(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _wj(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def _rb(path):
    with open(path, "rb") as f:
        return f.read()


def _lines(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _h(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Service:
    def __init__(self, data_dir, config=None):
        self.dir = os.path.abspath(data_dir)
        os.makedirs(os.path.join(self.dir, "devices"), exist_ok=True)
        os.makedirs(os.path.join(self.dir, "tts_cache"), exist_ok=True)
        self.cfg = config or {"engine": "abletalk"}
        self.library = _rj(os.path.join(HERE, "data", "library.json"))
        self.by_id = {s["id"]: s["text"] for st in self.library["sets"] for b in st["buttons"] for s in b["sentences"]}
        self.lock = threading.RLock()
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = make_engine(self.cfg)
        return self._engine

    # ---------- 기기 ----------
    def _ddir(self, dev):
        if not str(dev).isdigit() or not (0 < int(dev) < 2 ** 32):
            raise ServiceError("기기 ID는 숫자", 404)
        return os.path.join(self.dir, "devices", str(int(dev)))

    def _load(self, dev):
        p = os.path.join(self._ddir(dev), "device.json")
        if not os.path.exists(p):
            raise ServiceError("없는 기기", 404)
        return _rj(p)

    def _save(self, dev, d):
        _wj(os.path.join(self._ddir(dev), "device.json"), d)

    def create_device(self, dev, name=""):
        """기기 등록. 기본 선택: 각 버튼 1번 문장, 작업장 시간 월~금 09:00~16:00. 토큰 3종 반환(한 번만 표시)."""
        with self.lock:
            d = self._ddir(dev)
            if os.path.exists(os.path.join(d, "device.json")):
                raise ServiceError("이미 있는 기기", 409)
            for sub in ("recordings", "packages", "audio"):
                os.makedirs(os.path.join(d, sub), exist_ok=True)
            tokens = {r: secrets.token_urlsafe(24) for r in ("admin", "viewer", "device")}
            slots = {f"{s}-{b}": {"mode": "library", "id": (s + 1) * 1000 + (b + 1) * 100 + 1} for s in range(2) for b in range(4)}
            self._save(dev, {"device_id": int(dev), "name": name, "created": int(time.time()), "slots": slots,
                             "schedule": [{"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "16:00"}],
                             "voice": {"voice": "", "rate": 0.85, "pitch": 1.0, "volume": 1.0},
                             "config_version": 0, "dirty": True, "tokens": {r: _h(t) for r, t in tokens.items()}})
            return tokens

    def check(self, dev, token, roles):
        """roles 중 하나의 토큰이면 통과. admin 은 문장 변경 권한(관리자 보호자 1명)."""
        d = self._load(dev)
        h = _h(token or "")
        for r in roles:
            if secrets.compare_digest(d["tokens"].get(r, ""), h):
                return r
        raise ServiceError("권한 없음", 403)

    def library_view(self):
        return self.library

    def device_view(self, dev):
        d = self._load(dev)
        slots = []
        for s in range(2):
            for b in range(4):
                sl = d["slots"][f"{s}-{b}"]
                slots.append({"set": s, "set_name": SET_NAMES[s], "button": b + 1, **sl, "text": self._slot_text(d, s, b)})
        return {"device_id": d["device_id"], "name": d["name"], "config_version": d["config_version"],
                "pending_changes": d["dirty"], "schedule": d["schedule"], "voice": d["voice"], "slots": slots}

    def _slot_text(self, d, s, b):
        sl = d["slots"][f"{s}-{b}"]
        if sl["mode"] == "library": return self.by_id[sl["id"]]
        if sl["mode"] == "text": return sl["text"]
        return sl.get("label", "(녹음)")

    # ---------- 설정 변경(관리자) ----------
    def set_slot(self, dev, set_id, button, body):
        set_id, button = int(set_id), int(button)
        if set_id not in (0, 1) or not 1 <= button <= 4:
            raise ServiceError("세트 0~1, 버튼 1~4")
        mode = body.get("mode")
        if mode == "library":
            vid = int(body["id"]) if "id" in body else (set_id + 1) * 1000 + button * 100 + int(body["index"])
            if vid not in self.by_id or vid // 1000 != set_id + 1 or vid // 100 % 10 != button:
                raise ServiceError("해당 세트·버튼의 문장 목록(1~20)에서 골라야 함")
            slot = {"mode": "library", "id": vid}
        elif mode == "text":
            text = " ".join(str(body.get("text", "")).split())
            if not text: raise ServiceError("문장을 입력해야 함")
            if len(text) > MAX_CHARS: raise ServiceError(f"{MAX_CHARS}자 이내로 입력(현재 {len(text)}자)")
            slot = {"mode": "text", "text": text}
        elif mode == "recording":
            rid = body.get("recording_id", "")
            if not os.path.exists(os.path.join(self._ddir(dev), "recordings", f"{rid}.wav")):
                raise ServiceError("없는 녹음")
            label = " ".join(str(body.get("label", "")).split())[:MAX_CHARS] or "(녹음)"
            slot = {"mode": "recording", "recording_id": rid, "label": label}
        else:
            raise ServiceError("mode 는 library | text | recording")
        with self.lock:
            d = self._load(dev); d["slots"][f"{set_id}-{button - 1}"] = slot; d["dirty"] = True; self._save(dev, d)
        return self.device_view(dev)

    def set_schedule(self, dev, items):
        out = []
        for it in items:
            days = sorted({int(x) for x in it["days"]})
            if not days or days[0] < 0 or days[-1] > 6: raise ServiceError("days 는 0(월)~6(일)")
            st, en = it["start"], it["end"]
            def mins(v):
                h, m = v.split(":"); h, m = int(h), int(m)
                if not (0 <= h <= 24 and 0 <= m < 60) or h * 60 + m > 1440: raise ServiceError(f"시각 형식 오류 {v}")
                return h * 60 + m
            if mins(st) >= mins(en): raise ServiceError("시작 < 끝 이어야 함(자정을 넘으면 두 개로 나눔)")
            out.append({"days": days, "start": st, "end": en})
        if len(out) > 16: raise ServiceError("시간표는 16개까지")
        with self.lock:
            d = self._load(dev); d["schedule"] = out; d["dirty"] = True; self._save(dev, d)
        return self.device_view(dev)

    def set_voice(self, dev, v):
        with self.lock:
            d = self._load(dev)
            for k in ("voice", "rate", "pitch", "volume"):
                if k in v: d["voice"][k] = v[k]
            d["dirty"] = True; self._save(dev, d)
        return self.device_view(dev)

    # ---------- 음원 ----------
    def tts(self, text, voice):
        """문장 → 본체 포맷 WAV 경로(캐시). 같은 문장·음성 설정은 한 번만 합성."""
        key = hashlib.sha1(json.dumps([self.cfg.get("engine"), text, voice], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        out = os.path.join(self.dir, "tts_cache", key + ".wav")
        if os.path.exists(out):
            return out
        raw = out + ".raw.wav"
        self.engine.synthesize(text, raw, voice.get("voice") or None, voice.get("rate", 1.0), voice.get("pitch", 1.0), voice.get("volume", 1.0))
        x, sr = audio.read_wav(raw)
        audio.write_wav(out, audio.speaker_chain(audio.resample(x, sr, SR), SR), SR)
        os.remove(raw)
        return out

    def add_recording(self, dev, wav_bytes):
        """보호자 녹음(WAV) → 잡음 제거 → 무음 제거·EQ·음량 맞춤 → 16kHz 모노. 녹음 ID 와 처리 전후 통계 반환."""
        try:
            x, sr = audio.read_wav(bytes(wav_bytes))
        except Exception as e:
            raise ServiceError(f"WAV(16bit PCM) 파일만 가능: {e}")
        if len(x) / sr > MAX_REC_SEC + 2:
            raise ServiceError(f"녹음은 {MAX_REC_SEC:.0f}초 이내")
        y = audio.resample(x, sr, SR)
        before = audio.snr_estimate_db(y, SR)
        y = audio.denoise(y, SR)
        after = audio.snr_estimate_db(y, SR)
        y = audio.speaker_chain(y, SR)
        if len(y) / SR > MAX_REC_SEC:
            raise ServiceError(f"말소리 구간이 {MAX_REC_SEC:.0f}초를 넘음")
        rid = time.strftime("%Y%m%d%H%M%S") + "_" + secrets.token_hex(3)
        audio.write_wav(os.path.join(self._ddir(dev), "recordings", rid + ".wav"), y, SR)
        return {"recording_id": rid, "noise_ratio_before_db": before, "noise_ratio_after_db": after, **audio.stats(y, SR)}

    def _slot_audio(self, dev, d, s, b):
        sl = d["slots"][f"{s}-{b}"]
        if sl["mode"] == "recording":
            return 4000 + s * 10 + b, sl.get("label", "(녹음)"), "recording", os.path.join(self._ddir(dev), "recordings", sl["recording_id"] + ".wav")
        text = self._slot_text(d, s, b)
        vid = sl["id"] if sl["mode"] == "library" else 3000 + s * 10 + b
        return vid, text, sl["mode"], self.tts(text, d["voice"])

    # ---------- 패키지 ----------
    def publish(self, dev):
        """현재 설정으로 음원을 준비(필요 시 합성)하고 기기 패키지 새 버전 생성."""
        package_from_config, build_package, parse_package = _aacpkg()
        with self.lock:
            d = self._load(dev)
            buttons = []
            for s in range(2):
                for b in range(4):
                    vid, text, src, path = self._slot_audio(dev, d, s, b)
                    buttons.append({"set": s, "button": b, "id": vid, "text": text, "source": src, "wav": path})
            ver = d["config_version"] + 1
            cfg = {"config_version": ver, "prev_config_version": d["config_version"], "device_id": d["device_id"],
                   "sample_rate": SR, "buttons": buttons, "schedule": d["schedule"]}
            data = build_package(package_from_config(cfg, "/"))
            pdir = os.path.join(self._ddir(dev), "packages")
            with open(os.path.join(pdir, f"v{ver}.aacpkg"), "wb") as f:
                f.write(data)
            _wj(os.path.join(pdir, f"v{ver}.json"), cfg)
            d["config_version"] = ver; d["dirty"] = False
            d["published"] = {"version": ver, "size": len(data), "crc": parse_package(data).payload_crc, "time": int(time.time())}
            self._save(dev, d)
            return d["published"]

    def latest_package(self, dev):
        d = self._load(dev)
        if not d.get("published"):
            raise ServiceError("아직 생성된 패키지 없음", 404)
        v = d["published"]["version"]
        return v, d["published"]["crc"], _rb(os.path.join(self._ddir(dev), "packages", f"v{v}.aacpkg"))

    def preview_wav(self, dev, set_id, button):
        d = self._load(dev)
        return _rb(self._slot_audio(dev, d, int(set_id), int(button) - 1)[3])

    # ---------- 누름 기록 ----------
    def _texts_for(self, dev):
        """설정 버전별 음원 ID → 문장(기록에 문장 표시용)."""
        pdir = os.path.join(self._ddir(dev), "packages"); m = {}
        for f in os.listdir(pdir):
            if f.endswith(".json"):
                cfg = _rj(os.path.join(pdir, f))
                for b in cfg["buttons"]: m[(cfg["config_version"], b["id"])] = b["text"]
        return m

    def add_events(self, dev, events):
        """기기 누름 기록(앱·거치대가 회수해 전달). 중복(같은 시각·버튼·음원)은 무시."""
        if not isinstance(events, list) or len(events) > 1000:
            raise ServiceError("events 는 1000건 이하 목록")
        texts = self._texts_for(dev)
        path = os.path.join(self._ddir(dev), "events.jsonl")
        with self.lock:
            seen = set()
            if os.path.exists(path):
                for e in _lines(path):
                    seen.add((e["unix_time"], e["button"], e["vocab_id"]))
            added = []
            with open(path, "a", encoding="utf-8") as f:
                for e in events:
                    rec = {"unix_time": int(e["unix_time"]), "set": int(e["set"]), "button": int(e["button"]),
                           "vocab_id": int(e["vocab_id"]), "config_version": int(e.get("config_version", 0))}
                    if not (0 <= rec["set"] <= 1 and 1 <= rec["button"] <= 4): raise ServiceError("set 0~1, button 1~4")
                    k = (rec["unix_time"], rec["button"], rec["vocab_id"])
                    if k in seen: continue
                    seen.add(k)
                    rec["text"] = texts.get((rec["config_version"], rec["vocab_id"]), self.by_id.get(rec["vocab_id"], ""))
                    rec["set_name"] = SET_NAMES[rec["set"]]
                    rec["help"] = rec["button"] == 4
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n"); added.append(rec)
        return {"received": len(events), "added": len(added), "events": added}

    def list_events(self, dev, since=0, limit=500):
        path = os.path.join(self._ddir(dev), "events.jsonl")
        if not os.path.exists(path): return []
        out = _lines(path)
        return sorted([e for e in out if e["unix_time"] >= since], key=lambda e: e["unix_time"])[-limit:]
