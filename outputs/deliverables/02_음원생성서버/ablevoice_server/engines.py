"""서버 TTS 엔진 어댑터.

- AbleTalkEngine : u2tech AbleTalk TTS. ※ 엔진 API 규격(엔드포인트·인증·파라미터)은 u2tech 측 자료로
  확정해야 함. 아래 구현은 일반적인 HTTP 합성 API 형태를 가정했고, server_config.json 의 abletalk 항목과
  _request()·synthesize() 두 곳만 맞추면 되도록 분리함.
- EspeakEngine   : 개발·시험용 임시 엔진(espeak-ng). 음질이 낮아 납품 음원에는 쓰지 않음.
- WavFileEngine  : 미리 녹음/합성된 WAV 파일을 가져옴(가족 목소리 등, 동의 절차 후).
"""
import json, os, shutil, subprocess, tempfile, urllib.request, urllib.error


class EngineError(RuntimeError):
    pass


class BaseEngine:
    name = "base"
    def voices(self):
        return []
    def synthesize(self, text, out_wav, voice=None, rate=1.0, pitch=1.0, volume=1.0):
        raise NotImplementedError


class AbleTalkEngine(BaseEngine):
    name = "abletalk"

    def __init__(self, base_url, api_key="", default_voice="", timeout=20, extra=None):
        self.base_url, self.api_key, self.default_voice, self.timeout = base_url.rstrip("/"), api_key, default_voice, timeout
        self.extra = extra or {}

    def _request(self, path, body):
        req = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.api_key}"} if self.api_key else
                                     {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.read(), r.headers.get("Content-Type", "")
        except urllib.error.URLError as e:
            raise EngineError(f"AbleTalk 엔진 호출 실패: {e}")

    def voices(self):
        try:
            data, _ = self._request("/voices", {})
            return json.loads(data)
        except Exception:
            return [self.default_voice] if self.default_voice else []

    def synthesize(self, text, out_wav, voice=None, rate=1.0, pitch=1.0, volume=1.0):
        body = {"text": text, "voice": voice or self.default_voice, "speed": rate, "pitch": pitch,
                "volume": volume, "format": "wav", **self.extra}
        data, ctype = self._request("/synthesize", body)
        if not data.startswith(b"RIFF"):
            raise EngineError(f"WAV 응답이 아님 (Content-Type: {ctype})")
        open(out_wav, "wb").write(data)


class EspeakEngine(BaseEngine):
    name = "espeak"

    def __init__(self, exe=None):
        self.exe = exe or shutil.which("espeak-ng") or shutil.which("espeak")
        if not self.exe:
            raise EngineError("espeak-ng 미설치")

    def voices(self):
        return ["ko", "ko+f3", "ko+m3"]

    def synthesize(self, text, out_wav, voice=None, rate=1.0, pitch=1.0, volume=1.0):
        args = [self.exe, "-v", voice or "ko+f3", "-s", str(int(155 * rate)), "-p", str(int(50 * pitch)),
                "-a", str(int(150 * volume)), "-w", out_wav, text]
        r = subprocess.run(args, capture_output=True)
        if r.returncode != 0:
            raise EngineError(r.stderr.decode(errors="ignore"))


class WavFileEngine(BaseEngine):
    name = "wavfile"

    def __init__(self, folder):
        self.folder = folder

    def synthesize(self, text, out_wav, voice=None, **_):
        src = os.path.join(self.folder, voice) if voice else None
        if not src or not os.path.exists(src):
            raise EngineError(f"WAV 파일 없음: {src}")
        shutil.copyfile(src, out_wav)


def make_engine(cfg):
    kind = cfg.get("engine", "abletalk")
    if kind == "abletalk":
        a = cfg.get("abletalk", {})
        if not a.get("base_url"):
            raise EngineError("server_config.json 의 abletalk.base_url 미설정 — u2tech 엔진 정보 확정 후 입력")
        return AbleTalkEngine(a["base_url"], a.get("api_key", ""), a.get("voice", ""), extra=a.get("extra"))
    if kind == "espeak":
        return EspeakEngine(cfg.get("espeak_exe"))
    if kind == "wavfile":
        return WavFileEngine(cfg.get("wav_folder", "recordings"))
    raise EngineError(f"알 수 없는 엔진 {kind}")
