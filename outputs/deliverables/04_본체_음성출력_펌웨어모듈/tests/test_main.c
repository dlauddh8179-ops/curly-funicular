/* 호스트 시험: ./test_aac v1.aacpkg v2.aacpkg reference.txt */
#define _POSIX_C_SOURCE 199309L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mock_hal.h"
#include "aac_pkg.h"
#include "aac_player.h"
#include "aac_update.h"
#include "aac_hal.h"

static int fails, checks;
#define CHECK(c, ...) do { checks++; if (!(c)) { fails++; printf("  FAIL %s:%d ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static uint8_t *load_file(const char *p, size_t *n)
{
    FILE *f = fopen(p, "rb"); if (!f) { perror(p); exit(2); }
    fseek(f, 0, SEEK_END); *n = (size_t)ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *b = malloc(*n); if (fread(b, 1, *n, f) != *n) exit(2); fclose(f); return b;
}

static void put_slot(uint32_t addr, const uint8_t *d, size_t n) { memcpy(g_flash + addr, d, n); }

/* 한 클립 전체를 재생해 출력 샘플 CRC32 와 샘플 수 반환 */
static uint32_t play_all(uint16_t vid, uint32_t *count)
{
    int16_t buf[160]; uint32_t crc = 0, n = 0;
    g_prime_on_start = 0;
    if (aac_player_play(vid) != AAC_OK) return 0;
    size_t k;
    while ((k = aac_player_fill(buf, 160)) > 0) { crc = aac_crc32(crc, buf, k * 2); n += (uint32_t)k; }
    g_prime_on_start = 1;
    *count = n; return crc;
}

static size_t frame(uint8_t *out, uint8_t type, uint16_t seq, const uint8_t *p, uint16_t len)
{
    out[0] = 0xA5; out[1] = type; out[2] = (uint8_t)seq; out[3] = (uint8_t)(seq >> 8); out[4] = (uint8_t)len; out[5] = (uint8_t)(len >> 8);
    if (len) memcpy(out + 6, p, len);
    uint16_t c = aac_crc16_ccitt(0xFFFF, out + 1, 5u + len); out[6 + len] = (uint8_t)c; out[7 + len] = (uint8_t)(c >> 8);
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

    printf("[T1] 패키지 적재·인덱스\n");
    mock_reset(); put_slot(AAC_SLOT_A_ADDR, p1, n1);
    CHECK(aac_player_init(AAC_SLOT_A_ADDR) == AAC_OK, "load");
    const aac_pkg_t *pk = aac_player_pkg();
    CHECK(pk && pk->entry_count == 31, "entry_count=%d", pk ? pk->entry_count : -1);
    CHECK(pk && pk->zones[0].vocab_id == 1 && pk->zones[2].long_press_vocab_id == 104, "zones");
    printf("  항목 %u개, 세트 v%u, %uHz, 코덱 %u\n", pk->entry_count, pk->set_version, pk->sample_rate, pk->codec);

    printf("[T2] 손상 패키지 거부(무작위 1비트 200회)\n");
    srand(7); int rej = 0;
    for (int i = 0; i < 200; i++) {
        mock_reset(); put_slot(AAC_SLOT_A_ADDR, p1, n1);
        size_t pos = (size_t)rand() % n1; g_flash[pos] ^= (uint8_t)(1u << (rand() % 8));
        aac_pkg_t tmp; if (aac_pkg_load(&tmp, AAC_SLOT_A_ADDR) != AAC_OK) rej++;
    }
    CHECK(rej == 200, "rejected %d/200", rej);
    printf("  거부 %d/200\n", rej);

    printf("[T3] 문구 재생 정확도(31종 × 20회, Python 참조 디코더와 비트 단위 비교)\n");
    mock_reset(); put_slot(AAC_SLOT_A_ADDR, p1, n1); aac_player_init(AAC_SLOT_A_ADDR);
    FILE *rf = fopen(argv[3], "r"); unsigned vid, cnt, crc; int ok = 0, total = 0;
    while (rf && fscanf(rf, "%u %u %x", &vid, &cnt, &crc) == 3) {
        for (int r = 0; r < 20; r++) {
            uint32_t c2, n = 0; c2 = play_all((uint16_t)vid, &n); total++;
            if (c2 == crc && n == cnt) ok++;
        }
    }
    if (rf) fclose(rf);
    CHECK(total == 31 * 20 && ok == total, "ok %d/%d", ok, total);
    printf("  일치 %d/%d\n", ok, total);

    printf("[T4] 터치 → 첫 오디오 버퍼 공급 지연(호스트 CPU, 100회)\n");
    uint32_t sum = 0, mx = 0;
    for (int i = 0; i < 100; i++) {
        aac_player_stop();
        aac_player_on_touch((uint8_t)(i % 4), AAC_TOUCH_TAP);
        uint32_t l = aac_player_stats()->last_latency_us; sum += l; if (l > mx) mx = l;
    }
    printf("  평균 %u us, 최대 %u us (모듈 처리 시간만; 실기 I2S·앰프 기동 시간은 미포함)\n", sum / 100, mx);
    CHECK(mx < 150000, "latency");

    printf("[T5] 우선순위: 응급이 일반을 끊고, 일반은 응급을 못 끊음\n");
    aac_player_stop();
    aac_player_on_touch(0, AAC_TOUCH_TAP);                     /* 배고파요(일반) */
    CHECK(aac_player_current() == 1, "cur=%u", aac_player_current());
    CHECK(aac_player_on_touch(3, AAC_TOUCH_TAP) == AAC_OK && aac_player_current() == 4, "emergency preempt");
    CHECK(g_evt_count[AAC_EVT_EMERGENCY] >= 1 && g_evt_last[AAC_EVT_EMERGENCY] == 4, "emergency event");
    CHECK(g_led[0][0] == 0 && g_led[3][2] == pk->zones[3].b, "LED 전환");
    CHECK(aac_player_on_touch(0, AAC_TOUCH_TAP) == AAC_ERR_BUSY && aac_player_current() == 4, "normal ignored");
    CHECK(aac_player_play(101) == AAC_ERR_BUSY, "system < emergency");
    aac_player_stop(); aac_player_on_touch(1, AAC_TOUCH_TAP);
    CHECK(aac_player_play(105) == AAC_OK && aac_player_current() == 105, "system preempts normal");
    aac_player_stop();
    CHECK(!g_amp_on && !g_audio_running, "정지 시 앰프 OFF");

    printf("[T6] 도움 영역 길게 누르기 → SOS\n");
    int sos0 = g_evt_count[AAC_EVT_SOS];
    CHECK(aac_player_on_touch(2, AAC_TOUCH_LONG) == AAC_OK && aac_player_current() == 104, "long press");
    CHECK(g_evt_count[AAC_EVT_SOS] == sos0 + 1, "SOS event");
    aac_player_stop();

    printf("[T7] 업로드 프로토콜·A/B 슬롯·롤백\n");
    mock_reset();
    CHECK(aac_update_init() < 0, "빈 플래시: 패키지 없음");
    CHECK(upload(p1, n1) == 0, "upload v1");
    CHECK(aac_player_pkg() && aac_player_pkg()->set_version == 1, "active v1");
    CHECK(upload(p2, n2) == 0, "upload v2");
    CHECK(aac_player_pkg()->set_version == 2, "active v2");
    uint8_t *bad = malloc(n2); memcpy(bad, p2, n2); bad[n2 / 2] ^= 0x5A;
    CHECK(upload(bad, n2) == 4, "corrupt → VERIFY_FAIL");
    CHECK(aac_player_pkg()->set_version == 2, "손상 업로드 후에도 v2 유지");
    CHECK(send_frame(7, 99, NULL, 0) == 5, "손상 업로드로 지워진 슬롯으로는 롤백 거부");
    /* 실패한 업로드가 스테이징 슬롯(v1)을 지웠으므로 롤백 불가가 정상 */
    CHECK(upload(p1, n1) == 0 && aac_player_pkg()->set_version == 1, "v1 재업로드");
    CHECK(send_frame(7, 100, NULL, 0) == 0 && aac_player_pkg()->set_version == 2, "rollback → v2");
    printf("  재부팅 모사: ");
    CHECK(aac_update_init() == 0 && aac_player_pkg()->set_version == 2, "meta 유지");
    printf("활성 v%u\n", aac_player_pkg()->set_version);
    uint8_t f[16]; size_t fl = frame(f, 5, 1, NULL, 0); f[3] ^= 1; g_tx_len = 0; aac_update_rx(f, fl);
    CHECK(last_ack() == 1, "frame CRC error ack");

    printf("[T8] 통신 계층 없이 독립 동작: 본 시험 전체가 BLE·Wi-Fi·DX-M2 없이 실행됨\n");
    printf("\n결과: %d/%d 통과\n", checks - fails, checks);
    free(p1); free(p2); free(bad);
    return fails ? 1 : 0;
}
