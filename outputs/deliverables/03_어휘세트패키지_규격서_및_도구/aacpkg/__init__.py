"""에이블톡 기기 음원 패키지(.aacpkg v2) 라이브러리.

- format: 바이너리 포맷(헤더·인덱스·버튼 매핑·작업장 시간표) 빌드/파싱
- adpcm : IMA-ADPCM 4bit 인코더/디코더
- build : 설정 JSON + WAV → 패키지
- upload: 기기 전송 프로토콜(BLE / USB CDC), 누름 기록 회수, 시각 설정
"""
from .format import (MAGIC, FORMAT_VERSION, CODEC_PCM16, CODEC_IMA_ADPCM, PRIO_NORMAL, PRIO_HELP,
                     SRC_LIBRARY, SRC_TEXT, SRC_RECORDING, SET_GENERAL, SET_WORKPLACE, SET_NAMES, MAX_TEXT_CHARS,
                     Entry, ButtonMap, Schedule, Package, build_package, parse_package, active_set, PackageError)

__version__ = "2.0.0"
