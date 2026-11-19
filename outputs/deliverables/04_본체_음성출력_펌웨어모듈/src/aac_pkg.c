#include <string.h>
#include "aac_pkg.h"
#include "aac_hal.h"

#define FMT_VERSION 1u
#define ENTRY_SIZE  32u
#define ZONE_SIZE   8u

static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }

/* 헤더 필드 오프셋(규격서 표 3) */
enum { H_MAGIC = 0, H_FMT = 4, H_HSIZE = 6, H_SETVER = 8, H_CREATED = 12, H_COUNT = 16, H_ZONES = 18, H_CODEC = 19,
       H_SR = 20, H_IDX_OFF = 24, H_IDX_SIZE = 28, H_ZONE_OFF = 32, H_STR_OFF = 36, H_STR_SIZE = 40, H_SYM_OFF = 44,
       H_SYM_SIZE = 48, H_AUD_OFF = 52, H_AUD_SIZE = 56, H_PREV = 60, H_PCRC = 64, H_HCRC = 76 };

static aac_err_t read_header(uint32_t base, uint8_t h[AAC_HEADER_SIZE])
{
    if (aac_hal_flash_read(base, h, AAC_HEADER_SIZE) != 0) return AAC_ERR_IO;
    if (memcmp(h + H_MAGIC, "AACV", 4) != 0) return AAC_ERR_MAGIC;
    if (rd16(h + H_FMT) != FMT_VERSION || rd16(h + H_HSIZE) != AAC_HEADER_SIZE) return AAC_ERR_VERSION;
    if (aac_crc32(0, h, H_HCRC) != rd32(h + H_HCRC)) return AAC_ERR_HDR_CRC;
    return AAC_OK;
}

static aac_err_t check_payload(uint32_t base, const uint8_t *h)
{
    uint32_t total = rd32(h + H_AUD_OFF) + rd32(h + H_AUD_SIZE);
    uint8_t buf[256];
    uint32_t crc = 0;
    for (uint32_t off = AAC_HEADER_SIZE; off < total;) {
        uint32_t n = total - off > sizeof buf ? sizeof buf : total - off;
        if (aac_hal_flash_read(base + off, buf, n) != 0) return AAC_ERR_IO;
        crc = aac_crc32(crc, buf, n);
        off += n;
    }
    return crc == rd32(h + H_PCRC) ? AAC_OK : AAC_ERR_PAYLOAD_CRC;
}

aac_err_t aac_pkg_verify(uint32_t slot_base, uint32_t *set_version_out)
{
    uint8_t h[AAC_HEADER_SIZE];
    aac_err_t e = read_header(slot_base, h);
    if (e == AAC_OK) e = check_payload(slot_base, h);
    if (e == AAC_OK && set_version_out) *set_version_out = rd32(h + H_SETVER);
    return e;
}

aac_err_t aac_pkg_load(aac_pkg_t *pkg, uint32_t slot_base)
{
    uint8_t h[AAC_HEADER_SIZE];
    aac_err_t e = read_header(slot_base, h);
    if (e != AAC_OK) return e;
    uint16_t n = rd16(h + H_COUNT);
    if (n > AAC_MAX_ENTRIES) return AAC_ERR_TOO_MANY;
    if (rd32(h + H_IDX_SIZE) != n * ENTRY_SIZE || h[H_ZONES] != AAC_ZONE_COUNT) return AAC_ERR_LAYOUT;
    if ((e = check_payload(slot_base, h)) != AAC_OK) return e;

    memset(pkg, 0, sizeof *pkg);
    pkg->base = slot_base;
    pkg->set_version = rd32(h + H_SETVER);
    pkg->prev_set_version = rd32(h + H_PREV);
    pkg->sample_rate = rd32(h + H_SR);
    pkg->payload_crc = rd32(h + H_PCRC);
    pkg->codec = h[H_CODEC];
    pkg->entry_count = n;
    pkg->total_size = rd32(h + H_AUD_OFF) + rd32(h + H_AUD_SIZE);
    uint32_t aud = slot_base + rd32(h + H_AUD_OFF), aud_size = rd32(h + H_AUD_SIZE);

    uint8_t rec[ENTRY_SIZE];
    for (uint16_t i = 0; i < n; i++) {
        if (aac_hal_flash_read(slot_base + rd32(h + H_IDX_OFF) + i * ENTRY_SIZE, rec, ENTRY_SIZE) != 0) return AAC_ERR_IO;
        aac_entry_t *en = &pkg->entries[i];
        en->vocab_id = rd16(rec);
        en->category = rec[2];
        en->priority = rec[3];
        en->duration_ms = rd16(rec + 6);
        en->audio_addr = aud + rd32(rec + 8);
        en->audio_len = rd32(rec + 12);
        en->sample_count = rd32(rec + 16);
        if (rd32(rec + 8) + en->audio_len > aud_size) return AAC_ERR_LAYOUT;
        if (i && en->vocab_id <= pkg->entries[i - 1].vocab_id) return AAC_ERR_LAYOUT;   /* 정렬·중복 검사 */
    }
    uint8_t z[ZONE_SIZE];
    for (int i = 0; i < AAC_ZONE_COUNT; i++) {
        if (aac_hal_flash_read(slot_base + rd32(h + H_ZONE_OFF) + i * ZONE_SIZE, z, ZONE_SIZE) != 0) return AAC_ERR_IO;
        if (z[0] >= AAC_ZONE_COUNT) return AAC_ERR_LAYOUT;
        aac_zone_t *zz = &pkg->zones[z[0]];
        zz->r = z[1]; zz->g = z[2]; zz->b = z[3];
        zz->vocab_id = rd16(z + 4);
        zz->long_press_vocab_id = rd16(z + 6);
    }
    return AAC_OK;
}

const aac_entry_t *aac_pkg_find(const aac_pkg_t *pkg, uint16_t vocab_id)
{
    int lo = 0, hi = (int)pkg->entry_count - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        uint16_t v = pkg->entries[mid].vocab_id;
        if (v == vocab_id) return &pkg->entries[mid];
        if (v < vocab_id) lo = mid + 1; else hi = mid - 1;
    }
    return NULL;
}
