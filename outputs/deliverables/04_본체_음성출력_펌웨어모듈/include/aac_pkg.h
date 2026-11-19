/**
 * @file aac_pkg.h
 * @brief AAC 어휘 세트 패키지(.aacpkg v1) 파서. 포맷: 어휘세트_패키지_규격서 참조.
 */
#ifndef AAC_PKG_H
#define AAC_PKG_H
#include <stdint.h>
#include <stddef.h>

#ifndef AAC_MAX_ENTRIES
#define AAC_MAX_ENTRIES 64            /* RAM 인덱스 캐시: 64 × 24B */
#endif
#define AAC_ZONE_COUNT   4
#define AAC_NO_VOCAB     0xFFFFu
#define AAC_HEADER_SIZE  80u

enum { AAC_CODEC_PCM16 = 0, AAC_CODEC_IMA_ADPCM = 1 };
enum { AAC_PRIO_NORMAL = 0, AAC_PRIO_SYSTEM = 1, AAC_PRIO_EMERGENCY = 2 };

typedef enum {
    AAC_OK = 0, AAC_ERR_MAGIC = -1, AAC_ERR_VERSION = -2, AAC_ERR_HDR_CRC = -3, AAC_ERR_PAYLOAD_CRC = -4,
    AAC_ERR_LAYOUT = -5, AAC_ERR_TOO_MANY = -6, AAC_ERR_IO = -7, AAC_ERR_NOT_FOUND = -8, AAC_ERR_BUSY = -9,
    AAC_ERR_STATE = -10, AAC_ERR_NO_PKG = -11
} aac_err_t;

typedef struct {
    uint16_t vocab_id;
    uint8_t  category;
    uint8_t  priority;
    uint16_t duration_ms;
    uint32_t audio_addr;              /* 플래시 절대 주소 */
    uint32_t audio_len;
    uint32_t sample_count;
} aac_entry_t;

typedef struct {
    uint16_t vocab_id;
    uint16_t long_press_vocab_id;
    uint8_t  r, g, b;
} aac_zone_t;

typedef struct {
    uint32_t base;                    /* 슬롯 시작 주소 */
    uint32_t total_size;
    uint32_t set_version;
    uint32_t prev_set_version;
    uint32_t sample_rate;
    uint32_t payload_crc;
    uint8_t  codec;
    uint16_t entry_count;
    aac_entry_t entries[AAC_MAX_ENTRIES];   /* vocab_id 오름차순 */
    aac_zone_t  zones[AAC_ZONE_COUNT];
} aac_pkg_t;

/** 슬롯을 검증(헤더·페이로드 CRC, 레이아웃)하고 인덱스를 RAM 에 적재. */
aac_err_t aac_pkg_load(aac_pkg_t *pkg, uint32_t slot_base);
/** CRC 만 검증(업로드 직후 스테이징 슬롯 검사용). */
aac_err_t aac_pkg_verify(uint32_t slot_base, uint32_t *set_version_out);
/** 어휘 ID 로 항목 조회(이진 탐색, O(log n)). */
const aac_entry_t *aac_pkg_find(const aac_pkg_t *pkg, uint16_t vocab_id);

uint32_t aac_crc32(uint32_t crc, const void *data, size_t len);   /* zlib 호환, 초기값 0 */
uint16_t aac_crc16_ccitt(uint16_t crc, const void *data, size_t len); /* 초기값 0xFFFF */
#endif
