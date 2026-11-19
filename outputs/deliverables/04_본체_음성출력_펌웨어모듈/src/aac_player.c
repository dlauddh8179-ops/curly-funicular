#include <string.h>
#include "aac_player.h"
#include "aac_adpcm.h"
#include "aac_hal.h"

#define DEC_BUF   256u                 /* 디코드 버퍼(샘플) */
#define NO_ZONE   0xFFu

static struct {
    aac_pkg_t pkg;
    int loaded;
    volatile int playing;
    const aac_entry_t *cur;
    uint8_t  zone;
    uint8_t  prio;
    uint8_t  from_touch;
    uint8_t  first;
    uint32_t read_pos;                 /* 소비한 오디오 바이트 */
    uint32_t decoded;                  /* 디코드한 샘플 */
    aac_adpcm_state_t st;
    int16_t  buf[DEC_BUF];
    uint16_t buf_len, buf_pos;
    aac_player_stats_t stats;
} P;

aac_err_t aac_player_init(uint32_t slot_base)
{
    memset(&P, 0, sizeof P);
    P.zone = NO_ZONE;
    aac_err_t e = aac_pkg_load(&P.pkg, slot_base);
    P.loaded = (e == AAC_OK);
    return e;
}

aac_err_t aac_player_reload(uint32_t slot_base)
{
    aac_player_stop();
    static aac_pkg_t tmp;              /* 실패 시 기존 패키지 유지 */
    aac_err_t e = aac_pkg_load(&tmp, slot_base);
    if (e == AAC_OK) { P.pkg = tmp; P.loaded = 1; }
    return e;
}

static void finish(void)
{
    if (!P.playing) return;
    P.playing = 0;
    if (P.zone != NO_ZONE) aac_hal_led_set(P.zone, 0, 0, 0);
    aac_hal_audio_stop();
    aac_hal_amp_enable(0);
    aac_hal_event(AAC_EVT_PLAY_END, P.cur ? P.cur->vocab_id : AAC_NO_VOCAB);
    P.cur = NULL;
    P.zone = NO_ZONE;
}

void aac_player_stop(void) { finish(); }
int aac_player_is_playing(void) { return P.playing; }
uint16_t aac_player_current(void) { return P.playing && P.cur ? P.cur->vocab_id : AAC_NO_VOCAB; }
const aac_pkg_t *aac_player_pkg(void) { return P.loaded ? &P.pkg : NULL; }
const aac_player_stats_t *aac_player_stats(void) { return &P.stats; }

static aac_err_t start(const aac_entry_t *en, uint8_t zone, int from_touch)
{
    if (P.playing) {
        if (en->priority < P.prio) { P.stats.ignored++; return AAC_ERR_BUSY; }
        P.stats.preempted++;
        if (P.zone != NO_ZONE && P.zone != zone) aac_hal_led_set(P.zone, 0, 0, 0);
        P.playing = 0;                 /* 오디오 스트림은 유지한 채 클립만 교체(지연 최소화) */
    } else {
        aac_hal_amp_enable(1);
    }
    P.cur = en; P.zone = zone; P.prio = en->priority; P.from_touch = (uint8_t)from_touch; P.first = 1;
    P.read_pos = 0; P.decoded = 0; P.buf_len = P.buf_pos = 0;
    aac_adpcm_reset(&P.st);
    if (zone != NO_ZONE) {
        const aac_zone_t *z = &P.pkg.zones[zone];
        aac_hal_led_set(zone, z->r, z->g, z->b);
    }
    P.playing = 1;
    P.stats.plays++;
    aac_hal_event(AAC_EVT_PLAY_START, en->vocab_id);
    if (en->priority == AAC_PRIO_EMERGENCY) aac_hal_event(AAC_EVT_EMERGENCY, en->vocab_id);
    return aac_hal_audio_start(P.pkg.sample_rate) == 0 ? AAC_OK : AAC_ERR_IO;
}

aac_err_t aac_player_on_touch(uint8_t zone, aac_touch_t t)
{
    P.stats.touch_us = aac_hal_time_us();
    if (!P.loaded) return AAC_ERR_NO_PKG;
    if (zone >= AAC_ZONE_COUNT) return AAC_ERR_NOT_FOUND;
    const aac_zone_t *z = &P.pkg.zones[zone];
    uint16_t vid = z->vocab_id;
    if (t == AAC_TOUCH_LONG && z->long_press_vocab_id != AAC_NO_VOCAB) {
        vid = z->long_press_vocab_id;
        aac_hal_event(AAC_EVT_SOS, z->vocab_id);
    }
    const aac_entry_t *en = aac_pkg_find(&P.pkg, vid);
    if (!en) return AAC_ERR_NOT_FOUND;
    return start(en, zone, 1);
}

aac_err_t aac_player_play(uint16_t vocab_id)
{
    if (!P.loaded) return AAC_ERR_NO_PKG;
    const aac_entry_t *en = aac_pkg_find(&P.pkg, vocab_id);
    if (!en) return AAC_ERR_NOT_FOUND;
    uint8_t zone = NO_ZONE;
    for (uint8_t i = 0; i < AAC_ZONE_COUNT; i++)
        if (P.pkg.zones[i].vocab_id == vocab_id) zone = i;
    return start(en, zone, 0);
}

static int refill(void)
{
    const aac_entry_t *en = P.cur;
    if (P.decoded >= en->sample_count || P.read_pos >= en->audio_len) return 0;
    uint8_t raw[DEC_BUF];              /* ADPCM: 128B → 256샘플, PCM16: 256B → 128샘플 */
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
        if (P.from_touch) {
            P.stats.first_audio_us = aac_hal_time_us();
            P.stats.last_latency_us = P.stats.first_audio_us - P.stats.touch_us;
            if (P.stats.last_latency_us > P.stats.max_latency_us) P.stats.max_latency_us = P.stats.last_latency_us;
        }
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
