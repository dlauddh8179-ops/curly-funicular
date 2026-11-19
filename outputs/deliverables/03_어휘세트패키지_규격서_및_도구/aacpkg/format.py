"""에이블톡 기기 음원 패키지(.aacpkg) 포맷 v2.

기기에는 버튼마다 일반 세트 1개 + 작업장 세트 1개 음원을 저장하고, 작업장 시간표에 따라 세트를 자동 전환한다.
모든 정수는 little-endian, 오프셋은 파일 시작 기준(인덱스의 audio_offset 만 오디오 섹션 기준).

  [헤더 80B][인덱스 N×32B][버튼 매핑 세트×버튼×8B][시간표 4B+M×8B][문자열][오디오]
"""
import struct, time, zlib
from dataclasses import dataclass, field
from typing import List, Optional

MAGIC = b"AACV"
FORMAT_VERSION = 2
HEADER_SIZE = 80
ENTRY_SIZE = 32
MAP_SIZE = 8
SCHED_SIZE = 8
BUTTON_COUNT = 4
SET_COUNT = 2
SET_GENERAL, SET_WORKPLACE = 0, 1
SET_NAMES = {SET_GENERAL: "일반", SET_WORKPLACE: "작업장"}

CODEC_PCM16 = 0
CODEC_IMA_ADPCM = 1

PRIO_NORMAL = 0
PRIO_HELP = 2                # 버튼 4(도움 요청): 다른 버튼 재생을 끊고, 다른 버튼에 끊기지 않음

SRC_LIBRARY, SRC_TEXT, SRC_RECORDING = 0, 1, 2
MAX_TEXT_CHARS = 15
NO_VOCAB = 0xFFFF

# magic fmt hdr cfgver created count buttons sets codec rsv sr | idx_off idx_size map_off str_off str_size
# sched_off sched_size aud_off aud_size prev | payload_crc device_id reserved(2)
_HDR = struct.Struct("<4sHHIIHBBBBIIIIIIIIIIIII2s")
_ENTRY = struct.Struct("<HBBBBHIIII8s")
_MAP = struct.Struct("<BBBBBBH")
_SCHED = struct.Struct("<BBHHH")
assert _HDR.size == HEADER_SIZE - 4 and _ENTRY.size == ENTRY_SIZE and _MAP.size == MAP_SIZE and _SCHED.size == SCHED_SIZE

# 버튼 기본 불빛 색(제품 버튼 색과 같게): 1 빨강, 2 노랑, 3 초록, 4 파랑
DEFAULT_RGB = [(217, 71, 58), (232, 164, 0), (58, 154, 74), (47, 111, 191)]


class PackageError(ValueError):
    pass


@dataclass
class Entry:
    vocab_id: int
    text: str
    source: int = SRC_LIBRARY
    priority: int = PRIO_NORMAL
    audio: bytes = b""
    sample_count: int = 0
    duration_ms: int = 0


@dataclass
class ButtonMap:
    set_id: int
    button: int            # 0~3 (버튼 1~4)
    vocab_id: int
    rgb: tuple = (255, 255, 255)


@dataclass
class Schedule:
    """작업장 시간: days 비트(0=월 … 6=일), [start_min, end_min) 분 단위. 해당 시간에는 set_id 세트."""
    days: int
    start_min: int
    end_min: int
    set_id: int = SET_WORKPLACE


@dataclass
class Package:
    config_version: int
    codec: int
    sample_rate: int
    entries: List[Entry]
    buttons: List[ButtonMap]
    schedule: List[Schedule] = field(default_factory=list)
    prev_config_version: int = 0
    device_id: int = 0
    created: int = 0
    payload_crc: int = 0

    def entry(self, vocab_id) -> Optional[Entry]:
        return next((e for e in self.entries if e.vocab_id == vocab_id), None)

    def button(self, set_id, button) -> Optional[ButtonMap]:
        return next((b for b in self.buttons if b.set_id == set_id and b.button == button), None)


def build_package(pkg: Package) -> bytes:
    entries = sorted(pkg.entries, key=lambda e: e.vocab_id)
    ids = [e.vocab_id for e in entries]
    if len(set(ids)) != len(ids):
        raise PackageError("중복된 음원 ID")
    for e in entries:
        if len(e.text) > MAX_TEXT_CHARS:
            raise PackageError(f"[{e.vocab_id}] 문장이 {MAX_TEXT_CHARS}자를 넘음: {e.text}")
    keys = {(b.set_id, b.button) for b in pkg.buttons}
    if keys != {(s, b) for s in range(SET_COUNT) for b in range(BUTTON_COUNT)} or len(pkg.buttons) != SET_COUNT * BUTTON_COUNT:
        raise PackageError("버튼 매핑은 세트 2 × 버튼 4 = 8개가 모두 있어야 함")
    for b in pkg.buttons:
        if b.vocab_id not in ids:
            raise PackageError(f"세트{b.set_id} 버튼{b.button + 1}: 없는 음원 ID {b.vocab_id}")
    for s in pkg.schedule:
        if not (0 <= s.start_min < s.end_min <= 1440) or not (0 < s.days < 128) or s.set_id >= SET_COUNT:
            raise PackageError(f"잘못된 시간표 {s}")

    strings, audio, idx = bytearray(), bytearray(), bytearray()
    for e in entries:
        t_off = len(strings); strings += e.text.encode("utf-8") + b"\0"
        a_off = len(audio); audio += e.audio
        while len(audio) % 4: audio += b"\0"
        dur = e.duration_ms or int(e.sample_count * 1000 / pkg.sample_rate)
        idx += _ENTRY.pack(e.vocab_id, e.source, e.priority, 0, 0, min(dur, 0xFFFF), a_off, len(e.audio), e.sample_count, t_off, b"\0" * 8)
    maps = b"".join(_MAP.pack(b.set_id, b.button, *b.rgb, 0, b.vocab_id) for b in sorted(pkg.buttons, key=lambda b: (b.set_id, b.button)))
    sched = struct.pack("<HH", len(pkg.schedule), 0) + b"".join(_SCHED.pack(s.days, s.set_id, s.start_min, s.end_min, 0) for s in pkg.schedule)

    index_off = HEADER_SIZE
    map_off = index_off + len(idx)
    sched_off = map_off + len(maps)
    str_off = sched_off + len(sched)
    audio_off = str_off + len(strings)
    pad = (-audio_off) % 4
    audio_off += pad
    payload = bytes(idx) + maps + sched + bytes(strings) + b"\0" * pad + bytes(audio)
    payload_crc = zlib.crc32(payload) & 0xFFFFFFFF
    created = pkg.created or int(time.time())
    hdr = _HDR.pack(MAGIC, FORMAT_VERSION, HEADER_SIZE, pkg.config_version, created, len(entries), BUTTON_COUNT, SET_COUNT,
                    pkg.codec, 0, pkg.sample_rate, index_off, len(idx), map_off, str_off, len(strings), sched_off, len(sched),
                    audio_off, len(audio), pkg.prev_config_version, payload_crc, pkg.device_id, b"\0\0")
    hdr += struct.pack("<I", zlib.crc32(hdr) & 0xFFFFFFFF)
    return hdr + payload


def parse_package(data: bytes) -> Package:
    if len(data) < HEADER_SIZE:
        raise PackageError("헤더보다 짧음")
    (magic, fver, hsize, cfg, created, n, nb, ns, codec, _r, sr, index_off, index_size, map_off, str_off, str_size,
     sched_off, sched_size, audio_off, audio_size, prev, pcrc, dev, _res) = _HDR.unpack_from(data, 0)
    if magic != MAGIC: raise PackageError("magic 불일치")
    if fver != FORMAT_VERSION: raise PackageError(f"지원하지 않는 포맷 버전 {fver}")
    (hcrc,) = struct.unpack_from("<I", data, HEADER_SIZE - 4)
    if zlib.crc32(data[:HEADER_SIZE - 4]) & 0xFFFFFFFF != hcrc: raise PackageError("헤더 CRC 불일치")
    if audio_off + audio_size != len(data): raise PackageError("파일 길이 불일치")
    if zlib.crc32(data[HEADER_SIZE:]) & 0xFFFFFFFF != pcrc: raise PackageError("페이로드 CRC 불일치")
    if index_size != n * ENTRY_SIZE or nb != BUTTON_COUNT or ns != SET_COUNT: raise PackageError("레이아웃 불일치")
    strings = data[str_off:str_off + str_size]
    audio = data[audio_off:audio_off + audio_size]
    entries = []
    for i in range(n):
        vid, src, prio, _f, _r2, dur, a_off, a_len, sc, t_off, _x = _ENTRY.unpack_from(data, index_off + i * ENTRY_SIZE)
        text = strings[t_off:strings.index(b"\0", t_off)].decode("utf-8")
        entries.append(Entry(vid, text, src, prio, audio[a_off:a_off + a_len], sc, dur))
    buttons = []
    for i in range(nb * ns):
        s, b, r, g, bl, _z, vid = _MAP.unpack_from(data, map_off + i * MAP_SIZE)
        buttons.append(ButtonMap(s, b, vid, (r, g, bl)))
    (cnt, _z) = struct.unpack_from("<HH", data, sched_off)
    if 4 + cnt * SCHED_SIZE != sched_size: raise PackageError("시간표 크기 불일치")
    schedule = []
    for i in range(cnt):
        days, sid, st, en, _z = _SCHED.unpack_from(data, sched_off + 4 + i * SCHED_SIZE)
        schedule.append(Schedule(days, st, en, sid))
    return Package(cfg, codec, sr, entries, buttons, schedule, prev, dev, created, pcrc)


def active_set(schedule: List[Schedule], weekday: int, minute: int) -> int:
    """weekday 0=월, minute 0~1439. 시간표에 걸리면 그 세트, 아니면 일반 세트(펌웨어와 같은 규칙)."""
    for s in schedule:
        if s.days & (1 << weekday) and s.start_min <= minute < s.end_min:
            return s.set_id
    return SET_GENERAL
