#include <string.h>
#include "aac_pkg.h"
#include "aac_hal.h"

#define FMT_VERSION 2u
#define ENTRY_SIZE  32u
#define MAP_SIZE    8u
#define SCHED_SIZE  8u

static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }

/* 헤더 필드 오프셋(규격서 3장) */
enum { H_FMT = 4, H_HSIZE = 6, H_CFG = 8, H_COUNT = 16, H_BTNS = 18, H_SETS = 19, H_CODEC = 20, H_SR = 22,
       H_IDX_OFF = 26, H_IDX_SIZE = 30, H_MAP_OFF = 34, H_SCHED_OFF = 46, H_SCHED_SIZE = 50, H_AUD_OFF = 54,
       H_AUD_SIZE = 58, H_PREV = 62, H_PCRC = 66, H_DEV = 70, H_HCRC = 76 };

static aac_err_t read_header(uint32_t base, uint8_t h[AAC_HEADER_SIZE])
{
    if (aac_hal_flash_read(base, h, AAC_HEADER_SIZE) != 0) return AAC_ERR_IO;
    if (memcmp(h, "AACV", 4) != 0) return AAC_ERR_MAGIC;
    if (rd16(h + H_FMT) != FMT_VERSION || rd16(h + H_HSIZE) != AAC_HEADER_SIZE) return AAC_ERR_VERSION;
    if (aac_crc32(0, h, H_HCRC) != rd32(h + H_HCRC)) return AAC_ERR_HDR_CRC;
    return AAC_OK;
}

static aac_err_t check_payload(uint32_t base, const uint8_t *h)
{
    uint32_t total = rd32(h + H_AUD_OFF) + rd32(h + H_AUD_SIZE), crc = 0;
    uint8_t buf[256];
    for (uint32_t off = AAC_HEADER_SIZE; off < total;) {
        uint32_t n = total - off > sizeof buf ? sizeof buf : total - off;
        if (aac_hal_flash_read(base + off, buf, n) != 0) return AAC_ERR_IO;
        crc = aac_crc32(crc, buf, n); off += n;
    }
    return crc == rd32(h + H_PCRC) ? AAC_OK : AAC_ERR_PAYLOAD_CRC;
}

aac_err_t aac_pkg_verify(uint32_t slot_base, uint32_t *cfg_out)
{
    uint8_t h[AAC_HEADER_SIZE];
    aac_err_t e = read_header(slot_base, h);
    if (e == AAC_OK) e = check_payload(slot_base, h);
    if (e == AAC_OK && cfg_out) *cfg_out = rd32(h + H_CFG);
    return e;
}

aac_err_t aac_pkg_load(aac_pkg_t *pkg, uint32_t base)
{
    uint8_t h[AAC_HEADER_SIZE];
    aac_err_t e = read_header(base, h);
    if (e != AAC_OK) return e;
    uint16_t n = rd16(h + H_COUNT);
    if (n > AAC_MAX_ENTRIES) return AAC_ERR_TOO_MANY;
    if (rd32(h + H_IDX_SIZE) != n * ENTRY_SIZE || h[H_BTNS] != AAC_BUTTONS || h[H_SETS] != AAC_SETS) return AAC_ERR_LAYOUT;
    if ((e = check_payload(base, h)) != AAC_OK) return e;

    memset(pkg, 0, sizeof *pkg);
    pkg->base = base;
    pkg->config_version = rd32(h + H_CFG);
    pkg->prev_config_version = rd32(h + H_PREV);
    pkg->device_id = rd32(h + H_DEV);
    pkg->sample_rate = rd32(h + H_SR);
    pkg->payload_crc = rd32(h + H_PCRC);
    pkg->codec = h[H_CODEC];
    pkg->entry_count = n;
    pkg->total_size = rd32(h + H_AUD_OFF) + rd32(h + H_AUD_SIZE);
    uint32_t aud = base + rd32(h + H_AUD_OFF), aud_size = rd32(h + H_AUD_SIZE);

    uint8_t r[ENTRY_SIZE];
    for (uint16_t i = 0; i < n; i++) {
        if (aac_hal_flash_read(base + rd32(h + H_IDX_OFF) + i * ENTRY_SIZE, r, ENTRY_SIZE) != 0) return AAC_ERR_IO;
        aac_entry_t *en = &pkg->entries[i];
        en->vocab_id = rd16(r); en->source = r[2]; en->priority = r[3]; en->duration_ms = rd16(r + 6);
        en->audio_addr = aud + rd32(r + 8); en->audio_len = rd32(r + 12); en->sample_count = rd32(r + 16);
        if (rd32(r + 8) + en->audio_len > aud_size) return AAC_ERR_LAYOUT;
        if (i && en->vocab_id <= pkg->entries[i - 1].vocab_id) return AAC_ERR_LAYOUT;
    }
    uint8_t m[MAP_SIZE], seen = 0;
    for (int i = 0; i < AAC_SETS * AAC_BUTTONS; i++) {
        if (aac_hal_flash_read(base + rd32(h + H_MAP_OFF) + i * MAP_SIZE, m, MAP_SIZE) != 0) return AAC_ERR_IO;
        if (m[0] >= AAC_SETS || m[1] >= AAC_BUTTONS) return AAC_ERR_LAYOUT;
        aac_button_t *b = &pkg->buttons[m[0]][m[1]];
        b->r = m[2]; b->g = m[3]; b->b = m[4]; b->vocab_id = rd16(m + 6);
        if (!aac_pkg_find(pkg, b->vocab_id)) return AAC_ERR_LAYOUT;
        seen |= (uint8_t)(1u << (m[0] * AAC_BUTTONS + m[1]));
    }
    if (seen != 0xFF) return AAC_ERR_LAYOUT;                   /* 8개 매핑 모두 있어야 함 */
    uint8_t sh[4];
    uint32_t so = base + rd32(h + H_SCHED_OFF);
    if (aac_hal_flash_read(so, sh, 4) != 0) return AAC_ERR_IO;
    uint16_t sc = rd16(sh);
    if (sc > AAC_MAX_SCHED || rd32(h + H_SCHED_SIZE) != 4u + sc * SCHED_SIZE) return AAC_ERR_LAYOUT;
    for (uint16_t i = 0; i < sc; i++) {
        uint8_t s[SCHED_SIZE];
        if (aac_hal_flash_read(so + 4 + i * SCHED_SIZE, s, SCHED_SIZE) != 0) return AAC_ERR_IO;
        aac_sched_t *t = &pkg->sched[i];
        t->days = s[0]; t->set_id = s[1]; t->start_min = rd16(s + 2); t->end_min = rd16(s + 4);
        if (t->set_id >= AAC_SETS || t->start_min >= t->end_min || t->end_min > 1440) return AAC_ERR_LAYOUT;
    }
    pkg->sched_count = (uint8_t)sc;
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

uint8_t aac_pkg_active_set(const aac_pkg_t *pkg, uint32_t local_unix)
{
    uint32_t days = local_unix / 86400u;
    uint8_t wday = (uint8_t)((days + 3u) % 7u);               /* 1970-01-01 = 목요일 → 0=월 */
    uint16_t minute = (uint16_t)((local_unix % 86400u) / 60u);
    for (uint8_t i = 0; i < pkg->sched_count; i++) {
        const aac_sched_t *s = &pkg->sched[i];
        if ((s->days >> wday & 1u) && minute >= s->start_min && minute < s->end_min) return s->set_id;
    }
    return AAC_SET_GENERAL;
}
