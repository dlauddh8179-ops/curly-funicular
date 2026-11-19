/**
 * @file aac_pkg.h
 * @brief 에이블톡 기기 음원 패키지(.aacpkg v2) 파서: 버튼 4개 × 세트 2개(일반·작업장) + 작업장 시간표.
 */
#ifndef AAC_PKG_H
#define AAC_PKG_H
#include <stdint.h>
#include <stddef.h>

#define AAC_BUTTONS      4
#define AAC_SETS         2
#define AAC_SET_GENERAL  0
#define AAC_SET_WORKPLACE 1
#ifndef AAC_MAX_ENTRIES
#define AAC_MAX_ENTRIES  16            /* 필요 8개(세트 2 × 버튼 4) */
#endif
#ifndef AAC_MAX_SCHED
#define AAC_MAX_SCHED    16
#endif
#define AAC_NO_VOCAB     0xFFFFu
#define AAC_HEADER_SIZE  80u

enum { AAC_CODEC_PCM16 = 0, AAC_CODEC_IMA_ADPCM = 1 };
enum { AAC_PRIO_NORMAL = 0, AAC_PRIO_HELP = 2 };
enum { AAC_SRC_LIBRARY = 0, AAC_SRC_TEXT = 1, AAC_SRC_RECORDING = 2 };

typedef enum {
    AAC_OK = 0, AAC_ERR_MAGIC = -1, AAC_ERR_VERSION = -2, AAC_ERR_HDR_CRC = -3, AAC_ERR_PAYLOAD_CRC = -4,
    AAC_ERR_LAYOUT = -5, AAC_ERR_TOO_MANY = -6, AAC_ERR_IO = -7, AAC_ERR_NOT_FOUND = -8, AAC_ERR_BUSY = -9,
    AAC_ERR_STATE = -10, AAC_ERR_NO_PKG = -11
} aac_err_t;

typedef struct {
    uint16_t vocab_id;
    uint8_t  source;
    uint8_t  priority;
    uint16_t duration_ms;
    uint32_t audio_addr;
    uint32_t audio_len;
    uint32_t sample_count;
} aac_entry_t;

typedef struct { uint16_t vocab_id; uint8_t r, g, b; } aac_button_t;
typedef struct { uint8_t days; uint8_t set_id; uint16_t start_min, end_min; } aac_sched_t;   /* days bit0=월 … bit6=일 */

typedef struct {
    uint32_t base, total_size;
    uint32_t config_version, prev_config_version, device_id;
    uint32_t sample_rate, payload_crc;
    uint8_t  codec;
    uint16_t entry_count;
    uint8_t  sched_count;
    aac_entry_t  entries[AAC_MAX_ENTRIES];
    aac_button_t buttons[AAC_SETS][AAC_BUTTONS];
    aac_sched_t  sched[AAC_MAX_SCHED];
} aac_pkg_t;

aac_err_t aac_pkg_load(aac_pkg_t *pkg, uint32_t slot_base);
aac_err_t aac_pkg_verify(uint32_t slot_base, uint32_t *config_version_out);
const aac_entry_t *aac_pkg_find(const aac_pkg_t *pkg, uint16_t vocab_id);
/** 현지 시각(unix + tz)으로 세트 결정: 시간표에 걸리면 그 세트, 아니면 일반 세트. */
uint8_t aac_pkg_active_set(const aac_pkg_t *pkg, uint32_t local_unix);

uint32_t aac_crc32(uint32_t crc, const void *data, size_t len);
uint16_t aac_crc16_ccitt(uint16_t crc, const void *data, size_t len);
#endif
