#include <string.h>
#include <stddef.h>
#include "aac_update.h"
#include "aac_pkg.h"
#include "aac_player.h"
#include "aac_events.h"
#include "aac_hal.h"

/* 프레임: 0xA5 | type | seq(2) | len(2) | payload | crc16(2) — 규격서 5장 */
enum { T_BEGIN = 1, T_DATA = 2, T_END = 3, T_ACK = 4, T_QUERY = 5, T_VERSION = 6, T_ROLLBACK = 7,
       T_EVENTS_GET = 8, T_EVENTS = 9, T_EVENTS_ACK = 10, T_TIME_SET = 11 };
enum { ST_OK = 0, ST_FRAME_CRC = 1, ST_TOO_LARGE = 2, ST_SEQ = 3, ST_VERIFY_FAIL = 4, ST_STATE = 5 };
#define SOF 0xA5
#define MAX_PAYLOAD 256
#define META_MAGIC 0xAAC0517Au
#define ERASE_UNIT 4096u

typedef struct { uint32_t magic; uint8_t active; uint8_t valid_a; uint8_t valid_b; uint8_t pad; int16_t tz; uint16_t pad2; uint32_t crc; } meta_t;

static meta_t M;
static struct { int active; uint32_t size; uint32_t erased_to; } S;
static uint8_t fb[8 + MAX_PAYLOAD];
static size_t flen;

static uint32_t slot_addr(int s) { return s ? AAC_SLOT_B_ADDR : AAC_SLOT_A_ADDR; }
static int staging_slot(void) { return M.active ^ 1; }

static void meta_save(void)
{
    M.magic = META_MAGIC;
    M.crc = aac_crc32(0, &M, offsetof(meta_t, crc));
    aac_hal_meta_write(&M, sizeof M);
}

uint32_t aac_update_active_slot_addr(void) { return slot_addr(M.active); }

int aac_update_init(void)
{
    memset(&S, 0, sizeof S);
    if (aac_hal_meta_read(&M, sizeof M) != 0 || M.magic != META_MAGIC || M.crc != aac_crc32(0, &M, offsetof(meta_t, crc))) {
        memset(&M, 0, sizeof M);       /* 최초 부팅: 슬롯 A, 한국 시간 */
        M.tz = 540;
    }
    aac_player_set_tz(M.tz);
    if (aac_player_init(slot_addr(M.active)) == AAC_OK) return 0;
    /* 활성 슬롯 손상 시 다른 슬롯으로 자동 복구 */
    if ((M.active ? M.valid_a : M.valid_b) && aac_player_init(slot_addr(M.active ^ 1)) == AAC_OK) {
        M.active ^= 1; meta_save(); return 1;
    }
    return -1;
}

static void send(uint8_t type, uint16_t seq, const uint8_t *p, uint16_t len)
{
    uint8_t out[8 + 3 + 20 * 12];
    out[0] = SOF; out[1] = type; out[2] = (uint8_t)seq; out[3] = (uint8_t)(seq >> 8);
    out[4] = (uint8_t)len; out[5] = (uint8_t)(len >> 8);
    memcpy(out + 6, p, len);
    uint16_t c = aac_crc16_ccitt(0xFFFF, out + 1, 5u + len);
    out[6 + len] = (uint8_t)c; out[7 + len] = (uint8_t)(c >> 8);
    aac_hal_tx(out, 8u + len);
}

static void ack(uint16_t seq, uint8_t st)
{
    uint8_t p[3] = {(uint8_t)seq, (uint8_t)(seq >> 8), st};
    send(T_ACK, seq, p, 3);
}

static void w32(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24); }
static uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }

static void handle(uint8_t type, uint16_t seq, const uint8_t *p, uint16_t len)
{
    switch (type) {
    case T_QUERY: {
        uint32_t a = 0, b = 0;
        aac_pkg_verify(slot_addr(M.active), &a);
        if (M.active ? M.valid_a : M.valid_b) aac_pkg_verify(slot_addr(M.active ^ 1), &b);
        uint8_t v[8] = {(uint8_t)a, (uint8_t)(a >> 8), (uint8_t)(a >> 16), (uint8_t)(a >> 24),
                        (uint8_t)b, (uint8_t)(b >> 8), (uint8_t)(b >> 16), (uint8_t)(b >> 24)};
        send(T_VERSION, seq, v, 8);
        return;
    }
    case T_BEGIN:
        if (len < 12) { ack(seq, ST_STATE); return; }
        S.size = rd32(p);
        if (S.size > AAC_SLOT_SIZE || S.size < AAC_HEADER_SIZE) { S.active = 0; ack(seq, ST_TOO_LARGE); return; }
        S.active = 1; S.erased_to = 0;
        if (staging_slot()) M.valid_b = 0; else M.valid_a = 0;
        ack(seq, ST_OK);
        return;
    case T_DATA: {
        if (!S.active || len < 4) { ack(seq, ST_STATE); return; }
        uint32_t off = rd32(p), n = len - 4u;
        if (off + n > S.size) { ack(seq, ST_TOO_LARGE); return; }
        uint32_t base = slot_addr(staging_slot());
        while (S.erased_to < off + n) { aac_hal_flash_erase(base + S.erased_to, ERASE_UNIT); S.erased_to += ERASE_UNIT; }
        ack(seq, aac_hal_flash_write(base + off, p + 4, n) == 0 ? ST_OK : ST_STATE);
        return;
    }
    case T_END: {
        if (!S.active) { ack(seq, ST_STATE); return; }
        S.active = 0;
        int st = staging_slot();
        if (aac_pkg_verify(slot_addr(st), NULL) != AAC_OK) { ack(seq, ST_VERIFY_FAIL); return; }   /* 활성 슬롯 유지 */
        if (st) M.valid_b = 1; else M.valid_a = 1;
        if (aac_player_reload(slot_addr(st)) != AAC_OK) { ack(seq, ST_VERIFY_FAIL); return; }
        M.active = (uint8_t)st; meta_save();
        aac_hal_event(AAC_EVT_PKG_UPDATED, AAC_NO_VOCAB);
        ack(seq, ST_OK);
        return;
    }
    case T_EVENTS_GET: {
        aac_event_t ev[20];
        uint8_t want = len ? p[0] : 20, body[3 + 20 * 12];
        if (want > 20) want = 20;
        uint16_t n = aac_events_peek(ev, want), d = aac_events_dropped();
        body[0] = (uint8_t)n; body[1] = (uint8_t)d; body[2] = (uint8_t)(d >> 8);
        for (uint16_t i = 0; i < n; i++) {
            uint8_t *q = body + 3 + i * 12;
            w32(q, ev[i].unix_time); q[4] = (uint8_t)ev[i].vocab_id; q[5] = (uint8_t)(ev[i].vocab_id >> 8);
            q[6] = ev[i].set_id; q[7] = ev[i].button; w32(q + 8, ev[i].config_version);
        }
        send(T_EVENTS, seq, body, (uint16_t)(3 + n * 12));
        return;
    }
    case T_EVENTS_ACK:
        if (!len || p[0] > aac_events_count()) { ack(seq, ST_STATE); return; }
        aac_events_drop(p[0]);
        ack(seq, ST_OK);
        return;
    case T_TIME_SET:
        if (len < 6) { ack(seq, ST_STATE); return; }
        aac_hal_rtc_set(rd32(p));
        M.tz = (int16_t)(p[4] | (p[5] << 8));
        aac_player_set_tz(M.tz); meta_save();
        ack(seq, ST_OK);
        return;
    case T_ROLLBACK: {
        int other = M.active ^ 1;
        if (!(other ? M.valid_b : M.valid_a) || aac_player_reload(slot_addr(other)) != AAC_OK) { ack(seq, ST_STATE); return; }
        M.active = (uint8_t)other; meta_save();
        aac_hal_event(AAC_EVT_PKG_UPDATED, AAC_NO_VOCAB);
        ack(seq, ST_OK);
        return;
    }
    default:
        ack(seq, ST_STATE);
    }
}

void aac_update_rx(const uint8_t *data, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        uint8_t b = data[i];
        if (flen == 0 && b != SOF) continue;
        fb[flen++] = b;
        if (flen >= 6) {
            uint16_t plen = (uint16_t)(fb[4] | (fb[5] << 8));
            if (plen > MAX_PAYLOAD) { flen = 0; continue; }
            if (flen == 8u + plen) {
                uint16_t seq = (uint16_t)(fb[2] | (fb[3] << 8));
                uint16_t crc = (uint16_t)(fb[6 + plen] | (fb[7 + plen] << 8));
                if (crc != aac_crc16_ccitt(0xFFFF, fb + 1, 5u + plen)) ack(seq, ST_FRAME_CRC);
                else handle(fb[1], seq, fb + 6, plen);
                flen = 0;
            }
        }
    }
}
