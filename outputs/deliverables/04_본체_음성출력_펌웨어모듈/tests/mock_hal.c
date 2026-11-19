/* 호스트(PC) 시험용 HAL: 외장 플래시 2MB 배열, 오디오 출력은 메모리로 캡처 */
#define _POSIX_C_SOURCE 199309L
#include <string.h>
#include <time.h>
#include "aac_hal.h"
#include "mock_hal.h"

uint8_t  g_flash[MOCK_FLASH_SIZE];
uint8_t  g_meta[64]; int g_meta_valid;
int      g_audio_running, g_amp_on, g_audio_starts;
uint8_t  g_led[4][3];
int      g_evt_count[8]; uint16_t g_evt_last[8];
uint8_t  g_tx[4096]; size_t g_tx_len;
int      g_prime_on_start = 1;
uint32_t g_rtc; int64_t g_time_offset_us; int g_vibrate_ms, g_vibrate_count;
int16_t  g_prime_buf[256];

int aac_hal_flash_read(uint32_t a, void *b, size_t n) { if (a + n > MOCK_FLASH_SIZE) return -1; memcpy(b, g_flash + a, n); return 0; }
int aac_hal_flash_write(uint32_t a, const void *b, size_t n) {
    if (a + n > MOCK_FLASH_SIZE) return -1;
    for (size_t i = 0; i < n; i++) g_flash[a + i] &= ((const uint8_t *)b)[i];   /* NOR 플래시: 1→0 만 가능 */
    return 0;
}
int aac_hal_flash_erase(uint32_t a, size_t n) { if (a + n > MOCK_FLASH_SIZE) return -1; memset(g_flash + a, 0xFF, n); return 0; }
int aac_hal_meta_read(void *b, size_t n) { if (!g_meta_valid) return -1; memcpy(b, g_meta, n); return 0; }
int aac_hal_meta_write(const void *b, size_t n) { memcpy(g_meta, b, n); g_meta_valid = 1; return 0; }
int aac_hal_audio_start(uint32_t sr) {
    (void)sr; g_audio_starts++; g_audio_running = 1;
    /* 실제 I2S 드라이버처럼 시작 즉시 첫 버퍼를 요청 */
    if (g_prime_on_start) aac_player_fill(g_prime_buf, 256);
    return 0;
}
void aac_hal_audio_stop(void) { g_audio_running = 0; }
void aac_hal_amp_enable(int on) { g_amp_on = on; }
void aac_hal_led_set(uint8_t z, uint8_t r, uint8_t g, uint8_t b) { g_led[z][0] = r; g_led[z][1] = g; g_led[z][2] = b; }
void aac_hal_event(aac_evt_t e, uint16_t v) { g_evt_count[e]++; g_evt_last[e] = v; }
uint32_t aac_hal_time_us(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (uint32_t)((int64_t)t.tv_sec * 1000000 + t.tv_nsec / 1000 + g_time_offset_us); }
void aac_hal_vibrate(uint16_t ms) { g_vibrate_ms = ms; g_vibrate_count++; }
uint32_t aac_hal_rtc_get(void) { return g_rtc; }
void aac_hal_rtc_set(uint32_t t) { g_rtc = t; }
void aac_hal_tx(const uint8_t *d, size_t n) { if (g_tx_len + n <= sizeof g_tx) { memcpy(g_tx + g_tx_len, d, n); g_tx_len += n; } }

void mock_reset(void)
{
    memset(g_flash, 0xFF, sizeof g_flash); g_meta_valid = 0; g_audio_running = g_amp_on = g_audio_starts = 0;
    memset(g_led, 0, sizeof g_led); memset(g_evt_count, 0, sizeof g_evt_count); g_tx_len = 0; g_vibrate_count = 0; g_time_offset_us = 0;
}
