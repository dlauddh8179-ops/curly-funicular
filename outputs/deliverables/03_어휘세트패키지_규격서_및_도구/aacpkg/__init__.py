"""AAC 어휘 세트 패키지(.aacpkg) 라이브러리.

- format: 바이너리 포맷 정의(헤더·인덱스·영역 매핑)와 빌드/파싱
- adpcm : IMA-ADPCM 4bit 인코더/디코더
- upload: 본체 업로드 프로토콜(USB CDC 시리얼 / BLE)
"""
from .format import (MAGIC, FORMAT_VERSION, CODEC_PCM16, CODEC_IMA_ADPCM,
                     PRIO_NORMAL, PRIO_SYSTEM, PRIO_EMERGENCY,
                     Entry, Zone, Package, build_package, parse_package, PackageError)

__version__ = "1.0.0"
