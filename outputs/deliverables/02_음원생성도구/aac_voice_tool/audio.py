"""음원 후처리 (외부 라이브러리 없이 동작): WAV 입출력, 리샘플, 무음 제거, 음량 정규화, 스피커 대역 EQ."""
import math, struct, wave


def read_wav(path):
    with wave.open(path, "rb") as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError("16bit WAV만 지원")
    s = struct.unpack("<%dh" % (len(raw) // 2), raw)
    if ch > 1:
        s = [sum(s[i:i + ch]) / ch for i in range(0, len(s), ch)]
    return [x / 32768.0 for x in s], sr


def write_wav(path, samples, sr):
    pcm = [max(-32768, min(32767, int(round(x * 32767)))) for x in samples]
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(struct.pack("<%dh" % len(pcm), *pcm))
    return pcm


def resample(x, sr_in, sr_out, taps=32):
    """윈도우드 sinc 보간 리샘플러(앤티앨리어싱 포함)."""
    if sr_in == sr_out:
        return list(x)
    ratio = sr_out / sr_in
    cutoff = min(1.0, ratio) * 0.95
    n_out = int(len(x) * ratio)
    out = []
    for i in range(n_out):
        t = i / ratio
        c = int(t)
        acc = 0.0
        for k in range(c - taps + 1, c + taps + 1):
            if 0 <= k < len(x):
                d = t - k
                w = 0.5 + 0.5 * math.cos(math.pi * d / taps) if abs(d) < taps else 0.0
                s = cutoff if d == 0 else math.sin(math.pi * cutoff * d) / (math.pi * d)
                acc += x[k] * s * w
        out.append(acc)
    return out


def trim_silence(x, sr, thresh_db=-45.0, pad_ms=30):
    thr = 10 ** (thresh_db / 20)
    win = max(1, int(sr * 0.01))
    def loud(i):
        seg = x[i:i + win]
        return seg and math.sqrt(sum(v * v for v in seg) / len(seg)) > thr
    start = next((i for i in range(0, len(x), win) if loud(i)), 0)
    end = next((i + win for i in range(len(x) - win, 0, -win) if loud(i)), len(x))
    pad = int(sr * pad_ms / 1000)
    return x[max(0, start - pad):min(len(x), end + pad)]


def normalize(x, target_dbfs=-3.0, rms_target_db=-16.0):
    """RMS를 목표치로 맞추되 피크는 target_dbfs 를 넘지 않게."""
    if not x:
        return x
    rms = math.sqrt(sum(v * v for v in x) / len(x)) or 1e-9
    peak = max(abs(v) for v in x) or 1e-9
    g = min(10 ** (rms_target_db / 20) / rms, 10 ** (target_dbfs / 20) / peak)
    return [v * g for v in x]


def _biquad(x, b0, b1, b2, a1, a2):
    y, x1, x2, y1, y2 = [], 0.0, 0.0, 0.0, 0.0
    for v in x:
        o = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, v, y1, o
        y.append(o)
    return y


def highpass(x, sr, fc=250.0, q=0.707):
    w = 2 * math.pi * fc / sr; al = math.sin(w) / (2 * q); c = math.cos(w); a0 = 1 + al
    return _biquad(x, (1 + c) / 2 / a0, -(1 + c) / a0, (1 + c) / 2 / a0, -2 * c / a0, (1 - al) / a0)


def peaking(x, sr, fc=3000.0, gain_db=4.0, q=1.0):
    A = 10 ** (gain_db / 40); w = 2 * math.pi * fc / sr; al = math.sin(w) / (2 * q); c = math.cos(w); a0 = 1 + al / A
    return _biquad(x, (1 + al * A) / a0, -2 * c / a0, (1 - al * A) / a0, -2 * c / a0, (1 - al / A) / a0)


def fade(x, sr, ms=8):
    n = min(len(x) // 2, int(sr * ms / 1000))
    y = list(x)
    for i in range(n):
        g = i / n
        y[i] *= g; y[-1 - i] *= g
    return y


def speaker_chain(x, sr, eq=True):
    """본체 소형 스피커(2~3W)용: 저역 컷 + 명료도 대역 부스트 + 정규화 + 페이드."""
    y = trim_silence(x, sr)
    if eq:
        y = highpass(y, sr, 250.0)
        y = peaking(y, sr, 3000.0, 4.0, 1.0)
    return fade(normalize(y), sr)


def stats(x, sr):
    if not x:
        return {"duration_ms": 0, "peak_dbfs": -120.0, "rms_dbfs": -120.0, "clipped": 0}
    peak = max(abs(v) for v in x)
    rms = math.sqrt(sum(v * v for v in x) / len(x))
    return {"duration_ms": int(len(x) * 1000 / sr),
            "peak_dbfs": round(20 * math.log10(peak or 1e-9), 1),
            "rms_dbfs": round(20 * math.log10(rms or 1e-9), 1),
            "clipped": sum(1 for v in x if abs(v) >= 0.999)}
