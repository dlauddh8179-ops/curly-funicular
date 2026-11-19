"""본체 업로드 프로토콜 v1 (USB CDC 시리얼 / BLE GATT 공통 프레임).

프레임: 0xA5 | type(1) | seq(2) | len(2) | payload(len) | crc16-ccitt(2)  (crc 범위: type~payload)
  0x01 BEGIN   payload = total_size u32, set_version u32, payload_crc u32
  0x02 DATA    payload = offset u32 + data(<=240)
  0x03 END     payload = 없음 → 본체가 CRC 검증 후 활성 슬롯 전환
  0x05 QUERY   payload = 없음 → 0x06 VERSION 응답
  0x04 ACK     payload = seq u16, status u8          (본체 → PC)
  0x06 VERSION payload = active u32, previous u32    (본체 → PC)
  0x07 ROLLBACK payload = 없음 → 이전 슬롯으로 복귀
status: 0 OK, 1 FRAME_CRC, 2 TOO_LARGE, 3 SEQ, 4 VERIFY_FAIL, 5 STATE
"""
import struct, time

SOF = 0xA5
T_BEGIN, T_DATA, T_END, T_ACK, T_QUERY, T_VERSION, T_ROLLBACK = 1, 2, 3, 4, 5, 6, 7
ST_OK, ST_FRAME_CRC, ST_TOO_LARGE, ST_SEQ, ST_VERIFY_FAIL, ST_STATE = range(6)
CHUNK = 240
STATUS_TEXT = {0: "OK", 1: "프레임 CRC 오류", 2: "용량 초과", 3: "순서 오류", 4: "패키지 검증 실패", 5: "상태 오류"}

# BLE GATT (제니스테크놀러지 펌웨어와 협의 후 확정)
BLE_SERVICE_UUID = "7a1e0001-5a0c-4c2b-9b3e-0aac00000001"
BLE_RX_CHAR_UUID = "7a1e0002-5a0c-4c2b-9b3e-0aac00000001"   # PC→본체 write without response
BLE_TX_CHAR_UUID = "7a1e0003-5a0c-4c2b-9b3e-0aac00000001"   # 본체→PC notify


def crc16_ccitt(data, crc=0xFFFF):
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def make_frame(ftype, seq, payload=b""):
    body = struct.pack("<BHH", ftype, seq, len(payload)) + payload
    return bytes([SOF]) + body + struct.pack("<H", crc16_ccitt(body))


class FrameReader:
    """바이트 스트림에서 프레임을 꺼냄."""
    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf += data
        out = []
        while True:
            try:
                i = self.buf.index(SOF)
            except ValueError:
                self.buf.clear(); break
            del self.buf[:i]
            if len(self.buf) < 6: break
            ftype, seq, ln = struct.unpack_from("<BHH", self.buf, 1)
            if len(self.buf) < 8 + ln: break
            body = bytes(self.buf[1:6 + ln])
            (crc,) = struct.unpack_from("<H", self.buf, 6 + ln)
            del self.buf[:8 + ln]
            out.append((ftype, seq, body[5:], crc == crc16_ccitt(body)))
        return out


class Uploader:
    """transport: write(bytes) 와 read(timeout)->bytes 를 가진 객체."""
    def __init__(self, transport, timeout=2.0, retries=3, log=print):
        self.t, self.timeout, self.retries, self.log = transport, timeout, retries, log
        self.reader = FrameReader()
        self.seq = 0

    def _xfer(self, ftype, payload=b"", expect=T_ACK):
        for attempt in range(self.retries):
            self.seq = (self.seq + 1) & 0xFFFF
            self.t.write(make_frame(ftype, self.seq, payload))
            deadline = time.time() + self.timeout
            while time.time() < deadline:
                for rtype, rseq, rp, ok in self.reader.feed(self.t.read(self.timeout)):
                    if not ok: continue
                    if rtype == expect == T_VERSION:
                        return struct.unpack("<II", rp)
                    if rtype == T_ACK and expect == T_ACK:
                        aseq, status = struct.unpack("<HB", rp)
                        if aseq != self.seq: continue
                        if status == ST_FRAME_CRC: break      # 재전송
                        return status
            self.log(f"  재시도 {attempt + 1}/{self.retries}")
        raise TimeoutError("본체 응답 없음")

    def query(self):
        return self._xfer(T_QUERY, expect=T_VERSION)

    def rollback(self):
        return self._xfer(T_ROLLBACK)

    def upload(self, pkg_bytes, set_version, payload_crc, progress=None):
        st = self._xfer(T_BEGIN, struct.pack("<III", len(pkg_bytes), set_version, payload_crc))
        if st != ST_OK: raise RuntimeError("BEGIN 거부: " + STATUS_TEXT[st])
        for off in range(0, len(pkg_bytes), CHUNK):
            st = self._xfer(T_DATA, struct.pack("<I", off) + pkg_bytes[off:off + CHUNK])
            if st != ST_OK: raise RuntimeError(f"DATA@{off} 거부: " + STATUS_TEXT[st])
            if progress: progress(min(off + CHUNK, len(pkg_bytes)), len(pkg_bytes))
        st = self._xfer(T_END)
        if st != ST_OK: raise RuntimeError("END 거부: " + STATUS_TEXT[st])
        return True


# ---- 전송 계층 ----
class SerialTransport:
    def __init__(self, port, baud=115200):
        import serial  # pip install pyserial
        self.s = serial.Serial(port, baud, timeout=0.05)
    def write(self, b): self.s.write(b)
    def read(self, timeout): return self.s.read(4096)


class BleTransport:
    """bleak 기반 동기 래퍼 (pip install bleak)."""
    def __init__(self, address):
        import asyncio, queue
        from bleak import BleakClient
        self.loop = asyncio.new_event_loop()
        self.q = queue.Queue()
        self.client = BleakClient(address)
        self.loop.run_until_complete(self.client.connect())
        self.loop.run_until_complete(self.client.start_notify(BLE_TX_CHAR_UUID, lambda _h, d: self.q.put(bytes(d))))
    def write(self, b):
        for i in range(0, len(b), 244):
            self.loop.run_until_complete(self.client.write_gatt_char(BLE_RX_CHAR_UUID, b[i:i + 244], response=False))
    def read(self, timeout):
        import queue
        self.loop.run_until_complete(__import__("asyncio").sleep(0.01))
        try: return self.q.get(timeout=min(timeout, 0.1))
        except queue.Empty: return b""


class SimulatedDevice:
    """본체 수신 로직의 파이썬 모델(A/B 슬롯). 펌웨어 aac_pkg_update.c 와 같은 상태 전이. 시험용."""
    def __init__(self, slot_size=1024 * 1024, drop_every=0):
        from .format import parse_package, PackageError
        self._parse, self._err = parse_package, PackageError
        self.slot_size, self.drop_every = slot_size, drop_every
        self.slots = {0: None, 1: None}
        self.active = None
        self.staging = None
        self.reader = FrameReader()
        self.out = bytearray()
        self.n = 0

    def _ver(self, slot):
        return 0 if slot is None or self.slots[slot] is None else self._parse(self.slots[slot]).set_version

    def write(self, data):
        for ftype, seq, p, ok in self.reader.feed(data):
            self.n += 1
            if self.drop_every and self.n % self.drop_every == 0:
                continue                                         # 패킷 손실 모사
            st = ST_OK
            if not ok:
                st = ST_FRAME_CRC
            elif ftype == T_QUERY:
                prev = None if self.active is None else 1 - self.active
                self.out += make_frame(T_VERSION, seq, struct.pack("<II", self._ver(self.active), self._ver(prev))); continue
            elif ftype == T_BEGIN:
                size, ver, crc = struct.unpack("<III", p)
                if size > self.slot_size: st = ST_TOO_LARGE
                else: self.staging = bytearray(size)
            elif ftype == T_DATA:
                if self.staging is None: st = ST_STATE
                else:
                    (off,) = struct.unpack_from("<I", p); chunk = p[4:]
                    if off + len(chunk) > len(self.staging): st = ST_TOO_LARGE
                    else: self.staging[off:off + len(chunk)] = chunk
            elif ftype == T_END:
                if self.staging is None: st = ST_STATE
                else:
                    try:
                        self._parse(bytes(self.staging))
                        target = 0 if self.active is None else 1 - self.active
                        self.slots[target] = bytes(self.staging); self.active = target
                    except self._err:
                        st = ST_VERIFY_FAIL                       # 활성 슬롯 유지
                    self.staging = None
            elif ftype == T_ROLLBACK:
                other = None if self.active is None else 1 - self.active
                if other is None or self.slots[other] is None: st = ST_STATE
                else: self.active = other
            self.out += make_frame(T_ACK, seq, struct.pack("<HB", seq, st))

    def read(self, timeout):
        b = bytes(self.out); self.out.clear(); return b

    def active_package(self):
        return None if self.active is None else self._parse(self.slots[self.active])
