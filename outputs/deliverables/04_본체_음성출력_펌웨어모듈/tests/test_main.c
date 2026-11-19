/* 호스트 시험: ./test_aac v1.aacpkg v2.aacpkg reference.txt */
#define _POSIX_C_SOURCE 199309L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mock_hal.h"
#include "aac_pkg.h"
#include "aac_player.h"
#include "aac_events.h"
#include "aac_update.h"
#include "aac_hal.h"

static int fails, checks;
#define CHECK(c, ...) do { checks++; if (!(c)) { fails++; printf("  FAIL %s:%d ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* 2026-11-16(월) 10:00 KST = 01:00 UTC */
#define MON_1000_KST 1794790800u
#define SAT_1000_KST (MON_1000_KST + 5u * 86400u)
#define MON_1700_KST (MON_1000_KST + 7u * 3600u)

static uint8_t *load_file(const char *p, size_t *n)
{
    FILE *f = fopen(p, "rb"); if (!f) { perror(p); exit(2); }
    fseek(f, 0, SEEK_END); *n = (size_t)ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *b = malloc(*n); if (fread(b, 1, *n, f) != *n) exit(2); fclose(f); return b;
}
static void put_slot(uint32_t a, const uint8_t *d, size_t n) { memcpy(g_flash + a, d, n); }

static uint32_t play_all(uint16_t vid, uint32_t *count)
{
    int16_t buf[160]; uint32_t crc = 0, n = 0; size_t k;
    g_prime_on_start = 0;
    if (aac_player_play_vocab(vid) != AAC_OK) { g_prime_on_start = 1; return 0; }
    while ((k = aac_player_fill(buf, 160)) > 0) { crc = aac_crc32(crc, buf, k * 2); n += (uint32_t)k; }
    g_prime_on_start = 1; *count = n; return crc;
}

static size_t frame(uint8_t *o, uint8_t type, uint16_t seq, const uint8_t *p, uint16_t len)
{
    o[0] = 0xA5; o[1] = type; o[2] = (uint8_t)seq; o[3] = (uint8_t)(seq >> 8); o[4] = (uint8_t)len; o[5] = (uint8_t)(len >> 8);
    if (len) memcpy(o + 6, p, len);
    uint16_t c = aac_crc16_ccitt(0xFFFF, o + 1, 5u + len); o[6 + len] = (uint8_t)c; o[7 + len] = (uint8_t)(c >> 8);
    return 8u + len;
}
static int last_ack(void) { return g_tx_len >= 11 && g_tx[1] == 4 ? g_tx[g_tx_len - 3] : -1; }
static int send_frame(uint8_t type, uint16_t seq, const uint8_t *p, uint16_t len)
{
    uint8_t f[300]; size_t n = frame(f, type, seq, p, len); g_tx_len = 0; aac_update_rx(f, n); return last_ack();
}
static void w32(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24); }
static int upload(const uint8_t *d, size_t n)
{
    uint8_t p[260]; uint16_t seq = 1;
    w32(p, (uint32_t)n); w32(p + 4, 0); w32(p + 8, 0);
    if (send_frame(1, seq++, p, 12) != 0) return -1;
    for (size_t off = 0; off < n; off += 240) {
        size_t k = n - off > 240 ? 240 : n - off;
        w32(p, (uint32_t)off); memcpy(p + 4, d + off, k);
        if (send_frame(2, seq++, p, (uint16_t)(4 + k)) != 0) return -2;
    }
    return send_frame(3, seq, NULL, 0);
}

int main(int argc, char **argv)
{
    if (argc < 4) { fprintf(stderr, "usage: %s v1.aacpkg v2.aacpkg reference.txt\n", argv[0]); return 2; }
    size_t n1, n2; uint8_t *p1 = load_file(argv[1], &n1), *p2 = load_file(argv[2], &n2);

    printf("[T1] 패키지 적재: 세트 2 × 버튼 4, 작업장 시간표\n");
    mock_reset(); put_slot(AAC_SLOT_A_ADDR, p1, n1); g_rtc = MON_1000_KST;
    CHECK(aac_player_init(AAC_SLOT_A_ADDR) == AAC_OK, "load");
    const aac_pkg_t *pk = aac_player_pkg();
    CHECK(pk && pk->entry_count == 8 && pk->sched_count >= 1, "entries=%d sched=%d", pk ? pk->entry_count : -1, pk ? pk->sched_count : -1);
    printf("  음원 %u개, 설정 v%u, 기기 %u, 시간표 %u개\n", pk->entry_count, pk->config_version, pk->device_id, pk->sched_count);

    printf("[T2] 손상 패키지 거부(무작위 1비트 200회)\n");
    srand(7); int rej = 0;
    for (int i = 0; i < 200; i++) {
        mock_reset(); put_slot(AAC_SLOT_A_ADDR, p1, n1);
        g_flash[(size_t)rand() % n1] ^= (uint8_t)(1u << (rand() % 8));
        aac_pkg_t t; if (aac_pkg_load(&t, AAC_SLOT_A_ADDR) != AAC_OK) rej++;
    }
    CHECK(rej == 200, "%d/200", rej); printf("  거부 %d/200\n", rej);

    printf("[T3] 재생 정확도(8개 음원 × 20회, Python 참조 디코더와 비트 비교)\n");
    mock_reset(); put_slot(AAC_SLOT_A_ADDR, p1, n1); g_rtc = MON_1000_KST; aac_player_init(AAC_SLOT_A_ADDR);
    FILE *rf = fopen(argv[3], "r"); unsigned vid, cnt, crc; int ok = 0, total = 0;
    while (rf && fscanf(rf, "%u %u %x", &vid, &cnt, &crc) == 3)
        for (int r = 0; r < 20; r++) { uint32_t n = 0, c2 = play_all((uint16_t)vid, &n); total++; if (c2 == crc && n == cnt) ok++; }
    if (rf) fclose(rf);
    CHECK(total == 160 && ok == total, "%d/%d", ok, total); printf("  일치 %d/%d\n", ok, total);

    printf("[T4] 세트 자동 전환: 시간표(평일 작업장 시간)에 따라 버튼 문장 선택\n");
    int okset = 1;
    g_rtc = MON_1000_KST;
    for (uint8_t b = 0; b < 4; b++) { aac_player_stop(); aac_player_on_button(b); okset &= aac_player_current() == pk->buttons[1][b].vocab_id && aac_player_current_set() == 1; }
    g_rtc = SAT_1000_KST;
    for (uint8_t b = 0; b < 4; b++) { aac_player_stop(); aac_player_on_button(b); okset &= aac_player_current() == pk->buttons[0][b].vocab_id && aac_player_current_set() == 0; }
    g_rtc = MON_1700_KST;
    for (uint8_t b = 0; b < 4; b++) { aac_player_stop(); aac_player_on_button(b); okset &= aac_player_current() == pk->buttons[0][b].vocab_id; }
    CHECK(okset, "set selection");
    int sc0 = g_evt_count[AAC_EVT_SET_CHANGED]; g_rtc = MON_1000_KST; aac_player_tick();
    CHECK(g_evt_count[AAC_EVT_SET_CHANGED] == sc0 + 1 && aac_player_current_set() == 1, "tick → SET_CHANGED");
    printf("  월 10:00 작업장 / 토 10:00 일반 / 월 17:00 일반 — %s\n", okset ? "정상" : "오류");

    printf("[T5] 불빛 5초 + 진동\n");
    aac_player_stop(); memset(g_led, 0, sizeof g_led); g_time_offset_us = 0; int vib0 = g_vibrate_count;
    aac_player_on_button(2);
    CHECK(g_led[2][1] == pk->buttons[1][2].g && g_vibrate_count == vib0 + 1 && g_vibrate_ms == AAC_VIBRATE_MS, "LED on + vibrate");
    g_time_offset_us = 4900000; aac_player_tick(); CHECK(g_led[2][1] != 0, "4.9초: 켜짐");
    g_time_offset_us = 5000500; aac_player_tick(); CHECK(g_led[2][0] == 0 && g_led[2][1] == 0 && g_led[2][2] == 0, "5.0초: 꺼짐");
    g_time_offset_us = 0;

    printf("[T6] 버튼 4(도움 요청) 우선: 다른 버튼을 끊고, 다른 버튼에 끊기지 않음\n");
    aac_player_stop(); g_rtc = SAT_1000_KST;
    aac_player_on_button(0);
    CHECK(aac_player_on_button(3) == AAC_OK && aac_player_current() == pk->buttons[0][3].vocab_id, "help preempts");
    uint16_t evn = aac_events_count();
    CHECK(aac_player_on_button(1) == AAC_ERR_BUSY && aac_player_current() == pk->buttons[0][3].vocab_id, "normal ignored");
    CHECK(aac_events_count() == evn + 1 && g_led[1][0] == pk->buttons[0][1].r, "무시돼도 기록·불빛은 남음");
    aac_player_stop(); CHECK(!g_amp_on && !g_audio_running, "정지 시 앰프 OFF");

    printf("[T7] 누름 기록: 저장·회수(EVENTS_GET/ACK)·버퍼 초과\n");
    mock_reset(); put_slot(AAC_SLOT_A_ADDR, p1, n1); g_rtc = MON_1000_KST;
    CHECK(aac_update_init() == 0, "init"); aac_events_reset();
    for (int i = 0; i < 25; i++) { g_rtc = MON_1000_KST + (uint32_t)i; aac_player_stop(); aac_player_on_button((uint8_t)(i % 4)); }
    uint8_t mx = 20; send_frame(8, 1, &mx, 1);
    CHECK(g_tx[1] == 9 && g_tx[6] == 20, "EVENTS 20건");
    uint32_t t0 = (uint32_t)g_tx[9] | ((uint32_t)g_tx[10] << 8) | ((uint32_t)g_tx[11] << 16) | ((uint32_t)g_tx[12] << 24);
    CHECK(t0 == MON_1000_KST && g_tx[15] == 1 && g_tx[16] == 0, "첫 기록: 시각·작업장 세트·버튼1");
    uint8_t k = 20; CHECK(send_frame(10, 2, &k, 1) == 0 && aac_events_count() == 5, "ACK 후 5건 남음");
    k = 9; CHECK(send_frame(10, 3, &k, 1) == 5, "남은 수보다 큰 ACK 거부");
    aac_events_reset(); for (int i = 0; i < 130; i++) { aac_player_stop(); aac_player_on_button(0); }
    CHECK(aac_events_count() == AAC_EVENT_CAP && aac_events_dropped() == 2, "128건 보관, 2건 유실 표시");

    printf("[T8] 시각 설정(TIME_SET)\n");
    uint8_t tp[6]; w32(tp, SAT_1000_KST); tp[4] = (uint8_t)540; tp[5] = (uint8_t)(540 >> 8);
    CHECK(send_frame(11, 4, tp, 6) == 0 && g_rtc == SAT_1000_KST && aac_player_tz() == 540, "time set");
    aac_player_tick(); CHECK(aac_player_current_set() == 0, "토요일 → 일반 세트");

    printf("[T9] 패키지 전송·A/B 슬롯·롤백, 안내 음성 없음\n");
    mock_reset(); g_rtc = MON_1000_KST;
    CHECK(aac_update_init() < 0, "빈 플래시");
    CHECK(upload(p1, n1) == 0 && aac_player_pkg()->config_version == 1, "v1");
    CHECK(upload(p2, n2) == 0 && aac_player_pkg()->config_version == 2, "v2");
    uint8_t *bad = malloc(n2); memcpy(bad, p2, n2); bad[n2 / 2] ^= 0x5A;
    CHECK(upload(bad, n2) == 4 && aac_player_pkg()->config_version == 2, "손상 → 거부, v2 유지");
    CHECK(send_frame(7, 50, NULL, 0) == 5, "지워진 슬롯 롤백 거부");
    CHECK(upload(p1, n1) == 0 && send_frame(7, 51, NULL, 0) == 0 && aac_player_pkg()->config_version == 2, "롤백");
    CHECK(aac_update_init() == 0 && aac_player_pkg()->config_version == 2, "재부팅 후 유지");
    CHECK(g_evt_count[AAC_EVT_PLAY_START] == 0, "전송·롤백·재부팅 중 음성 출력 0회(안내 음성 없음)");

    printf("[T10] 처리 지연(버튼 → 첫 오디오 버퍼, 호스트 CPU 100회)\n");
    uint32_t sum = 0, mxl = 0;
    for (int i = 0; i < 100; i++) { aac_player_stop(); aac_player_on_button((uint8_t)(i % 4)); uint32_t l = aac_player_stats()->last_latency_us; sum += l; if (l > mxl) mxl = l; }
    printf("  평균 %u us, 최대 %u us (모듈 처리만; 실기 I2S·앰프 기동 미포함)\n", sum / 100, mxl);
    CHECK(mxl < 150000, "latency");

    printf("[T11] 통신 계층 없이 독립 동작: 전 시험을 BLE·Wi-Fi 없이 수행\n");
    printf("\n결과: %d/%d 통과\n", checks - fails, checks);
    free(p1); free(p2); free(bad);
    return fails ? 1 : 0;
}
