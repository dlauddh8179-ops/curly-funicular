#include <string.h>
#include "aac_player.h"
#include "aac_events.h"
#include "aac_adpcm.h"
#include "aac_hal.h"

#define DEC_BUF 256u

static struct {
    aac_pkg_t pkg;
    int loaded;
    volatile int playing;
    const aac_entry_t *cur;
    uint8_t  prio, first, set_now;
    uint32_t read_pos, decoded;
    aac_adpcm_state_t st;
    int16_t  buf[DEC_BUF];
    uint16_t buf_len, buf_pos;
    uint32_t led_on_us[AAC_BUTTONS];
    uint8_t  led_on;                   /* 비트마스크 */
    aac_player_stats_t stats;
} P;
static int16_t g_tz = 540;           /* 한국 표준시 기본 */

static uint32_t local_now(void) { return (uint32_t)((int32_t)aac_hal_rtc_get() + g_tz * 60); }

aac_err_t aac_player_init(uint32_t slot_base)
{
    memset(&P, 0, sizeof P);
    aac_err_t e = aac_pkg_load(&P.pkg, slot_base);
    P.loaded = (e == AAC_OK);
    if (P.loaded) P.set_now = aac_pkg_active_set(&P.pkg, local_now());
    return e;
}

aac_err_t aac_player_reload(uint32_t slot_base)
{
    static aac_pkg_t tmp;              /* 실패 시 기존 유지 */
    aac_player_stop();
    aac_err_t e = aac_pkg_load(&tmp, slot_base);
    if (e == AAC_OK) { P.pkg = tmp; P.loaded = 1; P.set_now = aac_pkg_active_set(&P.pkg, local_now()); }
    return e;
}

void aac_player_set_tz(int16_t tz) { g_tz = tz; }
int16_t aac_player_tz(void) { return g_tz; }
uint8_t aac_player_current_set(void) { return P.set_now; }
int aac_player_is_playing(void) { return P.playing; }
uint16_t aac_player_current(void) { return P.playing && P.cur ? P.cur->vocab_id : AAC_NO_VOCAB; }
const aac_pkg_t *aac_player_pkg(void) { return P.loaded ? &P.pkg : NULL; }
const aac_player_stats_t *aac_player_stats(void) { return &P.stats; }

static void finish(void)
{
    if (!P.playing) return;
    P.playing = 0;
    aac_hal_audio_stop();
    aac_hal_amp_enable(0);
    aac_hal_event(AAC_EVT_PLAY_END, P.cur ? P.cur->vocab_id : AAC_NO_VOCAB);
    P.cur = NULL;
}

void aac_player_stop(void) { finish(); }

static aac_err_t start(const aac_entry_t *en)
{
    if (P.playing) {
        if (en->priority < P.prio) { P.stats.ignored++; return AAC_ERR_BUSY; }
        P.stats.preempted++;
        P.playing = 0;                 /* I2S 스트림 유지, 클립만 교체 */
    } else {
        aac_hal_amp_enable(1);
    }
    P.cur = en; P.prio = en->priority; P.first = 1;
    P.read_pos = P.decoded = 0; P.buf_len = P.buf_pos = 0;
    aac_adpcm_reset(&P.st);
    P.playing = 1;
    P.stats.plays++;
    aac_hal_event(AAC_EVT_PLAY_START, en->vocab_id);
    return aac_hal_audio_start(P.pkg.sample_rate) == 0 ? AAC_OK : AAC_ERR_IO;
}

aac_err_t aac_player_on_button(uint8_t button)
{
    P.stats.touch_us = aac_hal_time_us();
    if (!P.loaded) return AAC_ERR_NO_PKG;
    if (button >= AAC_BUTTONS) return AAC_ERR_NOT_FOUND;
    P.stats.presses++;
    uint32_t now_local = local_now();
    P.set_now = aac_pkg_active_set(&P.pkg, now_local);
    const aac_button_t *b = &P.pkg.buttons[P.set_now][button];
    const aac_entry_t *en = aac_pkg_find(&P.pkg, b->vocab_id);
    if (!en) return AAC_ERR_NOT_FOUND;

    /* 1) 불빛 5초 + 진동 — 재생 여부와 관계없이 눌림을 알려 줌 */
    aac_hal_led_set(button, b->r, b->g, b->b);
    P.led_on |= (uint8_t)(1u << button);
    P.led_on_us[button] = P.stats.touch_us;
    aac_hal_vibrate(AAC_VIBRATE_MS);
    /* 2) 누름 기록(보호자 웹 기록·알림의 원천) */
    aac_event_t ev = {aac_hal_rtc_get(), en->vocab_id, P.set_now, button, P.pkg.config_version};
    aac_events_push(&ev);
    aac_hal_event(AAC_EVT_PRESS, en->vocab_id);
    /* 3) 문장 재생 */
    return start(en);
}

aac_err_t aac_player_play_vocab(uint16_t vocab_id)
{
    if (!P.loaded) return AAC_ERR_NO_PKG;
    const aac_entry_t *en = aac_pkg_find(&P.pkg, vocab_id);
    if (!en) return AAC_ERR_NOT_FOUND;
    return start(en);
}

void aac_player_tick(void)
{
    uint32_t now = aac_hal_time_us();
    for (uint8_t i = 0; i < AAC_BUTTONS; i++) {
        if ((P.led_on >> i & 1u) && now - P.led_on_us[i] >= AAC_LED_MS * 1000u) {
            aac_hal_led_set(i, 0, 0, 0);
            P.led_on &= (uint8_t)~(1u << i);
        }
    }
    if (P.loaded) {
        uint8_t s = aac_pkg_active_set(&P.pkg, local_now());
        if (s != P.set_now) { P.set_now = s; aac_hal_event(AAC_EVT_SET_CHANGED, s); }
    }
}

static int refill(void)
{
    const aac_entry_t *en = P.cur;
    if (P.decoded >= en->sample_count || P.read_pos >= en->audio_len) return 0;
    uint8_t raw[DEC_BUF];
    uint32_t want = P.pkg.codec == AAC_CODEC_IMA_ADPCM ? DEC_BUF / 2 : DEC_BUF;
    if (want > en->audio_len - P.read_pos) want = en->audio_len - P.read_pos;
    if (aac_hal_flash_read(en->audio_addr + P.read_pos, raw, want) != 0) return 0;
    P.read_pos += want;
    size_t n;
    if (P.pkg.codec == AAC_CODEC_IMA_ADPCM) {
        n = aac_adpcm_decode(&P.st, raw, want, P.buf, DEC_BUF);
    } else {
        n = want / 2;
        for (size_t i = 0; i < n; i++) P.buf[i] = (int16_t)(raw[2 * i] | (raw[2 * i + 1] << 8));
    }
    if (P.decoded + n > en->sample_count) n = en->sample_count - P.decoded;
    P.decoded += (uint32_t)n;
    P.buf_len = (uint16_t)n; P.buf_pos = 0;
    return n > 0;
}

size_t aac_player_fill(int16_t *out, size_t n)
{
    size_t done = 0;
    if (!P.playing) return 0;
    if (P.first) {
        P.first = 0;
        P.stats.first_audio_us = aac_hal_time_us();
        P.stats.last_latency_us = P.stats.first_audio_us - P.stats.touch_us;
        if (P.stats.last_latency_us > P.stats.max_latency_us) P.stats.max_latency_us = P.stats.last_latency_us;
    }
    while (done < n) {
        if (P.buf_pos >= P.buf_len && !refill()) break;
        size_t k = P.buf_len - P.buf_pos;
        if (k > n - done) k = n - done;
        memcpy(out + done, P.buf + P.buf_pos, k * sizeof(int16_t));
        P.buf_pos += (uint16_t)k; done += k;
    }
    if (done == 0) finish();
    return done;
}
