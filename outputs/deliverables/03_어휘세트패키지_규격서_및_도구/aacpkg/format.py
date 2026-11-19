"""AAC 어휘 세트 패키지 바이너리 포맷 v1.

모든 정수는 little-endian. 오프셋은 파일 시작 기준(인덱스의 audio_offset만 오디오 섹션 기준).

  [헤더 80B][인덱스 N×32B][영역 매핑 4×8B][문자열][그림상징][오디오]

자세한 필드 설명은 "어휘세트_패키지_규격서.docx" 참조.
"""
import struct, time, zlib
from dataclasses import dataclass, field
from typing import List, Optional

MAGIC = b"AACV"
FORMAT_VERSION = 1
HEADER_SIZE = 80
ENTRY_SIZE = 32
ZONE_SIZE = 8
ZONE_COUNT = 4

CODEC_PCM16 = 0
CODEC_IMA_ADPCM = 1

PRIO_NORMAL = 0
PRIO_SYSTEM = 1
PRIO_EMERGENCY = 2

CATEGORIES = {"생활": 1, "응급": 2, "가정용": 3, "의료용": 4, "감정표현": 5, "외출용": 6, "시스템": 7, "맞춤": 8}
NO_VOCAB = 0xFFFF

# magic, fmt_ver, hdr_size, set_ver, created, entry_cnt, zone_cnt, codec, sample_rate,
# index_off, index_size, zone_off, str_off, str_size, sym_off, sym_size, audio_off, audio_size,
# prev_set_ver, payload_crc, reserved(8s) ; header_crc 는 마지막 4B
_HDR = struct.Struct("<4sHHIIHBBIIIIIIIIIIII8s")
_ENTRY = struct.Struct("<HBBBBHIIIIII")
_ZONE = struct.Struct("<BBBBHH")
assert _HDR.size == HEADER_SIZE - 4 and _ENTRY.size == ENTRY_SIZE and _ZONE.size == ZONE_SIZE


class PackageError(ValueError):
    pass


@dataclass
class Entry:
    vocab_id: int
    text: str
    category: int = 1
    priority: int = PRIO_NORMAL
    flags: int = 0
    audio: bytes = b""          # 코덱 적용 후 바이트
    sample_count: int = 0
    symbol: bytes = b""         # PNG 등(선택)
    duration_ms: int = 0


@dataclass
class Zone:
    zone_id: int                # 0=좌상 1=우상 2=좌하 3=우하
    vocab_id: int
    rgb: tuple = (255, 255, 255)
    long_press_vocab_id: int = NO_VOCAB


@dataclass
class Package:
    set_version: int
    codec: int
    sample_rate: int
    entries: List[Entry]
    zones: List[Zone]
    prev_set_version: int = 0
    created: int = 0
    payload_crc: int = 0

    def entry(self, vocab_id) -> Optional[Entry]:
        return next((e for e in self.entries if e.vocab_id == vocab_id), None)


def build_package(pkg: Package) -> bytes:
    entries = sorted(pkg.entries, key=lambda e: e.vocab_id)   # 펌웨어 이진 탐색을 위해 정렬
    ids = [e.vocab_id for e in entries]
    if len(set(ids)) != len(ids):
        raise PackageError("중복된 어휘 ID")
    if len(pkg.zones) != ZONE_COUNT:
        raise PackageError("영역 매핑은 4개여야 함")
    for z in pkg.zones:
        for vid in (z.vocab_id, z.long_press_vocab_id):
            if vid != NO_VOCAB and vid not in ids:
                raise PackageError(f"영역 {z.zone_id}: 없는 어휘 ID {vid}")

    strings, symbols, audio = bytearray(), bytearray(), bytearray()
    idx = bytearray()
    for e in entries:
        t_off = len(strings); strings += e.text.encode("utf-8") + b"\0"
        s_off = len(symbols); symbols += e.symbol
        a_off = len(audio); audio += e.audio
        while len(audio) % 4: audio += b"\0"                 # 4바이트 정렬
        dur = e.duration_ms or int(e.sample_count * 1000 / pkg.sample_rate)
        idx += _ENTRY.pack(e.vocab_id, e.category, e.priority, e.flags, 0, min(dur, 0xFFFF),
                           a_off, len(e.audio), e.sample_count, t_off, s_off, len(e.symbol))
    zones = bytearray()
    for z in sorted(pkg.zones, key=lambda z: z.zone_id):
        zones += _ZONE.pack(z.zone_id, *z.rgb, z.vocab_id, z.long_press_vocab_id)

    index_off = HEADER_SIZE
    zone_off = index_off + len(idx)
    str_off = zone_off + len(zones)
    sym_off = str_off + len(strings)
    audio_off = sym_off + len(symbols)
    audio_off += (-audio_off) % 4
    pad = b"\0" * (audio_off - (sym_off + len(symbols)))
    payload = bytes(idx + zones + strings + symbols) + pad + bytes(audio)
    payload_crc = zlib.crc32(payload) & 0xFFFFFFFF
    created = pkg.created or int(time.time())
    hdr = _HDR.pack(MAGIC, FORMAT_VERSION, HEADER_SIZE, pkg.set_version, created, len(entries), ZONE_COUNT,
                    pkg.codec, pkg.sample_rate, index_off, len(idx), zone_off, str_off, len(strings),
                    sym_off, len(symbols), audio_off, len(audio), pkg.prev_set_version, payload_crc, b"\0" * 8)
    hdr += struct.pack("<I", zlib.crc32(hdr) & 0xFFFFFFFF)
    return hdr + payload


def parse_package(data: bytes) -> Package:
    if len(data) < HEADER_SIZE:
        raise PackageError("헤더보다 짧음")
    f = _HDR.unpack_from(data, 0)
    (magic, fver, hsize, set_ver, created, n, zc, codec, sr, index_off, index_size, zone_off,
     str_off, str_size, sym_off, sym_size, audio_off, audio_size, prev, pcrc, _res) = f
    if magic != MAGIC: raise PackageError("magic 불일치")
    if fver != FORMAT_VERSION: raise PackageError(f"지원하지 않는 포맷 버전 {fver}")
    (hcrc,) = struct.unpack_from("<I", data, HEADER_SIZE - 4)
    if zlib.crc32(data[:HEADER_SIZE - 4]) & 0xFFFFFFFF != hcrc: raise PackageError("헤더 CRC 불일치")
    if audio_off + audio_size != len(data): raise PackageError("파일 길이 불일치")
    if zlib.crc32(data[HEADER_SIZE:]) & 0xFFFFFFFF != pcrc: raise PackageError("페이로드 CRC 불일치")
    if index_size != n * ENTRY_SIZE or zc != ZONE_COUNT: raise PackageError("인덱스/영역 크기 불일치")
    strings = data[str_off:str_off + str_size]
    symbols = data[sym_off:sym_off + sym_size]
    audio = data[audio_off:audio_off + audio_size]
    entries = []
    for i in range(n):
        (vid, cat, prio, flags, _r, dur, a_off, a_len, sc, t_off, s_off, s_len) = _ENTRY.unpack_from(data, index_off + i * ENTRY_SIZE)
        text = strings[t_off:strings.index(b"\0", t_off)].decode("utf-8")
        entries.append(Entry(vid, text, cat, prio, flags, audio[a_off:a_off + a_len], sc, symbols[s_off:s_off + s_len], dur))
    zones = []
    for i in range(zc):
        zid, r, g, b, vid, lp = _ZONE.unpack_from(data, zone_off + i * ZONE_SIZE)
        zones.append(Zone(zid, vid, (r, g, b), lp))
    return Package(set_ver, codec, sr, entries, zones, prev, created, pcrc)
