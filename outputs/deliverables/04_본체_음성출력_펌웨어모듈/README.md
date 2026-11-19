# 본체 음성출력 펌웨어 모듈 (nRF52832)

| 경로 | 내용 |
| --- | --- |
| include/ | 공개 API 헤더 (aac_player.h, aac_pkg.h, aac_update.h, aac_hal.h, aac_adpcm.h) |
| src/ | 플랫폼 독립 구현 (C11, 동적 메모리 없음) |
| port/zephyr/ | nRF Connect SDK(Zephyr) HAL 포팅 템플릿 — 실기 미검증 |
| tests/ | PC 호스트 시험 (mock HAL, `make run`) |

빠른 시험(PC): `cd tests && make run`

자세한 사용법은 `API_설명서.docx` 참조.
