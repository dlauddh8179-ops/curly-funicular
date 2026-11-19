"""중계 참조 구현 — 보호자 앱·거치대가 할 일(앱 개발사·거치대 펌웨어가 이 순서를 따르면 됨).

  1) 서버에서 최신 패키지 내려받기(ETag 로 변경 시에만)
  2) 기기 설정 버전이 다르면 BLE 로 전송
  3) 기기 시각 맞추기(작업장 시간표 판단용)
  4) 기기 누름 기록 회수 → 서버로 전달(버튼 번호는 1~4 로 변환) → 성공한 만큼만 기기에서 삭제
"""
import json, time, urllib.request, urllib.error
from . import upload as up
from .format import parse_package


class Relay:
    def __init__(self, server, device_id, device_token, transport, tz_offset_min=540, log=print):
        self.server, self.dev, self.tok, self.tz, self.log = server.rstrip("/"), int(device_id), device_token, tz_offset_min, log
        self.u = up.Uploader(transport, log=log)
        self.etag = None

    def _req(self, method, path, body=None, headers=None):
        h = {"Authorization": "Bearer " + self.tok, **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode(); h["Content-Type"] = "application/json"
        r = urllib.request.Request(self.server + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def sync_package(self):
        st, data, h = self._req("GET", f"/api/devices/{self.dev}/package/latest", headers={"If-None-Match": self.etag} if self.etag else None)
        if st == 304:
            return "변경 없음"
        if st == 404:
            return "서버에 패키지 없음"
        if st != 200:
            raise RuntimeError(f"내려받기 실패 {st}: {data[:200]!r}")
        pk = parse_package(data)
        active, _prev = self.u.query()
        if active == pk.config_version:
            self.etag = h.get("ETag"); return f"기기가 이미 v{active}"
        self.u.upload(data, pk.config_version, pk.payload_crc)
        self.etag = h.get("ETag")
        return f"v{active} → v{pk.config_version} 전송"

    def sync_time(self):
        return up.STATUS_TEXT[self.u.set_time(time.time(), self.tz)]

    def sync_events(self, batch=20):
        total = 0
        while True:
            evs, dropped = self.u._xfer(up.T_EVENTS_GET, bytes([batch]), expect=up.T_EVENTS)
            if not evs:
                return total
            body = {"events": [{"unix_time": t, "vocab_id": v, "set": s, "button": b + 1, "config_version": c} for t, v, s, b, c in evs]}
            st, resp, _ = self._req("POST", f"/api/devices/{self.dev}/events", body)
            if st != 200:
                raise RuntimeError(f"기록 전달 실패 {st}: 기기 기록은 지우지 않음")
            if self.u._xfer(up.T_EVENTS_ACK, bytes([len(evs)])) != up.ST_OK:
                raise RuntimeError("기기 기록 삭제 실패")
            total += len(evs)

    def sync_all(self):
        return {"package": self.sync_package(), "time": self.sync_time(), "events": self.sync_events()}
